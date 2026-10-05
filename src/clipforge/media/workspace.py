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

    def hero_root(self) -> Path:
        return _join(self.source_root, "hero")

    def hero_run_dir(self, hero_set_id: str) -> Path:
        return _join(self.hero_root(), "runs", _segment(hero_set_id))

    def hero_sidecar(self) -> Path:
        return self.metadata_file("hero-draft.recipe.json")

    def hero_lock_path(self) -> Path:
        return _join(self.source_root, "tmp", "hero.lock")

    def hero_candidate_dir(self, hero_set_id: str, candidate_id: str) -> Path:
        return _join(self.hero_run_dir(hero_set_id), "candidates", _segment(candidate_id))

    def hero_alignment_file(self, candidate_id: str) -> Path:
        return _join(self.hero_root(), "alignments", _segment(candidate_id), "alignment.json")

    def hero_plan_file(self, candidate_id: str) -> Path:
        return _join(self.hero_root(), "plans", _segment(candidate_id), "plan.json")

    def advanced_root(self) -> Path:
        return _join(self.source_root, "advanced-hero")

    def advanced_run_dir(self, advanced_set_id: str) -> Path:
        return _join(self.advanced_root(), "runs", _segment(advanced_set_id))

    def advanced_sidecar(self) -> Path:
        return self.metadata_file("advanced-hero.recipe.json")

    def advanced_lock_path(self) -> Path:
        return _join(self.source_root, "tmp", "advanced-hero.lock")

    def advanced_asset_catalog(self) -> Path:
        return self.metadata_file("advanced-assets.json")

    def advanced_asset_file(self, asset_id: str) -> Path:
        return _join(self.advanced_root(), "assets", _segment(asset_id), "media")

    def advanced_plan_file(self, candidate_id: str) -> Path:
        return _join(self.advanced_root(), "plans", _segment(candidate_id), "plan.json")

    def qa_root(self) -> Path:
        return _join(self.source_root, "qa")

    def qa_run_dir(self, qa_set_id: str) -> Path:
        return _join(self.qa_root(), "runs", _segment(qa_set_id))

    def qa_sidecar(self) -> Path:
        return self.metadata_file("qa-set.recipe.json")

    def qa_lock_path(self) -> Path:
        return _join(self.source_root, "tmp", "qa.lock")

    def publish_lock_path(self) -> Path:
        return _join(self.source_root, "tmp", "publish.lock")

    def prepare_qa_file(self, path: Path) -> Path:
        root = self.root.resolve()
        _mkdir_contained(root, self.qa_root())
        _mkdir_contained(root, _join(self.qa_root(), "runs"))
        _mkdir_contained(root, path.parent)
        return path

    def prepare_advanced_file(self, path: Path) -> Path:
        root = self.root.resolve()
        _mkdir_contained(root, self.advanced_root())
        _mkdir_contained(root, path.parent)
        return path

    def make_advanced_run(self, advanced_set_id: str) -> Path:
        self.ensure()
        root = self.root.resolve()
        _mkdir_contained(root, self.advanced_root())
        _mkdir_contained(root, _join(self.advanced_root(), "runs"))
        run = self.advanced_run_dir(advanced_set_id)
        if run.exists() or run.is_symlink():
            raise MediaError(
                f"advanced Hero run {advanced_set_id} already exists. "
                "A new run uses a new id and does not overwrite an existing run."
            )
        _mkdir_contained(root, run)
        _mkdir_contained(root, _join(run, "logs"))
        _mkdir_contained(root, _join(run, "candidates"))
        _mkdir_contained(root, _join(run, "staging"))
        return run

    def prepare_hero_file(self, path: Path) -> Path:
        """Create the parent of one Hero file. Refuse a symlink on the way."""
        root = self.root.resolve()
        _mkdir_contained(root, self.hero_root())
        _mkdir_contained(root, path.parent)
        return path

    def make_hero_candidate_dir(self, hero_set_id: str, candidate_id: str) -> Path:
        directory = self.hero_candidate_dir(hero_set_id, candidate_id)
        _mkdir_contained(self.root.resolve(), directory)
        return directory

    def make_hero_run(self, hero_set_id: str) -> Path:
        """Create one immutable Hero run. Refuse a symlink at any component."""
        self.ensure()
        root = self.root.resolve()
        _mkdir_contained(root, self.hero_root())
        _mkdir_contained(root, _join(self.hero_root(), "runs"))
        run = self.hero_run_dir(hero_set_id)
        if run.exists() or run.is_symlink():
            raise MediaError(
                f"Hero run {hero_set_id} already exists. "
                "A new Hero run uses a new id and does not overwrite an existing run."
            )
        _mkdir_contained(root, run)
        _mkdir_contained(root, _join(run, "logs"))
        _mkdir_contained(root, _join(run, "candidates"))
        _mkdir_contained(root, _join(run, "staging"))
        return run

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
def preview_read_lock(workspace: SourceWorkspace, *, busy: str | None = None) -> Iterator[Path]:
    """Share ``preview.lock`` while a reader needs the current rough preview set."""
    message = busy or (
        f"another rough preview render is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to read the preview set while it can be replaced."
    )
    with _flock(workspace, workspace.preview_lock_path(), exclusive=False, busy=message) as lock_path:
        yield lock_path


