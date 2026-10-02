"""Candidate mining against stored transcript and visual artifacts. No video decode."""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.candidates.constants import JOB_CANDIDATE, KIND_CANDIDATE
from clipforge.candidates.engine import reset_stage_calls, stage_calls
from clipforge.candidates.service import default_profile, mine_source
from clipforge.candidates.show import format_candidate, format_candidate_list, load_candidate_document
from clipforge.candidates.verify import verify_candidate
from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_to_file_uri
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.project import Project
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import (
    Database,
    find_artifact,
    get_job,
    insert_artifact,
    insert_asset_license_record,
    insert_job,
    insert_project,
    insert_source_asset,
    insert_source_manifest,
    list_jobs,
    update_job,
)
from clipforge.transcription.io import dump_json
from tests.candidate_support import (
    PROJECT_ID,
    SOURCE_ID,
    STAMP,
    manifest,
    owned_license,
    segment,
    source_asset,
    transcript_document,
    transcript_job,
    transcript_sidecar,
    visual_document,
    visual_job,
    visual_sidecar,
)

pytestmark = pytest.mark.candidate
runner = CliRunner()


def _reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")


def _ready(
    tmp_path: Path,
    *,
    segments: list[object] | None = None,
    duration_us: int = 90_000_000,
    faces: bool = False,
) -> tuple[Database, Path]:
    work = tmp_path / "work"
    source_file = tmp_path / "source.bin"
    source_file.write_bytes(b"source-bytes")
    source_sha = sha256_file(source_file)
    stat = source_file.stat()
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    workspace = SourceWorkspace(work, PROJECT_ID, SOURCE_ID)
    workspace.ensure()
    asr = workspace.audio_file("asr.flac")
    asr.write_bytes(b"asr-bytes")
    proxy = workspace.proxy_file("analysis.mp4")
    proxy.write_bytes(b"proxy-bytes")
    asr_sha = sha256_file(asr)
    proxy_sha = sha256_file(proxy)
    spoken = (
        segments
        if segments is not None
        else [segment(0, 0, 30_000_000, "A clear sentence explains the whole method from start to finish.")]
    )
    transcript = transcript_document(spoken, duration_us, asr_sha256=asr_sha)  # type: ignore[arg-type]
    run = workspace.make_vision_run("analysis-1")
    visual = visual_document(
        duration_us,
        [(0, duration_us)],
        source_sha256=source_sha,
        proxy_sha256=proxy_sha,
        faces=faces,
        run_dir=run,
    )
    transcript_path = workspace.transcript_file()
    transcript_path.write_text(dump_json(transcript), encoding="utf-8")
    analysis_path = run / "analysis.json"
    analysis_path.write_text(dump_json(visual), encoding="utf-8")
    transcript_record = transcript_sidecar(
        transcript,
        source_sha256=source_sha,
        digest=sha256_file(transcript_path),
        size=transcript_path.stat().st_size,
    )
    visual_record = visual_sidecar(
        visual,
        digest=sha256_file(analysis_path),
        size=analysis_path.stat().st_size,
    )
    workspace.transcript_sidecar().write_text(dump_json(transcript_record), encoding="utf-8")
    workspace.vision_sidecar().write_text(dump_json(visual_record), encoding="utf-8")
    project = Project(
        project_id=PROJECT_ID,
        name="Candidate",
        created_at=STAMP,
        provenance=ArtifactProvenance(
            created_at=STAMP,
            created_by="tester",
            tool="pytest",
            tool_version="0.1.0",
        ),
    )
    with database.transaction() as connection:
        insert_project(connection, project)
        insert_asset_license_record(connection, owned_license())
        insert_source_asset(connection, source_asset(path_to_file_uri(source_file)))
        insert_source_manifest(connection, manifest(source_sha, stat.st_size, stat.st_mtime_ns, duration_us))
        insert_job(connection, transcript_job(transcript, source_sha))
        insert_job(connection, visual_job(visual))
        insert_artifact(
            connection,
            artifact_id="artifact-transcript",
            project_id=PROJECT_ID,
            job_id=transcript.provenance.job_id,
            source_asset_id=SOURCE_ID,
            kind="transcript_json",
            uri=path_to_file_uri(transcript_path),
            provenance=transcript.provenance,
        )
        insert_artifact(
            connection,
            artifact_id="artifact-visual",
            project_id=PROJECT_ID,
            job_id=visual.provenance.job_id,
            source_asset_id=SOURCE_ID,
            kind="visual_analysis_json",
            uri=path_to_file_uri(analysis_path),
            provenance=visual.provenance,
        )
    return database, work


def _mine(database: Database, work: Path, **kwargs: object):
    return mine_source(database=database, source_asset_id=SOURCE_ID, work_root=work, **kwargs)  # type: ignore[arg-type]


