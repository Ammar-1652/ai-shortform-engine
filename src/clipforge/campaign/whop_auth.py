"""Operator Whop sign-in helper. Clipforge does not read the browser profile."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from clipforge.campaign.providers import CampaignError
from clipforge.preview.browser import resolve_browser

_PLUGIN_SOURCE = "whopio/plugins#dist/grok/whop"
_OFFICIAL_ENDPOINT = "https://mcp.whop.com/mcp"
_DIAGNOSTIC_COMMAND = "grok mcp doctor whop"
_AUTH_REQUIRED = """Whop authorization is required in Grok.
Open Grok, run /mcps, select Whop, authorize it, then run /whop-connect.
After that, rerun:
clipforge campaign operator whop auth status"""


def doctor_text() -> str:
    """Report local auth state. This does not open a browser or a Whop socket."""
    browser = "found" if _browser_state() == "found" else "missing"
    grok = "found" if grok_executable() is not None else "missing"
    plugin = _plugin_state()
    connector = _local_connector_state()
    smoke = "yes" if os.environ.get("CLIPFORGE_WHOP_LIVE_SMOKE", "").strip() == "1" else "no"
    lines = [
        f"grok: {grok}",
        f"browser: {browser}",
        f"plugin: {plugin}",
        f"connector: {connector}",
        f"authorization: {_authorization_state(plugin, connector)}",
        f"profile: {_profile_category()}",
        f"profile_permissions: {_profile_permissions()}",
        f"endpoint: {_OFFICIAL_ENDPOINT}",
        "live_smoke: not_executed",
        f"live_smoke_configured: {smoke}",
        "credentials: not stored",
        "cookies: not read",
        "live_claim: not_claimed",
        "socket: not opened",
    ]
    return "\n".join(lines)


def status_text() -> str:
    """Read saved metadata. This does not open a browser or a socket."""
    return doctor_text()


def login() -> str:
    """Install the official plugin, then use Grok's authorization flow when it exists."""
    if grok_executable() is None:
        raise CampaignError("Grok executable is missing", code="provider_unavailable")
    _prepare_profile()
    plugin = _plugin_state()
    if plugin == "provider_unavailable":
        raise CampaignError("whop connector is unavailable", code="provider_unavailable")
    if plugin == "plugin_missing":
        _install_plugin()
        if _plugin_state() != "installed":
            raise CampaignError(
                f"Whop plugin install failed. Run: grok plugin install {_PLUGIN_SOURCE}",
                code="plugin_missing",
            )
    if _slash_flow_is_programmable():
        _run_programmatic_authorization()
    return _finish_login()


def refresh() -> str:
    """Reuse the dedicated profile and re-check the official connector."""
    if grok_executable() is None:
        raise CampaignError("Grok executable is missing", code="provider_unavailable")
    if _profile_category() == "missing":
        _prepare_profile()
    state = _doctor_state()
    if state == "authenticated":
        _write_meta(auth_state="authenticated", connector="configured")
        return "authorization: authenticated\nconnector_health: ready\nlive_claim: not_claimed"
    if state == "expired":
        _write_meta(auth_state="expired", connector="configured")
        try:
            return login()
        except CampaignError as exc:
            if exc.code == "auth_required":
                raise CampaignError(f"whop authorization expired\n{_AUTH_REQUIRED}", code="expired") from exc
            raise
    if state == "provider_unavailable":
        raise CampaignError("whop connector is unavailable", code="provider_unavailable")
    return login()


def logout(*, confirmed: bool) -> str:
    """Remove only the dedicated profile after an explicit confirmation."""
    if not confirmed:
        raise CampaignError("whop logout was not confirmed", code="not_confirmed")
    _stop_recorded_browser()
    profile = _profile_path_unchecked()
    if profile.exists() and not profile.is_symlink() and _profile_is_allowed(profile):
        _remove_tree(profile)
    meta = _state_path()
    if meta.is_symlink() or meta.is_file():
        meta.unlink()
    browser = _process_path()
    if browser.is_symlink() or browser.is_file():
        browser.unlink()
    from clipforge.campaign.whop_tools import remove_verified_tool_map

    remove_verified_tool_map()
    return "profile: removed\ncredentials: not stored\nlive_claim: not_claimed"


