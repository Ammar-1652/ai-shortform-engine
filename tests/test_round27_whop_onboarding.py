"""Official Grok onboarding. Fakes stand in for Whop and the Grok CLI."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from clipforge.campaign.providers import CampaignError
from clipforge.campaign.whop_auth import (
    doctor_text,
    login,
    logout,
    refresh,
    refresh_tools,
    status_text,
    verify_tools,
)
from clipforge.campaign.whop_live import (
    FakeWhopProvider,
    discover_live,
    import_discovered,
    verify_discovery,
)
from clipforge.campaign.whop_mcp import PUBLIC_MCP_URL
from clipforge.campaign.whop_provider import OfficialGrokProvider, build_live_provider
from clipforge.campaign.whop_tools import (
    load_tool_map,
    load_verified_tool_map,
    mappings_from_tools_list,
    select_mapped_tool,
    show_verified_tool_map,
    write_verified_tool_map,
)
from clipforge.cli.main import app

runner = CliRunner()
_SOURCE = "whopio/plugins#dist/grok/whop"
_AUTH = (
    "Whop authorization is required in Grok.\n"
    "Open Grok, run /mcps, select Whop, authorize it, then run /whop-connect.\n"
    "After that, rerun:\n"
    "clipforge campaign operator whop auth status"
)


def test_login_installs_the_plugin_before_asking_for_grok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _grok(tmp_path, monkeypatch, "missing-plugin")
    with pytest.raises(CampaignError) as exc:
        login()
    assert exc.value.code == "auth_required"
    assert str(exc.value) == _AUTH
    assert "connector_unavailable" not in str(exc.value)
    lines = log.read_text(encoding="utf-8").splitlines()
    install = next(index for index, line in enumerate(lines) if line.startswith("plugin install "))
    assert lines[install] == f"plugin install --trust {_SOURCE}"
    assert any(line.startswith("mcp doctor") for line in lines[install + 1 :])
    assert not (tmp_path / "state" / "whop-browser.json").exists()
    _assert_no_secrets(tmp_path)


def test_login_with_plugin_and_no_connector_still_onboards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _grok(tmp_path, monkeypatch, "no-connector")
    with pytest.raises(CampaignError) as exc:
        login()
    assert exc.value.code == "auth_required"
    assert str(exc.value) == _AUTH
    text = log.read_text(encoding="utf-8")
    assert "plugin install " not in text
    assert "mcp doctor whop --json" in text
    assert "connector_unavailable" not in str(exc.value)


def test_programmable_login_waits_for_doctor_and_checks_the_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _grok(tmp_path, monkeypatch, "programmable")
    seen = _patch_reader(monkeypatch)
    text = login()
    assert "authorization: authenticated" in text
    assert "connector_health: ready" in text
    assert "live_claim: not_claimed" in text
    assert seen == [PUBLIC_MCP_URL, "initialize"]
    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines.index("mcps") < lines.index("whop-connect")
    assert lines.index("whop-connect") < lines.index("mcp doctor whop --json")
    _assert_no_secrets(tmp_path)


def test_already_authenticated_login_does_not_install_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _grok(tmp_path, monkeypatch, "authenticated")
    _patch_reader(monkeypatch)
    text = login()
    assert text.startswith("authorization: authenticated\n")
    assert "plugin install " not in log.read_text(encoding="utf-8")
    assert (tmp_path / "profile").is_dir()
    assert not (tmp_path / "state" / "whop-browser.json").exists()


def test_doctor_and_status_do_not_open_a_socket_or_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _grok(tmp_path, monkeypatch, "missing-plugin")

    def _refuse_socket(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("socket opened")

    monkeypatch.setattr("socket.socket", _refuse_socket)
    text = doctor_text()
    assert status_text() == text
    assert "socket: not opened" in text
    assert "authorization: plugin_missing" in text
    assert "endpoint: https://mcp.whop.com/mcp" in text
    assert "live_smoke: not_executed" in text
    assert "live_smoke_configured: no" in text
    assert str(tmp_path) not in text
    assert "mcp doctor" not in log.read_text(encoding="utf-8")
    assert not (tmp_path / "profile").exists()


def test_missing_grok_is_provider_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("CLIPFORGE_GROK_EXECUTABLE", str(tmp_path / "missing-grok"))
    with pytest.raises(CampaignError) as exc:
        login()
    assert exc.value.code == "provider_unavailable"
    assert "grok: missing" in doctor_text()
    assert "authorization: provider_unavailable" in doctor_text()


def test_malformed_grok_output_is_not_authenticated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _grok(tmp_path, monkeypatch, "malformed")
    assert "authorization: provider_unavailable" in doctor_text()
    with pytest.raises(CampaignError) as exc:
        login()
    assert exc.value.code == "provider_unavailable"


def test_connector_timeout_and_unavailable_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _grok(tmp_path, monkeypatch, "timeout")
    monkeypatch.setenv("CLIPFORGE_GROK_TIMEOUT_S", "0.2")
    with pytest.raises(CampaignError) as timed:
        refresh()
    assert timed.value.code == "provider_unavailable"
    assert "timed out" in str(timed.value)
    _grok(tmp_path, monkeypatch, "unavailable")
    with pytest.raises(CampaignError) as failed:
        refresh()
    assert failed.value.code == "provider_unavailable"
    assert "authenticated" not in str(failed.value)


def test_expired_refresh_retries_onboarding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = _grok(tmp_path, monkeypatch, "expired")
    with pytest.raises(CampaignError) as exc:
        refresh()
    assert exc.value.code == "expired"
    assert "/mcps" in str(exc.value)
    assert "authorization: authenticated" not in str(exc.value)
    assert "mcp doctor whop --json" in log.read_text(encoding="utf-8")
    assert (tmp_path / "profile").is_dir()


def test_logout_removes_only_the_dedicated_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _grok(tmp_path, monkeypatch, "authenticated")
    profile = tmp_path / "profile"
    profile.mkdir()
    os.chmod(profile, 0o700)
    chrome = tmp_path / "chrome-profile"
    chrome.mkdir()
    kept = chrome / "Cookies"
    kept.write_text("keep", encoding="utf-8")
    (profile / "link").symlink_to(kept)
    work = tmp_path / "work"
    work.mkdir()
    sidecar = work / "campaigns" / "note.json"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text("keep", encoding="utf-8")
    sleeper = os.spawnlp(os.P_NOWAIT, "sleep", "sleep", "30")
    state = tmp_path / "state"
    state.mkdir()
    (state / "whop-browser.json").write_text(json.dumps({"pid": sleeper, "port": 9}), encoding="utf-8")
    _write_map(tmp_path)
    try:
        with pytest.raises(CampaignError) as blocked:
            logout(confirmed=False)
        assert blocked.value.code == "not_confirmed"
        assert kept.read_text(encoding="utf-8") == "keep"
        assert logout(confirmed=True) == "profile: removed\ncredentials: not stored\nlive_claim: not_claimed"
        os.kill(sleeper, 0)
    finally:
        os.kill(sleeper, 15)
    assert not profile.exists()
    assert kept.read_text(encoding="utf-8") == "keep"
    assert sidecar.read_text(encoding="utf-8") == "keep"
    assert not (state / "whop" / "tool-map.json").exists()


def test_login_does_not_kill_an_unrelated_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _grok(tmp_path, monkeypatch, "missing-plugin")
    sleeper = os.spawnlp(os.P_NOWAIT, "sleep", "sleep", "30")
    try:
        with pytest.raises(CampaignError):
            login()
        os.kill(sleeper, 0)
    finally:
        os.kill(sleeper, 15)


def test_tools_refresh_does_not_call_whop_before_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grok(tmp_path, monkeypatch, "missing-plugin")

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("official endpoint contacted")

    monkeypatch.setattr("clipforge.campaign.whop_mcp.WhopMcpReader", _explode)
    with pytest.raises(CampaignError) as exc:
        refresh_tools()
    assert exc.value.code == "auth_required"
    assert not (tmp_path / "state" / "whop" / "tool-map.json").exists()
    assert "tool_map: missing" in verify_tools()


def test_tools_refresh_keeps_only_exact_read_only_campaign_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grok(tmp_path, monkeypatch, "authenticated")
    tools = [
        _tool("read_catalogue"),
        _tool("list_campaigns", annotations={"readOnlyHint": False}),
        _tool("create_campaign"),
        _tool("read_secret", inputSchema=_schema({"token": {"type": "string"}})),
        _tool("read_upload", inputSchema=_schema({"file": {"type": "string"}})),
    ]
    _patch_reader(monkeypatch, tools=tools)
    text = refresh_tools()
    rows, digest = load_verified_tool_map()
    assert [row["tool_name"] for row in rows] == ["read_catalogue"]
    assert f"tool_map_sha256: {digest}" in text
    assert "live_claim: not_claimed" in text
    stored = (tmp_path / "state" / "whop" / "tool-map.json").read_text(encoding="utf-8")
    assert "create_campaign" not in stored
    assert "should-not-be-stored" not in stored
    assert stored.count("https://mcp.whop.com/mcp") == 1
    assert (tmp_path / "state" / "whop" / "tool-map.json").stat().st_mode & 0o777 == 0o600
    shown = show_verified_tool_map()
    assert "read_catalogue" in shown
    assert str(tmp_path) not in shown
    assert load_tool_map() == []


def test_tool_map_rejects_symlinks_open_permissions_and_schema_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    rows = mappings_from_tools_list(
        [_tool("read_catalogue")],
        provider_version="test-1",
        protocol_version="2025-06-18",
    )
    digest = write_verified_tool_map(
        rows,
        server_name="whop",
        provider_version="test-1",
        protocol_version="2025-06-18",
    )
    path = tmp_path / "state" / "whop" / "tool-map.json"
    os.chmod(path, 0o644)
    with pytest.raises(CampaignError) as open_mode:
        load_verified_tool_map()
    assert open_mode.value.code == "invalid_document"
    os.chmod(path, 0o600)
    linked = tmp_path / "state" / "whop" / "linked.json"
    path.replace(linked)
    path.symlink_to(linked)
    with pytest.raises(CampaignError) as symlink:
        load_verified_tool_map()
    assert symlink.value.code == "invalid_document"
    path.unlink()
    linked.replace(path)
    os.chmod(path, 0o600)
    changed = json.loads(json.dumps(_tool("read_catalogue")))
    changed["inputSchema"]["properties"]["language"] = {"type": "string"}
    with pytest.raises(CampaignError) as mismatch:
        select_mapped_tool(
            [changed],
            rows,
            provider_version="test-1",
            protocol_version="2025-06-18",
        )
    assert mismatch.value.code == "schema_mismatch"
    with pytest.raises(CampaignError) as version:
        select_mapped_tool(
            [_tool("read_catalogue")],
            rows,
            provider_version="test-2",
            protocol_version="2025-06-18",
        )
    assert version.value.code == "unsupported_tool"
    assert digest == load_verified_tool_map()[1]


def test_changed_tool_map_and_policy_invalidate_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate(tmp_path, monkeypatch)
    rows = mappings_from_tools_list(
        [_tool("read_catalogue")],
        provider_version="test-1",
        protocol_version="2025-06-18",
    )
    digest = write_verified_tool_map(
        rows,
        server_name="whop",
        provider_version="test-1",
        protocol_version="2025-06-18",
    )
    work = tmp_path / "work"
    work.mkdir()
    provider = FakeWhopProvider()
    provider.tool_map_sha256 = digest
    discovered = import_discovered(work, provider, project_id="project-1")
    assert verify_discovery(work, discovered.discovery_id).tool_map_sha256 == digest
    write_verified_tool_map(
        rows,
        server_name="whop",
        provider_version="test-2",
        protocol_version="2025-06-18",
    )
    with pytest.raises(CampaignError) as stale_map:
        verify_discovery(work, discovered.discovery_id)
    assert stale_map.value.code == "stale_discovery"
    fresh = import_discovered(work, FakeWhopProvider(), project_id="project-2")
    monkeypatch.setattr(
        "clipforge.campaign.whop.current_policy_fingerprint",
        lambda _campaign_id: "f" * 64,
    )
    with pytest.raises(CampaignError) as stale_policy:
        verify_discovery(work, fresh.discovery_id)
    assert stale_policy.value.code == "stale_policy"


def test_secret_and_absolute_path_responses_write_nothing(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    for title in ("bearer secret", "/home/pakka/clip.mp4"):
        payload = FakeWhopProvider().payload
        payload["campaigns"][0]["title"] = title
        with pytest.raises(CampaignError):
            import_discovered(work, FakeWhopProvider(payload), project_id="project-1")
    assert not list(work.rglob("manifest.json"))


def test_loopback_and_forged_providers_cannot_claim_live(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    rows = mappings_from_tools_list(
        [_tool("read_catalogue")],
        provider_version="test-1",
        protocol_version="2025-06-18",
    )
    calls: list[str] = []

    def opener(request: Any, timeout: float = 0) -> _Body:
        del timeout
        headers = {key.lower(): value for key, value in request.header_items()}
        assert "authorization" not in headers
        assert "cookie" not in headers
        payload = json.loads(request.data.decode("utf-8"))
        method = payload["method"]
        calls.append(method)
        if method == "tools/call":
            assert payload["params"]["name"] == "read_catalogue"
            result = {"structuredContent": FakeWhopProvider().payload}
        elif method == "tools/list":
            result = {"tools": [_tool("read_catalogue")]}
        elif method == "initialize":
            result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "whop", "version": "test-1"}}
        else:
            return _Body(b"", status=202)
        body = {"jsonrpc": "2.0", "id": payload.get("id"), "result": result}
        return _Body(json.dumps(body).encode("utf-8"))

    provider = OfficialGrokProvider(
        "http://127.0.0.1/mcp",
        tool_map=rows,
        allow_loopback=True,
        opener=opener,
    )
    discovered = import_discovered(work, provider, project_id="project-1")
    assert calls == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
    assert discovered.evidence_origin == "test_double"
    assert discovered.live_status == "not_configured"
    assert discovered.live_claim == "not_claimed"
    forged = FakeWhopProvider()
    forged.live_claim = "claimed"
    forged.evidence_origin = "authenticated_connector"
    forged.live_status = "authenticated_discovery"
    forged.official_call_completed = True
    forged.url = PUBLIC_MCP_URL
    forged.opener = None
    with pytest.raises(CampaignError) as exc:
        import_discovered(work, forged, project_id="project-1")
    assert exc.value.code == "forged_status"


def test_official_discovery_stops_before_the_endpoint_until_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _grok(tmp_path, monkeypatch, "missing-plugin")
    monkeypatch.setenv("CLIPFORGE_WHOP_LIVE_SMOKE", "1")
    monkeypatch.setenv("CLIPFORGE_WHOP_CONNECTOR", "official-grok")
    work = tmp_path / "work"
    work.mkdir()

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("official endpoint contacted")

    monkeypatch.setattr("clipforge.campaign.whop_mcp.WhopMcpReader", _explode)
    with pytest.raises(CampaignError) as blocked:
        discover_live(work, project_id="project-1", operator_id="operator-1", connector="official-grok")
    assert blocked.value.code == "auth_required"
    assert list(work.rglob("manifest.json")) == []
    result = runner.invoke(
        app,
        [
            "campaign",
            "operator",
            "whop",
            "discover",
            "--live",
            "--connector",
            "official-grok",
            "--project",
            "project-1",
            "--operator",
            "operator-1",
            "--work-dir",
            str(work),
        ],
    )
    assert result.exit_code == 1
    assert "/mcps" in result.stderr
    assert list(work.rglob("manifest.json")) == []
    _grok(tmp_path, monkeypatch, "authenticated")
    monkeypatch.setenv("CLIPFORGE_WHOP_LIVE_SMOKE", "1")
    monkeypatch.setenv("CLIPFORGE_WHOP_CONNECTOR", "official-grok")
    with pytest.raises(CampaignError) as missing_map:
        build_live_provider("official-grok")
    assert missing_map.value.code == "unsupported_tool"
    _write_map(tmp_path)
    provider = build_live_provider("official-grok")
    assert isinstance(provider, OfficialGrokProvider)
    assert provider.url == PUBLIC_MCP_URL
    assert provider.opener is None
    assert provider.live_claim == "not_claimed"
    assert provider.official_call_completed is False


def test_auth_and_tool_commands_from_the_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _grok(tmp_path, monkeypatch, "missing-plugin")
    doctor = runner.invoke(app, ["campaign", "operator", "whop", "auth", "doctor"])
    assert doctor.exit_code == 0
    assert "socket: not opened" in doctor.stdout
    denied = runner.invoke(app, ["campaign", "operator", "whop", "auth", "login"])
    assert denied.exit_code == 1
    assert "/mcps" in denied.stderr
    assert "connector_unavailable" not in denied.stderr
    checked = runner.invoke(app, ["campaign", "operator", "whop", "tools", "verify"])
    assert checked.exit_code == 0
    assert "tool_map: missing" in checked.stdout
    refreshed = runner.invoke(app, ["campaign", "operator", "whop", "tools", "refresh"])
    assert refreshed.exit_code == 1
    assert "/mcps" in refreshed.stderr
    help_text = runner.invoke(app, ["--help"]).stdout
    assert "transcribe" not in help_text
    assert "render" not in help_text
    assert "upload" not in help_text


class _Body:
    def __init__(self, raw: bytes, status: int = 200) -> None:
        self._raw = raw
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def read(self, _size: int = -1) -> bytes:
        return self._raw

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _schema(properties: dict[str, object]) -> dict[str, object]:
    return {"type": "object", "properties": properties, "required": []}


def _tool(name: str, **overrides: object) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "name": name,
        "description": "Read the campaign catalogue",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": _schema({"query": {"type": "string"}}),
        "outputSchema": {
            "type": "object",
            "properties": {"campaigns": {"type": "array"}},
            "required": ["campaigns"],
        },
    }
    tool.update(overrides)
    return tool


def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_WHOP_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("CLIPFORGE_WHOP_STATE_DIR", str(tmp_path / "state"))
    for name in (
        "CLIPFORGE_WHOP_LIVE_SMOKE",
        "CLIPFORGE_WHOP_CONNECTOR",
        "CLIPFORGE_WHOP_URL",
        "CLIPFORGE_WHOP_AUTHORIZED",
        "CLIPFORGE_WHOP_CONNECTOR_URL",
        "CLIPFORGE_WHOP_SESSION_HANDLE",
        "CLIPFORGE_GROK_TIMEOUT_S",
    ):
        monkeypatch.delenv(name, raising=False)


def _grok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str) -> Path:
    _isolate(tmp_path, monkeypatch)
    log = tmp_path / "grok.log"
    executable = tmp_path / "grok"
    executable.write_text(_GROK, encoding="utf-8")
    executable.chmod(0o700)
    monkeypatch.setenv("CLIPFORGE_GROK_EXECUTABLE", str(executable))
    monkeypatch.setenv("CLIPFORGE_FAKE_GROK_LOG", str(log))
    monkeypatch.setenv("CLIPFORGE_FAKE_GROK_SCENARIO", scenario)
    return log


def _write_map(tmp_path: Path) -> None:
    rows = mappings_from_tools_list(
        [_tool("read_catalogue")],
        provider_version="test-1",
        protocol_version="2025-06-18",
    )
    write_verified_tool_map(
        rows,
        server_name="whop",
        provider_version="test-1",
        protocol_version="2025-06-18",
    )
    del tmp_path


def _patch_reader(monkeypatch: pytest.MonkeyPatch, tools: list[dict[str, Any]] | None = None) -> list[str]:
    seen: list[str] = []
    listed = tools or [_tool("read_catalogue")]

    class _Reader:
        def __init__(self, url: str, *_args: object, **_kwargs: object) -> None:
            assert url == PUBLIC_MCP_URL
            seen.append(url)
            self.server_name = "whop"
            self.server_version = "test-1"
            self.protocol_version = "2025-06-18"
            self.session_id = "should-not-be-stored"

        def initialize(self) -> None:
            seen.append("initialize")

        def list_tools(self) -> list[dict[str, Any]]:
            return listed

        def close(self) -> None:
            self.session_id = None

    monkeypatch.setattr("clipforge.campaign.whop_mcp.WhopMcpReader", _Reader)
    return seen


def _assert_no_secrets(tmp_path: Path) -> None:
    blob = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in tmp_path.rglob("*")
        if path.is_file() and path.name != "grok"
    )
    lowered = blob.lower()
    for token in ("bearer ", "cookie=", "password=", "api_key", "should-not-be-stored"):
        assert token not in lowered


_GROK = f"""#!{sys.executable}
import os
import sys
import time
from pathlib import Path