def _candidate_jobs(database: Database) -> list[JobRecord]:
    with database.connect() as connection:
        return [job for job in list_jobs(connection, PROJECT_ID) if job.kind == JOB_CANDIDATE]


def test_help_states_heuristics_without_the_transcribe_word() -> None:
    top = runner.invoke(app, ["--help"])
    assert top.exit_code == 0
    assert "candidate" in top.stdout
    assert "transcribe" not in top.stdout
    group = runner.invoke(app, ["candidate", "--help"])
    text = group.stdout.casefold()
    assert "heuristic" in text
    assert "edit opportunity" in text
    assert "virality" in text
    assert "publish" in text
    show = runner.invoke(app, ["candidate", "show", "--help"])
    assert "provisional" in show.stdout.casefold()


def test_mine_caches_and_verify_lists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    reset_stage_calls()
    first = _mine(database, work)
    called = stage_calls()
    assert first.cache_hit is False
    assert called["windows"] == 1 and called["score"] == 1 and called["dedupe"] == 1
    assert first.selected_count >= 1
    report = verify_candidate(database=database, source_asset_id=SOURCE_ID, work_root=work)
    assert report.status == "PASS"
    second = _mine(database, work)
    assert second.cache_hit is True
    assert second.job_id == first.job_id
    assert stage_calls() == called
    document = load_candidate_document(database, SOURCE_ID, work)
    listed = format_candidate_list(document)
    assert document.candidates[0].candidate_id in listed
    assert "virality" not in listed.casefold()
    shown = format_candidate(document, document.candidates[0].candidate_id)
    assert "provisional" in shown
    assert "quality_score:" in shown
    doctor = runner.invoke(app, ["candidate", "doctor", "--work-dir", str(work)])
    assert doctor.exit_code == 0
    assert "candidate-mining" in doctor.stdout
    assert "schema_version: 4" in doctor.stdout


def test_force_keeps_the_previous_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    first = _mine(database, work)
    second = _mine(database, work, force=True)
    assert second.cache_hit is False
    assert second.mining_id != first.mining_id
    assert second.job_id != first.job_id
    assert first.candidate_path.is_file()
    assert second.candidate_path.is_file()
    assert first.candidate_path != second.candidate_path


def test_profile_change_misses_the_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    first = _mine(database, work)
    changed = default_profile().model_copy(update={"max_candidates": 10, "soft_target_min": 10})
    second = _mine(database, work, profile=changed)
    assert second.cache_hit is False
    assert second.job_id != first.job_id
    assert second.selected_count <= 10


def test_transcript_and_visual_changes_invalidate_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    first = _mine(database, work)
    workspace = SourceWorkspace(work, PROJECT_ID, SOURCE_ID)
    transcript_path = workspace.transcript_file()
    original = transcript_path.read_text(encoding="utf-8")
    transcript_path.write_text(original.replace("clear sentence", "fresh sentence"), encoding="utf-8")
    assert verify_candidate(database=database, source_asset_id=SOURCE_ID, work_root=work).status == "FAIL"
    with pytest.raises(MediaError, match="transcript"):
        _mine(database, work)
    transcript_path.write_text(original, encoding="utf-8")
    assert _mine(database, work).cache_hit is True
    visual_row = None
    with database.connect() as connection:
        visual_row = find_artifact(connection, PROJECT_ID, SOURCE_ID, "visual_analysis_json")
    assert visual_row is not None
    from clipforge.media.local_file import path_from_file_uri

    visual_path = path_from_file_uri(visual_row.uri)
    visual_original = visual_path.read_text(encoding="utf-8")
    visual_path.write_text(visual_original.replace("analysis-1", "analysis-9"), encoding="utf-8")
    assert verify_candidate(database=database, source_asset_id=SOURCE_ID, work_root=work).status == "FAIL"
    with pytest.raises(MediaError, match="visual"):
        _mine(database, work)
    visual_path.write_text(visual_original, encoding="utf-8")
    assert first.candidate_path.is_file()


