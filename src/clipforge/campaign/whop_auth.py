"""Operator Whop sign-in helper. Clipforge does not read the browser profile."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from clipforge.campaign.providers import CampaignError
from clipforge.preview.browser import resolve_browser

_CONNECTOR_COMMAND = ("grok", "mcp", "doctor", "whop")
_OFFICIAL_ENDPOINT = "https://mcp.whop.com/mcp"


def doctor_text() -> str:
    """Report local auth state. This does not open a browser or a socket."""
    browser = "found" if _browser_state() == "found" else "missing"
    profile = _profile_category()
    permissions = _profile_permissions()
    meta = _read_meta()
    lines = [
        f"browser: {browser}",
        f"profile: {profile}",
        f"profile_permissions: {permissions}",
        f"connector: {meta.get('connector', 'not_configured')}",
        "endpoint: official",
        f"session: {meta.get('auth_state', 'missing')}",
        "credentials: not stored",
        "cookies: not read",
        "live_claim: not_claimed",
        f"connector_command: {' '.join(_CONNECTOR_COMMAND)}",
        "socket: not opened",
    ]
    return "\n".join(lines)


def status_text() -> str:
    """Read saved metadata. This does not open a browser or a socket."""
    return doctor_text()


def login() -> str:
    """Prepare the dedicated profile. A missing connector does not open Chrome."""
    directory = _prepare_profile()
    del directory
    state, detail = _connector_state()
    _write_meta(auth_state="auth_required" if state == "auth_required" else state, connector=state)
    if state == "connector_unavailable":
        raise CampaignError("whop connector is unavailable", code="connector_unavailable")
    if state != "authenticated":
        raise CampaignError("whop authorization is required", code="auth_required")
    return detail


def refresh() -> str:
    """Re-check the connector. The dedicated profile is not deleted."""
    if _profile_category() != "configured":
        raise CampaignError("whop profile is missing", code="not_configured")
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
    if meta.is_file() and not meta.is_symlink():
        meta.unlink()
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


def _connector_state() -> tuple[str, str]:
    try:
        completed = subprocess.run(
            list(_CONNECTOR_COMMAND),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CampaignError("whop connector is unavailable", code="connector_unavailable") from exc
    text = f"{completed.stdout}\n{completed.stderr}".lower()
    if "not found" in text or completed.returncode != 0:
        return "connector_unavailable", "connector: not_configured"
    if "auth" in text and "required" in text:
        return "auth_required", "session: auth_required"
    return "authenticated", "session: authenticated"


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
        "connector_command": " ".join(_CONNECTOR_COMMAND),
    }
    path = _state_path()
    partial = path.with_suffix(".json.partial")
    partial.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(partial, path)


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
