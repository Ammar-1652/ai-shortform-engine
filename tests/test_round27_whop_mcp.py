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
from clipforge.campaign.whop_tools import load_tool_map, schema_sha256, select_mapped_tool
from clipforge.cli.main import app
from clipforge.schemas.whop_discovery import WhopLiveDiscoveryRequest

runner = CliRunner()
_CREATED = datetime(2026, 10, 6, 12, tzinfo=UTC)
_FIXTURE_SCHEMA = {"additionalProperties": False, "properties": {}, "type": "object"}
_OUTPUT_SCHEMA = {"type": "object"}
_FIXTURE_TOOL = {
    "tool_name": "list_public_campaigns",
    "provider_id": "whop",
    "provider_version": "test-1",
    "protocol_version": "2025-06-18",
    "read_only": True,
    "destructive": False,
    "input_schema_sha256": schema_sha256(_FIXTURE_SCHEMA),
    "output_schema_sha256": schema_sha256(_OUTPUT_SCHEMA),
    "output_model": "campaign_catalogue",
    "verification_origin": "fixture_only",
    "verification_timestamp": "2026-10-06T12:00:00Z",
    "tool_map_version": "1",
}


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
                "protocol": self.headers.get("MCP-Protocol-Version"),
            }
        )
        mode = self.server.mode
        method = body.get("method")
        if mode == "auth":
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer realm="secret-challenge"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
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
                    {
                        "name": "list_public_campaigns",
                        "annotations": {"readOnlyHint": True, "destructiveHint": False},
                        "inputSchema": _FIXTURE_SCHEMA,
                    },
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
                decoy = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 99,
                        "result": {"content": [{"type": "text", "text": '{"campaigns":[]}'}]},
                    }
                )
                payload = f"event: message\ndata: {encoded}\n\ndata: {decoy}\n\n".encode()
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
    tools = [
        {"name": "create_campaign"},
        {"name": "list_public_campaigns_and_checkout"},
        {
            "name": "list_public_campaigns",
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
            "inputSchema": _FIXTURE_SCHEMA,
        },
    ]
    assert (
        select_discovery_tool(
            tools,
            [_FIXTURE_TOOL],
            provider_version="test-1",
            protocol_version="2025-06-18",
            allow_fixture=True,
        )
        == "list_public_campaigns"
    )
    with pytest.raises(CampaignError) as rejected:
        select_mapped_tool(
            [{"name": "create_campaign"}, {"name": "join_campaign"}],
            [_FIXTURE_TOOL],
            allow_fixture=True,
            provider_version="test-1",
            protocol_version="2025-06-18",
        )
    assert rejected.value.code == "unsupported_tool"
    with pytest.raises(CampaignError) as unverified:
        select_mapped_tool(
            tools,
            [],
            allow_fixture=False,
            provider_version="test-1",
            protocol_version="2025-06-18",
        )
    assert unverified.value.code == "unsupported_tool"
    assert load_tool_map() == []
    with pytest.raises(CampaignError) as official:
        select_mapped_tool(
            tools,
            load_tool_map(),
            allow_fixture=False,
            provider_version="test-1",
            protocol_version="2025-06-18",
        )
    assert official.value.code == "unsupported_tool"
    destructive = [
        {
            "name": "list_public_campaigns",
            "annotations": {"readOnlyHint": True, "destructiveHint": True},
            "inputSchema": _FIXTURE_SCHEMA,
        }
    ]
    with pytest.raises(CampaignError) as destroyed:
        select_mapped_tool(
            destructive,
            [_FIXTURE_TOOL],
            allow_fixture=True,
            provider_version="test-1",
            protocol_version="2025-06-18",
        )
    assert destroyed.value.code == "unsupported_tool"


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
        assert server.events[0]["protocol"] is None
        assert server.events[2]["protocol"] == "2025-06-18"
        assert server.events[3]["protocol"] == "2025-06-18"
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

    provider = PublicWhopMcpProvider(
        "http://127.0.0.1:9/mcp",
        timeout_s=0.01,
        opener=slow,
        allow_loopback=True,
    )
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
        assert "public_provider: unavailable" in text
        assert "live_smoke: not_executed" in text
        assert "whop_live: provider_unavailable" in text
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
        assert live.exit_code != 0
        assert "provider_unavailable" in live.stderr
        assert server.events == []
        assert not (work / "campaigns").exists()
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