def launch_login_browser(profile: Path) -> subprocess.Popen[bytes]:
    """Open a visible browser on the dedicated profile. No remote URL is supplied."""
    if profile.is_symlink() or not _profile_is_allowed(profile):
        raise CampaignError("whop profile path is not allowed", code="invalid_document")
    executable = resolve_browser()
    port = _ephemeral_port()
    argv = [
        str(executable),
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--new-window",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        "about:blank",
    ]
    if any(item.startswith("--headless") for item in argv):
        raise CampaignError("whop browser must stay visible", code="browser_unavailable")
    process = subprocess.Popen(argv, start_new_session=True)
    _write_process(process.pid, port)
    return process


def grok_executable() -> Path | None:
    """Return the Grok binary. An override is for tests and must be a real file."""
    override = os.environ.get("CLIPFORGE_GROK_EXECUTABLE", "").strip()
    if override:
        path = Path(override)
        if path.is_file() and not path.is_symlink() and os.access(path, os.X_OK):
            return path
        return None
    found = shutil.which("grok")
    if found is None:
        return None
    path = Path(found)
    if path.is_symlink():
        path = path.resolve()
    return path if path.is_file() and os.access(path, os.X_OK) else None


def _plugin_state() -> str:
    if grok_executable() is None:
        return "plugin_missing"
    try:
        completed = _grok("plugin", "list", timeout=10)
    except CampaignError:
        return "provider_unavailable"
    listed = _listed_name(completed, "whop", empty_markers=("no plugins installed",))
    if listed == "present":
        return "installed"
    if listed == "missing":
        return "plugin_missing"
    return "provider_unavailable"


def _local_connector_state() -> str:
    if grok_executable() is None:
        return "connector_not_configured"
    try:
        completed = _grok("mcp", "list", timeout=10)
    except CampaignError:
        return "provider_unavailable"
    listed = _listed_name(completed, "whop", empty_markers=("no mcp servers configured", "not found"))
    if listed == "present":
        return "configured"
    if listed == "missing":
        return "connector_not_configured"
    return "provider_unavailable"


def _listed_name(
    completed: subprocess.CompletedProcess[str],
    name: str,
    *,
    empty_markers: tuple[str, ...],
) -> str:
    text = f"{completed.stdout}\n{completed.stderr}"
    lowered = text.lower()
    if completed.returncode != 0 or not lowered.strip():
        return "unavailable"
    if any(marker in lowered for marker in empty_markers):
        return "missing"
    saw_token = False
    for line in text.splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        token = parts[0].strip("*`-").lower()
        if not token.replace("-", "").replace("_", "").isalnum():
            return "unavailable"
        saw_token = True
        if token == name:
            return "present"
    if not saw_token:
        return "unavailable"
    return "missing"


def _install_plugin() -> None:
    completed = _grok("plugin", "install", "--trust", _PLUGIN_SOURCE, timeout=60)
    if completed.returncode != 0:
        raise CampaignError(
            f"Whop plugin install failed. Run: grok plugin install {_PLUGIN_SOURCE}",
            code="plugin_missing",
        )


def _slash_flow_is_programmable() -> bool:
    """True only when this Grok build exposes /mcps or /whop-connect as a subcommand."""
    try:
        help_text = _grok("--help", timeout=10)
        agent_help = _grok("agent", "--help", timeout=10)
    except CampaignError:
        return False
    combined = f"{help_text.stdout}\n{help_text.stderr}\n{agent_help.stdout}\n{agent_help.stderr}"
    return _command_listed(combined, "mcps") or _command_listed(combined, "whop-connect")


def _command_listed(help_text: str, name: str) -> bool:
    for line in help_text.splitlines():
        parts = line.strip().split()
        if parts and parts[0] == name:
            return True
    return False


def _run_programmatic_authorization() -> None:
    help_text = _grok("--help", timeout=10)
    agent_help = _grok("agent", "--help", timeout=10)
    combined = "\n".join((help_text.stdout, help_text.stderr, agent_help.stdout, agent_help.stderr))
    ran = False
    if _command_listed(combined, "mcps"):
        _grok("mcps", timeout=600)
        ran = True
    if _command_listed(combined, "whop-connect"):
        _grok("whop-connect", timeout=600)
        ran = True
    if not ran:
        raise CampaignError(_AUTH_REQUIRED, code="auth_required")


