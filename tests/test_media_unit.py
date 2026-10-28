"""Media rules that do not need a real encode."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import sqlite3
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clipforge.errors import ComplianceGateError, MediaError, StorageError
from clipforge.media.cache import cache_identity_matches, write_cache_record
from clipforge.media.clock import (
    audio_filter_chain,
    build_timeline,
    canonical_duration,
    classify_frame_timing,
    display_dimensions,
    hdr_signal,
    parse_ratio,
    proxy_pixel_size,
    seconds_text_to_us,
    select_streams,
)
from clipforge.media.disk import DiskStatus, estimate_prepare_bytes, require_disk_budget
from clipforge.media.hashing import sha256_file
from clipforge.media.ingest import _write_json
from clipforge.media.local_file import require_local_media_file
from clipforge.media.mutation import inspect_mutation
from clipforge.media.prepare import prepare_source
from clipforge.media.process import ProcessResult, ProcessRunner, is_transcode
from clipforge.media.tools import resolve_ffmpeg
from clipforge.media.workspace import SourceWorkspace, prepare_lock, safe_unlink
from clipforge.schemas.ingest import (
    AudioStreamInfo,
    ColorMetadata,
    DerivativeCacheRecord,
    FrameTimingClass,
    HdrSignal,
    MediaClassification,
    MediaFormatInfo,
    MediaTimelineInfo,
    NormalizedMediaProbe,
    RationalNumber,
    RotationMetadata,
    SourceIngestManifest,
    StreamDisposition,
    StreamSelection,
    VideoStreamInfo,
)
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import SourceAsset
from clipforge.schemas.project import Project
from clipforge.storage import (
    Database,
    get_project,
    get_source_manifest,
    insert_asset_license_record,
    insert_job,
    insert_project,
    insert_source_asset,
    insert_source_manifest,
    list_jobs,
)
from clipforge.storage.db import _execute_script, _prepare
from clipforge.storage.migrations import MIGRATIONS
from tests.helpers import license_record, provenance, stamp

_GIB = 1024**3


def test_remote_and_directory_sources_are_rejected(tmp_path: Path) -> None:
    for raw in (
        "https://example.com/a.mp4",
        "http://example.com/a.mp4",
        "s3://bucket/a.mp4",
        "ftp://example.com/a.mp4",
        "https://www.youtube.com/watch?v=abc",
        "https://www.tiktok.com/@a/video/1",
        "https://www.instagram.com/reel/abc/",
        "https://drive.google.com/file/d/abc/view",
        "youtu.be/abc",
    ):
        with pytest.raises(MediaError):
            require_local_media_file(raw)
    with pytest.raises(MediaError, match="directory"):
        require_local_media_file(str(tmp_path))
    missing = tmp_path / "missing.mp4"
    with pytest.raises(MediaError, match="does not exist"):
        require_local_media_file(str(missing))


def test_spaces_and_unicode_paths_resolve(tmp_path: Path) -> None:
    spaced = tmp_path / "my video.mp4"
    spaced.write_bytes(b"not-media")
    assert require_local_media_file(str(spaced)) == spaced.resolve()
    unicode_path = tmp_path / "视频_é.mp4"
    unicode_path.write_bytes(b"not-media")
    assert require_local_media_file(str(unicode_path)).name == "视频_é.mp4"


def test_rational_rates_and_duration_strategy() -> None:
    ratio = parse_ratio("30000/1001")
    assert ratio is not None
    assert (ratio.numerator, ratio.denominator) == (30000, 1001)
    assert parse_ratio("0/0") is None
    assert seconds_text_to_us("1.5") == 1_500_000
    assert seconds_text_to_us("N/A") is None
    video = _video(duration_ts=60, time_base=(1, 30), duration_us=None)
    duration, evidence = canonical_duration(video, MediaFormatInfo(duration_us=9_000_000))
    assert duration == 2_000_000
    assert evidence == "selected_video_duration_ts"
    missing = _video(duration_ts=None, time_base=None, duration_us=None, start=5_000)
    with pytest.raises(MediaError, match="invent"):
        canonical_duration(missing, MediaFormatInfo(duration_us=2_000_000))


def test_stream_selection_is_deterministic() -> None:
    attached = _video(index=0, attached=True)
    first = _video(index=1)
    default = _video(index=2, default=True)
    video, _audio, selection = select_streams(
        [attached, first, default], [], video_override=None, audio_override=None
    )
    assert video.index == 2
    assert selection.video_selection == "automatic"
    forced, _, explicit = select_streams([attached, first, default], [], video_override=1, audio_override=None)
    assert forced.index == 1
    assert explicit.video_selection == "explicit"
    with pytest.raises(MediaError, match="did not fall back"):
        select_streams([first], [], video_override=9, audio_override=None)
    with pytest.raises(MediaError, match="no usable video"):
        select_streams([attached], [], video_override=None, audio_override=None)
    quiet, audio, chosen = select_streams([first], [], video_override=None, audio_override=None)
    assert quiet.index == 1
    assert audio is None
    assert chosen.audio_selection == "none"
    low = AudioStreamInfo(index=3, sample_rate=48000)
    high = AudioStreamInfo(index=4, sample_rate=48000, disposition=StreamDisposition(default=True))
    _, picked, _audio_choice = select_streams([first], [low, high], video_override=None, audio_override=None)
    assert picked is not None and picked.index == 4
    _, overridden, override_choice = select_streams([first], [low, high], video_override=None, audio_override=3)
    assert overridden is not None and overridden.index == 3
    assert override_choice.audio_selection == "explicit"
    with pytest.raises(MediaError, match="audio stream 8"):
        select_streams([first], [low], video_override=None, audio_override=8)


def test_frame_timing_hdr_and_scale() -> None:
    same = _video(avg=(30000, 1001), reported=(30000, 1001))
    assert classify_frame_timing(same) is FrameTimingClass.CFR_LIKELY
    differ = _video(avg=(30, 1), reported=(30000, 1001))
    assert classify_frame_timing(differ) is FrameTimingClass.VFR_POSSIBLE
    assert classify_frame_timing(_video(avg=None, reported=None)) is FrameTimingClass.UNKNOWN
    assert hdr_signal(ColorMetadata(color_transfer="smpte2084")) is HdrSignal.PQ
    assert hdr_signal(ColorMetadata(color_transfer="arib-std-b67")) is HdrSignal.HLG
    assert hdr_signal(ColorMetadata(color_transfer="bt709")) is HdrSignal.NONE
    assert proxy_pixel_size(160, 90) == (160, 90)
    assert proxy_pixel_size(90, 160) == (90, 160)
    assert proxy_pixel_size(120, 120) == (120, 120)
    assert proxy_pixel_size(1920, 1080) == (1280, 720)
    assert proxy_pixel_size(1080, 1920) == (720, 1280)
    width, height = proxy_pixel_size(101, 80)
    assert width <= 101 and height <= 80
    assert width % 2 == 0 and height % 2 == 0
    assert display_dimensions(160, 90, None, -90) == (90, 160)
    delayed = audio_filter_chain(1, 500_000, 3_000_000, output_rate=16000, label="out", pcm_s16=True)
    assert "aevalsrc=0:d=0.500000" in delayed
    assert "16000" in delayed
    early = audio_filter_chain(1, -500_000, 2_000_000, output_rate=16000, label="out", pcm_s16=True)
    assert "atrim=start=0.500000" in early
    assert "loudnorm" not in early
    assert "atempo" not in early


def test_disk_reserve_blocks_before_the_reserve_is_crossed() -> None:
    reserve = 10 * _GIB
    small = 1 * _GIB
    require_disk_budget(100 * _GIB, reserve, small)
    require_disk_budget(20 * _GIB, reserve, small)
    require_disk_budget(12 * _GIB, reserve, small)
    with pytest.raises(MediaError, match="reserve"):
        require_disk_budget(12 * _GIB, reserve, 2 * _GIB)
    with pytest.raises(MediaError, match="ffmpeg was not started"):
        require_disk_budget(8 * _GIB, reserve, small)
    with pytest.raises(MediaError, match="ffmpeg was not started"):
        require_disk_budget(5 * _GIB, reserve, small)
    estimate = estimate_prepare_bytes(2_000_000, has_audio=True)
    assert estimate > estimate_prepare_bytes(2_000_000, has_audio=False)


def test_low_disk_does_not_call_the_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, source_id, _manifest = _seed(tmp_path)
    calls: list[list[str]] = []

    class Boom(ProcessRunner):
        def run(
            self,
            argv: list[str],
            *,
            log_path: Path | None = None,
            cancel_event: threading.Event | None = None,
            check: bool = True,
        ) -> ProcessResult:
            calls.append(argv)
            raise AssertionError("runner should not be called")

    from clipforge.media.disk import DiskStatus

    with pytest.raises(MediaError, match="reserve"):
        prepare_source(
            database=database,
            source_asset_id=source_id,
            work_root=tmp_path / "work",
            runner=Boom(),
            disk_status=DiskStatus(
                work_root=tmp_path / "work",
                filesystem="test",
                total_bytes=20 * _GIB,
                used_bytes=15 * _GIB,
                free_bytes=5 * _GIB,
                reserve_bytes=10 * _GIB,
            ),
        )
    assert calls == []
    monkeypatch.setenv("CLIPFORGE_FFMPEG", "/no/such/ffmpeg")
    with pytest.raises(MediaError, match="CLIPFORGE_FFMPEG"):
        resolve_ffmpeg()


def test_unknown_and_prohibited_rights_block_prepare(tmp_path: Path) -> None:
    for status in ("unknown", "prohibited"):
        database, source_id, _manifest = _seed(tmp_path / status, rights=status, evidence=None)
        with pytest.raises(ComplianceGateError):
            prepare_source(
                database=database,
                source_asset_id=source_id,
                work_root=tmp_path / status / "work",
                runner=ProcessRunner(),
            )


def test_hash_is_streaming_and_mutation_keeps_the_old_digest(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(b"abc" * 1000)
    assert sha256_file(path) == hashlib.sha256(path.read_bytes()).hexdigest()
    database, source_id, manifest = _seed(tmp_path, media_path=path)
    assert inspect_mutation(path, manifest) is None
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(MediaError, match="changed since ingest"):
        inspect_mutation(path, manifest)
    with database.connect() as connection:
        stored = get_source_manifest(connection, source_id)
    assert stored.content_sha256 == manifest.content_sha256


def test_cache_identity_rejects_corrupt_and_recipe_changes(tmp_path: Path) -> None:
    artifact = tmp_path / "analysis.mp4"
    artifact.write_bytes(b"proxy-bytes")
    digest = sha256_file(artifact)
    record = DerivativeCacheRecord(
        recipe_name="analysis-proxy",
        recipe_version="1",
        source_sha256="a" * 64,
        project_id="project-1",
        source_asset_id="source-1",
        video_stream_index=0,
        audio_stream_index=None,
        artifact_sha256=digest,
        size_bytes=artifact.stat().st_size,
        ffmpeg_version="ffmpeg test",
        arguments=["ffmpeg", "-i", "in"],
        validation_status="passed",
        created_at=stamp(),
    )
    sidecar = tmp_path / "analysis-proxy.recipe.json"
    write_cache_record(sidecar, record, tmp_path)
    identity = {
        "recipe_name": "analysis-proxy",
        "recipe_version": "1",
        "source_sha256": "a" * 64,
        "project_id": "project-1",
        "source_asset_id": "source-1",
        "video_stream_index": 0,
        "audio_stream_index": None,
    }
    assert cache_identity_matches(record, artifact_path=artifact, **identity)
    artifact.write_bytes(b"corrupt")
    assert not cache_identity_matches(record, artifact_path=artifact, **identity)
    assert not cache_identity_matches(
        record,
        artifact_path=tmp_path / "missing.mp4",
        **{**identity, "recipe_version": "2"},
    )
    assert not cache_identity_matches(
        record,
        artifact_path=artifact,
        **{**identity, "project_id": "project-other"},
    )
    artifact.write_bytes(b"proxy-bytes")
    assert not cache_identity_matches(
        record,
        artifact_path=artifact,
        **{**identity, "source_asset_id": "source-other"},
    )


def test_cleanup_cannot_leave_the_work_root(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    outside = tmp_path / "keep.txt"
    outside.write_text("keep")
    with pytest.raises(MediaError, match="outside"):
        safe_unlink(root, outside)
    assert outside.read_text() == "keep"
    workspace = SourceWorkspace(root, "project-1", "source-1")
    workspace.ensure()
    partial = workspace.partial_for(workspace.proxy_file("analysis.mp4"))
    partial.write_bytes(b"partial")
    workspace.clear_partials()
    assert not partial.exists()
    assert outside.read_text() == "keep"


def test_process_runner_cancels_and_keeps_arguments_unsplit(tmp_path: Path) -> None:
    runner = ProcessRunner()
    spaced = tmp_path / "my file.txt"
    code = "import sys; print(sys.argv[1])"
    result = runner.run([sys.executable, "-c", code, str(spaced)], log_path=tmp_path / "run.log")
    assert result.stdout.strip() == str(spaced)
    assert result.returncode == 0
    cancel = threading.Event()

    def trip() -> None:
        time.sleep(0.2)
        cancel.set()

    threading.Thread(target=trip, daemon=True).start()
    with pytest.raises(MediaError, match="cancelled"):
        runner.run(["sleep", "30"], log_path=tmp_path / "cancel.log", cancel_event=cancel)
    with pytest.raises(MediaError, match="process deadline"):
        runner.run(["sleep", "30"], log_path=tmp_path / "timeout.log", timeout_s=0.1)
    assert is_transcode(["ffmpeg", "-c:v", "libx264"])
    assert not is_transcode(["ffprobe", "-show_format"])
    assert "shell=True" not in Path("src/clipforge/media/process.py").read_text(encoding="utf-8")


def test_manifest_cannot_cross_projects(tmp_path: Path) -> None:
    database, source_id, manifest = _seed(tmp_path)
    foreign = manifest.model_copy(update={"project_id": "project-other"})
    with database.transaction() as connection, pytest.raises(StorageError):
        insert_source_manifest(connection, foreign)
    with database.connect() as connection:
        assert get_source_manifest(connection, source_id).project_id == "project-1"


def test_migration_4_upgrades_a_version_3_file(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    _prepare(connection)
    connection.execute("BEGIN IMMEDIATE")
    now = stamp().isoformat()
    for migration in MIGRATIONS:
        if migration.version >= 4:
            break
        if migration.precheck is not None:
            migration.precheck(connection)
        _execute_script(connection, migration.sql)
        connection.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.name, now),
        )
    connection.execute("PRAGMA user_version = 3")
    connection.execute(
        """
        INSERT INTO projects (
            project_id, name, schema_version, profile_id, created_at, provenance_json, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "project-keep",
            "Keep",
            "1.0.0",
            None,
            now,
            json.dumps(provenance().model_dump(mode="json")),
            "{}",
        ),
    )
    connection.commit()
    connection.close()
    database = Database(path)
    assert database.initialize() == 7
    database.health_check()
    with database.connect() as checked:
        assert get_project(checked, "project-keep").name == "Keep"
        count = checked.execute("SELECT COUNT(*) FROM source_manifests").fetchone()
        assert count is not None and count[0] == 0