def test_source_mutation_blocks_mining(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    _mine(database, work)
    source = tmp_path / "source.bin"
    source.write_bytes(b"source-bytes-changed")
    assert verify_candidate(database=database, source_asset_id=SOURCE_ID, work_root=work).status == "FAIL"
    before = len(_candidate_jobs(database))
    with pytest.raises(MediaError, match="changed"):
        _mine(database, work)
    assert len(_candidate_jobs(database)) == before


def test_failed_upstream_jobs_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    _mine(database, work)
    with database.connect() as connection:
        job = get_job(connection, "job-transcript")
    failed = job.model_copy(
        update={"status": JobStatus.FAILED, "error_message": "upstream failed", "updated_at": job.created_at}
    )
    with database.transaction() as connection:
        update_job(connection, failed)
    assert verify_candidate(database=database, source_asset_id=SOURCE_ID, work_root=work).status == "FAIL"
    with pytest.raises(MediaError, match="transcript"):
        _mine(database, work, force=True)
    restored = job.model_copy(update={"status": JobStatus.SUCCEEDED, "error_message": None})
    with database.transaction() as connection:
        update_job(connection, restored)
        visual = get_job(connection, "job-visual")
        update_job(
            connection,
            visual.model_copy(
                update={
                    "status": JobStatus.FAILED,
                    "error_message": "visual failed",
                    "updated_at": visual.created_at,
                }
            ),
        )
    assert verify_candidate(database=database, source_asset_id=SOURCE_ID, work_root=work).status == "FAIL"
    with pytest.raises(MediaError, match="visual"):
        _mine(database, work, force=True)


def test_missing_transcript_and_unknown_rights_insert_no_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    with database.transaction() as connection:
        connection.execute("DELETE FROM artifacts WHERE kind = 'transcript_json'")
    with pytest.raises(MediaError, match="transcript run"):
        _mine(database, work)
    assert _candidate_jobs(database) == []


def test_symlink_candidate_directory_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    workspace = SourceWorkspace(work, PROJECT_ID, SOURCE_ID)
    target = tmp_path / "escape"
    target.mkdir()
    root = workspace.candidate_root()
    os.rename(root, tmp_path / "real-candidates")
    root.symlink_to(target, target_is_directory=True)
    with pytest.raises(MediaError, match="symlink"):
        _mine(database, work)
    assert _candidate_jobs(database) == []
    assert list(target.iterdir()) == []


def test_stale_running_job_is_failed_after_the_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    stale = JobRecord(
        job_id="job-stale-candidate",
        project_id=PROJECT_ID,
        kind=JOB_CANDIDATE,
        status=JobStatus.RUNNING,
        created_at=STAMP,
        updated_at=STAMP,
        payload={"source_asset_id": SOURCE_ID},
    )
    with database.transaction() as connection:
        insert_job(connection, stale)
    result = _mine(database, work)
    with database.connect() as connection:
        stored = get_job(connection, stale.job_id)
    assert stored.status is JobStatus.FAILED
    assert result.cache_hit is False


def test_generator_and_sidecar_failures_keep_the_previous_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    first = _mine(database, work)
    original = first.candidate_path.read_bytes()

    def explode(*_args: object, **_kwargs: object) -> None:
        raise MediaError("window generation failed")

    monkeypatch.setattr("clipforge.candidates.service.mine_documents", explode)
    with pytest.raises(MediaError, match="window generation"):
        _mine(database, work, force=True)
    assert first.candidate_path.read_bytes() == original
    with database.connect() as connection:
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_CANDIDATE)
        statuses = {job.status for job in list_jobs(connection, PROJECT_ID) if job.kind == JOB_CANDIDATE}
    assert row is not None and row.job_id == first.job_id
    assert JobStatus.RUNNING not in statuses
    assert JobStatus.FAILED in statuses

    from clipforge.candidates.engine import mine_documents as real_mine
    from clipforge.transcription.io import publish_json as real_publish

    monkeypatch.setattr("clipforge.candidates.service.mine_documents", real_mine)
    real = real_publish
    calls = {"count": 0}

    def fail_sidecar(*args: object, **kwargs: object) -> tuple[str, int]:
        calls["count"] += 1
        if calls["count"] >= 2:
            raise MediaError("sidecar failed")
        return real(*args, **kwargs)  # type: ignore[no-any-return]

    monkeypatch.setattr("clipforge.candidates.service.publish_json", fail_sidecar)
    with pytest.raises(MediaError, match="sidecar"):
        _mine(database, work, force=True)
    assert first.candidate_path.read_bytes() == original
    with database.connect() as connection:
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_CANDIDATE)
        running = [
            job
            for job in list_jobs(connection, PROJECT_ID)
            if job.kind == JOB_CANDIDATE and job.status is JobStatus.RUNNING
        ]
    assert row is not None and row.job_id == first.job_id
    assert running == []


def test_cancellation_closes_the_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    first = _mine(database, work)

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt("interrupted")

    monkeypatch.setattr("clipforge.candidates.service.mine_documents", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _mine(database, work, force=True)
    with database.connect() as connection:
        statuses = {job.status for job in list_jobs(connection, PROJECT_ID) if job.kind == JOB_CANDIDATE}
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_CANDIDATE)
    assert JobStatus.CANCELLED in statuses
    assert JobStatus.RUNNING not in statuses
    assert row is not None and row.job_id == first.job_id


