"""Jobs, cache checks, promotion boundaries, and batch execution."""

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from clipforge.batch.service import BatchError, resume_batch, run_batch, verify_batch
from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.jobs.confine import confine_reference
from clipforge.jobs.payload import JobPayloadError, assert_public_payload, public_payload
from clipforge.jobs.promote import PromotionError, promote
from clipforge.jobs.service import (
    JobError,
    list_job_text,
    recover_jobs,
    resume_job,
    retry_job,
    show_job,
    verify_job,
)
from clipforge.media import recipes
from clipforge.media.cache import cache_identity_matches, read_cache_record, write_cache_record
from clipforge.media.disk import DiskStatus
from clipforge.media.hashing import sha256_file
from clipforge.media.prepare import prepare_source
from clipforge.media.process import ProcessRunner
from clipforge.media.workspace import SourceWorkspace, prepare_lock
from clipforge.schemas.batch import BatchChild, BatchManifest, aggregate_batch_status
from clipforge.schemas.ingest import DerivativeCacheRecord
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
    update_project_profile,
)
from clipforge.transcription.cache import read_transcript_cache
from clipforge.transcription.models import ModelIdentity
from tests.helpers import license_record, provenance
from tests.test_media_unit import _probe, _seed

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
runner = CliRunner()


def test_help_does_not_grow_pipeline_words() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "job" in result.stdout
    assert "batch" in result.stdout
    for absent in ("publish", "transcribe", "render"):
        assert absent not in result.stdout


def test_public_payload_hides_paths() -> None:
    hidden = public_payload(
        {
            "source_asset_id": "source-1",
            "source_sha256": "a" * 64,
            "note": "/tmp/secret.mp4",
            "home": "/home/ada",
            "nested": "see /tmp/secret",
        }
    )
    assert hidden == {"source_asset_id": "source-1", "source_sha256": "a" * 64}
    with pytest.raises(JobPayloadError):
        assert_public_payload({"source_sha256": "/tmp/file"})
    with pytest.raises(JobPayloadError):
        assert_public_payload({"command": "echo secret"})
    with pytest.raises(JobPayloadError):
        assert_public_payload({"relative": "../outside"})
    with pytest.raises(JobPayloadError):
        assert_public_payload({"windows": "C:\\secret"})
    with pytest.raises(JobPayloadError):
        assert_public_payload({"remote": "https://example.invalid/a.mp4"})
    with pytest.raises(JobPayloadError):
        assert_public_payload({"uri": "file:///tmp/a.mp4"})


def test_failed_job_requires_an_error() -> None:
    with pytest.raises(ValidationError, match="error_message"):
        _job(status=JobStatus.FAILED, error=None)
    with pytest.raises(ValidationError, match="error_message"):
        _job(status=JobStatus.FAILED, error="   ")


def test_stale_running_job_is_failed_not_succeeded(tmp_path: Path) -> None:
    database = _database(tmp_path)
    job = _job(status=JobStatus.RUNNING, updated_at=datetime.now(UTC) - timedelta(hours=2))
    fresh = _job(status=JobStatus.RUNNING, updated_at=datetime.now(UTC))
    other = _job(
        status=JobStatus.RUNNING,
        updated_at=datetime.now(UTC) - timedelta(hours=3),
        project_id="project-2",
    )
    with database.transaction() as connection:
        insert_project(connection, _project("project-2"))
        insert_job(connection, job)
        insert_job(connection, fresh)
        insert_job(connection, other)
    changed = recover_jobs(database, "project-1", now=datetime.now(UTC), stale_after=timedelta(minutes=15))
    assert changed == [job.job_id]
    with database.connect() as connection:
        stored = get_job(connection, job.job_id)
        kept = get_job(connection, fresh.job_id)
        untouched = get_job(connection, other.job_id)
    assert stored.status is JobStatus.FAILED
    assert stored.error_message
    assert "not marked succeeded" in stored.error_message
    assert kept.status is JobStatus.RUNNING
    assert untouched.status is JobStatus.RUNNING