def test_audio_timeline_offsets_are_signed() -> None:
    video = _video(start=0)
    late = AudioStreamInfo(index=1, sample_rate=48000, start_time_us=500_000)
    timeline = build_timeline(video, late, MediaFormatInfo())
    assert timeline.audio_offset_us == 500_000
    early_video = _video(start=500_000)
    early_audio = AudioStreamInfo(index=1, sample_rate=48000, start_time_us=0)
    early = build_timeline(early_video, early_audio, MediaFormatInfo())
    assert early.video_origin_us == 500_000
    assert early.audio_offset_us == -500_000
    assumed = build_timeline(_video(start=None), None, MediaFormatInfo(duration_us=1_000_000))
    assert assumed.video_start_assumed_zero is True
    assert assumed.video_origin_us == 0


def _video(
    *,
    index: int = 0,
    attached: bool = False,
    default: bool = False,
    start: int | None = 0,
    duration_ts: int | None = 60,
    duration_us: int | None = 2_000_000,
    time_base: tuple[int, int] | None = (1, 30),
    avg: tuple[int, int] | None = (30, 1),
    reported: tuple[int, int] | None = (30, 1),
) -> VideoStreamInfo:
    return VideoStreamInfo(
        index=index,
        width=160,
        height=90,
        display_width=160,
        display_height=90,
        avg_frame_rate=None if avg is None else RationalNumber(numerator=avg[0], denominator=avg[1]),
        r_frame_rate=(
            None if reported is None else RationalNumber(numerator=reported[0], denominator=reported[1])
        ),
        time_base=(
            None if time_base is None else RationalNumber(numerator=time_base[0], denominator=time_base[1])
        ),
        start_time_us=start,
        duration_ts=duration_ts,
        duration_us=duration_us,
        disposition=StreamDisposition(default=default, attached_pic=attached),
        rotation=RotationMetadata(),
    )


