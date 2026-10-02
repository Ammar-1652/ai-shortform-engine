"""Filesystem locations. Environment variables are read explicitly. `.env` is not auto-loaded."""

from __future__ import annotations

import os
from pathlib import Path

from clipforge.errors import ClipforgeError


def resolve_db_path(explicit: Path | None) -> Path:
    """Return the SQLite path from `--db`, then `DATABASE_PATH`, then `var/clipforge.sqlite3`."""
    if explicit is not None:
        return explicit
    env = os.environ.get("DATABASE_PATH", "").strip()
    if env:
        return Path(env)
    return Path("var") / "clipforge.sqlite3"


def resolve_work_dir(explicit: Path | None = None) -> Path:
    """Return the artifact work directory from the argument, `WORK_ROOT`, or `var/work`."""
    if explicit is not None:
        return explicit
    env = os.environ.get("WORK_ROOT", "").strip()
    if env:
        return Path(env)
    return Path("var") / "work"


def find_repo_root(start: Path | None = None) -> Path:
    """Walk parents until `pyproject.toml` and `src/clipforge` are both present."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "clipforge").is_dir():
            return candidate
    raise ClipforgeError(
        "Could not find the clipforge repository root "
        "(a directory containing pyproject.toml and src/clipforge). "
        "Run the command from the repository, or pass an explicit path."
    )
