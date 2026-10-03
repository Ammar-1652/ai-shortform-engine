"""Resolve a local browser for Remotion. This does not download one."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from clipforge.errors import MediaError

_NAMES = ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")


def resolve_browser() -> Path:
    """Return a regular executable browser. ``CLIPFORGE_BROWSER_EXECUTABLE`` wins."""
    override = os.environ.get("CLIPFORGE_BROWSER_EXECUTABLE", "").strip()
    if override:
        return _executable(Path(override), label="CLIPFORGE_BROWSER_EXECUTABLE")
    for name in _NAMES:
        found = shutil.which(name)
        if found:
            return _executable(Path(found), label=name)
    raise MediaError(
        "no usable local browser was found for rough preview rendering. "
        "Install Google Chrome or Chromium, or set CLIPFORGE_BROWSER_EXECUTABLE "
        "to the browser binary. Clipforge does not download a browser."
    )


def browser_report() -> tuple[str, str]:
    """Return ``(status, detail)`` without launching the browser."""
    try:
        path = resolve_browser()
    except MediaError as exc:
        return "FAIL", str(exc)
    return "PASS", str(path)


def _executable(path: Path, *, label: str) -> Path:
    if any(part in {".", ".."} for part in path.parts):
        raise MediaError(f"{label} path {path} is not a direct executable path")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise MediaError(f"{label} browser path {path} could not be resolved: {exc}") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise MediaError(f"{label} browser {resolved} is not a regular file. A symlink was not used.")
    if not os.access(resolved, os.X_OK):
        raise MediaError(f"{label} browser {resolved} is not executable")
    return resolved