def _probe() -> NormalizedMediaProbe:
    video = _video()
    timeline = MediaTimelineInfo(
        video_origin_us=0,
        video_start_assumed_zero=False,
        canonical_duration_us=2_000_000,
        duration_evidence="selected_video_duration_ts",
    )
    return NormalizedMediaProbe(
        format=MediaFormatInfo(duration_us=2_000_000),
        video_streams=[video],
        audio_streams=[],
        chapter_count=0,
        ffprobe_version="test",
        selection=StreamSelection(
            video_stream_index=0,
            audio_stream_index=None,
            video_selection="automatic",
            audio_selection="none",
        ),
        timeline=timeline,
        classification=MediaClassification(
            frame_timing=FrameTimingClass.CFR_LIKELY,
            hdr=HdrSignal.NONE,
            transcription_eligible=False,
        ),
    )


def _seed(
    tmp_path: Path,
    *,
    rights: str = "owned",
    evidence: str | None = "file:///evidence.txt",
    media_path: Path | None = None,
) -> tuple[Database, str, SourceIngestManifest]:
    root = tmp_path
    root.mkdir(parents=True, exist_ok=True)
    database = Database(root / "clipforge.sqlite3")
    database.initialize()
    media = media_path or (root / "source.bin")
    if not media.exists():
        media.write_bytes(b"source-bytes")
    stat = media.stat()
    project = Project(
        project_id="project-1",
        name="Unit",
        created_at=stamp(),
        provenance=provenance(),
    )
    source = SourceAsset(
        source_asset_id="source-1",
        project_id="project-1",
        uri=media.resolve().as_uri(),
        license_record_id="lic-1",
        provenance=provenance(["source-1"]),
    )
    manifest = SourceIngestManifest(
        source_asset_id="source-1",
        project_id="project-1",
        content_sha256=hashlib.sha256(media.read_bytes()).hexdigest(),
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
    from clipforge.schemas.governance import RightsStatus

    record = license_record(asset_id="source-1", status=RightsStatus(rights), evidence_uri=evidence)
    with database.transaction() as connection:
        insert_project(connection, project)
        insert_asset_license_record(connection, record)
        insert_source_asset(connection, source)
        insert_source_manifest(connection, manifest)
    return database, "source-1", manifest


def test_failed_prepare_is_not_left_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, source_id, _manifest = _seed(tmp_path / "fail")
    monkeypatch.setattr("clipforge.media.prepare._resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("clipforge.media.prepare._resolve_ffprobe", lambda: "ffprobe")
    monkeypatch.setattr("clipforge.media.prepare._version", lambda _runner, _exe: "ffmpeg version test")

    def explode(self: ProcessRunner, argv: list[str], **kwargs: object) -> ProcessResult:
        if is_transcode(argv):
            Path(str(argv[-1])).write_bytes(b"partial-output")
            raise MediaError("ffmpeg exited 1. synthetic failure")
        return ProcessResult(tuple(argv), 0, "ffmpeg version test\n", "", 0.01, None)

    monkeypatch.setattr(ProcessRunner, "run", explode)
    from clipforge.media.disk import DiskStatus

    with pytest.raises(MediaError, match="synthetic"):
        prepare_source(
            database=database,
            source_asset_id=source_id,
            work_root=tmp_path / "fail" / "work",
            disk_status=DiskStatus(
                work_root=tmp_path / "fail" / "work",
                filesystem="test",
                total_bytes=100 * _GIB,
                used_bytes=1,
                free_bytes=100 * _GIB,
                reserve_bytes=0,
            ),
        )
    with database.connect() as connection:
        jobs = list_jobs(connection, "project-1")
    assert jobs
    assert jobs[-1].status is JobStatus.FAILED
    assert jobs[-1].status is not JobStatus.RUNNING
    partials = list((tmp_path / "fail" / "work").rglob("*.partial.*"))
    assert partials == []
    final_proxy = (
        tmp_path
        / "fail"
        / "work"
        / "projects"
        / "project-1"
        / "sources"
        / "source-1"
        / "proxy"
        / "analysis.mp4"
    )
    assert not os.path.exists(final_proxy)


def test_active_prepare_lock_rejects_a_second_prepare(tmp_path: Path) -> None:
    database, source_id, _manifest = _seed(tmp_path)
    work = tmp_path / "work"
    workspace = SourceWorkspace(work, "project-1", source_id)
    workspace.ensure()
    partial = workspace.proxy_file("analysis.mp4").with_name("analysis.partial.kept.mp4")
    partial.write_bytes(b"keep-this-partial")
    workspace.prepare_lock_path().touch()
    now = datetime.now(UTC)
    with database.transaction() as connection:
        insert_job(
            connection,
            JobRecord(
                job_id="job-live",
                project_id="project-1",
                kind="media_prepare",
                status=JobStatus.RUNNING,
                created_at=now,
                updated_at=now,
                payload={"source_asset_id": source_id},
            ),
        )
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_prepare_lock,
        args=(str(workspace.prepare_lock_path()), ready, release),
    )
    holder.start()
    assert ready.wait(10)
    runner = ProcessRunner()
    try:
        with pytest.raises(MediaError, match="another media prepare"):
            prepare_source(
                database=database,
                source_asset_id=source_id,
                work_root=work,
                runner=runner,
                disk_status=_roomy_disk(work),
            )
    finally:
        release.set()
        holder.join(10)
    assert holder.exitcode == 0
    assert runner.transcode_count == 0
    assert partial.read_bytes() == b"keep-this-partial"
    with database.connect() as connection:
        jobs = list_jobs(connection, "project-1")
    assert [job.job_id for job in jobs] == ["job-live"]
    assert jobs[0].status is JobStatus.RUNNING


def test_released_prepare_lock_allows_another_prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, source_id, _manifest = _seed(tmp_path / "release")
    work = tmp_path / "release" / "work"
    workspace = SourceWorkspace(work, "project-1", source_id)
    workspace.ensure()
    with prepare_lock(workspace):
        pass
    _stub_failing_encode(monkeypatch)
    with pytest.raises(MediaError, match="synthetic failure"):
        prepare_source(
            database=database,
            source_asset_id=source_id,
            work_root=work,
            disk_status=_roomy_disk(work),
        )
    with database.connect() as connection:
        jobs = list_jobs(connection, "project-1")
    assert jobs
    assert jobs[-1].status is JobStatus.FAILED
    assert "another media prepare" not in (jobs[-1].error_message or "")


def test_stale_running_job_is_recovered_after_the_lock_is_acquired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, source_id, _manifest = _seed(tmp_path / "stale")
    now = datetime.now(UTC)
    with database.transaction() as connection:
        insert_job(
            connection,
            JobRecord(
                job_id="job-stale",
                project_id="project-1",
                kind="media_prepare",
                status=JobStatus.RUNNING,
                created_at=now,
                updated_at=now,
                payload={"source_asset_id": source_id},
            ),
        )
    _stub_failing_encode(monkeypatch)
    with pytest.raises(MediaError, match="synthetic failure"):
        prepare_source(
            database=database,
            source_asset_id=source_id,
            work_root=tmp_path / "stale" / "work",
            disk_status=_roomy_disk(tmp_path / "stale" / "work"),
        )
    with database.connect() as connection:
        jobs = {job.job_id: job for job in list_jobs(connection, "project-1")}
    assert jobs["job-stale"].status is JobStatus.FAILED
    assert "no live prepare" in (jobs["job-stale"].error_message or "")
    fresh = [job for job_id, job in jobs.items() if job_id != "job-stale"]
    assert len(fresh) == 1
    assert fresh[0].status is JobStatus.FAILED


def test_symlink_escape_is_rejected_before_a_write(tmp_path: Path) -> None:
    root = tmp_path / "work"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    workspace = SourceWorkspace(root, "project-1", "source-1")
    workspace.ensure()
    metadata = workspace.source_root / "metadata"
    metadata.rmdir()
    metadata.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MediaError, match="symlink"):
        workspace.ensure()
    assert (outside / "keep.txt").read_text() == "keep"
    assert not (outside / "ffprobe.json").exists()
    linked = root / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MediaError, match="outside"):
        _write_json(linked / "note.json", {"ok": False}, root)
    assert not (outside / "note.json").exists()
    assert not (outside / "note.json.partial").exists()


def _hold_prepare_lock(path: str, ready: object, release: object) -> None:
    """Hold the source lock in another process until ``release`` is set."""
    import fcntl

    descriptor = os.open(path, os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    ready.set()  # type: ignore[attr-defined]
    release.wait(30)  # type: ignore[attr-defined]
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def _roomy_disk(root: Path) -> DiskStatus:
    return DiskStatus(
        work_root=root,
        filesystem="test",
        total_bytes=100 * _GIB,
        used_bytes=1,
        free_bytes=100 * _GIB,
        reserve_bytes=0,
    )


def _stub_failing_encode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("clipforge.media.prepare._resolve_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("clipforge.media.prepare._resolve_ffprobe", lambda: "ffprobe")
    monkeypatch.setattr("clipforge.media.prepare._version", lambda _runner, _exe: "ffmpeg version test")

    def explode(self: ProcessRunner, argv: list[str], **kwargs: object) -> ProcessResult:
        if is_transcode(argv):
            raise MediaError("ffmpeg exited 1. synthetic failure")
        return ProcessResult(tuple(argv), 0, "ffmpeg version test\n", "", 0.01, None)

    monkeypatch.setattr(ProcessRunner, "run", explode)
