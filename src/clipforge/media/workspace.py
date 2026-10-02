"""Derived files live under the work root. The original source is not one of them."""

from __future__ import annotations

import fcntl
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
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
        """Create the source directories. Refuse a symlink that leaves the work root."""
        root = self.root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        ensure_within(root, root)
        for relative in ("metadata", "audio", "proxy", "logs", "tmp"):
            _mkdir_contained(root, _join(self.source_root, relative))

    def clear_partials(self) -> None:
        """Delete ``*.partial.*`` under this source directory and nowhere else."""
        base = self.source_root
        ensure_within(self.root, base)
        if not base.is_dir() or base.is_symlink():
            return
        for path in _files_without_following_links(base):
            if _PARTIAL_MARKER in path.name:
                safe_unlink(self.root, path)

    def prepare_lock_path(self) -> Path:
        return _join(self.source_root, "tmp", "prepare.lock")


@contextmanager
def prepare_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Hold an exclusive POSIX lock for one source until this context exits.

    The lock file may remain after the process exits. Ownership is the kernel
    lock, not the file's existence. A crash releases it. Another process's
    lock file is not deleted.
    """
    root = workspace.root.resolve()
    lock_path = workspace.prepare_lock_path()
    ensure_within(root, lock_path)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o644)
    except OSError as exc:
        raise MediaError(
            f"could not open the prepare lock for source {workspace.source_asset_id}: {exc}. "
            "A symlink was not followed."
        ) from exc
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MediaError(
                f"another media prepare is already active for source {workspace.source_asset_id}. "
                "Clipforge refused to start a second preparation so partial and final artifacts cannot race."
            ) from exc
        yield lock_path
    finally:
        with suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


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


def _mkdir_contained(root: Path, directory: Path) -> None:
    """Create ``directory`` one component at a time. Do not follow a symlink."""
    root_resolved = root.resolve()
    try:
        relative = directory.relative_to(root)
    except ValueError as exc:
        raise MediaError(f"refusing to create {directory} outside the work root {root_resolved}") from exc
    current = root_resolved
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            resolved = current.resolve()
            raise MediaError(
                f"refusing to follow symlink {current}, which resolves to {resolved}. "
                "Work directories must be real directories inside the work root."
            )
        if current.exists():
            if not current.is_dir():
                raise MediaError(f"{current} exists and is not a directory. Refusing to write through it.")
            ensure_within(root_resolved, current)
            continue
        current.mkdir()
        ensure_within(root_resolved, current)


def _files_without_following_links(base: Path) -> list[Path]:
    found: list[Path] = []
    for child in base.iterdir():
        if child.is_symlink():
            continue
        if child.is_dir():
            found.extend(_files_without_following_links(child))
        elif child.is_file():
            found.append(child)
    return found


def _segment(name: str) -> str:
    if name != Path(name).name or name in {"", ".", ".."}:
        raise MediaError(f"refusing work-directory name {name!r}")
    return name


def _join(parent: Path, *parts: str) -> Path:
    current = parent
    for part in parts:
        current = current / _segment(part)
    return current
