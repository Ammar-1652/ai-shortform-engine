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

    def transcript_file(self) -> Path:
        return _join(self.source_root, "transcript", "transcript.json")

    def transcript_sidecar(self) -> Path:
        return self.metadata_file("transcript.recipe.json")

    def partial_for(self, final: Path) -> Path:
        ensure_within(self.root, final)
        name = f"{final.stem}{_PARTIAL_MARKER}{uuid.uuid4().hex}{final.suffix}"
        return _join(final.parent, name)

    def ensure(self) -> None:
        """Create the source directories. Refuse a symlink that leaves the work root."""
        root = self.root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        ensure_within(root, root)
        for relative in (
            "metadata",
            "audio",
            "proxy",
            "logs",
            "transcript",
            "tmp",
            "vision",
            "candidates",
            "previews",
        ):
            _mkdir_contained(root, _join(self.source_root, relative))
        _mkdir_contained(root, _join(self.vision_root(), "runs"))
        _mkdir_contained(root, _join(self.candidate_root(), "runs"))
        _mkdir_contained(root, _join(self.preview_root(), "runs"))

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

    def transcribe_lock_path(self) -> Path:
        return _join(self.source_root, "tmp", "transcribe.lock")

    def vision_root(self) -> Path:
        return _join(self.source_root, "vision")

    def vision_run_dir(self, analysis_id: str) -> Path:
        return _join(self.vision_root(), "runs", _segment(analysis_id))

    def vision_sidecar(self) -> Path:
        return self.metadata_file("visual-analysis.recipe.json")

    def vision_lock_path(self) -> Path:
        return _join(self.source_root, "tmp", "vision.lock")

    def candidate_root(self) -> Path:
        return _join(self.source_root, "candidates")

    def candidate_run_dir(self, mining_id: str) -> Path:
        return _join(self.candidate_root(), "runs", _segment(mining_id))

    def candidate_sidecar(self) -> Path:
        return self.metadata_file("candidate-mining.recipe.json")

    def candidate_lock_path(self) -> Path:
        return _join(self.source_root, "tmp", "candidate.lock")

    def preview_root(self) -> Path:
        return _join(self.source_root, "previews")

    def preview_run_dir(self, preview_set_id: str) -> Path:
        return _join(self.preview_root(), "runs", _segment(preview_set_id))

    def preview_sidecar(self) -> Path:
        return self.metadata_file("rough-preview.recipe.json")

    def preview_lock_path(self) -> Path:
        return _join(self.source_root, "tmp", "preview.lock")

    def preview_candidate_dir(self, preview_set_id: str, candidate_id: str) -> Path:
        """One candidate directory inside a preview run. The id is a path segment, not a path."""
        return _join(self.preview_run_dir(preview_set_id), "candidates", _segment(candidate_id))

    def make_preview_run(self, preview_set_id: str) -> Path:
        """Create one immutable preview run. Refuse a symlink at any component."""
        self.ensure()
        root = self.root.resolve()
        run = self.preview_run_dir(preview_set_id)
        if run.exists() or run.is_symlink():
            raise MediaError(
                f"rough preview run {preview_set_id} already exists. "
                "A new preview run uses a new id and does not overwrite an existing run."
            )
        _mkdir_contained(root, run)
        _mkdir_contained(root, _join(run, "logs"))
        _mkdir_contained(root, _join(run, "candidates"))
        _mkdir_contained(root, _join(run, "staging"))
        return run

    def make_candidate_run(self, mining_id: str) -> Path:
        """Create one immutable candidate run. Refuse a symlink at any component."""
        self.ensure()
        root = self.root.resolve()
        run = self.candidate_run_dir(mining_id)
        if run.exists() or run.is_symlink():
            raise MediaError(
                f"candidate mining run {mining_id} already exists. "
                "A new mining run uses a new id and does not overwrite an existing run."
            )
        _mkdir_contained(root, run)
        _mkdir_contained(root, _join(run, "logs"))
        return run

    def make_vision_run(self, analysis_id: str) -> Path:
        """Create one immutable run directory. Refuse a symlink at any component."""
        self.ensure()
        root = self.root.resolve()
        run = self.vision_run_dir(analysis_id)
        if run.exists() or run.is_symlink():
            raise MediaError(
                f"visual analysis run {analysis_id} already exists. "
                "A new analysis uses a new id and does not overwrite an existing run."
            )
        _mkdir_contained(root, run)
        for name in ("frames", "contact-sheets", "logs"):
            _mkdir_contained(root, _join(run, name))
        return run


