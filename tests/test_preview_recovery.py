"""Failure, lock, and recovery behavior for rough preview rendering."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import pytest

from clipforge.errors import MediaError, StorageError
from clipforge.media.workspace import (
    candidate_lock,
    prepare_lock,
    preview_lock,
    transcribe_lock,
    vision_lock,
)
from clipforge.preview.backend import FakeRoughRenderBackend
from clipforge.preview.constants import KIND_PREVIEW
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.storage import find_artifact, get_job, insert_job, list_jobs
from clipforge.transcription.io import publish_json as real_publish_json
from tests.candidate_support import PROJECT_ID, SOURCE_ID, STAMP
from tests.preview_support import PreviewFixture, mine, ready_stack, render, short_profile

pytestmark = pytest.mark.preview


@pytest.fixture(autouse=True)
def _reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")


def _fixture(tmp_path: Path) -> tuple[PreviewFixture, FakeRoughRenderBackend]:
    fixture = ready_stack(tmp_path)
    mined = mine(fixture, profile=short_profile())
    assert mined.selected_count == 1
    return fixture, FakeRoughRenderBackend()


def _preview_jobs(fixture: PreviewFixture) -> list[JobRecord]:
    with fixture.database.connect() as connection:
        return [job for job in list_jobs(connection, PROJECT_ID) if job.kind == "rough_preview_render"]


def _current_job(fixture: PreviewFixture) -> str | None:
    with fixture.database.connect() as connection:
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_PREVIEW)
    if row is None:
        return None
    return row.job_id


class _FailingBackend(FakeRoughRenderBackend):
    def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
        del batch_path, log_path
        raise MediaError("remotion failed")


class _CancelBackend(FakeRoughRenderBackend):
    def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
        del batch_path, log_path
        raise KeyboardInterrupt


def test_renderer_manifest_and_database_failures_keep_the_previous_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, backend = _fixture(tmp_path)
    first = render(fixture, backend)
    with pytest.raises(MediaError, match="remotion failed"):
        render(fixture, _FailingBackend(), force=True)
    assert _current_job(fixture) == first.job_id
    assert first.manifest_path.is_file()
    assert any(job.status is JobStatus.FAILED for job in _preview_jobs(fixture))

    def fail_manifest(final: Path, model: object, root: Path, partial: Path) -> tuple[str, int]:
        if final.name == "manifest.json":
            raise OSError("manifest failed")
        return real_publish_json(final, model, root, partial)  # type: ignore[arg-type]

    monkeypatch.setattr("clipforge.preview.service.publish_json", fail_manifest)
    with pytest.raises(OSError, match="manifest failed"):
        render(fixture, backend, force=True)
    assert _current_job(fixture) == first.job_id
    monkeypatch.undo()

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise StorageError("database write failed")

    monkeypatch.setattr("clipforge.preview.service.insert_artifact", fail_write)
    monkeypatch.setattr("clipforge.preview.service.update_artifact", fail_write)
    with pytest.raises(StorageError, match="database write failed"):
        render(fixture, backend, force=True)
    assert _current_job(fixture) == first.job_id
    assert JobStatus.RUNNING not in {job.status for job in _preview_jobs(fixture)}


def test_sidecar_failure_restores_previous_and_first_run_deletes_the_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_sidecar(final: Path, model: object, root: Path, partial: Path) -> tuple[str, int]:
        if final.name == "rough-preview.recipe.json":
            raise OSError("sidecar failed")
        return real_publish_json(final, model, root, partial)  # type: ignore[arg-type]

    first_root = tmp_path / "first"
    first_root.mkdir()
    fixture, backend = _fixture(first_root)
    monkeypatch.setattr("clipforge.preview.service.publish_json", fail_sidecar)
    with pytest.raises(MediaError, match="sidecar"):
        render(fixture, backend)
    assert _current_job(fixture) is None
    failed = _preview_jobs(fixture)
    assert failed and all(job.status is JobStatus.FAILED for job in failed)
    assert not fixture.workspace.preview_sidecar().exists()
    monkeypatch.undo()

    kept = render(fixture, backend)
    monkeypatch.setattr("clipforge.preview.service.publish_json", fail_sidecar)
    with pytest.raises(MediaError, match="sidecar"):
        render(fixture, backend, force=True)
    assert _current_job(fixture) == kept.job_id
    assert kept.manifest_path.is_file()
    assert fixture.workspace.preview_sidecar().is_file()


def test_cancellation_marks_the_job_cancelled_and_removes_transient_media(tmp_path: Path) -> None:
    fixture, _backend = _fixture(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        render(fixture, _CancelBackend())
    jobs = _preview_jobs(fixture)
    assert len(jobs) == 1
    assert jobs[0].status is JobStatus.CANCELLED
    assert _current_job(fixture) is None
    runs = [path for path in (fixture.workspace.preview_root() / "runs").iterdir() if path.is_dir()]
    assert len(runs) == 1
    assert not (runs[0] / "staging").exists()
    assert not (runs[0] / "render-batch.json").exists()


def test_stale_preview_job_fails_only_after_the_lock(tmp_path: Path) -> None:
    fixture, backend = _fixture(tmp_path)
    stale = JobRecord(
        job_id="job-stale-preview",
        project_id=PROJECT_ID,
        kind="rough_preview_render",
        status=JobStatus.RUNNING,
        created_at=STAMP,
        updated_at=STAMP,
        payload={"source_asset_id": SOURCE_ID},
    )
    with fixture.database.transaction() as connection:
        insert_job(connection, stale)
    lock = fixture.workspace.preview_lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(target=_hold_exclusive, args=(str(lock), ready, release))
    holder.start()
    ready.wait(5)
    try:
        with pytest.raises(MediaError, match="preview"):
            render(fixture, backend)
        with fixture.database.connect() as connection:
            assert get_job(connection, stale.job_id).status is JobStatus.RUNNING
        assert _current_job(fixture) is None
    finally:
        release.set()
        holder.join(5)
    result = render(fixture, backend)
    with fixture.database.connect() as connection:
        assert get_job(connection, stale.job_id).status is JobStatus.FAILED
    assert result.cache_hit is False
    assert _current_job(fixture) == result.job_id


def test_busy_writers_fail_before_a_preview_job(tmp_path: Path) -> None:
    fixture, backend = _fixture(tmp_path)
    workspace = fixture.workspace
    locks = {
        "media prepare": workspace.prepare_lock_path(),
        "transcription": workspace.transcribe_lock_path(),
        "visual analysis": workspace.vision_lock_path(),
        "candidate mining": workspace.candidate_lock_path(),
        "preview render": workspace.preview_lock_path(),
    }
    for path in locks.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    for label, path in locks.items():
        _expect_blocked(fixture, backend, path, label)
    assert _preview_jobs(fixture) == []


def test_preview_locks_block_upstream_writers(tmp_path: Path) -> None:
    fixture, backend = _fixture(tmp_path)
    workspace = fixture.workspace
    paths = (
        workspace.prepare_lock_path(),
        workspace.transcribe_lock_path(),
        workspace.vision_lock_path(),
        workspace.candidate_lock_path(),
        workspace.preview_lock_path(),
    )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(target=_hold_preview_locks, args=([str(path) for path in paths], ready, release))
    holder.start()
    ready.wait(5)
    try:
        with pytest.raises(MediaError, match="preview"):
            render(fixture, backend)
        for label, locker in (
            ("media prepare", prepare_lock),
            ("transcription", transcribe_lock),
            ("visual analysis", vision_lock),
            ("candidate mining", candidate_lock),
            ("preview render", preview_lock),
        ):
            with pytest.raises(MediaError, match=label), locker(workspace):
                pass
    finally:
        release.set()
        holder.join(5)
    assert _preview_jobs(fixture) == []


def test_unsafe_symlinks_fail_before_a_job(tmp_path: Path) -> None:
    fixture, backend = _fixture(tmp_path)
    outside = tmp_path / "escape"
    outside.mkdir()
    preview_root = fixture.workspace.preview_root()
    os.rename(preview_root, tmp_path / "real-previews")
    preview_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MediaError, match="symlink"):
        render(fixture, backend)
    assert _preview_jobs(fixture) == []
    assert list(outside.iterdir()) == []

    fixture, backend = _fixture(tmp_path / "candidates")
    candidate_root = fixture.workspace.candidate_root()
    os.rename(candidate_root, tmp_path / "real-candidates")
    candidate_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MediaError, match="symlink"):
        render(fixture, backend)
    assert _preview_jobs(fixture) == []
    assert list(outside.iterdir()) == []


def _expect_blocked(
    fixture: PreviewFixture,
    backend: FakeRoughRenderBackend,
    lock_path: Path,
    label: str,
) -> None:
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(target=_hold_exclusive, args=(str(lock_path), ready, release))
    holder.start()
    ready.wait(5)
    try:
        with pytest.raises(MediaError, match=label):
            render(fixture, backend)
    finally:
        release.set()
        holder.join(5)


def _hold_exclusive(path: str, ready: object, release: object) -> None:
    import fcntl

    descriptor = os.open(path, os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    ready.set()  # type: ignore[attr-defined]
    release.wait(30)  # type: ignore[attr-defined]
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def _hold_preview_locks(paths: list[str], ready: object, release: object) -> None:
    import fcntl

    descriptors = [os.open(path, os.O_RDWR) for path in paths]
    modes = (fcntl.LOCK_SH, fcntl.LOCK_SH, fcntl.LOCK_SH, fcntl.LOCK_SH, fcntl.LOCK_EX)
    for descriptor, mode in zip(descriptors, modes, strict=True):
        fcntl.flock(descriptor, mode)
    ready.set()  # type: ignore[attr-defined]
    release.wait(30)  # type: ignore[attr-defined]
    for descriptor in descriptors:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
