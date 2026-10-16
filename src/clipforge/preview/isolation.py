"""One browser render at a time, each with its own temp directory."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_executable
from clipforge.preview.browser import resolve_browser

_LOCK_NAME = "clipforge-browser.lock"
_PREFIX = "cfb"
# sockaddr_un.sun_path holds 108 bytes, including the trailing NUL.
_SOCKET_LIMIT = 108
# Remotion creates puppeteer_dev_chrome_profile-<6> and Chrome adds its singleton dir.
_SOCKET_TAIL = Path("puppeteer_dev_chrome_profile-XXXXXX") / "com.google.Chrome.XXXXXX" / "SingletonSocket"


@contextmanager
def browser_render_lock() -> Iterator[None]:
    """Serialize renders that launch Chrome. The lock file is not a profile."""
    import fcntl

    path = Path(tempfile.gettempdir()) / _LOCK_NAME
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o644)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def chrome_socket_fits(directory: Path) -> bool:
    """True when Chrome can create its singleton socket inside this directory."""
    return len(os.fsencode(directory / _SOCKET_TAIL)) < _SOCKET_LIMIT


def run_remotion_script(script: Path, batch_path: Path, *, log_path: Path) -> None:
    """Launch one renderer. Temp files stay private and Chrome is reaped."""
    if not script.is_file():
        raise MediaError(f"renderer script is missing at {script.name}")
    if batch_path.is_symlink() or log_path.is_symlink():
        raise MediaError("renderer batch or log path is a symlink")
    isolation = _browser_temp_dir()
    caught: BaseException | None = None
    try:
        browser = resolve_browser()
        node = resolve_executable("CLIPFORGE_NODE", "node")
        env = dict(os.environ)
        env["TMPDIR"] = str(isolation)
        env["TMP"] = str(isolation)
        env["TEMP"] = str(isolation)
        deadline_s = _remotion_process_deadline_s(batch_path)
        with browser_render_lock():
            ProcessRunner().run(
                [node, str(script), str(batch_path), str(browser), str(isolation)],
                log_path=log_path,
                env=env,
                reap_group=True,
                timeout_s=deadline_s,
                check=True,
            )
    except BaseException as exc:
        caught = exc
        raise
    finally:
        try:
            if isolation.exists() or isolation.is_symlink():
                _remove_browser_temp(isolation)
        except Exception:
            if caught is None:
                raise


def _temp_base() -> Path:
    base = Path("/tmp")
    if base.is_symlink() or not base.is_dir():
        return Path(tempfile.gettempdir())
    return base


def _remotion_process_deadline_s(batch_path: Path) -> float:
    """Bound bundle + browser lifetime from the declared output-frame budget.

    Remotion's media timeout does not cover a stalled Node bundle or Chrome
    launch. The outer child must therefore have its own deterministic deadline
    and be reaped as one process group. The cap is deliberately generous for a
    60-second portrait draft while ensuring a tiny smoke render cannot wait
    forever.
    """
    try:
        payload = json.loads(batch_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise MediaError("renderer batch could not be read for its process deadline") from exc
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise MediaError("renderer batch has no items for its process deadline")
    frames = 0
    for item in items:
        rendered = item.get("input") if isinstance(item, dict) else None
        duration = rendered.get("duration_in_frames") if isinstance(rendered, dict) else None
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 1:
            raise MediaError("renderer batch has an invalid duration for its process deadline")
        frames += duration
    # 90s covers cold bundling; budget 0.2s per frame thereafter. The upper
    # bound keeps a failed browser process from holding the shared lock forever.
    return float(min(600, max(120, 90 + frames // 5)))


def _browser_temp_dir() -> Path:
    """A private directory short enough for Chrome's singleton socket."""
    base = _temp_base()
    path = Path(tempfile.mkdtemp(prefix=_PREFIX, dir=base))
    if path.is_symlink() or not chrome_socket_fits(path):
        _remove_browser_temp(path)
        raise MediaError("browser temp directory would make the Chrome socket path too long")
    return path


def _remove_browser_temp(path: Path) -> None:
    if path.is_symlink():
        raise MediaError("refusing to remove a symlinked browser temp directory")
    base = _temp_base()
    if path.parent != base or not path.name.startswith(_PREFIX):
        raise MediaError("refusing to remove a browser temp directory outside the temp base")
    shutil.rmtree(path)
