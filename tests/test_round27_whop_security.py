"""Security regressions for the Whop connector, tool map, and discovery cache."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from clipforge.campaign.providers import CampaignError
from clipforge.campaign.whop import import_whop_snapshot
from clipforge.campaign.whop_bridge import serve_catalogue
from clipforge.campaign.whop_live import (
    FakeWhopProvider,
    cancel_discovery,
    import_discovered,
    resume_discovery,
    select_whop_campaign,
    verify_discovery,
)
from clipforge.campaign.whop_mcp import PUBLIC_MCP_URL, WhopMcpReader, official_endpoint, url_is_allowed
from clipforge.campaign.whop_provider import (
    AuthenticatedConnectorSession,
    FixtureCatalogueReader,
    build_live_provider,
)
from clipforge.campaign.whop_tools import load_tool_map, select_mapped_tool
from tests.test_round27_whop_mcp import _FIXTURE_TOOL, _public


def test_prove_session_flag_is_rejected(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps(_public()), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "clipforge.campaign.whop_bridge",
            "--catalogue",
            str(catalogue),
            "--prove-session",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode != 0
    assert "--prove-session" not in completed.stderr


def test_local_catalogue_cannot_claim_authenticated_discovery(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    discovered = import_discovered(work, FakeWhopProvider(), project_id="project-1")
    assert discovered.evidence_origin == "test_double"
    assert discovered.live_status != "authenticated_discovery"
    assert discovered.live_claim == "not_claimed"
    fixture = FixtureCatalogueReader(_public())
    from clipforge.campaign.whop_provider import AuthenticatedBrowserProvider

    bridged = import_discovered(work, AuthenticatedBrowserProvider(fixture), project_id="project-1")
    assert bridged.evidence_origin == "test_double"
    assert bridged.live_status != "authenticated_discovery"


def test_real_connector_session_is_not_a_fixture(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    session = AuthenticatedConnectorSession("opaque-handle", lambda: _public())
    from clipforge.campaign.whop_provider import AuthenticatedBrowserProvider

    discovered = import_discovered(work, AuthenticatedBrowserProvider(session), project_id="project-1")
    assert discovered.evidence_origin == "authenticated_connector"
    assert discovered.live_status == "authenticated_discovery"
    assert discovered.live_claim == "not_claimed"
    stored = " ".join(path.read_text(encoding="utf-8") for path in work.rglob("*.json"))
    assert "opaque-handle" not in stored
    assert "cookie=" not in stored.lower()
    assert "bearer " not in stored.lower()


def test_operator_snapshot_does_not_claim_transport(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    payload = _public()
    payload["intake_label"] = "authenticated_operator_snapshot"
    attempt = import_whop_snapshot(work, json.dumps(payload).encode(), project_id="project-1")
    assert attempt.whop_live == "not_configured"
    assert attempt.intake_label == "authenticated_operator_snapshot"
    stored = (work / "campaigns" / "whop" / attempt.import_id / "snapshot.json").read_text(encoding="utf-8")
    assert "credentials_stored" in stored
    assert "not_stored" in stored
    assert "not_claimed" in stored


def test_forged_bridge_session_flag_is_rejected() -> None:
    from clipforge.campaign.whop_bridge import AuthenticatedBridgeProvider, _campaigns_from_envelope

    provider = AuthenticatedBridgeProvider("http://127.0.0.1:9/handoff", "nonce-1")
    with pytest.raises(CampaignError) as forged:
        _campaigns_from_envelope(
            provider,
            {
                "provider": {"id": "whop", "version": "1", "mode": "test_double", "session_proven": True},
                "campaigns": _public()["campaigns"],
            },
        )
    assert forged.value.code == "forged_status"


def test_official_endpoint_rejects_other_hosts() -> None:
    assert official_endpoint(PUBLIC_MCP_URL)
    assert url_is_allowed(PUBLIC_MCP_URL)
    assert not url_is_allowed("https://example.com/mcp")
    assert not url_is_allowed("http://localhost:9/mcp", allow_loopback=True)
    assert url_is_allowed("http://127.0.0.1:9/mcp", allow_loopback=True)
    with pytest.raises(CampaignError) as denied:
        WhopMcpReader("https://example.com/mcp").initialize()
    assert denied.value.code == "provider_unavailable"


def test_malformed_tool_map_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = (
        b'{"schema_version":"1.0.0","tool_map_version":"1",'
        b'"official_names_verified":false,"mappings":[{"tool_name":"x"}]}'
    )
    monkeypatch.setattr("clipforge.campaign.whop_tools._map_bytes", lambda: broken)
    with pytest.raises(CampaignError) as invalid:
        load_tool_map()
    assert invalid.value.code == "invalid_document"

    def missing_bytes() -> bytes:
        raise FileNotFoundError("missing map")

    monkeypatch.setattr("clipforge.campaign.whop_tools._map_bytes", missing_bytes)
    with pytest.raises(FileNotFoundError):
        load_tool_map()


def test_schema_mismatch_and_required_arguments() -> None:
    tool = {
        "name": "list_public_campaigns",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    }
    with pytest.raises(CampaignError) as mismatch:
        select_mapped_tool(
            [tool],
            [_FIXTURE_TOOL],
            allow_fixture=True,
            provider_version="test-1",
            protocol_version="2025-06-18",
        )
    assert mismatch.value.code == "schema_mismatch"
    matched = dict(_FIXTURE_TOOL)
    from clipforge.campaign.whop_tools import schema_sha256

    schema = tool["inputSchema"]
    matched["input_schema_sha256"] = schema_sha256(schema)
    with pytest.raises(CampaignError) as required:
        select_mapped_tool(
            [tool],
            [matched],
            allow_fixture=True,
            provider_version="test-1",
            protocol_version="2025-06-18",
        )
    assert required.value.code == "unsupported_tool"


def test_policy_change_creates_a_new_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "work"
    work.mkdir()
    payload = json.dumps(FakeWhopProvider().payload).encode()
    first = import_whop_snapshot(work, payload, project_id="project-1")
    monkeypatch.setattr("clipforge.campaign.whop.current_policy_fingerprint", lambda _campaign_id: "e" * 64)
    second = import_whop_snapshot(work, payload, project_id="project-1")
    assert second.import_id != first.import_id
    assert second.policy_fingerprint != first.policy_fingerprint


def test_tampered_manifest_is_stale(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    discovered = import_discovered(work, FakeWhopProvider(), project_id="project-1")
    manifest = work / "campaigns" / "whop-discoveries" / discovered.discovery_id / "manifest.json"
    original = manifest.read_bytes()
    manifest.write_bytes(b"{")
    with pytest.raises(CampaignError) as stale:
        verify_discovery(work, discovered.discovery_id)
    assert stale.value.code == "stale_discovery"
    manifest.write_bytes(original)
    assert verify_discovery(work, discovered.discovery_id).discovery_id == discovered.discovery_id


def test_empty_catalogue_is_blocked_and_not_malformed(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    empty = _public()
    empty["campaigns"] = []
    blocked = import_discovered(work, FakeWhopProvider(empty), project_id="project-1")
    assert blocked.status == "blocked"
    assert blocked.reason_code == "no_matching_campaigns"
    with pytest.raises(CampaignError) as missing:
        select_whop_campaign(
            work,
            campaign_id="camp-city",
            import_id=blocked.import_id or "",
            project_id="project-1",
            source_ids=["src-city"],
            operator_id="operator-1",
        )
    assert missing.value.code == "missing_campaign"
    with pytest.raises(CampaignError) as malformed:
        import_discovered(work, FakeWhopProvider({"operator_id": "operator-1"}), project_id="project-1")
    assert malformed.value.code == "empty_discovery"
    later = import_discovered(work, FakeWhopProvider(), project_id="project-1")
    assert later.status == "ready"
    assert later.discovery_id != blocked.discovery_id


def test_resume_leaves_the_cancelled_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "work"
    work.mkdir()
    first = import_discovered(work, FakeWhopProvider(), project_id="project-1")
    cancelled = cancel_discovery(work, first.discovery_id)
    before = (work / "campaigns" / "whop-discoveries" / first.discovery_id / "manifest.json").read_bytes()
    resumed = resume_discovery(work, cancelled.discovery_id)
    assert resumed.discovery_id != cancelled.discovery_id
    kept = work / "campaigns" / "whop-discoveries" / first.discovery_id / "manifest.json"
    assert kept.read_bytes() == before
    evidence = select_whop_campaign(
        work,
        campaign_id="camp-city",
        import_id=resumed.import_id or "",
        project_id="project-1",
        source_ids=["src-city"],
        operator_id="operator-1",
    )
    assert evidence.discovery_id == resumed.discovery_id
    monkeypatch.setattr("clipforge.campaign.whop.current_policy_fingerprint", lambda _campaign_id: "f" * 64)
    with pytest.raises(CampaignError) as stale:
        resume_discovery(work, cancelled.discovery_id)
    assert stale.value.code == "stale_policy"


def test_bridge_rejects_bad_requests(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps(_public()), encoding="utf-8")
    with pytest.raises(SystemExit):
        serve_catalogue("0.0.0.0", 0, catalogue, "nonce-1", expires_at=1)
    linked = tmp_path / "linked.json"
    linked.symlink_to(catalogue)
    with pytest.raises(SystemExit):
        serve_catalogue("127.0.0.1", 0, linked, "nonce-1", expires_at=1)
    for text in (
        "bearer secret",
        "cookie=abc",
        "token=abc",
        "<script>",
        "/home/pakka/clip.mp4",
    ):
        secret = tmp_path / "secret.json"
        secret.write_text(json.dumps({"campaigns": [], "title": text}), encoding="utf-8")
        with pytest.raises(SystemExit):
            serve_catalogue("127.0.0.1", 0, secret, "nonce-1", expires_at=1)


def _start_bridge(
    tmp_path: Path,
    *,
    nonce: str = "nonce-1",
    expires_in: str = "30",
) -> tuple[subprocess.Popen[str], int]:
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps(_public()), encoding="utf-8")
    reader, writer = os.pipe()
    os.write(writer, nonce.encode("utf-8"))
    os.close(writer)
    process = subprocess.Popen(
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
            "--work-dir",
            str(tmp_path),
            "--nonce-fd",
            str(reader),
            "--expires-in",
            expires_in,
        ],
        pass_fds=(reader,),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    os.close(reader)
    assert process.stdout is not None
    line = process.stdout.readline().strip()
    assert line.startswith("port=")
    return process, int(line.split("=", 1)[1])


def _raw_post(
    port: int,
    *,
    path: str = "/handoff",
    nonce: str = "nonce-1",
    host: str | None = None,
    origin: str | None = None,
    body: bytes = b'{"discover":"read_only"}',
    length: int | None = None,
    chunked: bool = False,
    method: str = "POST",
    include_length: bool = True,
) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.putrequest(method, path, skip_host=True)
    connection.putheader("Host", host or f"127.0.0.1:{port}")
    connection.putheader("Origin", origin or f"http://127.0.0.1:{port}")
    connection.putheader("Content-Type", "application/json")
    connection.putheader("X-Clipforge-Nonce", nonce)
    send_body = method == "POST" and not chunked and include_length and (length is None or length == len(body))
    if chunked:
        connection.putheader("Transfer-Encoding", "chunked")
    elif include_length and length is not None:
        connection.putheader("Content-Length", str(length))
    elif include_length and method == "POST":
        connection.putheader("Content-Length", str(len(body)))
    connection.endheaders(body if send_body else None)
    status = connection.getresponse().status
    connection.close()
    return status


def test_bridge_http_guards(tmp_path: Path) -> None:
    process, port = _start_bridge(tmp_path)
    try:
        assert _raw_post(port, path="/wrong") == 404
        assert _raw_post(port, host="evil.example") == 403
        assert _raw_post(port, origin="https://evil.example") == 403
        assert _raw_post(port, method="GET") == 405
        assert _raw_post(port, chunked=True, body=b"") == 411
        assert _raw_post(port, include_length=False, body=b"") == 411
        assert _raw_post(port, length=2_000_000, body=b"") == 413
        assert _raw_post(port) == 200
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_bridge_nonce_expiry_reuse_and_concurrency(tmp_path: Path) -> None:
    expired_dir = tmp_path / "expired"
    expired_dir.mkdir()
    expired, expired_port = _start_bridge(expired_dir, nonce="nonce-exp", expires_in="-1")
    try:
        assert _raw_post(expired_port, nonce="nonce-exp") == 410
    finally:
        expired.terminate()
        expired.wait(timeout=5)
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    process, port = _start_bridge(live_dir, nonce="nonce-live")
    statuses: list[int] = []
    lock = threading.Lock()

    def once() -> None:
        try:
            code = _raw_post(port, nonce="nonce-live")
        except (OSError, http.client.HTTPException):
            code = 0
        with lock:
            statuses.append(code)

    try:
        first = threading.Thread(target=once)
        second = threading.Thread(target=once)
        first.start()
        second.start()
        first.join(timeout=5)
        second.join(timeout=5)
        assert 200 in statuses
        assert 410 in statuses
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_redirect_is_not_followed() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(302)
            self.send_header("Location", "https://example.com/mcp")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        reader = WhopMcpReader(f"http://{host}:{port}/mcp", allow_loopback=True, timeout_s=2)
        with pytest.raises(CampaignError) as rejected:
            reader.initialize()
        assert rejected.value.code == "provider_unavailable"
    finally:
        server.shutdown()
        server.server_close()


def test_build_live_provider_does_not_use_a_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_WHOP_LIVE_SMOKE", "1")
    monkeypatch.setenv("CLIPFORGE_WHOP_CONNECTOR", "public")
    monkeypatch.setenv("CLIPFORGE_WHOP_URL", "https://example.com/mcp")
    with pytest.raises(CampaignError) as denied:
        build_live_provider()
    assert denied.value.code == "provider_unavailable"
    monkeypatch.setenv("CLIPFORGE_WHOP_URL", PUBLIC_MCP_URL)
    provider = build_live_provider()
    assert provider.url == PUBLIC_MCP_URL