@contextmanager
def prepare_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Hold an exclusive POSIX lock for one source until this context exits.

    The lock file may remain after the process exits. Ownership is the kernel
    lock, not the file's existence. A crash releases it. Another process's
    lock file is not deleted.
    """
    busy = (
        f"another media prepare is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to start a second preparation so partial and final artifacts cannot race."
    )
    with _flock(workspace, workspace.prepare_lock_path(), exclusive=True, busy=busy) as lock_path:
        yield lock_path


@contextmanager
def prepare_read_lock(workspace: SourceWorkspace, *, busy: str | None = None) -> Iterator[Path]:
    """Share ``prepare.lock`` while a reader needs the current derived media.

    Media prepare takes the same file exclusively. A reader that holds this
    shared lock blocks replacement of ``audio/asr.flac`` and ``proxy/analysis.mp4``.
    Acquire this before the caller's exclusive lock. Never acquire them in the
    other order.
    """
    message = busy or (
        f"another media prepare is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to start transcription so the ASR audio cannot be replaced during inference."
    )
    with _flock(workspace, workspace.prepare_lock_path(), exclusive=False, busy=message) as lock_path:
        yield lock_path


@contextmanager
def vision_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Hold the exclusive per-source visual-analysis lock until this context exits."""
    busy = (
        f"another visual analysis is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to start a second visual analysis so evidence artifacts cannot race."
    )
    with _flock(workspace, workspace.vision_lock_path(), exclusive=True, busy=busy) as lock_path:
        yield lock_path


@contextmanager
def transcribe_read_lock(workspace: SourceWorkspace, *, busy: str | None = None) -> Iterator[Path]:
    """Share ``transcribe.lock`` while a reader needs the current transcript.

    Acquire this only after the shared prepare lock. An exclusive transcription
    cannot start while this shared lock is held.
    """
    message = busy or (
        f"another transcription is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to read the transcript while it can be replaced."
    )
    with _flock(workspace, workspace.transcribe_lock_path(), exclusive=False, busy=message) as lock_path:
        yield lock_path


@contextmanager
def vision_read_lock(workspace: SourceWorkspace, *, busy: str | None = None) -> Iterator[Path]:
    """Share ``vision.lock`` while a reader needs the current visual analysis.

    Acquire this only after the shared prepare lock and the shared transcription
    lock. An exclusive visual analysis cannot start while this shared lock is held.
    """
    message = busy or (
        f"another visual analysis is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to read the visual analysis while it can be replaced."
    )
    with _flock(workspace, workspace.vision_lock_path(), exclusive=False, busy=message) as lock_path:
        yield lock_path


@contextmanager
def candidate_read_lock(workspace: SourceWorkspace, *, busy: str | None = None) -> Iterator[Path]:
    """Share ``candidate.lock`` while a reader needs the current candidate set.

    Acquire this only after the shared prepare, transcription, and vision locks.
    An exclusive candidate mining run cannot start while this shared lock is held.
    """
    message = busy or (
        f"another candidate mining run is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to read the candidate set while it can be replaced."
    )
    with _flock(workspace, workspace.candidate_lock_path(), exclusive=False, busy=message) as lock_path:
        yield lock_path


@contextmanager
def preview_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Hold the exclusive per-source rough-preview lock until this context exits."""
    busy = (
        f"another rough preview render is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to start a second preview render so preview artifacts cannot race."
    )
    with _flock(workspace, workspace.preview_lock_path(), exclusive=True, busy=busy) as lock_path:
        yield lock_path


@contextmanager
def candidate_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Hold the exclusive per-source candidate-mining lock until this context exits."""
    busy = (
        f"another candidate mining run is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to start a second mining run so candidate artifacts cannot race."
    )
    with _flock(workspace, workspace.candidate_lock_path(), exclusive=True, busy=busy) as lock_path:
        yield lock_path


@contextmanager
def transcribe_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Hold the exclusive per-source transcription lock until this context exits."""
    busy = (
        f"another transcription is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to start a second transcription so transcript artifacts cannot race."
    )
    with _flock(workspace, workspace.transcribe_lock_path(), exclusive=True, busy=busy) as lock_path:
        yield lock_path


@contextmanager
def _flock(workspace: SourceWorkspace, lock_path: Path, *, exclusive: bool, busy: str) -> Iterator[Path]:
    root = workspace.root.resolve()
    ensure_within(root, lock_path)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o644)
    except OSError as exc:
        raise MediaError(
            f"could not open {lock_path.name} for source {workspace.source_asset_id}: {exc}. "
            "A symlink was not followed."
        ) from exc
    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    try:
        try:
            fcntl.flock(descriptor, mode | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MediaError(busy) from exc
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
