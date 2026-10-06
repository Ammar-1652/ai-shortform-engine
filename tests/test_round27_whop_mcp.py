"""Round 27: real Whop MCP adapter, selection filters, and atomic promotion."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from clipforge.campaign.providers import CampaignError
from clipforge.campaign.whop import whop_doctor
from clipforge.campaign.whop_live import (
    FakeWhopProvider,
    cancel_discovery,
    import_discovered,
    resume_discovery,
    select_whop_campaign,
    verify_discovery,
)
from clipforge.campaign.whop_mcp import select_discovery_tool
from clipforge.campaign.whop_provider import (
    AuthenticatedConnectorSession,
    FixtureCatalogueReader,
    PublicWhopMcpProvider,
    build_live_provider,
    clear_authenticated_readers,
    register_authenticated_reader,
)
from clipforge.cli.main import app
from clipforge.schemas.whop_discovery import WhopLiveDiscoveryRequest

runner = CliRunner()
_CREATED = datetime(2026, 10, 6, 12, tzinfo=UTC)


class _Server(ThreadingHTTPServer):
    def __init__(self, document: dict[str, Any], mode: str) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.document = document
        self.mode = mode
        self.events: list[dict[str, str | None]] = []


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _Server

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        params = body.get("params") if isinstance(body.get("params"), dict) else {}
        self.server.events.append(
            {
                "method": body.get("method"),
                "session": self.headers.get("Mcp-Session-Id"),
                "tool": params.get("name") if isinstance(params.get("name"), str) else None,
                "authorization": self.headers.get("Authorization"),
            }
        )
        mode = self.server.mode
        method = body.get("method")
        if mode == "oversize":
            self._send(200, b"{" + (b"x" * 1_000_002), "application/json")
            return
        if mode == "malformed":
            self._send(200, b"not-json", "application/json")
            return
        if mode == "rpc_shape" and method == "initialize":
            self._send(200, b'{"jsonrpc":"2.0","id":1}', "application/json", session="mcp-session")
            return
        if mode == "stale" and method == "tools/call":
            self._send(404, b"{}", "application/json", session="mcp-session")
            return
        if method == "initialize":
            result = {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "serverInfo": {"name": "whop", "version": "test-1"},
            }
            self._send(200, _rpc(body.get("id"), result), "application/json", session="mcp-session")
            return
        if method == "notifications/initialized":
            self._send(202, b"", "application/json", session="mcp-session")
            return
        if method == "tools/list":
            if mode == "mutating_only":
                tools = [{"name": "create_campaign"}, {"name": "join_campaign"}]
            else:
                tools = [
                    {"name": "create_campaign"},
                    {"name": "list_public_campaigns_and_checkout"},
                    {"name": "list_public_campaigns"},
                ]
            self._send(200, _rpc(body.get("id"), {"tools": tools}), "application/json", session="mcp-session")
            return
        if method == "tools/call":
            document = self.server.document
            if mode == "sse":
                encoded = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "result": {"content": [{"type": "text", "text": json.dumps(document)}]},
                    }
                )
                payload = f"event: message\ndata: {encoded}\n\n".encode()
                self._send(200, payload, "text/event-stream", session="mcp-session")
                return
            result = {"content": [{"type": "text", "text": json.dumps(document)}]}
            self._send(200, _rpc(body.get("id"), result), "application/json", session="mcp-session")
            return
        self._send(200, _rpc(body.get("id"), {}), "application/json", session="mcp-session")

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str, session: str | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if session is not None:
            self.send_header("Mcp-Session-Id", session)
        self.end_headers()
        self.wfile.write(body)


def test_allowlist_rejects_mutating_and_prefix_tools() -> None:
    names = ["create_campaign", "list_public_campaigns_and_checkout", "list_public_campaigns"]
    assert select_discovery_tool(names) == "list_public_campaigns"
    with pytest.raises(CampaignError) as rejected:
        select_discovery_tool(["create_campaign", "join_campaign", "list_public_campaigns_and_checkout"])
    assert rejected.value.code == "unsupported_tool"


def test_public_mcp_json_sse_and_failures(tmp_path: Path) -> None:
    document = _public()
    with _running(document, "json") as server:
        provider = _provider(server)
        json_root = tmp_path / "json"
        json_root.mkdir()
        first = import_discovered(json_root, provider, project_id="project-1")
        assert first.evidence_origin == "public_connector"
        assert first.live_claim == "not_claimed"
        assert first.live_status == "public_discovery"
        assert first.tool_name == "list_public_campaigns"
        assert first.provider_version == "test-1"
        methods = [item["method"] for item in server.events]
        assert methods[:4] == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
        assert server.events[2]["session"] == "mcp-session"
        assert server.events[3]["tool"] == "list_public_campaigns"
        assert all(item["authorization"] is None for item in server.events)
        stored = " ".join(path.read_text(encoding="utf-8") for path in json_root.rglob("*.json"))
        assert "mcp-session" not in stored
        assert "Authorization" not in stored
        again = import_discovered(json_root, _provider(server), project_id="project-1")
        assert again.cache_status == "hit"
        assert again.discovery_id == first.discovery_id
    with _running(document, "sse") as server:
        sse_root = tmp_path / "sse"
        sse_root.mkdir()
        sse = import_discovered(sse_root, _provider(server), project_id="project-1")
        assert sse.tool_name == "list_public_campaigns"
        assert sse.evidence_origin == "public_connector"
    with _running(document, "mutating_only") as server:
        with pytest.raises(CampaignError) as missing_tool:
            import_discovered(tmp_path / "mutate", _provider(server), project_id="project-1")
        assert missing_tool.value.code == "unsupported_tool"
        (tmp_path / "mutate").mkdir()
        assert not (tmp_path / "mutate" / "campaigns").exists()
    secret = _public()
    secret["campaigns"][0]["title"] = "bearer abc"
    with _running(secret, "json") as server:
        with pytest.raises(CampaignError) as leaked:
            import_discovered(tmp_path / "secret", _provider(server), project_id="project-1")
        assert leaked.value.code == "secret_rejected"
        (tmp_path / "secret").mkdir()
        assert not (tmp_path / "secret" / "campaigns").exists()
    failures = (
        ("malformed", "malformed_response"),
        ("rpc_shape", "malformed_response"),
        ("oversize", "oversized_response"),
        ("stale", "stale_session"),
    )
    for mode, code in failures:
        with _running(document, mode) as server:
            with pytest.raises(CampaignError) as failed:
                _provider(server).discover()
            assert failed.value.code == code


def test_timeout_and_forged_status(tmp_path: Path) -> None:
    def slow(_request: object, timeout: float = 0) -> None:
        del timeout
        raise TimeoutError("slow")

    provider = PublicWhopMcpProvider("http://127.0.0.1:9/mcp", timeout_s=0.01, opener=slow)
    with pytest.raises(CampaignError) as timed:
        provider.discover()
    assert timed.value.code == "timeout"
    forged = _public()
    forged["live_status"] = "authenticated_discovery"
    with pytest.raises(CampaignError) as status:
        import_discovered(tmp_path, FakeWhopProvider(forged), project_id="project-1")
    assert status.value.code == "forged_status"
    wrong = _public()
    wrong["provider_version"] = "forged"
    with pytest.raises(CampaignError) as version:
        import_discovered(tmp_path, FakeWhopProvider(wrong), project_id="project-1")
    assert version.value.code == "forged_status"
    assert not (tmp_path / "campaigns").exists()


def test_doctor_and_cli_do_not_claim_a_closed_connector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _public()
    with _running(document, "json") as server:
        monkeypatch.setenv("CLIPFORGE_WHOP_LIVE_SMOKE", "1")
        monkeypatch.setenv("CLIPFORGE_WHOP_CONNECTOR", "public")
        monkeypatch.setenv("CLIPFORGE_WHOP_URL", _url(server))
        text = whop_doctor()
        assert server.events == []
        assert "public_provider: available" in text
        assert "live_smoke: not_executed" in text
        assert "whop_live: not_configured" in text
        work = tmp_path / "work"
        work.mkdir()
        live = runner.invoke(
            app,
            [
                "campaign",
                "operator",
                "whop",
                "discover",
                "--live",
                "--project",
                "project-1",
                "--operator",
                "operator-1",
                "--work-dir",
                str(work),
            ],
        )
        assert live.exit_code == 0, live.stderr
        assert "evidence_origin: public_connector" in live.stdout
        assert "live_claim: not_claimed" in live.stdout
        assert "mcp-session" not in live.stdout
    monkeypatch.delenv("CLIPFORGE_WHOP_CONNECTOR", raising=False)
    monkeypatch.delenv("CLIPFORGE_WHOP_URL", raising=False)
    monkeypatch.delenv("CLIPFORGE_WHOP_LIVE_SMOKE", raising=False)
    absent = runner.invoke(
        app,
        [
            "campaign",
            "operator",
            "whop",
            "discover",
            "--live",
            "--project",
            "project-1",
            "--work-dir",
            str(tmp_path),
        ],
    )
    assert absent.exit_code != 0
    assert "not_configured" in absent.stderr
    monkeypatch.setenv("CLIPFORGE_WHOP_LIVE_SMOKE", "1")
    unavailable = runner.invoke(
        app,
        [
            "campaign",
            "operator",
            "whop",
            "discover",
            "--live",
            "--project",
            "project-1",
            "--work-dir",
            str(tmp_path),
        ],
    )
    assert unavailable.exit_code != 0
    assert "provider_unavailable" in unavailable.stderr


def test_authenticated_handle_is_not_stored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_WHOP_LIVE_SMOKE", "1")
    monkeypatch.setenv("CLIPFORGE_WHOP_CONNECTOR", "authenticated")
    monkeypatch.setenv("CLIPFORGE_WHOP_SESSION_HANDLE", "browser-handle")
    clear_authenticated_readers()
    try:
        with pytest.raises(CampaignError) as missing:
            build_live_provider()
        assert missing.value.code == "provider_unavailable"
        register_authenticated_reader("browser-handle", FixtureCatalogueReader(_public()))
        double_root = tmp_path / "double"
        double_root.mkdir()
        double = import_discovered(double_root, build_live_provider(), project_id="project-1")
        assert double.evidence_origin == "test_double"
        assert double.live_claim == "not_claimed"
        session = AuthenticatedConnectorSession("browser-handle", _public)
        assert not hasattr(session, "password")
        register_authenticated_reader("browser-handle", session)
        real_root = tmp_path / "real"
        real_root.mkdir()
        real = import_discovered(real_root, build_live_provider(), project_id="project-1")
        assert real.evidence_origin == "authenticated_connector"
        assert real.live_status == "authenticated_discovery"
        assert real.live_claim == "not_claimed"
        stored = " ".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
        assert "browser-handle" not in stored
        assert "password" not in stored.lower()
    finally:
        clear_authenticated_readers()


def test_project_isolation_policy_and_catalogue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "work"
    work.mkdir()
    provider = FakeWhopProvider()
    first = import_discovered(work, provider, project_id="project-1")
    second = import_discovered(work, provider, project_id="project-2")
    assert first.discovery_id != second.discovery_id
    assert first.identity_sha256 != second.identity_sha256
    assert first.import_id != second.import_id
    hit = import_discovered(work, provider, project_id="project-1")
    assert hit.cache_status == "hit"
    assert hit.discovery_id == first.discovery_id
    with pytest.raises(CampaignError) as mismatch:
        select_whop_campaign(
            work,
            campaign_id="camp-city",
            import_id=first.import_id or "",
            project_id="project-2",
            source_ids=["src-city"],
            operator_id="operator-1",
        )
    assert mismatch.value.code == "project_mismatch"
    changed = _public()
    changed["campaigns"][0]["title"] = "Other rewards"
    other = import_discovered(work, FakeWhopProvider(changed), project_id="project-1")
    assert other.discovery_id != first.discovery_id
    monkeypatch.setattr("clipforge.campaign.whop.current_policy_fingerprint", lambda _campaign_id: "d" * 64)
    shifted = import_discovered(work, provider, project_id="project-1")
    assert shifted.discovery_id != first.discovery_id
    with pytest.raises(CampaignError) as stale:
        verify_discovery(work, first.discovery_id)
    assert stale.value.code == "stale_policy"


def test_filter_blocks_selection_even_when_selected(tmp_path: Path) -> None:
    cases = [
        (_public(status="paused"), {"require_status": "active"}, "status_not_active", "src-city"),
        (
            _public(category="gambling"),
            {"prohibited_categories": ["gambling"]},
            "category_prohibited",
            "src-city",
        ),
        (_public(), {"query": "zzzz"}, "search_mismatch", "src-city"),
        (_public(), {"language": "ja"}, "language_mismatch", "src-city"),
        (_public(exported_at="2020-01-01T00:00:00Z"), {"max_age_hours": 1}, "stale_campaign", "src-city"),
        (_source(availability="offline"), {}, "source_unavailable", "src-city"),
        (_source(media_format="mov"), {"media_format": "mp4"}, "format_mismatch", "src-city"),
        (_source(size_bytes=50), {"max_size_bytes": 10}, "source_too_large", "src-city"),
        (_source(duration_us=1), {"min_duration_us": 5_000_000}, "duration_out_of_range", "src-city"),
        (_source(rights_state="unknown"), {}, "rights_not_allowed", "src-city"),
        (_source(content_sha256=None), {}, "missing_content_hash", "src-city"),
    ]
    for index, (payload, overrides, code, source_id) in enumerate(cases):
        work = tmp_path / str(index)
        work.mkdir()
        discovered = import_discovered(
            work,
            FakeWhopProvider(payload),
            project_id="project-1",
            request=_request(**overrides),
        )
        with pytest.raises(CampaignError) as blocked:
            select_whop_campaign(
                work,
                campaign_id=str(payload["campaigns"][0]["campaign_id"]),
                import_id=discovered.import_id or "",
                project_id="project-1",
                source_ids=[source_id],
                operator_id="operator-1",
            )
        assert blocked.value.code == code
        assert not list(work.rglob("evidence.json"))


def test_selected_flag_does_not_override_the_request(tmp_path: Path) -> None:
    payload = _public()
    first = payload["campaigns"][0]["sources"][0]
    first["media_format"] = "mov"
    first["selected"] = True
    second = deepcopy(first)
    second["source_id"] = "src-good"
    second["media_format"] = "mp4"
    second["selected"] = False
    payload["campaigns"][0]["sources"].append(second)
    work = tmp_path / "work"
    work.mkdir()
    discovered = import_discovered(
        work,
        FakeWhopProvider(payload),
        project_id="project-1",
        request=_request(media_format="mp4"),
    )
    with pytest.raises(CampaignError) as blocked:
        select_whop_campaign(
            work,
            campaign_id="camp-city",
            import_id=discovered.import_id or "",
            project_id="project-1",
            source_ids=["src-city"],
            operator_id="operator-1",
        )
    assert blocked.value.code == "format_mismatch"
    evidence = select_whop_campaign(
        work,
        campaign_id="camp-city",
        import_id=discovered.import_id or "",
        project_id="project-1",
        source_ids=["src-good"],
        operator_id="operator-1",
    )
    assert evidence.source_ids == ["src-good"]
    assert evidence.source_hashes == ["a" * 64]
    assert evidence.live_claim == "not_claimed"


@pytest.mark.parametrize(
    "stage",
    [
        "stage_import",
        "stage_discovery_response",
        "stage_discovery_manifest",
        "final_rename",
        "promote_import",
        "promote_discovery_response",
        "promote_discovery_manifest",
    ],
)
def test_promotion_rollback_on_first_and_previous_runs(tmp_path: Path, stage: str) -> None:
    empty = tmp_path / stage / "empty"
    empty.mkdir(parents=True)
    with pytest.raises(CampaignError) as first_failure:
        import_discovered(empty, FakeWhopProvider(), project_id="project-1", promotion_hook=_stop(stage))
    assert first_failure.value.code == "promotion_failed"
    assert not list(empty.rglob("manifest.json"))
    assert not list(empty.rglob("*.partial"))
    previous = tmp_path / stage / "previous"
    previous.mkdir()
    kept = import_discovered(previous, FakeWhopProvider(), project_id="project-1")
    manifest = (previous / "campaigns" / "whop-discoveries" / kept.discovery_id / "manifest.json").read_bytes()
    snapshot = (previous / "campaigns" / "whop" / (kept.import_id or "") / "snapshot.json").read_bytes()
    with pytest.raises(CampaignError) as later:
        import_discovered(
            previous,
            FakeWhopProvider(_public(title="Interrupted rewards", campaign_id="camp-interrupted")),
            project_id="project-1",
            promotion_hook=_stop(stage),
        )
    assert later.value.code == "promotion_failed"
    kept_manifest = previous / "campaigns" / "whop-discoveries" / kept.discovery_id / "manifest.json"
    assert kept_manifest.read_bytes() == manifest
    assert (previous / "campaigns" / "whop" / (kept.import_id or "") / "snapshot.json").read_bytes() == snapshot
    assert not list(previous.rglob("*.partial"))
    stored = " ".join(path.read_text(encoding="utf-8") for path in previous.rglob("*.json"))
    assert "camp-interrupted" not in stored


def test_cancel_then_resume_without_a_provider_call(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    provider = FakeWhopProvider()
    first = import_discovered(work, provider, project_id="project-1")
    cancelled = cancel_discovery(work, first.discovery_id)
    assert cancelled.status == "cancelled"
    calls = provider.calls
    resumed = resume_discovery(work, first.discovery_id)
    assert provider.calls == calls
    assert resumed.discovery_id != first.discovery_id
    assert resumed.status == "ready"
    assert verify_discovery(work, resumed.discovery_id).discovery_id == resumed.discovery_id
    with pytest.raises(CampaignError) as denied:
        verify_discovery(work, first.discovery_id)
    assert denied.value.code == "cancelled"


def test_optional_live_smoke_stays_unclaimed() -> None:
    if os.environ.get("CLIPFORGE_WHOP_LIVE_SMOKE") != "1":
        pytest.skip("live smoke not executed")
    from clipforge.campaign.whop_mcp import configured_connector, session_handle

    if configured_connector() != "authenticated" or session_handle() is None:
        pytest.skip("provider_unavailable")
    try:
        provider = build_live_provider()
        payload = provider.discover()
    except CampaignError as exc:
        pytest.skip(exc.code)
    assert isinstance(payload, dict)
    assert provider.live_status in {"public_discovery", "authenticated_discovery"}


def _provider(server: _Server) -> PublicWhopMcpProvider:
    return PublicWhopMcpProvider(_url(server), timeout_s=2)


def _url(server: _Server) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/mcp"


def _rpc(request_id: object, result: dict[str, Any]) -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}).encode("utf-8")


def _request(**overrides: object) -> WhopLiveDiscoveryRequest:
    payload: dict[str, object] = {
        "request_id": "req-filter",
        "provider_id": "fake_whop",
        "provider_version": "1",
        "created_at": _CREATED,
        "require_policy": "allowed",
        "require_rights": "allowed",
    }
    payload.update(overrides)
    return WhopLiveDiscoveryRequest.model_validate(payload)


def _public(**campaign: object) -> dict[str, Any]:
    payload = FakeWhopProvider().payload
    exported = campaign.pop("exported_at", None)
    payload["campaigns"][0].update(campaign)
    if exported is not None:
        payload["exported_at"] = exported
    return payload


def _source(**fields: object) -> dict[str, Any]:
    payload = _public()
    payload["campaigns"][0]["sources"][0].update(fields)
    return payload


def _stop(stage: str):
    def hook(name: str) -> None:
        if name == stage:
            raise CampaignError("promotion stopped", code="promotion_failed")

    return hook


class _running:
    def __init__(self, document: dict[str, Any], mode: str) -> None:
        self.server = _Server(document, mode)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> _Server:
        self.thread.start()
        return self.server

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
