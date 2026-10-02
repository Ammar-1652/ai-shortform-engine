"""Derived files live under the work root. The original source is not one of them."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from clipforge.errors import MediaError

_PARTIAL_MARKER = ".partial."


@dataclass(frozen=True, slots=True)
class SourceWorkspace:
    root: Path
    project_id: str
    source_asset_id: str

    @property
    def source_root(self) -> Path:
        return _join(self.root, "projects", self.project_id, "sources", self.source_asset_id)

    def metadata_file(self, name: str) -> Path:
        return _join(self.source_root, "metadata", _segment(name))

    def audio_file(self, name: str) -> Path:
        return _join(self.source_root, "audio", _segment(name))

    def proxy_file(self, name: str) -> Path:
        return _join(self.source_root, "proxy", _segment(name))

    def log_file(self, name: str) -> Path:
        return _join(self.source_root, "logs", _segment(name))

    def partial_for(self, final: Path) -> Path:
        ensure_within(self.root, final)
        name = f"{final.stem}{_PARTIAL_MARKER}{uuid.uuid4().hex}{final.suffix}"
        return _join(final.parent, name)

    def ensure(self) -> None:
        root = self.root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        for relative in ("metadata", "audio", "proxy", "logs", "tmp"):
            _join(self.source_root, relative).mkdir(parents=True, exist_ok=True)

    def clear_partials(self) -> None:
        """Delete ``*.partial.*`` under this source directory and nowhere else."""
        base = self.source_root
        ensure_within(self.root, base)
        if not base.is_dir():
            return
        for path in base.rglob(f"*{_PARTIAL_MARKER}*"):
            if path.is_file() and _PARTIAL_MARKER in path.name:
                safe_unlink(self.root, path)


def ensure_within(root: Path, path: Path) -> None:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    if path_resolved != root_resolved and root_resolved not in path_resolved.parents:
        raise MediaError(
            f"refusing to touch {path_resolved} because it is outside the work root {root_resolved}"
        )


def safe_unlink(root: Path, path: Path) -> None:
    ensure_within(root, path)
    if not path.is_file():
        return
    path.unlink()


def fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_replace(partial: Path, final: Path, root: Path) -> None:
    ensure_within(root, partial)
    ensure_within(root, final)
    if not partial.is_file():
        raise MediaError(f"partial output is missing, so {final.name} was not published")
    fsync_file(partial)
    os.replace(partial, final)


def _segment(name: str) -> str:
    if name != Path(name).name or name in {"", ".", ".."}:
        raise MediaError(f"refusing work-directory name {name!r}")
    return name


def _join(parent: Path, *parts: str) -> Path:
    current = parent
    for part in parts:
        current = current / _segment(part)
    return current