@contextmanager
def advanced_hero_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Hold the exclusive per-source advanced Hero lock until this context exits."""
    busy = (
        f"another advanced Hero edit is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to start a second advanced Hero edit."
    )
    with _flock(workspace, workspace.advanced_lock_path(), exclusive=True, busy=busy) as lock_path:
        yield lock_path


@contextmanager
def advanced_read_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Share the advanced Hero lock while QA reads the current advanced set."""
    busy = (
        f"another advanced Hero edit is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to read the advanced set while it can be replaced."
    )
    with _flock(workspace, workspace.advanced_lock_path(), exclusive=False, busy=busy) as lock_path:
        yield lock_path


@contextmanager
def hero_read_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Share the Hero lock while QA reads the current Hero draft."""
    busy = (
        f"another Hero draft is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to read the Hero set while it can be replaced."
    )
    with _flock(workspace, workspace.hero_lock_path(), exclusive=False, busy=busy) as lock_path:
        yield lock_path


@contextmanager
def qa_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Hold the exclusive per-source QA lock until this context exits."""
    busy = (
        f"another QA run is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to start a second QA run."
    )
    with _flock(workspace, workspace.qa_lock_path(), exclusive=True, busy=busy) as lock_path:
        yield lock_path


@contextmanager
def qa_read_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Share the QA lock while delivery reads the current QA set."""
    busy = (
        f"another QA run is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to read the QA set while it can be replaced."
    )
    with _flock(workspace, workspace.qa_lock_path(), exclusive=False, busy=busy) as lock_path:
        yield lock_path


@contextmanager
def publish_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Hold the exclusive per-source delivery lock until this context exits.

    Acquire this only after the shared advanced and QA locks.
    """
    busy = (
        f"another local delivery export is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to start a second export."
    )
    with _flock(workspace, workspace.publish_lock_path(), exclusive=True, busy=busy) as lock_path:
        yield lock_path


@contextmanager
def hero_lock(workspace: SourceWorkspace) -> Iterator[Path]:
    """Hold the exclusive per-source Hero lock until this context exits."""
    busy = (
        f"another Hero draft is already active for source {workspace.source_asset_id}. "
        "Clipforge refused to start a second Hero draft so Hero artifacts cannot race."
    )
    with _flock(workspace, workspace.hero_lock_path(), exclusive=True, busy=busy) as lock_path:
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


def mkdir_contained(root: Path, directory: Path) -> None:
    """Create ``directory`` inside ``root``. A symlink on the way is refused."""
    _mkdir_contained(root.resolve(), directory)


def reject_symlink_chain(path: Path) -> None:
    """Reject a symlink at ``path`` or any parent. The target is not followed."""
    current = path
    while True:
        if current.is_symlink():
            raise MediaError(f"{current.name} is a symlink")
        if current.parent == current:
            return
        current = current.parent


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
