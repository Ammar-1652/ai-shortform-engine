"""Deterministic transcription tests. No model weights and no network."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.main import app
from clipforge.errors import ComplianceGateError, MediaError
from clipforge.media import recipes
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.governance import RightsStatus
from clipforge.schemas.ingest import (
    AudioStreamInfo,
    DerivativeCacheRecord,
    FrameTimingClass,
    HdrSignal,
    MediaClassification,
    MediaFormatInfo,
    MediaTimelineInfo,
    NormalizedMediaProbe,
    SourceIngestManifest,
    StreamSelection,
)
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import SourceAsset
from clipforge.schemas.project import Project
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
from clipforge.transcription.backend import RawSegment, RawWord
from clipforge.transcription.cache import cache_identity_matches, read_transcript_cache
from clipforge.transcription.constants import KIND_TRANSCRIPT
from clipforge.transcription.document import build_transcript, display_text
from clipforge.transcription.models import ModelIdentity
from clipforge.transcription.profile import TranscriptionRequest, decoding_profile
from clipforge.transcription.runtime import RuntimeFacts, resolve_runtime
from clipforge.transcription.service import transcribe_source
from clipforge.transcription.timeutil import seconds_to_microseconds
from tests.helpers import license_record, provenance, stamp
from tests.test_media_unit import _video
from tests.transcription_fakes import FakeTranscriptionBackend

pytestmark = pytest.mark.transcription

runner = CliRunner()


@pytest.fixture(autouse=True)
def _hub_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("HF_HUB_DISABLE_TELEMETRY", "1")


DURATION_US = 4_000_000


def test_seconds_convert_with_decimal_half_up() -> None:
    assert seconds_to_microseconds(0.0) == 0
    assert seconds_to_microseconds(0.001) == 1_000
    assert seconds_to_microseconds(1.234567) == 1_234_567
    assert seconds_to_microseconds(29.97) == 29_970_000
    assert seconds_to_microseconds(0.0000005) == 1
    with pytest.raises(MediaError, match="not finite"):
        seconds_to_microseconds(float("nan"))
    with pytest.raises(MediaError, match="not finite"):
        seconds_to_microseconds(float("inf"))


def test_timestamp_edges_fail_closed() -> None:
    base = _build_kwargs()
    over = _segment(0.0, 1.05, "near")
    clamped = build_transcript(**base, segments=[over], canonical_duration_us=1_000_000)
    assert clamped.segments[0].end_us == 1_000_000
    assert clamped.timing_adjustments
    with pytest.raises(MediaError, match="was not published"):
        build_transcript(**base, segments=[_segment(0.0, 1.25, "far")], canonical_duration_us=1_000_000)
    with pytest.raises(MediaError, match="was not published"):
        build_transcript(**base, segments=[_segment(-0.25, 0.4, "early")], canonical_duration_us=1_000_000)
    tiny = build_transcript(**base, segments=[_segment(-0.04, 0.4, "tiny")], canonical_duration_us=1_000_000)
    assert tiny.segments[0].start_us == 0
    with pytest.raises(MediaError, match=r"before it starts|at or before"):
        build_transcript(**base, segments=[_segment(0.5, 0.1, "backwards")], canonical_duration_us=1_000_000)
    with pytest.raises(MediaError, match="not reordered"):
        build_transcript(
            **base,
            segments=[_segment(0.5, 1.0, "first"), _segment(0.0, 0.2, "second")],
            canonical_duration_us=1_000_000,
        )
    with pytest.raises(MediaError, match=r"outside 0\.\.1"):
        build_transcript(
            **base,
            segments=[_segment(0.0, 0.4, "bad", probability=1.4)],
            canonical_duration_us=1_000_000,
        )
    rejected = dict(base)
    rejected["language_probability"] = 1.2
    with pytest.raises(MediaError, match="language_probability"):
        build_transcript(**rejected, segments=[], canonical_duration_us=1_000_000)


def test_empty_speech_and_unicode_and_whitespace() -> None:
    base = _build_kwargs()
    empty = build_transcript(**base, segments=[], canonical_duration_us=DURATION_US)
    assert empty.speech_detected is False
    assert empty.segments == []
    assert empty.alignment == "approximate"
    assert empty.timing_quality == "provisional"
    arabic = _segment(0.0, 0.4, "مرحبا café 😀")
    document = build_transcript(**base, segments=[arabic], canonical_duration_us=DURATION_US)
    rendered = document.model_dump_json()
    assert "\\u" not in rendered
    assert "مرحبا café 😀" in rendered
    assert document.segments[0].words[0].text == " مرحبا café 😀"
    assert display_text(document) == "مرحبا café 😀"


def test_canonical_clock_does_not_reapply_the_audio_offset(tmp_path: Path) -> None:
    database, source_id, _work = _ready(tmp_path, audio_offset_us=500_000, video_origin_us=250_000)
    backend = FakeTranscriptionBackend(segments=(_segment(0.5, 1.2, "later"),))
    result = _run(database, source_id, tmp_path, backend)
    document = _load(tmp_path, source_id)
    assert result.cache_hit is False
    assert document.segments[0].start_us == 500_000
    assert document.segments[0].words[0].start_us == 500_000
    assert document.clock == "canonical_video_t0"


def test_cache_hit_force_and_identity_misses(tmp_path: Path) -> None:
    database, source_id, work = _ready(tmp_path)
    backend = FakeTranscriptionBackend()
    first = _run(database, source_id, tmp_path, backend)
    assert first.cache_hit is False
    assert backend.calls == 1
    assert first.word_count == 3
    second = _run(database, source_id, tmp_path, backend)
    assert second.cache_hit is True
    assert backend.calls == 1
    assert second.job_id == first.job_id
    forced = _run(database, source_id, tmp_path, backend, force=True)
    assert forced.cache_hit is False
    assert backend.calls == 2
    assert forced.job_id != first.job_id
    with database.connect() as connection:
        jobs = list_jobs(connection, "project-1")
        row = find_artifact(connection, "project-1", source_id, KIND_TRANSCRIPT)
    assert row is not None and row.job_id == forced.job_id
    assert {job.job_id for job in jobs} >= {first.job_id, forced.job_id}
    assert all(job.status is JobStatus.SUCCEEDED for job in jobs)
    record = read_transcript_cache(SourceWorkspace(work, "project-1", source_id).transcript_sidecar())
    assert record is not None
    path = SourceWorkspace(work, "project-1", source_id).transcript_file()
    identity = _identity()
    runtime = resolve_runtime(requested_device="cpu", requested_compute_type="int8", facts=_cpu_facts())
    profile = decoding_profile("en")
    assert cache_identity_matches(
        record,
        project_id="project-1",
        source_asset_id=source_id,
        source_sha256=record.source_sha256,
        input_audio_sha256=record.input_audio_sha256,
        asr_recipe_name=record.asr_recipe_name,
        asr_recipe_version=record.asr_recipe_version,
        recipe_name=record.recipe_name,
        recipe_version=record.recipe_version,
        faster_whisper_version=record.faster_whisper_version,
        ctranslate2_version=record.ctranslate2_version,
        model=identity,
        runtime=runtime,
        profile=profile,
        transcript_path=path,
    )
    assert not cache_identity_matches(
        record,
        project_id="project-2",
        source_asset_id=source_id,
        source_sha256=record.source_sha256,
        input_audio_sha256=record.input_audio_sha256,
        asr_recipe_name=record.asr_recipe_name,
        asr_recipe_version=record.asr_recipe_version,
        recipe_name=record.recipe_name,
        recipe_version=record.recipe_version,
        faster_whisper_version=record.faster_whisper_version,
        ctranslate2_version=record.ctranslate2_version,
        model=identity,
        runtime=runtime,
        profile=profile,
        transcript_path=path,
    )
    assert not cache_identity_matches(
        record,
        project_id="project-1",
        source_asset_id="source-2",
        source_sha256=record.source_sha256,
        input_audio_sha256=record.input_audio_sha256,
        asr_recipe_name=record.asr_recipe_name,
        asr_recipe_version=record.asr_recipe_version,
        recipe_name=record.recipe_name,
        recipe_version=record.recipe_version,
        faster_whisper_version=record.faster_whisper_version,
        ctranslate2_version=record.ctranslate2_version,
        model=identity,
        runtime=runtime,
        profile=profile,
        transcript_path=path,
    )
    changed = record.model_copy(update={"source_sha256": "a" * 64, "input_audio_sha256": "b" * 64})
    assert not cache_identity_matches(
        changed,
        project_id="project-1",
        source_asset_id=source_id,
        source_sha256=record.source_sha256,
        input_audio_sha256=record.input_audio_sha256,
        asr_recipe_name=record.asr_recipe_name,
        asr_recipe_version=record.asr_recipe_version,
        recipe_name=record.recipe_name,
        recipe_version=record.recipe_version,
        faster_whisper_version=record.faster_whisper_version,
        ctranslate2_version=record.ctranslate2_version,
        model=identity,
        runtime=runtime,
        profile=profile,
        transcript_path=path,
    )
    drifted_engine = record.model_copy(
        update={"faster_whisper_version": "0.0.0", "ctranslate2_version": "0.0.0"}
    )
    assert not cache_identity_matches(
        drifted_engine,
        project_id="project-1",
        source_asset_id=source_id,
        source_sha256=record.source_sha256,
        input_audio_sha256=record.input_audio_sha256,
        asr_recipe_name=record.asr_recipe_name,
        asr_recipe_version=record.asr_recipe_version,
        recipe_name=record.recipe_name,
        recipe_version=record.recipe_version,
        faster_whisper_version=record.faster_whisper_version,
        ctranslate2_version=record.ctranslate2_version,
        model=identity,
        runtime=runtime,
        profile=profile,
        transcript_path=path,
    )
    other_device = resolve_runtime(requested_device="cpu", requested_compute_type="float32", facts=_cpu_facts())
    assert not cache_identity_matches(
        record,
        project_id="project-1",
        source_asset_id=source_id,
        source_sha256=record.source_sha256,
        input_audio_sha256=record.input_audio_sha256,
        asr_recipe_name=record.asr_recipe_name,
        asr_recipe_version=record.asr_recipe_version,
        recipe_name=record.recipe_name,
        recipe_version=record.recipe_version,
        faster_whisper_version=record.faster_whisper_version,
        ctranslate2_version=record.ctranslate2_version,
        model=identity,
        runtime=other_device,
        profile=profile,
        transcript_path=path,
    )
    other_language = decoding_profile("fr")
    assert not cache_identity_matches(
        record,
        project_id="project-1",
        source_asset_id=source_id,
        source_sha256=record.source_sha256,
        input_audio_sha256=record.input_audio_sha256,
        asr_recipe_name=record.asr_recipe_name,
        asr_recipe_version=record.asr_recipe_version,
        recipe_name=record.recipe_name,
        recipe_version="9",
        faster_whisper_version=record.faster_whisper_version,
        ctranslate2_version=record.ctranslate2_version,
        model=identity,
        runtime=runtime,
        profile=other_language,
        transcript_path=path,
    )
    other = ModelIdentity(
        requested="small.en",
        source="local_directory",
        local_path="/models/small.en",
        revision="rev-b",
    )
    _run(database, source_id, tmp_path, backend, identity=other)
    assert backend.calls == 3
    path.write_bytes(path.read_bytes() + b" ")
    assert not cache_identity_matches(
        record,
        project_id="project-1",
        source_asset_id=source_id,
        source_sha256=record.source_sha256,
        input_audio_sha256=record.input_audio_sha256,
        asr_recipe_name=record.asr_recipe_name,
        asr_recipe_version=record.asr_recipe_version,
        recipe_name=record.recipe_name,
        recipe_version=record.recipe_version,
        faster_whisper_version=record.faster_whisper_version,
        ctranslate2_version=record.ctranslate2_version,
        model=identity,
        runtime=runtime,
        profile=profile,
        transcript_path=path,
    )


def test_rights_mutation_corrupt_audio_and_failed_prepare_block_inference(tmp_path: Path) -> None:
    database, source_id, work = _ready(tmp_path, rights="unknown")
    backend = FakeTranscriptionBackend()
    with pytest.raises(ComplianceGateError):
        _run(database, source_id, tmp_path, backend)
    assert backend.calls == 0
    prohibited, prohibited_id, _prohibited_work = _ready(tmp_path / "no", rights="prohibited")
    with pytest.raises(ComplianceGateError):
        _run(prohibited, prohibited_id, tmp_path / "no", backend)
    assert backend.calls == 0
    database, source_id, work = _ready(tmp_path / "change")
    source = work.parent / "source.bin"
    source.write_bytes(b"mutated-source")
    os.utime(source, None)
    with pytest.raises(MediaError, match="changed since ingest"):
        _run(database, source_id, tmp_path / "change", backend)
    assert backend.calls == 0
    database, source_id, work = _ready(tmp_path / "corrupt")
    asr = SourceWorkspace(work, "project-1", source_id).audio_file("asr.flac")
    asr.write_bytes(b"not-the-same-flac")
    with pytest.raises(MediaError, match="media prepare"):
        _run(database, source_id, tmp_path / "corrupt", backend)
    assert backend.calls == 0
    database, source_id, work = _ready(tmp_path / "job")
    with database.connect() as connection:
        media_job = next(job for job in list_jobs(connection, "project-1") if job.kind == "media_prepare")
    with database.transaction() as connection:
        update_job(
            connection,
            media_job.model_copy(
                update={
                    "status": JobStatus.FAILED,
                    "error_message": "forced failure for the transcription gate",
                    "updated_at": datetime.now(UTC),
                }
            ),
        )
    with pytest.raises(MediaError, match="expected succeeded"):
        _run(database, source_id, tmp_path / "job", backend)
    assert backend.calls == 0
    silent, silent_id, _silent_work = _ready(tmp_path / "silent", eligible=False)
    with pytest.raises(MediaError, match="not transcription-eligible"):
        _run(silent, silent_id, tmp_path / "silent", backend)
    assert backend.calls == 0


def test_generator_failure_keeps_the_previous_transcript(tmp_path: Path) -> None:
    database, source_id, work = _ready(tmp_path)
    backend = FakeTranscriptionBackend()
    _run(database, source_id, tmp_path, backend)
    path = SourceWorkspace(work, "project-1", source_id).transcript_file()
    original = path.read_bytes()
    exploding = FakeTranscriptionBackend(fail_after=1)
    with pytest.raises(MediaError, match="segment iterator failed"):
        _run(database, source_id, tmp_path, exploding, force=True)
    assert path.read_bytes() == original
    assert list(path.parent.glob("*.partial.*")) == []
    with database.connect() as connection:
        jobs = list_jobs(connection, "project-1")
        row = find_artifact(connection, "project-1", source_id, KIND_TRANSCRIPT)
    failed = [job for job in jobs if job.status is JobStatus.FAILED]
    assert failed
    assert row is not None and row.job_id != failed[-1].job_id
    cancelled = FakeTranscriptionBackend(interrupt_after=1)
    with pytest.raises(Exception, match="interrupted"):
        _run(database, source_id, tmp_path, cancelled, force=True)
    assert path.read_bytes() == original
    with database.connect() as connection:
        statuses = {job.status for job in list_jobs(connection, "project-1")}
    assert JobStatus.CANCELLED in statuses


def test_database_failure_after_publish_restores_the_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, source_id, work = _ready(tmp_path)
    backend = FakeTranscriptionBackend()
    _run(database, source_id, tmp_path, backend)
    path = SourceWorkspace(work, "project-1", source_id).transcript_file()
    original = path.read_bytes()

    def explode(*_args: object, **_kwargs: object) -> None:
        raise MediaError("database rejected the artifact update")

    monkeypatch.setattr("clipforge.transcription.service.update_artifact", explode)
    with pytest.raises(MediaError, match="database rejected"):
        _run(database, source_id, tmp_path, backend, force=True)
    assert path.read_bytes() == original
    with database.connect() as connection:
        failed = [job for job in list_jobs(connection, "project-1") if job.status is JobStatus.FAILED]
    assert failed


def test_missing_model_does_not_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, source_id, _work = _ready(tmp_path)

    def explode(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("download was not authorized")

    monkeypatch.setattr("clipforge.transcription.models._download", explode)
    monkeypatch.setattr("clipforge.transcription.models._cached_snapshot", lambda *_args, **_kwargs: None)
    backend = FakeTranscriptionBackend()
    with pytest.raises(MediaError, match="not available"):
        transcribe_source(
            database=database,
            source_asset_id=source_id,
            work_root=_work_of(tmp_path),
            model_root=tmp_path / "models",
            request=TranscriptionRequest(model="small.en", allow_model_download=False),
            backend=backend,
            runtime_facts=_cpu_facts(),
            audio_validator=lambda _path, _manifest: None,
        )
    assert backend.calls == 0


def test_cuda_request_does_not_fall_back_and_auto_uses_cpu(tmp_path: Path) -> None:
    database, source_id, _work = _ready(tmp_path)
    backend = FakeTranscriptionBackend()
    with pytest.raises(MediaError, match="did not fall back"):
        _run(database, source_id, tmp_path, backend, device="cuda")
    assert backend.calls == 0
    result = _run(database, source_id, tmp_path, backend, device="auto")
    assert result.device == "cpu"
    assert result.compute_type == "int8"
    assert result.warning is not None
    assert "CPU" in result.warning
    assert backend.devices == ["cpu"]


def test_active_prepare_blocks_transcription(tmp_path: Path) -> None:
    database, source_id, work = _ready(tmp_path)
    workspace = SourceWorkspace(work, "project-1", source_id)
    workspace.ensure()
    partial = workspace.transcript_file().with_name("transcript.json.partial.live")
    partial.write_bytes(b"live-partial")
    now = datetime.now(UTC)
    with database.transaction() as connection:
        insert_job(
            connection,
            JobRecord(
                job_id="job-live-transcript",
                project_id="project-1",
                kind="transcribe",
                status=JobStatus.RUNNING,
                created_at=now,
                updated_at=now,
                payload={"source_asset_id": source_id},
            ),
        )
    lock_path = workspace.prepare_lock_path()
    lock_path.touch()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(target=_hold_prepare_lock, args=(str(lock_path), ready, release))
    holder.start()
    assert ready.wait(10)
    backend = FakeTranscriptionBackend()
    try:
        with pytest.raises(MediaError, match="another media prepare"):
            _run(database, source_id, tmp_path, backend)
    finally:
        release.set()
        holder.join(10)
    assert holder.exitcode == 0
    assert backend.calls == 0
    assert partial.read_bytes() == b"live-partial"
    with database.connect() as connection:
        jobs = list_jobs(connection, "project-1")
    live = next(job for job in jobs if job.job_id == "job-live-transcript")
    assert live.status is JobStatus.RUNNING
    assert not any(job.kind == "transcribe" and job.job_id != "job-live-transcript" for job in jobs)


def test_second_transcription_is_rejected(tmp_path: Path) -> None:
    database, source_id, work = _ready(tmp_path)
    workspace = SourceWorkspace(work, "project-1", source_id)
    workspace.ensure()
    partial = workspace.audio_file("asr.partial.live.flac")
    partial.write_bytes(b"keep")
    workspace.prepare_lock_path().touch()
    workspace.transcribe_lock_path().touch()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_transcribe_locks,
        args=(str(workspace.prepare_lock_path()), str(workspace.transcribe_lock_path()), ready, release),
    )
    holder.start()
    assert ready.wait(10)
    backend = FakeTranscriptionBackend()
    try:
        with pytest.raises(MediaError, match="another transcription"):
            _run(database, source_id, tmp_path, backend)
    finally:
        release.set()
        holder.join(10)
    assert holder.exitcode == 0
    assert backend.calls == 0
    assert partial.read_bytes() == b"keep"
    with database.connect() as connection:
        assert [job for job in list_jobs(connection, "project-1") if job.kind == "transcribe"] == []


def test_stale_transcription_job_is_recovered(tmp_path: Path) -> None:
    database, source_id, _work = _ready(tmp_path)
    now = datetime.now(UTC)
    with database.transaction() as connection:
        insert_job(
            connection,
            JobRecord(
                job_id="job-stale-transcript",
                project_id="project-1",
                kind="transcribe",
                status=JobStatus.RUNNING,
                created_at=now,
                updated_at=now,
                payload={"source_asset_id": source_id},
            ),
        )
    backend = FakeTranscriptionBackend()
    result = _run(database, source_id, tmp_path, backend)
    assert backend.calls == 1
    with database.connect() as connection:
        stale = get_job(connection, "job-stale-transcript")
    assert stale.status is JobStatus.FAILED
    assert "no live transcription" in (stale.error_message or "")
    assert result.job_id != stale.job_id


def test_verify_and_show_do_not_need_the_model(tmp_path: Path) -> None:
    database, source_id, work = _ready(tmp_path)
    backend = FakeTranscriptionBackend()
    _run(database, source_id, tmp_path, backend)
    from clipforge.transcription.show import format_transcript, load_transcript
    from clipforge.transcription.verify import verify_transcript

    document = load_transcript(database=database, source_asset_id=source_id, work_root=work)
    text = format_transcript(document, as_json=False)
    assert "Hello world." in text
    assert "provisional" in text
    payload = document.model_dump_json()
    assert " Hello" in payload
    report = verify_transcript(
        database=database,
        source_asset_id=source_id,
        work_root=work,
        model_root=tmp_path / "empty-models",
    )
    assert report.status == "WARN"
    assert any(line.name == "model_cache" and line.status == "WARN" for line in report.lines)
    update_target = get_job_outside(database, source_id)
    with database.transaction() as connection:
        update_job(
            connection,
            update_target.model_copy(
                update={
                    "status": JobStatus.FAILED,
                    "error_message": "marked failed after a successful transcript",
                    "updated_at": datetime.now(UTC),
                }
            ),
        )
    failed = verify_transcript(database=database, source_asset_id=source_id, work_root=work, model_root=None)
    assert failed.status == "FAIL"
    assert any("expected" in line.detail for line in failed.lines)


def test_symlink_transcript_directory_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "work"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    workspace = SourceWorkspace(root, "project-1", "source-1")
    workspace.ensure()
    transcript = workspace.source_root / "transcript"
    transcript.rmdir()
    transcript.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MediaError, match="symlink"):
        workspace.ensure()
    assert (outside / "keep.txt").read_text() == "keep"
    assert not (outside / "transcript.json").exists()


def test_transcript_help_describes_the_round_3_limits() -> None:
    group = runner.invoke(app, ["transcript", "--help"])
    assert group.exit_code == 0
    for name in ("doctor", "run", "show", "verify"):
        assert name in _plain(group.stdout)
    run_help = runner.invoke(app, ["transcript", "run", "--help"])
    assert run_help.exit_code == 0
    lowered = _plain(run_help.stdout).lower()
    assert "asr" in lowered
    assert "provisional" in lowered
    assert "allow-model-download" in lowered
    assert "translation" in lowered
    doctor = runner.invoke(app, ["transcript", "doctor", "--help"])
    show = runner.invoke(app, ["transcript", "show", "--help"])
    verify = runner.invoke(app, ["transcript", "verify", "--help"])
    assert doctor.exit_code == 0
    assert show.exit_code == 0
    assert verify.exit_code == 0
    assert "download" in _plain(doctor.stdout).lower()


def test_asr_packages_import_without_a_model() -> None:
    import importlib.metadata

    import ctranslate2
    import faster_whisper

    assert importlib.metadata.version("faster-whisper") == "1.2.1"
    assert ctranslate2.get_supported_compute_types("cpu")
    assert faster_whisper.WhisperModel is not None


def test_auto_selects_cpu_when_cuda_libraries_do_not_load() -> None:
    from clipforge.transcription.runtime import probe_runtime

    facts = probe_runtime()
    runtime = resolve_runtime(requested_device="auto", requested_compute_type="auto", facts=facts)
    if facts.cuda_usable:
        assert runtime.device == "cuda"
        assert runtime.warning is None
        return
    assert runtime.device == "cpu"
    assert runtime.warning is not None
    with pytest.raises(MediaError, match="did not fall back"):
        resolve_runtime(requested_device="cuda", requested_compute_type="auto", facts=facts)


def test_english_only_model_rejects_auto_language() -> None:
    with pytest.raises(MediaError, match="English-only"):
        TranscriptionRequest(model="small.en", language="auto")
        from clipforge.transcription.profile import normalize_request

        normalize_request(TranscriptionRequest(model="small.en", language="auto"))


def _run(
    database: Database,
    source_id: str,
    tmp_path: Path,
    backend: FakeTranscriptionBackend,
    *,
    device: str = "cpu",
    force: bool = False,
    identity: ModelIdentity | None = None,
) -> object:
    from clipforge.transcription.service import TranscriptResult

    result = transcribe_source(
        database=database,
        source_asset_id=source_id,
        work_root=_work_of(tmp_path),
        model_root=tmp_path / "models",
        request=TranscriptionRequest(
            model="small.en",
            language="en",
            device=device,
            compute_type="auto",
            force=force,
        ),
        backend=backend,
        runtime_facts=_cpu_facts(),
        model_identity=identity or _identity(),
        audio_validator=lambda _path, _manifest: None,
        created_by="tester",
    )
    assert isinstance(result, TranscriptResult)
    return result


def _ready(
    tmp_path: Path,
    *,
    rights: str = "owned",
    eligible: bool = True,
    audio_offset_us: int = 0,
    video_origin_us: int = 0,
) -> tuple[Database, str, Path]:
    root = tmp_path
    root.mkdir(parents=True, exist_ok=True)
    database = Database(root / "clipforge.sqlite3")
    database.initialize()
    media = root / "source.bin"
    media.write_bytes(b"source-bytes")
    stat = media.stat()
    digest = hashlib.sha256(media.read_bytes()).hexdigest()
    project = Project(project_id="project-1", name="Unit", created_at=stamp(), provenance=provenance())
    source = SourceAsset(
        source_asset_id="source-1",
        project_id="project-1",
        uri=media.resolve().as_uri(),
        license_record_id="lic-1",
        provenance=provenance(["source-1"]),
    )
    manifest = _manifest(digest, stat.st_size, stat.st_mtime_ns, eligible, audio_offset_us, video_origin_us)
    record = license_record(
        asset_id="source-1", status=RightsStatus(rights), evidence_uri="file:///evidence.txt"
    )
    work = _work_of(tmp_path)
    workspace = SourceWorkspace(work, "project-1", "source-1")
    workspace.ensure()
    audio = workspace.audio_file("asr.flac")
    audio.write_bytes(b"asr-flac-bytes")
    audio_sha = hashlib.sha256(b"asr-flac-bytes").hexdigest()
    sidecar = DerivativeCacheRecord(
        recipe_name=recipes.ASR_AUDIO_NAME,
        recipe_version=recipes.ASR_AUDIO_VERSION,
        source_sha256=digest,
        project_id="project-1",
        source_asset_id="source-1",
        video_stream_index=0,
        audio_stream_index=1 if eligible else None,
        artifact_sha256=audio_sha,
        size_bytes=audio.stat().st_size,
        ffmpeg_version="test",
        arguments=["ffmpeg", "-i", "source.bin", "asr.flac"],
        validation_status="passed",
        created_at=datetime.now(UTC),
    )
    workspace.transcript_sidecar().parent.mkdir(parents=True, exist_ok=True)
    workspace.metadata_file("asr-audio.recipe.json").write_text(
        sidecar.model_dump_json(),
        encoding="utf-8",
    )
    now = datetime.now(UTC)
    job = JobRecord(
        job_id="job-prepare",
        project_id="project-1",
        kind="media_prepare",
        status=JobStatus.SUCCEEDED,
        created_at=now,
        updated_at=now,
        payload={"source_asset_id": "source-1", "source_sha256": digest, "asr_audio_sha256": audio_sha},
    )
    with database.transaction() as connection:
        insert_project(connection, project)
        insert_asset_license_record(connection, record)
        insert_source_asset(connection, source)
        insert_source_manifest(connection, manifest)
        insert_job(connection, job)
        insert_artifact(
            connection,
            artifact_id="artifact-asr",
            project_id="project-1",
            job_id=job.job_id,
            source_asset_id="source-1",
            kind=recipes.KIND_ASR,
            uri=audio.resolve().as_uri(),
            provenance=provenance(["source-1"], job.job_id),
        )
    return database, "source-1", work


def _manifest(
    digest: str,
    size: int,
    mtime_ns: int,
    eligible: bool,
    audio_offset_us: int,
    video_origin_us: int,
) -> SourceIngestManifest:
    video = _video(duration_us=DURATION_US)
    timeline = MediaTimelineInfo(
        video_origin_us=video_origin_us,
        video_start_assumed_zero=False,
        audio_start_us=audio_offset_us,
        audio_offset_us=audio_offset_us,
        canonical_duration_us=DURATION_US,
        duration_evidence="selected_video_duration_ts",
    )
    probe = NormalizedMediaProbe(
        format=MediaFormatInfo(duration_us=DURATION_US),
        video_streams=[video],
        audio_streams=[AudioStreamInfo(index=1, sample_rate=16000, channels=1)],
        chapter_count=0,
        ffprobe_version="test",
        selection=StreamSelection(
            video_stream_index=0,
            audio_stream_index=1 if eligible else None,
            video_selection="automatic",
            audio_selection="automatic" if eligible else "none",
        ),
        timeline=timeline,
        classification=MediaClassification(
            frame_timing=FrameTimingClass.CFR_LIKELY,
            hdr=HdrSignal.NONE,
            transcription_eligible=eligible,
        ),
    )
    return SourceIngestManifest(
        source_asset_id="source-1",
        project_id="project-1",
        content_sha256=digest,
        size_bytes=size,
        mtime_ns=mtime_ns,
        original_filename="source.bin",
        transcription_eligible=eligible,
        video_stream_index=0,
        audio_stream_index=1 if eligible else None,
        canonical_duration_us=DURATION_US,
        video_origin_us=video_origin_us,
        ingested_at=datetime.now(UTC),
        probe=probe,
    )


def _identity() -> ModelIdentity:
    return ModelIdentity(
        requested="small.en",
        source="local_directory",
        local_path="/models/small.en",
        revision="rev-a",
    )


def _cpu_facts() -> RuntimeFacts:
    return RuntimeFacts(
        cuda_device_count=0,
        cpu_compute_types=("int8", "float32"),
        cuda_compute_types=(),
        cuda_error="CTranslate2 CUDA is unavailable in this test",
    )


def _plain(text: str) -> str:
    """Drop ANSI and whitespace so a wrapped CI help line still matches."""
    import re

    cleaned = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return re.sub(r"\s+", "", cleaned)


def _work_of(tmp_path: Path) -> Path:
    return tmp_path / "work"


def _load(tmp_path: Path, source_id: str) -> object:
    from clipforge.schemas.media import Transcript

    path = SourceWorkspace(_work_of(tmp_path), "project-1", source_id).transcript_file()
    return Transcript.model_validate_json(path.read_text(encoding="utf-8"))


def _segment(start: float, end: float, text: str, *, probability: float = 0.9) -> RawSegment:
    return RawSegment(
        text=text,
        start_seconds=start,
        end_seconds=end,
        words=(RawWord(text=" " + text, start_seconds=start, end_seconds=end, probability=probability),),
        avg_logprob=-0.2,
        no_speech_prob=0.01,
        compression_ratio=1.0,
        temperature=0.0,
    )


def _build_kwargs() -> dict[str, object]:
    from datetime import UTC, datetime

    return {
        "project_id": "project-1",
        "source_asset_id": "source-1",
        "asr_audio_sha256": "a" * 64,
        "asr_recipe_name": "asr-audio",
        "asr_recipe_version": "1",
        "model": _identity(),
        "runtime": resolve_runtime(requested_device="cpu", requested_compute_type="int8", facts=_cpu_facts()),
        "profile": decoding_profile("en"),
        "detected_language": "en",
        "language_probability": 0.5,
        "faster_whisper_version": "1.2.1",
        "ctranslate2_version": "4.8.2",
        "created_at": datetime.now(UTC),
        "created_by": "tester",
        "job_id": "job-1",
        "tool_version": "1.2.1",
    }


def get_job_outside(database: Database, source_id: str) -> JobRecord:
    with database.connect() as connection:
        return get_job(connection, _producer_job(database, source_id))


def _producer_job(database: Database, source_id: str) -> str:
    with database.connect() as connection:
        row = find_artifact(connection, "project-1", source_id, KIND_TRANSCRIPT)
    assert row is not None and row.job_id is not None
    return row.job_id


def _hold_prepare_lock(path: str, ready: object, release: object) -> None:
    import fcntl

    descriptor = os.open(path, os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    ready.set()  # type: ignore[attr-defined]
    release.wait(30)  # type: ignore[attr-defined]
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def _hold_transcribe_locks(prepare_path: str, transcribe_path: str, ready: object, release: object) -> None:
    import fcntl

    prepare_fd = os.open(prepare_path, os.O_RDWR)
    transcribe_fd = os.open(transcribe_path, os.O_RDWR)
    fcntl.flock(prepare_fd, fcntl.LOCK_SH)
    fcntl.flock(transcribe_fd, fcntl.LOCK_EX)
    ready.set()  # type: ignore[attr-defined]
    release.wait(30)  # type: ignore[attr-defined]
    fcntl.flock(transcribe_fd, fcntl.LOCK_UN)
    fcntl.flock(prepare_fd, fcntl.LOCK_UN)
    os.close(transcribe_fd)
    os.close(prepare_fd)