def test_in_memory_registry_is_not_the_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_WHOP_LIVE_SMOKE", "1")
    monkeypatch.setenv("CLIPFORGE_WHOP_CONNECTOR", "authenticated")
    monkeypatch.setenv("CLIPFORGE_WHOP_SESSION_HANDLE", "browser-handle")
    clear_authenticated_readers()
    try:
        with pytest.raises(CampaignError) as missing:
            build_live_provider()
        assert missing.value.code == "provider_unavailable"
        register_authenticated_reader("browser-handle", FixtureCatalogueReader(_public()))
        with pytest.raises(CampaignError) as still_missing:
            build_live_provider()
        assert still_missing.value.code == "provider_unavailable"
        session = AuthenticatedConnectorSession("browser-handle", _public)
        assert not hasattr(session, "password")
        assert not hasattr(session, "cookie")
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
        (_public(status="unknown"), {"require_status": "active"}, "missing_status", "src-city"),
        (_public(category=None), {"allowed_categories": ["clipping"]}, "missing_category", "src-city"),
        (_public(language=None), {"language": "en-US"}, "missing_language", "src-city"),
        (_source(availability="unknown"), {}, "source_unavailable", "src-city"),
        (_source(media_format=None), {"media_format": "mp4"}, "missing_format", "src-city"),
        (_source(size_bytes=None), {"max_size_bytes": 10}, "missing_size", "src-city"),
        (_source(duration_us=None), {"min_duration_us": 1}, "missing_duration", "src-city"),
        (_source(), {"require_acquisition_reference": True}, "manual_download_required", "src-city"),
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
        "stage_import_manifest",
        "stage_discovery_response",
        "stage_discovery_request",
        "stage_discovery_manifest",
        "final_rename",
        "promote_import",
        "promote_import_manifest",
        "promote_discovery_response",
        "promote_discovery_request",
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


def test_auth_challenge_is_not_stored(tmp_path: Path) -> None:
    with _running(_public(), "auth") as server, pytest.raises(CampaignError) as challenged:
        _provider(server).discover()
    assert challenged.value.code == "auth_required"
    assert "secret-challenge" not in str(challenged.value)


def test_rollback_restores_an_existing_file(tmp_path: Path) -> None:
    from clipforge.campaign.whop import plan_whop_import

    work = tmp_path / "work"
    work.mkdir()
    payload = json.dumps(FakeWhopProvider().payload).encode()
    planned, _raw, write = plan_whop_import(
        work,
        payload,
        project_id="project-1",
        provider_id="fake_whop",
        provider_version="1",
    )
    assert write
    destination = work / "campaigns" / "whop" / planned.import_id
    destination.mkdir(parents=True)
    target = destination / "snapshot.json"
    target.write_bytes(b"previous-bytes")
    with pytest.raises(CampaignError) as failed:
        import_discovered(
            work,
            FakeWhopProvider(),
            project_id="project-1",
            promotion_hook=_stop("promote_discovery_response"),
        )
    assert failed.value.code == "promotion_failed"
    assert target.read_bytes() == b"previous-bytes"
    assert not list(work.rglob("*.partial"))


def test_symlink_destination_is_rejected(tmp_path: Path) -> None:
    from clipforge.campaign.whop import plan_whop_import

    work = tmp_path / "work"
    work.mkdir()
    payload = json.dumps(FakeWhopProvider().payload).encode()
    planned, _raw, write = plan_whop_import(
        work,
        payload,
        project_id="project-1",
        provider_id="fake_whop",
        provider_version="1",
    )
    assert write
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"keep-me")
    destination = work / "campaigns" / "whop" / planned.import_id
    destination.mkdir(parents=True)
    link = destination / "snapshot.json"
    link.symlink_to(outside)
    with pytest.raises(CampaignError) as failed:
        import_discovered(work, FakeWhopProvider(), project_id="project-1")
    assert failed.value.code == "symlink_rejected"
    assert outside.read_bytes() == b"keep-me"
    assert link.is_symlink()