def test_resume_rejects_unknown_kinds_hash_drift_rights_and_cross_project(tmp_path: Path) -> None:
    database, source_id, manifest = _seed(tmp_path)
    calls: list[str] = []

    def executor(job: JobRecord, root: Path, actor: str) -> str:
        del job, root, actor
        calls.append("ran")
        return "not-a-job"

    unknown = _job(kind="publish_clip", status=JobStatus.FAILED, error="nope")
    with database.transaction() as connection:
        insert_job(connection, unknown)
    with pytest.raises(JobError, match="cannot be resumed"):
        resume_job(database, unknown.job_id, tmp_path, created_by="ada", executors={})

    drifted = _failed_parent(manifest)
    with database.transaction() as connection:
        insert_job(connection, drifted)
    media = tmp_path / "source.bin"
    media.write_bytes(media.read_bytes() + b"changed")
    with pytest.raises(JobError, match="source hash changed"):
        resume_job(database, drifted.job_id, tmp_path, created_by="ada", executors={"media_prepare": executor})
    assert calls == []

    blocked = _seed(tmp_path / "rights", rights="prohibited")
    rights_db, _rights_source, rights_manifest = blocked
    parent = _failed_parent(rights_manifest)
    with rights_db.transaction() as connection:
        insert_job(connection, parent)
    with pytest.raises(JobError, match="rights status"):
        resume_job(
            rights_db,
            parent.job_id,
            tmp_path / "rights",
            created_by="ada",
            executors={"media_prepare": executor},
        )
    assert calls == []

    crossed = _failed_parent(manifest)
    crossed = crossed.model_copy(update={"project_id": "project-2", "job_id": str(uuid.uuid4())})
    with database.transaction() as connection:
        insert_project(connection, _project("project-2"))
        insert_job(connection, crossed)
    with pytest.raises(JobError, match="does not belong"):
        resume_job(database, crossed.job_id, tmp_path, created_by="ada", executors={"media_prepare": executor})
    assert calls == []
    del source_id


def test_resume_and_retry_keep_history_and_a_failure_leaves_the_artifact(tmp_path: Path) -> None:
    database, _source_id, manifest = _seed(tmp_path)
    parent = _failed_parent(manifest)
    with database.transaction() as connection:
        insert_job(connection, parent)
        insert_artifact(
            connection,
            artifact_id="artifact-proxy",
            project_id="project-1",
            job_id=parent.job_id,
            source_asset_id=manifest.source_asset_id,
            kind=recipes.KIND_PROXY,
            uri="file:///keep/proxy.mp4",
            provenance=provenance([manifest.source_asset_id], parent.job_id),
        )

    def executor(job: JobRecord, root: Path, actor: str) -> str:
        del root, actor
        child = _job(
            status=JobStatus.SUCCEEDED,
            source_sha256=job.payload["source_sha256"],
            source_id=job.payload["source_asset_id"],
        )
        with database.transaction() as connection:
            insert_job(connection, child)
        return child.job_id

    child_id = resume_job(
        database,
        parent.job_id,
        tmp_path,
        created_by="ada",
        executors={"media_prepare": executor},
    )
    assert child_id != parent.job_id
    with database.connect() as connection:
        child = get_job(connection, child_id)
        kept = get_job(connection, parent.job_id)
        artifact = find_artifact(connection, "project-1", manifest.source_asset_id, recipes.KIND_PROXY)
    assert kept.status is JobStatus.FAILED
    assert kept.payload.get("parent_job_id") is None
    assert child.payload["parent_job_id"] == parent.job_id
    assert child.payload["attempt"] == "2"
    assert artifact is not None and artifact.artifact_id == "artifact-proxy"

    def fail(job: JobRecord, root: Path, actor: str) -> str:
        del job, root, actor
        raise JobError("encoder failed again")

    with pytest.raises(JobError, match="encoder failed again"):
        retry_job(database, parent.job_id, tmp_path, created_by="ada", executors={"media_prepare": fail})
    with database.connect() as connection:
        assert get_job(connection, parent.job_id).status is JobStatus.FAILED
        again = find_artifact(connection, "project-1", manifest.source_asset_id, recipes.KIND_PROXY)
    assert again is not None and again.uri == "file:///keep/proxy.mp4"

    reused = _job(status=JobStatus.SUCCEEDED, source_sha256=manifest.content_sha256)
    with database.transaction() as connection:
        insert_job(connection, reused)

    def cache_hit(job: JobRecord, root: Path, actor: str) -> str:
        del job, root, actor
        return reused.job_id

    attempt_id = resume_job(
        database,
        parent.job_id,
        tmp_path,
        created_by="ada",
        executors={"media_prepare": cache_hit},
    )
    assert attempt_id not in {parent.job_id, reused.job_id, child_id}
    with database.connect() as connection:
        attempt = get_job(connection, attempt_id)
        original = get_job(connection, reused.job_id)
        parent_again = get_job(connection, parent.job_id)
    assert attempt.status is JobStatus.SUCCEEDED
    assert attempt.payload["cache"] == "hit"
    assert attempt.payload["reused_job_id"] == reused.job_id
    assert original.payload.get("parent_job_id") is None
    assert parent_again.status is JobStatus.FAILED