def _doctor_state() -> str:
    try:
        completed = _grok("mcp", "doctor", "whop", "--json", timeout=20)
    except CampaignError as exc:
        if "timed out" in str(exc):
            raise
        return "provider_unavailable"
    text = f"{completed.stdout}\n{completed.stderr}".lower()
    if completed.returncode == 0 and ('"ok": true' in text or '"ready": true' in text):
        return "authenticated"
    if "expired" in text and "not expired" not in text:
        return "expired"
    if "not found" in text or "not configured" in text:
        return "connector_not_configured"
    if "unauthorized" in text or "auth_required" in text:
        return "auth_required"
    return "provider_unavailable"


def _finish_login() -> str:
    state = _doctor_state()
    if state == "authenticated":
        _verify_official_session()
        _write_meta(auth_state="authenticated", connector="configured")
        return (
            "authorization: authenticated\n"
            "connector_health: ready\n"
            "live_claim: not_claimed\n"
            "credentials: not stored"
        )
    if state == "expired":
        _write_meta(auth_state="expired", connector="configured")
        raise CampaignError(f"whop authorization expired\n{_AUTH_REQUIRED}", code="expired")
    if state == "provider_unavailable":
        raise CampaignError("whop connector is unavailable", code="provider_unavailable")
    _write_meta(auth_state="auth_required", connector="connector_not_configured")
    raise CampaignError(_AUTH_REQUIRED, code="auth_required")


def _verify_official_session() -> None:
    """Confirm the official endpoint accepts initialize. The session id is not stored."""
    from clipforge.campaign.whop_mcp import PUBLIC_MCP_URL, WhopMcpReader

    reader = WhopMcpReader(PUBLIC_MCP_URL)
    try:
        reader.initialize()
    except CampaignError as exc:
        if exc.code == "auth_required":
            raise CampaignError(_AUTH_REQUIRED, code="auth_required") from exc
        raise
    finally:
        reader.close()


def refresh_tools() -> str:
    """Record a verified tool map only after the official connector is ready."""
    if _doctor_state() != "authenticated":
        raise CampaignError(_AUTH_REQUIRED, code="auth_required")
    from clipforge.campaign.whop_mcp import PUBLIC_MCP_URL, WhopMcpReader
    from clipforge.campaign.whop_tools import (
        mappings_from_tools_list,
        public_descriptions,
        write_verified_tool_map,
    )

    reader = WhopMcpReader(PUBLIC_MCP_URL)
    try:
        reader.initialize()
        tools = reader.list_tools()
    except CampaignError as exc:
        if exc.code == "auth_required":
            raise CampaignError(_AUTH_REQUIRED, code="auth_required") from exc
        raise
    finally:
        reader.close()
    version = reader.server_version or ""
    protocol = reader.protocol_version or ""
    server = reader.server_name or ""
    if not version or not protocol or not server:
        raise CampaignError("whop provider response was malformed", code="malformed_response")
    mappings = mappings_from_tools_list(tools, provider_version=version, protocol_version=protocol)
    accepted = {str(row["tool_name"]) for row in mappings}
    descriptions = {name: text for name, text in public_descriptions(tools).items() if name in accepted}
    digest = write_verified_tool_map(
        mappings,
        server_name=server,
        provider_version=version,
        protocol_version=protocol,
        descriptions=descriptions,
    )
    return f"tool_map_sha256: {digest}\nlive_claim: not_claimed\ncredentials: not stored"


def verify_tools() -> str:
    """Re-read the local map. This does not open a socket."""
    from clipforge.campaign.whop_tools import load_verified_tool_map

    rows, digest = load_verified_tool_map()
    if not rows:
        return "tool_map: missing\nofficial_names_verified: false\nlive_claim: not_claimed"
    return f"tool_map: configured\ntool_map_sha256: {digest}\nlive_claim: not_claimed"


def _authorization_state(plugin: str, connector: str) -> str:
    """Classify local files and local Grok commands. This does not call mcp doctor."""
    if grok_executable() is None or plugin == "provider_unavailable" or connector == "provider_unavailable":
        return "provider_unavailable"
    if plugin != "installed":
        return "plugin_missing"
    if connector != "configured":
        return "connector_not_configured"
    return "auth_required"


