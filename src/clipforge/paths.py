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
    """Return the artifact work directory.

    Order: explicit argument, ``CLIPFORGE_WORK_ROOT``, ``WORK_ROOT``, then ``var/work``.
    The default stays ``var/work`` because that is the repository convention.
    """
    if explicit is not None:
        return explicit
    clipforge_root = os.environ.get("CLIPFORGE_WORK_ROOT", "").strip()
    if clipforge_root:
        return Path(clipforge_root)
    env = os.environ.get("WORK_ROOT", "").strip()
    if env:
        return Path(env)
    return Path("var") / "work"


def resolve_model_root(explicit: Path | None = None) -> Path:
    """Return the model cache directory.

    Order: explicit argument, ``CLIPFORGE_MODEL_ROOT``, then ``var/models``.
    Model weights stay out of the work root and out of git.
    """
    if explicit is not None:
        return explicit
    env = os.environ.get("CLIPFORGE_MODEL_ROOT", "").strip()
    if env:
        return Path(env)
    return Path("var") / "models"


def resolve_disk_reserve_bytes(explicit: int | None = None) -> int:
    """Return the free-space reserve in bytes. The default is 10 GiB.

    ``CLIPFORGE_DISK_RESERVE_GB`` is a non-negative number of gibibytes.
    There is no flag that disables the check.
    """
    gibibyte = 1024**3
    if explicit is not None:
        if explicit < 0:
            raise ClipforgeError("disk reserve must be zero or a positive number of bytes")
        return explicit
    raw = os.environ.get("CLIPFORGE_DISK_RESERVE_GB", "").strip()
    if not raw:
        return 10 * gibibyte
    try:
        value = float(raw)
    except ValueError as exc:
        raise ClipforgeError(
            "CLIPFORGE_DISK_RESERVE_GB must be a number of gibibytes, "
            f"for example 10. The current value is {raw!r}."
        ) from exc
    if value < 0:
        raise ClipforgeError("CLIPFORGE_DISK_RESERVE_GB must be zero or positive")
    return int(value * gibibyte)


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
