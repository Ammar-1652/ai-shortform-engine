"""Real PySceneDetect and PyAV coverage. The face backend stays fake."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import pytest

from clipforge.media import recipes
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.governance import RightsStatus
from clipforge.schemas.ingest import (
    DerivativeCacheRecord,
    FrameTimingClass,
    HdrSignal,
    MediaClassification,
    MediaFormatInfo,
    MediaTimelineInfo,
    NormalizedMediaProbe,
    RationalNumber,
    SourceIngestManifest,
    StreamSelection,
    VideoStreamInfo,
)
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import SourceAsset
from clipforge.schemas.project import Project
from clipforge.storage import (
    Database,
    insert_artifact,
    insert_asset_license_record,
    insert_job,
    insert_project,
    insert_source_asset,
    insert_source_manifest,
)
from clipforge.vision.frame_reader import PyAVFrameReader
from clipforge.vision.models import FaceModel
from clipforge.vision.sampling import normalize_scenes
from clipforge.vision.scene_backend import PySceneDetectBackend
from clipforge.vision.service import analyze_source
from clipforge.vision.timeutil import rational_to_us
from tests.helpers import license_record, provenance, stamp
from tests.media_factory import require_ffmpeg, run_ffmpeg
from tests.vision_fakes import FakeFaceBackend

pytestmark = pytest.mark.vision


@pytest.fixture(autouse=True)
def _reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")


def test_hard_cuts_and_stable_video_use_real_scene_detection(tmp_path: Path) -> None:
    require_ffmpeg()
    hard = _color_cut(tmp_path / "hard.mp4")
    hard_duration = _duration_us(hard)
    document = _analyze_real(tmp_path / "hard-case", hard, hard_duration, 160, 90)
    assert document.summary.scene_count == 3
    starts = [scene.time_range.start_us for scene in document.scenes]
    assert starts[0] == 0
    assert abs(starts[1] - 2_000_000) <= 100_000
    assert abs(starts[2] - 4_000_000) <= 100_000
    assert document.scenes[-1].time_range.end_us == hard_duration
    assert all(scene.analysis_complete is False for scene in document.scenes)
    assert all(scene.transcript_evidence is None for scene in document.scenes)
    stable = _solid(tmp_path / "stable.mp4", "gray", "160x90", "3")
    stable_duration = _duration_us(stable)
    stable_document = _analyze_real(tmp_path / "stable-case", stable, stable_duration, 160, 90)
    assert stable_document.summary.scene_count == 1
    assert stable_document.scenes[0].time_range.start_us == 0
    assert stable_document.scenes[0].time_range.end_us == stable_duration


def test_portrait_and_square_proxies_keep_display_dimensions(tmp_path: Path) -> None:
    require_ffmpeg()
    portrait = _solid(tmp_path / "portrait.mp4", "red", "90x160", "1")
    portrait_document = _analyze_real(tmp_path / "portrait-case", portrait, _duration_us(portrait), 90, 160)
    assert portrait_document.proxy_height > portrait_document.proxy_width
    square = _solid(tmp_path / "square.mp4", "blue", "96x96", "1")
    square_document = _analyze_real(tmp_path / "square-case", square, _duration_us(square), 96, 96)
    assert square_document.proxy_width == square_document.proxy_height


def test_vfr_timestamps_come_from_frame_pts(tmp_path: Path) -> None:
    require_ffmpeg()
    path = tmp_path / "vfr.mp4"
    staged = tmp_path / "vfr.mkv"
    # libx264 into MP4 can collapse the PTS edit. Stage Matroska, then copy.
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x90:rate=30:duration=2",
            "-vf",
            "setpts='PTS+if(eq(mod(N,2),0),0,0.04/TB)'",
            "-fps_mode",
            "passthrough",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            str(staged),
        ]
    )
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(staged),
            "-c",
            "copy",
            "-fps_mode",
            "passthrough",
            str(path),
        ]
    )
    duration = _duration_us(path)
    reader = PyAVFrameReader(duration_us=duration)
    frames = list(reader.frames(path))
    assert frames
    assert all(frames[index].timestamp_us <= frames[index + 1].timestamp_us for index in range(len(frames) - 1))
    assert all(0 <= frame.timestamp_us < duration for frame in frames)
    nominal = [round(index * 1_000_000 / 30) for index in range(len(frames))]
    assert any(abs(frame.timestamp_us - nominal[index]) > 1_000 for index, frame in enumerate(frames))
    spans = normalize_scenes(PySceneDetectBackend().detect(path, duration), duration)
    assert spans[0][0] == 0
    assert spans[-1][1] == duration
    document = _analyze_real(tmp_path / "vfr-case", path, duration, 160, 90)
    decoded = {frame.timestamp_us for frame in frames}
    assert all(item.actual_timestamp_us in decoded for item in document.frame_evidence)


def _analyze_real(root: Path, proxy_source: Path, duration_us: int, width: int, height: int) -> object:
    database, source_id, work, model = _ready(root, proxy_source, duration_us, width, height)
    result = analyze_source(
        database=database,
        source_asset_id=source_id,
        work_root=work,
        model_root=model.path.parents[2],
        scene_backend=PySceneDetectBackend(),
        frame_reader=PyAVFrameReader(duration_us=duration_us),
        face_backend=FakeFaceBackend({}),
        face_model=model,
        proxy_validator=lambda _path, _manifest: None,
        created_by="tester",
    )
    from clipforge.media.local_file import path_from_file_uri
    from clipforge.schemas.vision import VisualAnalysisDocument
    from clipforge.storage import find_artifact
    from clipforge.vision.constants import KIND_VISUAL

    with database.connect() as connection:
        row = find_artifact(connection, "project-1", source_id, KIND_VISUAL)
    assert row is not None
    text = path_from_file_uri(row.uri).read_text(encoding="utf-8")
    document = VisualAnalysisDocument.model_validate_json(text)
    assert result.cache_hit is False
    assert document.proxy_width == width
    assert document.proxy_height == height
    return document


def _ready(
    root: Path,
    proxy_source: Path,
    duration_us: int,
    width: int,
    height: int,
) -> tuple[Database, str, Path, FaceModel]:
    database = Database(root / "clipforge.sqlite3")
    database.initialize()
    media = root / "source.bin"
    media.write_bytes(b"source-bytes")
    stat = media.stat()
    digest = hashlib.sha256(media.read_bytes()).hexdigest()
    project = Project(project_id="project-1", name="Media", created_at=stamp(), provenance=provenance())
    source = SourceAsset(
        source_asset_id="source-1",
        project_id="project-1",
        uri=media.resolve().as_uri(),
        license_record_id="lic-1",
        provenance=provenance(["source-1"]),
    )
    manifest = _manifest(digest, stat.st_size, stat.st_mtime_ns, duration_us, width, height)
    work = root / "work"
    workspace = SourceWorkspace(work, "project-1", "source-1")
    workspace.ensure()
    proxy = workspace.proxy_file("analysis.mp4")
    proxy.write_bytes(proxy_source.read_bytes())
    proxy_sha = hashlib.sha256(proxy.read_bytes()).hexdigest()
    sidecar = DerivativeCacheRecord(
        recipe_name=recipes.ANALYSIS_PROXY_NAME,
        recipe_version=recipes.ANALYSIS_PROXY_VERSION,
        source_sha256=digest,
        project_id="project-1",
        source_asset_id="source-1",
        video_stream_index=0,
        audio_stream_index=None,
        artifact_sha256=proxy_sha,
        size_bytes=proxy.stat().st_size,
        ffmpeg_version="test",
        arguments=["ffmpeg", "-i", "source.bin", "analysis.mp4"],
        validation_status="passed",
        created_at=datetime.now(UTC),
    )
    recipe = workspace.metadata_file("analysis-proxy.recipe.json")
    recipe.write_text(sidecar.model_dump_json(), encoding="utf-8")
    now = datetime.now(UTC)
    job = JobRecord(
        job_id="job-prepare",
        project_id="project-1",
        kind="media_prepare",
        status=JobStatus.SUCCEEDED,
        created_at=now,
        updated_at=now,
        payload={"source_asset_id": "source-1", "source_sha256": digest, "analysis_proxy_sha256": proxy_sha},
    )
    with database.transaction() as connection:
        insert_project(connection, project)
        insert_asset_license_record(
            connection,
            license_record(asset_id="source-1", status=RightsStatus.OWNED, evidence_uri="file:///evidence.txt"),
        )
        insert_source_asset(connection, source)
        insert_source_manifest(connection, manifest)
        insert_job(connection, job)
        insert_artifact(
            connection,
            artifact_id="artifact-proxy",
            project_id="project-1",
            job_id=job.job_id,
            source_asset_id="source-1",
            kind=recipes.KIND_PROXY,
            uri=proxy.resolve().as_uri(),
            provenance=provenance(["source-1"], job.job_id),
        )
    model_path = root / "models" / "vision" / "face-detector" / "blaze_face_short_range.tflite"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"face-model")
    model = FaceModel(
        filename=model_path.name,
        sha256=hashlib.sha256(b"face-model").hexdigest(),
        source_url=(
            "https://storage.googleapis.com/mediapipe-models/face_detector/"
            "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
        ),
        path=model_path,
        size_bytes=len(b"face-model"),
    )
    return database, "source-1", work, model


def _manifest(
    digest: str,
    size: int,
    mtime_ns: int,
    duration_us: int,
    width: int,
    height: int,
) -> SourceIngestManifest:
    video = VideoStreamInfo(
        index=0,
        width=width,
        height=height,
        display_width=width,
        display_height=height,
        avg_frame_rate=RationalNumber(numerator=30, denominator=1),
        duration_us=duration_us,
    )
    timeline = MediaTimelineInfo(
        video_origin_us=0,
        video_start_assumed_zero=False,
        audio_start_us=0,
        audio_offset_us=0,
        canonical_duration_us=duration_us,
        duration_evidence="selected_video_duration_ts",
    )
    probe = NormalizedMediaProbe(
        format=MediaFormatInfo(duration_us=duration_us),
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
    return SourceIngestManifest(
        source_asset_id="source-1",
        project_id="project-1",
        content_sha256=digest,
        size_bytes=size,
        mtime_ns=mtime_ns,
        original_filename="source.bin",
        transcription_eligible=False,
        video_stream_index=0,
        audio_stream_index=None,
        canonical_duration_us=duration_us,
        video_origin_us=0,
        ingested_at=datetime.now(UTC),
        probe=probe,
    )


def _color_cut(path: Path) -> Path:
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=160x90:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=160x90:r=30:d=2",
            "-filter_complex",
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            str(path),
        ]
    )
    return path


def _solid(path: Path, color: str, size: str, duration: str) -> Path:
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={size}:r=30:d={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "ultrafast",
            str(path),
        ]
    )
    return path


def _duration_us(path: Path) -> int:
    import av

    container = av.open(str(path))
    try:
        stream = container.streams.video[0]
        if stream.duration is None or stream.time_base is None:
            raise RuntimeError(f"{path.name} has no video duration")
        return rational_to_us(Fraction(stream.duration) * Fraction(stream.time_base))
    finally:
        container.close()