def test_clean_process_connector(tmp_path: Path) -> None:
    import subprocess
    import sys

    clipforge = str(Path(sys.executable).parent / "clipforge")
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps(_public()), encoding="utf-8")
    nonce = "bridge-nonce-1"
    bridge = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "clipforge.campaign.whop_bridge",
            "--bind",
            "127.0.0.1",
            "--port",
            "0",
            "--catalogue",
            str(catalogue),
            "--nonce",
            nonce,
            "--expires-in",
            "30",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert bridge.stdout is not None
    line = bridge.stdout.readline().strip()
    assert line.startswith("port=")
    port = line.split("=", 1)[1]
    work = tmp_path / "work"
    work.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "CLIPFORGE_WHOP_LIVE_SMOKE": "1",
            "CLIPFORGE_WHOP_CONNECTOR": "authenticated",
            "CLIPFORGE_WHOP_CONNECTOR_URL": f"http://127.0.0.1:{port}/handoff",
            "CLIPFORGE_WHOP_SESSION_HANDLE": nonce,
        }
    )
    try:
        first = subprocess.run(
            [
                clipforge,
                "campaign",
                "operator",
                "whop",
                "discover",
                "--live",
                "--connector",
                "authenticated",
                "--project",
                "project-1",
                "--operator",
                "operator-1",
                "--work-dir",
                str(work),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert first.returncode == 0, first.stderr
        assert "evidence_origin: test_double" in first.stdout
        assert "live_claim: not_claimed" in first.stdout
        assert "authenticated_discovery" not in first.stdout
        assert nonce not in first.stdout
        assert nonce not in first.stderr
        stored = " ".join(path.read_text(encoding="utf-8") for path in work.rglob("*.json"))
        assert nonce not in stored
        assert "cookie" not in stored.lower()
        second = subprocess.run(
            [
                clipforge,
                "campaign",
                "operator",
                "whop",
                "discover",
                "--live",
                "--connector",
                "authenticated",
                "--project",
                "project-1",
                "--operator",
                "operator-1",
                "--work-dir",
                str(work),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert second.returncode != 0
        assert "stale_session" in second.stderr or "provider_unavailable" in second.stderr
    finally:
        bridge.terminate()
        bridge.wait(timeout=5)


def test_discovery_keeps_declared_hashes_out_of_acquisition(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    discovered = import_discovered(work, FakeWhopProvider(), project_id="project-1")
    evidence = select_whop_campaign(
        work,
        campaign_id="camp-city",
        import_id=discovered.import_id or "",
        project_id="project-1",
        source_ids=["src-city"],
        operator_id="operator-1",
    )
    assert evidence.hash_basis == "declared"
    assert evidence.source_hashes == ["a" * 64]
    selection = work / "campaigns" / "whop-selections" / evidence.evidence_id
    assert not (selection / "acquired.json").exists()
    assert not list(work.rglob("*.sqlite*"))


def test_content_rewards_fixture_selects_only_the_valid_source(tmp_path: Path) -> None:
    payload = _public(title="Allowed clipping", campaign_type="clipping", category="clipping")
    good = payload["campaigns"][0]
    good["sources"][0]["acquisition_reference"] = "manual-ref"
    inactive = json.loads(json.dumps(good))
    inactive["campaign_id"] = "camp-paused"
    inactive["status"] = "paused"
    inactive["title"] = "Paused rewards"
    gambling = json.loads(json.dumps(good))
    gambling["campaign_id"] = "camp-gambling"
    gambling["category"] = "gambling"
    gambling["title"] = "Gambling rewards"
    ugc = json.loads(json.dumps(good))
    ugc["campaign_id"] = "camp-ugc"
    ugc["campaign_type"] = "ugc"
    ugc["category"] = "ugc"
    ugc["title"] = "UGC rewards"
    missing = json.loads(json.dumps(good))
    missing["campaign_id"] = "camp-missing"
    missing["title"] = "Missing footage"
    missing["sources"][0]["availability"] = "missing"
    missing["sources"][0]["source_id"] = "src-missing-footage"
    huge = json.loads(json.dumps(good["sources"][0]))
    huge["source_id"] = "src-huge"
    huge["size_bytes"] = 201 * 1024 * 1024
    huge["selected"] = True
    no_hash = json.loads(json.dumps(good["sources"][0]))
    no_hash["source_id"] = "src-no-hash"
    no_hash["content_sha256"] = None
    no_hash["declared_content_sha256"] = None
    no_hash["selected"] = True
    changed = json.loads(json.dumps(good["sources"][0]))
    changed["source_id"] = "src-changed-hash"
    changed["acquired_file_sha256"] = "b" * 64
    changed["acquisition_status"] = "hash_mismatch"
    changed["selected"] = True
    good["sources"].extend([huge, no_hash, changed])
    prohibited = json.loads(json.dumps(good))
    prohibited["campaign_id"] = "camp-prohibited"
    prohibited["title"] = "Prohibited requirements"
    prohibited["policy_state"] = "prohibited"
    prohibited["requirements_text"] = "must include a banned claim"
    prohibited["prohibited_text"] = "operator policy blocks this requirement"
    prohibited["sources"] = [json.loads(json.dumps(good["sources"][0]))]
    prohibited["sources"][0]["source_id"] = "src-prohibited"
    payload["campaigns"].extend([inactive, gambling, ugc, missing, prohibited])
    work = tmp_path / "work"
    work.mkdir()
    discovered = import_discovered(
        work,
        FakeWhopProvider(payload),
        project_id="project-1",
        request=_request(
            require_status="active",
            allowed_categories=["clipping"],
            prohibited_categories=["gambling"],
            max_size_bytes=200 * 1024 * 1024,
            require_acquisition_reference=True,
        ),
    )
    included = [item.campaign_id for item in discovered.decisions if item.included]
    assert included == ["camp-city"]
    city = next(item for item in discovered.decisions if item.campaign_id == "camp-city")
    assert city.included_source_ids == ["src-city"]
    assert city.filter_fingerprint == discovered.filter_fingerprint
    excluded = {item.source_id: item.reason_code for item in city.excluded_sources}
    assert excluded["src-huge"] == "source_too_large"
    assert excluded["src-no-hash"] == "missing_content_hash"
    assert excluded["src-changed-hash"] == "hash_mismatch"
    blocked_campaigns = {item.campaign_id: item.reason_code for item in discovered.decisions}
    assert blocked_campaigns["camp-paused"] == "status_not_active"
    assert blocked_campaigns["camp-gambling"] == "category_prohibited"
    assert blocked_campaigns["camp-ugc"] == "category_not_allowed"
    assert blocked_campaigns["camp-missing"] == "missing_source"
    assert blocked_campaigns["camp-prohibited"] == "policy_blocked"
    evidence = select_whop_campaign(
        work,
        campaign_id="camp-city",
        import_id=discovered.import_id or "",
        project_id="project-1",
        source_ids=["src-city"],
        operator_id="operator-1",
    )
    assert evidence.source_ids == ["src-city"]
    with pytest.raises(CampaignError) as blocked:
        select_whop_campaign(
            work,
            campaign_id="camp-city",
            import_id=discovered.import_id or "",
            project_id="project-1",
            source_ids=["src-huge"],
            operator_id="operator-1",
        )
    assert blocked.value.code == "source_too_large"
    with pytest.raises(CampaignError) as changed_hash:
        select_whop_campaign(
            work,
            campaign_id="camp-city",
            import_id=discovered.import_id or "",
            project_id="project-1",
            source_ids=["src-changed-hash"],
            operator_id="operator-1",
        )
    assert changed_hash.value.code == "hash_mismatch"


def test_identity_binds_operator_tool_and_blocks_a_stale_response(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    provider = FakeWhopProvider()
    first = import_discovered(work, provider, project_id="project-1", operator_id="operator-1")
    other_operator = import_discovered(work, provider, project_id="project-1", operator_id="operator-2")
    assert other_operator.identity_sha256 != first.identity_sha256
    assert other_operator.import_id != first.import_id
    with pytest.raises(CampaignError) as operator_miss:
        select_whop_campaign(
            work,
            campaign_id="camp-city",
            import_id=other_operator.import_id or "",
            project_id="project-1",
            source_ids=["src-city"],
            operator_id="operator-1",
            discovery_id=other_operator.discovery_id,
        )
    assert operator_miss.value.code == "operator_mismatch"
    renamed = FakeWhopProvider()
    renamed.tool_name = "other_tool"
    other_tool = import_discovered(work, renamed, project_id="project-1")
    assert other_tool.identity_sha256 != first.identity_sha256
    versioned = FakeWhopProvider()
    versioned.provider_version = "9"
    other_version = import_discovered(work, versioned, project_id="project-1")
    assert other_version.identity_sha256 != first.identity_sha256
    filtered = import_discovered(
        work,
        provider,
        project_id="project-1",
        request=_request(require_status="active"),
    )
    assert filtered.identity_sha256 != first.identity_sha256
    newer = import_discovered(work, FakeWhopProvider(_public(title="Newer rewards")), project_id="project-1")
    with pytest.raises(CampaignError) as crossed:
        select_whop_campaign(
            work,
            campaign_id="camp-city",
            import_id=newer.import_id or "",
            project_id="project-1",
            source_ids=["src-city"],
            operator_id="operator-1",
            discovery_id=first.discovery_id,
        )
    assert crossed.value.code == "project_mismatch"
    response = work / "campaigns" / "whop-discoveries" / first.discovery_id / "response.json"
    original = response.read_bytes()
    response.write_bytes(original + b" ")
    with pytest.raises(CampaignError) as stale:
        verify_discovery(work, first.discovery_id)
    assert stale.value.code == "stale_discovery"
    response.write_bytes(original)
    assert verify_discovery(work, first.discovery_id).discovery_id == first.discovery_id


def test_rollback_restores_overwritten_discovery_files(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    kept = import_discovered(work, FakeWhopProvider(), project_id="project-1")
    import_dir = work / "campaigns" / "whop" / (kept.import_id or "")
    snapshot = import_dir / "snapshot.json"
    import_manifest = import_dir / "manifest.json"
    previous_snapshot = snapshot.read_bytes()
    previous_import = import_manifest.read_bytes()
    disc_dir = work / "campaigns" / "whop-discoveries" / kept.discovery_id
    response = disc_dir / "response.json"
    request = disc_dir / "request.json"
    manifest = disc_dir / "manifest.json"
    response.write_bytes(b"old-response")
    request.write_bytes(b"old-request")
    manifest.write_bytes(b"old-manifest")
    with pytest.raises(CampaignError) as failed:
        import_discovered(
            work,
            FakeWhopProvider(),
            project_id="project-1",
            promotion_hook=_stop("promoted"),
        )
    assert failed.value.code == "stale_discovery"
    assert snapshot.read_bytes() == previous_snapshot
    assert import_manifest.read_bytes() == previous_import
    assert response.read_bytes() == b"old-response"
    assert request.read_bytes() == b"old-request"
    assert manifest.read_bytes() == b"old-manifest"
    assert not list(work.rglob("*.partial"))
    assert not list(work.rglob("*.sqlite*"))


def test_operator_snapshot_import_does_not_claim_live_transport(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    payload = FakeWhopProvider().payload
    payload["intake_label"] = "authenticated_operator_snapshot"
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    imported = runner.invoke(
        app,
        [
            "campaign",
            "operator",
            "whop",
            "import",
            "--file",
            str(snapshot),
            "--project",
            "project-1",
            "--work-dir",
            str(work),
        ],
    )
    assert imported.exit_code == 0, imported.stderr
    assert "whop_live: not_configured" in imported.stdout
    assert "intake_label: authenticated_operator_snapshot" in imported.stdout
    assert "credentials_stored: not_stored" in imported.stdout
    assert "live_transport: not_claimed" in imported.stdout
    stored = " ".join(path.read_text(encoding="utf-8") for path in work.rglob("*.json"))
    assert "authenticated_operator_snapshot" in stored
    assert "not_claimed" in stored


def test_optional_live_smoke_stays_unclaimed() -> None:
    from clipforge.campaign.whop_mcp import official_endpoint

    authorized = os.environ.get("CLIPFORGE_WHOP_AUTHORIZED") == "1" and official_endpoint()
    if not authorized:
        pytest.skip("whop_live: not_configured; live_smoke: not_executed")
    try:
        provider = build_live_provider()
        payload = provider.discover()
    except CampaignError as exc:
        pytest.skip(f"whop_live: {exc.code}; live_smoke: not_executed")
    assert isinstance(payload, dict)
    assert "campaigns" in payload
    dumped = json.dumps(payload).lower()
    assert "bearer " not in dumped
    assert "cookie=" not in dumped
    assert provider.live_status != "authenticated_discovery"
    assert "session_proven" not in dumped


def _provider(server: _Server) -> PublicWhopMcpProvider:
    return PublicWhopMcpProvider(
        _url(server),
        timeout_s=2,
        tool_map=[_FIXTURE_TOOL],
        allow_fixture=True,
        allow_loopback=True,
    )


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