def test_cancelled_job_can_be_resumed(tmp_path: Path) -> None:
    database, _source_id, manifest = _seed(tmp_path)
    parent = _failed_parent(manifest).model_copy(
        update={"status": JobStatus.CANCELLED, "error_message": "cancelled by the operator"}
    )
    with database.transaction() as connection:
        insert_job(connection, parent)

    def executor(job: JobRecord, root: Path, actor: str) -> str:
        del root, actor
        child = _job(status=JobStatus.SUCCEEDED, source_sha256=job.payload["source_sha256"])
        with database.transaction() as connection:
            insert_job(connection, child)
        return child.job_id

    child_id = resume_job(
        database,
        parent.job_id,
        tmp_path,
        created_by="ada",
        executors={"media_prepare": executor},
    )
    with database.connect() as connection:
        assert get_job(connection, parent.job_id).status is JobStatus.CANCELLED
        assert get_job(connection, child_id).payload["parent_job_id"] == parent.job_id


def test_lock_contention_is_refused_before_a_new_job(tmp_path: Path) -> None:
    database, source_id, manifest = _seed(tmp_path)
    work = tmp_path / "work"
    workspace = SourceWorkspace(work, "project-1", source_id)
    workspace.ensure()
    parent = _failed_parent(manifest)
    with database.transaction() as connection:
        insert_job(connection, parent)
    held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with prepare_lock(workspace):
            held.set()
            assert release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert held.wait(5)

    def executor(job: JobRecord, root: Path, actor: str) -> str:
        del job, root, actor
        prepare_source(
            database=database,
            source_asset_id=source_id,
            work_root=work,
            disk_status=_roomy(work),
        )
        return "should-not-run"

    try:
        with pytest.raises(JobError, match="another media prepare"):
            resume_job(
                database,
                parent.job_id,
                work,
                created_by="ada",
                executors={"media_prepare": executor},
            )
    finally:
        release.set()
        thread.join(5)
    with database.connect() as connection:
        jobs = [str(row["job_id"]) for row in connection.execute("SELECT job_id FROM jobs")]
    assert jobs == [parent.job_id]