log = Path(os.environ["CLIPFORGE_FAKE_GROK_LOG"])
marker = Path(str(log) + ".installed")
auth = Path(str(log) + ".authorized")
args = sys.argv[1:]
with log.open("a", encoding="utf-8") as handle:
    handle.write(" ".join(args) + "\\n")
scenario = os.environ.get("CLIPFORGE_FAKE_GROK_SCENARIO", "missing-plugin")
if scenario == "timeout" and args[:3] == ["mcp", "doctor", "whop"]:
    time.sleep(5)
if args[:3] == ["plugin", "install", "--trust"]:
    if args[3:] != ["{_SOURCE}"]:
        sys.exit(2)
    marker.write_text("installed", encoding="utf-8")
    sys.exit(0)
if args in (["--help"], ["agent", "--help"]):
    sys.stdout.write("mcps\\nwhop-connect\\n" if scenario == "programmable" else "plugin\\nmcp\\n")
    sys.exit(0)
if args in (["mcps"], ["whop-connect"]):
    auth.write_text("done", encoding="utf-8")
    sys.exit(0)
if args[:2] == ["plugin", "list"]:
    if scenario == "malformed":
        sys.stdout.write("{{broken\\n")
        sys.exit(0)
    installed = marker.exists() or scenario in {{
        "installed",
        "no-connector",
        "authenticated",
        "expired",
        "programmable",
        "unavailable",
        "timeout",
        "malformed-doctor",
    }}
    sys.stdout.write("whop\\n" if installed else "No plugins installed.\\n")
    sys.exit(0)
if args[:2] == ["mcp", "list"]:
    configured = scenario in {{
        "authenticated",
        "expired",
        "programmable",
        "unavailable",
        "timeout",
        "malformed-doctor",
    }}
    sys.stdout.write("whop\\n" if configured else "No MCP servers configured.\\n")
    sys.exit(0)
if args[:3] == ["mcp", "doctor", "whop"]:
    if scenario == "unavailable":
        sys.stdout.write("connection refused\\n")
        sys.exit(1)
    if scenario == "expired":
        sys.stdout.write("authorization expired\\n")
        sys.exit(1)
    if scenario == "malformed-doctor":
        sys.stdout.write("{{broken\\n")
        sys.exit(0)
    ready = scenario == "authenticated" or (scenario == "programmable" and auth.exists())
    if ready:
        sys.stdout.write('{{"ok": true, "ready": true}}\\n')
        sys.exit(0)
    sys.stdout.write("MCP server 'whop' not found.\\n")
    sys.exit(1)
sys.exit(0)
"""