def test_mismatched_bytes_fail_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    result = _mine(database, work)
    result.candidate_path.write_text(result.candidate_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert verify_candidate(database=database, source_asset_id=SOURCE_ID, work_root=work).status == "FAIL"
    recomputed = _mine(database, work)
    assert recomputed.cache_hit is False
    assert recomputed.job_id != result.job_id


def test_active_prepare_blocks_before_a_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    workspace = SourceWorkspace(work, PROJECT_ID, SOURCE_ID)
    workspace.prepare_lock_path().touch()
    _hold_and_expect(database, work, workspace.prepare_lock_path(), None, None, "candidate mining")


def test_active_transcription_and_vision_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    workspace = SourceWorkspace(work, PROJECT_ID, SOURCE_ID)
    for path in (workspace.prepare_lock_path(), workspace.transcribe_lock_path(), workspace.vision_lock_path()):
        path.touch()
    _hold_and_expect(
        database,
        work,
        workspace.prepare_lock_path(),
        workspace.transcribe_lock_path(),
        None,
        "candidate mining",
        shared_prepare=True,
        exclusive_second=True,
    )
    _hold_and_expect(
        database,
        work,
        workspace.prepare_lock_path(),
        workspace.vision_lock_path(),
        None,
        "candidate mining",
        shared_prepare=True,
        exclusive_second=True,
    )


def test_second_candidate_and_writer_locks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    workspace = SourceWorkspace(work, PROJECT_ID, SOURCE_ID)
    for path in (
        workspace.prepare_lock_path(),
        workspace.transcribe_lock_path(),
        workspace.vision_lock_path(),
        workspace.candidate_lock_path(),
    ):
        path.touch()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_candidate_locks,
        args=(
            str(workspace.prepare_lock_path()),
            str(workspace.transcribe_lock_path()),
            str(workspace.vision_lock_path()),
            str(workspace.candidate_lock_path()),
            ready,
            release,
        ),
    )
    holder.start()
    ready.wait(5)
    try:
        with pytest.raises(MediaError, match="second mining run"):
            _mine(database, work)
        with pytest.raises(MediaError, match="transcription"):
            from clipforge.media.workspace import transcribe_lock

            with transcribe_lock(workspace):
                pass
        with pytest.raises(MediaError, match="visual analysis"):
            from clipforge.media.workspace import vision_lock

            with vision_lock(workspace):
                pass
    finally:
        release.set()
        holder.join(5)
    assert _candidate_jobs(database) == []


def _hold_and_expect(
    database: Database,
    work: Path,
    first: Path,
    second: Path | None,
    third: Path | None,
    match: str,
    *,
    shared_prepare: bool = False,
    exclusive_second: bool = False,
) -> None:
    del third
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_one_or_two,
        args=(
            str(first),
            None if second is None else str(second),
            ready,
            release,
            shared_prepare,
            exclusive_second,
        ),
    )
    holder.start()
    ready.wait(5)
    try:
        with pytest.raises(MediaError, match=match):
            _mine(database, work)
    finally:
        release.set()
        holder.join(5)
    assert _candidate_jobs(database) == []


def _hold_one_or_two(
    first: str,
    second: str | None,
    ready: object,
    release: object,
    shared_prepare: bool,
    exclusive_second: bool,
) -> None:
    import fcntl

    first_fd = os.open(first, os.O_RDWR)
    fcntl.flock(first_fd, fcntl.LOCK_SH if shared_prepare else fcntl.LOCK_EX)
    second_fd = None
    if second is not None:
        second_fd = os.open(second, os.O_RDWR)
        fcntl.flock(second_fd, fcntl.LOCK_EX if exclusive_second else fcntl.LOCK_SH)
    ready.set()  # type: ignore[attr-defined]
    release.wait(30)  # type: ignore[attr-defined]
    if second_fd is not None:
        fcntl.flock(second_fd, fcntl.LOCK_UN)
        os.close(second_fd)
    fcntl.flock(first_fd, fcntl.LOCK_UN)
    os.close(first_fd)


def _hold_candidate_locks(
    prepare: str,
    transcribe: str,
    vision: str,
    candidate: str,
    ready: object,
    release: object,
) -> None:
    import fcntl

    descriptors = [os.open(path, os.O_RDWR) for path in (prepare, transcribe, vision, candidate)]
    modes = (fcntl.LOCK_SH, fcntl.LOCK_SH, fcntl.LOCK_SH, fcntl.LOCK_EX)
    for descriptor, mode in zip(descriptors, modes, strict=True):
        fcntl.flock(descriptor, mode)
    ready.set()  # type: ignore[attr-defined]
    release.wait(30)  # type: ignore[attr-defined]
    for descriptor in descriptors:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