def test_media_cache_hit_skips_the_worker_and_a_bad_producer_misses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, source_id, manifest = _seed(tmp_path)
    work = tmp_path / "work"
    _plant_proxy(database, work, manifest, status=JobStatus.SUCCEEDED)

    def fail_if_ffmpeg_starts() -> str:
        raise AssertionError("ffmpeg started on a cache hit")

    monkeypatch.setattr("clipforge.media.prepare._resolve_ffmpeg", fail_if_ffmpeg_starts)
    hit = prepare_source(
        database=database,
        source_asset_id=source_id,
        work_root=work,
        disk_status=_roomy(work),
    )
    assert hit.proxy_from_cache is True
    assert hit.job_id == "job-prepare"
    with database.connect() as connection:
        assert [str(row["job_id"]) for row in connection.execute("SELECT job_id FROM jobs")] == ["job-prepare"]

    miss_root = tmp_path / "miss"
    miss_db, miss_source, miss_manifest = _seed(miss_root)
    miss_work = miss_root / "work"
    _plant_proxy(miss_db, miss_work, miss_manifest, status=JobStatus.FAILED)
    calls: list[str] = []
    monkeypatch.setattr("clipforge.media.prepare._resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("clipforge.media.prepare._resolve_ffprobe", lambda: "ffprobe")
    monkeypatch.setattr("clipforge.media.prepare._version", lambda _runner, _exe: "ffmpeg version test")

    def explode(self: ProcessRunner, argv: list[str], **kwargs: object) -> object:
        del self, kwargs
        calls.append(argv[0])
        raise MediaError("synthetic encode failure")

    monkeypatch.setattr(ProcessRunner, "run", explode)
    with pytest.raises(MediaError, match="synthetic encode failure"):
        prepare_source(
            database=miss_db,
            source_asset_id=miss_source,
            work_root=miss_work,
            disk_status=_roomy(miss_work),
        )
    assert calls
    with miss_db.connect() as connection:
        jobs = list(connection.execute("SELECT job_id, status FROM jobs"))
    assert len(jobs) == 2
    assert any(row[1] == "failed" for row in jobs)


def test_transcript_cache_hit_skips_the_backend_and_changes_miss(tmp_path: Path) -> None:
    from tests.test_transcription import _run
    from tests.transcription_fakes import FakeTranscriptionBackend

    database, source_id, work = _ready_transcript(tmp_path)
    backend = FakeTranscriptionBackend()
    first = _run(database, source_id, tmp_path, backend)
    assert first.cache_hit is False
    assert backend.calls == 1
    second = _run(database, source_id, tmp_path, backend)
    assert second.cache_hit is True
    assert second.job_id == first.job_id
    assert backend.calls == 1
    forced = _run(database, source_id, tmp_path, backend, force=True)
    assert forced.cache_hit is False
    assert forced.job_id != first.job_id
    assert backend.calls == 2
    revised = _run(
        database,
        source_id,
        tmp_path,
        backend,
        identity=ModelIdentity(
            requested="small.en",
            source="local_directory",
            local_path="models/small.en",
            revision="rev-b",
        ),
    )
    assert revised.cache_hit is False
    assert backend.calls == 3
    workspace = SourceWorkspace(work, "project-1", source_id)
    workspace.transcript_sidecar().write_text("{", encoding="utf-8")
    repaired = _run(database, source_id, tmp_path, backend)
    assert repaired.cache_hit is False
    assert backend.calls == 4
    media = tmp_path / "source.bin"
    media.write_bytes(b"changed-source-bytes")
    before = backend.calls
    with pytest.raises(MediaError, match="changed since ingest"):
        _run(database, source_id, tmp_path, backend)
    assert backend.calls == before


def test_cache_readers_reject_symlinks_and_hash_mismatches(tmp_path: Path) -> None:
    target = tmp_path / "real.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "cache.json"
    link.symlink_to(target)
    assert read_cache_record(link) is None
    assert read_transcript_cache(link) is None
    assert read_cache_record(tmp_path / "missing.json") is None
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert read_cache_record(broken) is None
    record = DerivativeCacheRecord(
        recipe_name="analysis-proxy",
        recipe_version="1",
        source_sha256="a" * 64,
        project_id="project-1",
        source_asset_id="source-1",
        video_stream_index=0,
        audio_stream_index=None,
        artifact_sha256="b" * 64,
        size_bytes=1,
        ffmpeg_version="test",
        arguments=["ffmpeg"],
        validation_status="passed",
        created_at=datetime.now(UTC),
    )
    media = tmp_path / "analysis.mp4"
    media.write_bytes(b"x")
    assert (
        cache_identity_matches(
            record,
            recipe_name="analysis-proxy",
            recipe_version="1",
            source_sha256="a" * 64,
            project_id="project-1",
            source_asset_id="source-1",
            video_stream_index=0,
            audio_stream_index=None,
            artifact_path=media,
        )
        is False
    )
    linked = tmp_path / "linked.mp4"
    linked.symlink_to(media)
    assert (
        cache_identity_matches(
            record,
            recipe_name="analysis-proxy",
            recipe_version="1",
            source_sha256="a" * 64,
            project_id="project-1",
            source_asset_id="source-1",
            video_stream_index=0,
            audio_stream_index=None,
            artifact_path=linked,
        )
        is False
    )


def test_promotion_boundaries_keep_the_previous_artifact() -> None:
    def fail_at(stage: str) -> None:
        state = {"artifact": "old", "sidecar": "old"}

        def write_output() -> None:
            if stage == "output":
                raise OSError("output failed")

        def write_manifest() -> None:
            if stage == "manifest":
                raise OSError("manifest failed")

        def commit_database() -> None:
            state["artifact"] = "new"
            if stage == "database":
                raise OSError("database failed")

        def write_sidecar() -> None:
            if stage == "sidecar":
                raise OSError("sidecar failed")
            state["sidecar"] = "new"

        def rollback() -> None:
            state["artifact"] = "old"

        with pytest.raises(PromotionError):
            promote(
                write_output=write_output,
                write_manifest=write_manifest,
                commit_database=commit_database,
                write_sidecar=write_sidecar,
                rollback_database=rollback,
            )
        assert state["sidecar"] == "old"
        assert state["artifact"] == "old"

    for name in ("output", "manifest", "database", "sidecar"):
        fail_at(name)


def test_batch_orders_isolates_resumes_and_stays_read_only(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _add_source(database, tmp_path, "source-a")
    _add_source(database, tmp_path, "source-b")
    calls: list[str] = []

    def executor(source_id: str, operation: str, force: bool) -> tuple[str, bool]:
        calls.append(f"{source_id}:{operation}:{force}")
        if source_id == "source-b" and calls.count(f"{source_id}:{operation}:{force}") == 1:
            raise JobError("source-b failed once")
        job_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        with database.transaction() as connection:
            insert_job(
                connection,
                JobRecord(
                    job_id=job_id,
                    project_id="project-1",
                    kind=operation,
                    status=JobStatus.SUCCEEDED,
                    created_at=now,
                    updated_at=now,
                    payload={"source_asset_id": source_id, "source_sha256": "ab" * 32, "cache": "miss"},
                ),
            )
        return job_id, source_id == "source-a"

    with database.transaction() as connection:
        update_project_profile(connection, "project-1", "profile-organic")
    document = run_batch(
        database=database,
        source_asset_ids=["source-a", "source-b"],
        work_root=tmp_path,
        created_by="ada",
        executor=executor,
    )
    assert document.profile_id == "profile-organic"
    assert "policy-source-rights" in document.policy_ids
    assert [item.source_asset_id for item in document.children] == ["source-a", "source-b"]
    assert document.children[0].status == "succeeded"
    assert document.children[0].cache_hit is True
    assert document.children[1].status == "failed"
    assert document.status == "partial"
    manifest = tmp_path / "batches" / document.batch_id / "manifest.json"
    text = manifest.read_text(encoding="utf-8")
    assert "/tmp/" not in text
    assert "/home/" not in text
    before = manifest.read_bytes()
    db_before = database.path.read_bytes()
    verify_batch(tmp_path, document.batch_id)
    assert manifest.read_bytes() == before
    assert database.path.read_bytes() == db_before
    manifest.write_text(json_status_succeeded(manifest), encoding="utf-8")
    with pytest.raises(BatchError):
        verify_batch(tmp_path, document.batch_id)
    manifest.write_bytes(before)
    resumed = resume_batch(database, document.batch_id, tmp_path, created_by="ada", executor=executor)
    assert resumed.children[0].job_id == document.children[0].job_id
    assert resumed.children[1].status == "succeeded"
    assert resumed.status == "succeeded"
    assert calls == [
        "source-a:media_prepare:False",
        "source-b:media_prepare:False",
        "source-b:media_prepare:False",
    ]


def test_batch_rejects_duplicates_mixed_projects_links_and_sidecar_failure(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _add_source(database, tmp_path, "source-a")
    _add_source(database, tmp_path, "source-b", project_id="project-2")
    with pytest.raises(BatchError, match="duplicate"):
        run_batch(
            database=database,
            source_asset_ids=["source-a", "source-a"],
            work_root=tmp_path,
            created_by="ada",
            executor=lambda *_args: ("job-1", False),
        )
    with pytest.raises(BatchError, match="mix projects"):
        run_batch(
            database=database,
            source_asset_ids=["source-a", "source-b"],
            work_root=tmp_path,
            created_by="ada",
            executor=lambda *_args: ("job-1", False),
        )
    with pytest.raises(BatchError, match="concurrency"):
        run_batch(
            database=database,
            source_asset_ids=["source-a"],
            work_root=tmp_path,
            created_by="ada",
            concurrency=2,
            executor=lambda *_args: ("job-1", False),
        )
    with pytest.raises(ValidationError, match="filesystem paths"):
        BatchManifest(
            batch_id=str(uuid.uuid4()),
            project_id="project-1",
            source_asset_ids=["source-a"],
            operations=["media_prepare"],
            children=[
                BatchChild(
                    source_asset_id="source-a",
                    operation="media_prepare",
                    status="failed",
                    error="see /tmp/secret",
                )
            ],
            status="failed",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            provenance=ArtifactProvenance(
                created_at=datetime.now(UTC),
                created_by="ada",
                tool="clipforge-test",
                tool_version="0",
                source_asset_ids=["source-a"],
            ),
        )
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked-work"
    linked.mkdir()
    (linked / "batches").symlink_to(outside, target_is_directory=True)
    with pytest.raises(BatchError, match="symlink"):
        run_batch(
            database=database,
            source_asset_ids=["source-a"],
            work_root=linked,
            created_by="ada",
            executor=lambda *_args: ("job-1", True),
        )
    assert list(outside.iterdir()) == []

    def boom() -> None:
        raise OSError("sidecar failed")

    with pytest.raises(BatchError, match="sidecar"):
        run_batch(
            database=database,
            source_asset_ids=["source-a"],
            work_root=tmp_path / "first",
            created_by="ada",
            executor=lambda *_args: ("job-1", False),
            sidecar_hook=boom,
        )
    assert list((tmp_path / "first").rglob("manifest.json")) == []


def test_batch_aggregate_cannot_hide_a_failure() -> None:
    assert aggregate_batch_status(["succeeded", "failed"]) == "partial"
    assert aggregate_batch_status(["failed", "failed"]) == "failed"
    assert aggregate_batch_status(["succeeded", "cancelled"]) == "partial"
    assert aggregate_batch_status(["cancelled", "cancelled"]) == "cancelled"
    assert aggregate_batch_status(["blocked"]) == "partial"
    assert aggregate_batch_status([]) == "running"
    assert aggregate_batch_status(["running"]) == "running"


def test_show_and_verify_are_read_only(tmp_path: Path) -> None:
    database, _source_id, manifest = _seed(tmp_path)
    leaked = _failed_parent(manifest)
    job = leaked.model_copy(update={"payload": {**leaked.payload, "leak": "/tmp/secret.mp4"}})
    with database.transaction() as connection:
        insert_job(connection, job)
    text = show_job(database, job.job_id)
    assert "/tmp/" not in text
    assert "source_sha256" in text
    with pytest.raises(JobError, match="local path"):
        verify_job(database, job.job_id, tmp_path)
    clean = _failed_parent(manifest)
    with database.transaction() as connection:
        insert_job(connection, clean)
    before = database.path.read_bytes()
    listed = list_job_text(database, "project-1")
    verify_job(database, clean.job_id, tmp_path)
    assert "failed" in listed
    assert clean.updated_at.isoformat() in listed
    assert database.path.read_bytes() == before
    missing = runner.invoke(app, ["job", "show", "missing-job", "--db", str(database.path)])
    assert missing.exit_code != 0
    assert "Traceback" not in (missing.stderr or "")
    assert "Traceback" not in (missing.stdout or "")


def test_promotion_references_stay_inside_the_work_root(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    inside = root / "batches" / "one"
    inside.mkdir(parents=True)
    confine_reference(root, "batches/one")
    with pytest.raises(JobPayloadError):
        confine_reference(root, "../outside")
    with pytest.raises(JobPayloadError):
        confine_reference(root, "batches\\one")
    with pytest.raises(JobPayloadError):
        confine_reference(root, "https://example.invalid/a.mp4")
    with pytest.raises(JobPayloadError):
        confine_reference(root, (tmp_path / "outside.txt").resolve().as_uri())
    outside = tmp_path / "linked-target"
    outside.mkdir()
    link = root / "alias"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(JobPayloadError, match="symlink"):
        confine_reference(root, "alias")


def _ready_transcript(tmp_path: Path) -> tuple[Database, str, Path]:
    from tests.test_transcription import _ready

    return _ready(tmp_path)


def _plant_proxy(database: Database, work: Path, manifest: object, *, status: JobStatus) -> None:
    from clipforge.schemas.ingest import SourceIngestManifest

    assert isinstance(manifest, SourceIngestManifest)
    workspace = SourceWorkspace(work, manifest.project_id, manifest.source_asset_id)
    workspace.ensure()
    proxy = workspace.proxy_file("analysis.mp4")
    proxy.parent.mkdir(parents=True, exist_ok=True)
    proxy.write_bytes(b"proxy-bytes")
    digest = sha256_file(proxy)
    now = datetime.now(UTC)
    error = None if status is not JobStatus.FAILED else "prepare failed"
    job = JobRecord(
        job_id="job-prepare",
        project_id=manifest.project_id,
        kind=recipes.JOB_MEDIA_PREPARE,
        status=status,
        created_at=now,
        updated_at=now,
        error_message=error,
        payload={
            "source_asset_id": manifest.source_asset_id,
            "source_sha256": manifest.content_sha256,
            "analysis_proxy_sha256": digest,
            "cache": "miss",
        },
    )
    record = DerivativeCacheRecord(
        recipe_name=recipes.ANALYSIS_PROXY_NAME,
        recipe_version=recipes.ANALYSIS_PROXY_VERSION,
        source_sha256=manifest.content_sha256,
        project_id=manifest.project_id,
        source_asset_id=manifest.source_asset_id,
        video_stream_index=manifest.video_stream_index,
        audio_stream_index=manifest.audio_stream_index,
        artifact_sha256=digest,
        size_bytes=proxy.stat().st_size,
        ffmpeg_version="ffmpeg version test",
        arguments=["ffmpeg", "-i", "source.bin"],
        validation_status="passed",
        created_at=now,
    )
    write_cache_record(workspace.metadata_file("analysis-proxy.recipe.json"), record, work)
    with database.transaction() as connection:
        insert_job(connection, job)
        if status is JobStatus.SUCCEEDED:
            insert_artifact(
                connection,
                artifact_id="artifact-proxy",
                project_id=manifest.project_id,
                job_id=job.job_id,
                source_asset_id=manifest.source_asset_id,
                kind=recipes.KIND_PROXY,
                uri=proxy.resolve().as_uri(),
                provenance=provenance([manifest.source_asset_id], job.job_id),
            )


def json_status_succeeded(path: Path) -> str:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "succeeded"
    return json.dumps(payload)


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        insert_project(connection, _project("project-1"))
    return database


def _add_source(database: Database, root: Path, source_id: str, project_id: str = "project-1") -> None:
    media = root / f"{source_id}.bin"
    media.write_bytes(source_id.encode("ascii"))
    stat = media.stat()
    digest = hashlib.sha256(media.read_bytes()).hexdigest()
    source_project = project_id
    if project_id != "project-1":
        with database.connect() as connection:
            existing = connection.execute(
                "SELECT project_id FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if existing is None:
            with database.transaction() as connection:
                insert_project(connection, _project(project_id))
    asset_license = license_record(asset_id=source_id, license_record_id=f"lic-{source_id}")
    from clipforge.schemas.media import SourceAsset

    source = SourceAsset(
        source_asset_id=source_id,
        project_id=source_project,
        uri=media.resolve().as_uri(),
        license_record_id=asset_license.license_record_id,
        provenance=provenance([source_id]),
    )
    from clipforge.schemas.ingest import SourceIngestManifest

    manifest = SourceIngestManifest(
        source_asset_id=source_id,
        project_id=source_project,
        content_sha256=digest,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        original_filename=media.name,
        transcription_eligible=False,
        video_stream_index=0,
        audio_stream_index=None,
        canonical_duration_us=2_000_000,
        video_origin_us=0,
        ingested_at=datetime.now(UTC),
        probe=_probe(),
    )
    with database.transaction() as connection:
        insert_asset_license_record(connection, asset_license)
        insert_source_asset(connection, source)
        insert_source_manifest(connection, manifest)


def _project(project_id: str) -> Project:
    return Project(
        project_id=project_id,
        name="Round 12",
        created_at=datetime.now(UTC),
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="ada",
            tool="clipforge-test",
            tool_version="0",
        ),
    )


def _failed_parent(manifest: object) -> JobRecord:
    from clipforge.schemas.ingest import SourceIngestManifest

    assert isinstance(manifest, SourceIngestManifest)
    return _job(
        status=JobStatus.FAILED,
        error="encoder failed",
        source_sha256=manifest.content_sha256,
        source_id=manifest.source_asset_id,
    )


def _job(
    *,
    status: JobStatus,
    kind: str = "media_prepare",
    error: str | None = None,
    updated_at: datetime | None = None,
    source_sha256: str = "a" * 64,
    source_id: str = "source-1",
    project_id: str = "project-1",
) -> JobRecord:
    now = updated_at or datetime.now(UTC)
    return JobRecord(
        job_id=str(uuid.uuid4()),
        project_id=project_id,
        kind=kind,
        status=status,
        created_at=now - timedelta(hours=3),
        updated_at=now,
        error_message=error,
        payload={
            "source_asset_id": source_id,
            "source_sha256": source_sha256,
            "operation": kind,
            "attempt": "1",
            "cache": "miss",
        },
    )


def _roomy(root: Path) -> DiskStatus:
    return DiskStatus(
        work_root=root,
        filesystem="test",
        total_bytes=100 * 1024**3,
        used_bytes=1,
        free_bytes=100 * 1024**3,
        reserve_bytes=0,
    )