def _grok(*args: str, timeout: float) -> subprocess.CompletedProcess[str]:
    executable = grok_executable()
    if executable is None:
        raise CampaignError("Grok executable is missing", code="provider_unavailable")
    limit = float(os.environ.get("CLIPFORGE_GROK_TIMEOUT_S", str(timeout)))
    try:
        return subprocess.run(
            [str(executable), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=limit,
        )
    except subprocess.TimeoutExpired as exc:
        raise CampaignError("whop connector timed out", code="provider_unavailable") from exc
    except OSError as exc:
        raise CampaignError("whop connector is unavailable", code="provider_unavailable") from exc


def _prepare_profile() -> Path:
    path = _checked_profile()
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _checked_profile() -> Path:
    path = _profile_path_unchecked()
    if path.is_symlink() or not _profile_is_allowed(path):
        raise CampaignError("whop profile path is not allowed", code="invalid_document")
    current = path
    while True:
        if current.is_symlink():
            raise CampaignError("whop profile path is not allowed", code="invalid_document")
        if current.parent == current:
            break
        current = current.parent
    return path


def _profile_path_unchecked() -> Path:
    raw = os.environ.get("CLIPFORGE_WHOP_PROFILE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".config" / "clipforge" / "whop-profile"


def _profile_is_allowed(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    repo = Path(__file__).resolve().parents[3]
    work = os.environ.get("CLIPFORGE_WHOP_WORK_ROOT", "").strip()
    banned = [repo.resolve()]
    if work:
        banned.append(Path(work).expanduser().resolve())
    return all(resolved != root and root not in resolved.parents for root in banned)


def _profile_category() -> str:
    try:
        path = _checked_profile()
    except CampaignError:
        return "rejected"
    if path.is_dir() and not path.is_symlink():
        return "configured"
    return "missing"


def _profile_permissions() -> str:
    try:
        path = _checked_profile()
    except CampaignError:
        return "rejected"
    if not path.exists():
        return "missing"
    mode = path.stat().st_mode & 0o777
    if mode == 0o700:
        return "owner_only"
    return "open"


def _browser_state() -> str:
    try:
        resolve_browser()
    except Exception:
        return "missing"
    return "found"


def _state_dir() -> Path:
    raw = os.environ.get("CLIPFORGE_WHOP_STATE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".config" / "clipforge"


def _state_path() -> Path:
    return _state_dir() / "whop-auth.json"


def _process_path() -> Path:
    return _state_dir() / "whop-browser.json"


def _read_meta() -> dict[str, str]:
    path = _state_path()
    if path.is_symlink() or not path.is_file():
        return {"connector": "not_configured", "auth_state": "missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"connector": "not_configured", "auth_state": "unknown"}
    if not isinstance(payload, dict):
        return {"connector": "not_configured", "auth_state": "unknown"}
    return {str(key): str(value) for key, value in payload.items()}


def _write_meta(*, auth_state: str, connector: str) -> None:
    directory = _state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile_version": "1",
        "auth_state": auth_state,
        "connector": connector,
        "endpoint": _OFFICIAL_ENDPOINT,
        "credentials": "not_stored",
        "cookies": "not_read",
        "live_claim": "not_claimed",
        "last_attempt_at": datetime.now(UTC).isoformat(),
        "connector_command": _DIAGNOSTIC_COMMAND,
    }
    path = _state_path()
    if path.is_symlink():
        raise CampaignError("whop profile path is not allowed", code="invalid_document")
    partial = path.with_suffix(".json.partial")
    if partial.is_symlink():
        raise CampaignError("whop profile path is not allowed", code="invalid_document")
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(partial, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)
    os.chmod(partial, 0o600)
    os.replace(partial, path)
    os.chmod(path, 0o600)


def _write_process(pid: int, port: int) -> None:
    directory = _state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"pid": pid, "port": port, "debugging_address": "127.0.0.1"}
    path = _process_path()
    partial = path.with_suffix(".json.partial")
    partial.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(partial, path)


def _stop_recorded_browser() -> None:
    path = _process_path()
    if path.is_symlink() or not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        pid = int(payload["pid"])
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return
    if pid <= 0 or not _owned_browser(pid):
        if path.is_file() and not path.is_symlink():
            path.unlink()
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return
    finally:
        if path.is_file() and not path.is_symlink():
            path.unlink()


def _owned_browser(pid: int) -> bool:
    command = Path(f"/proc/{pid}/cmdline")
    try:
        text = command.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace")
    except OSError:
        return False
    return "--remote-debugging-address=127.0.0.1" in text and "--user-data-dir=" in text


def _ephemeral_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _remove_tree(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()
