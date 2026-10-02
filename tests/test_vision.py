"""Deterministic visual-analysis tests. No face-model download and no network."""

from __future__ import annotations

import hashlib
import multiprocessing
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.main import app
from clipforge.errors import MediaError, StorageError
from clipforge.media import recipes
from clipforge.media.disk import DiskStatus
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
from clipforge.schemas.vision import VisualAnalysisDocument
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
from clipforge.vision.cache import read_visual_cache
from clipforge.vision.constants import KIND_VISUAL
from clipforge.vision.geometry import normalize_box
from clipforge.vision.metrics import measure_frame
from clipforge.vision.models import FaceModel, ensure_face_model, require_face_download_budget
from clipforge.vision.service import analyze_source
from clipforge.vision.tracking import TimedFace, associate_scene
from clipforge.vision.verify import verify_vision
from tests.helpers import license_record, provenance, stamp
from tests.vision_fakes import FakeFaceBackend, FakeFrameReader, FakeSceneBackend, face_at, solid_frame

pytestmark = pytest.mark.vision
runner = CliRunner()
DURATION_US = 2_000_000


@pytest.fixture(autouse=True)
def _reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")


def test_help_states_detection_limits() -> None:
    for args in (
        ["vision", "--help"],
        ["vision", "doctor", "--help"],
        ["vision", "analyze", "--help"],
        ["vision", "show", "--help"],
        ["vision", "verify", "--help"],
        ["vision", "model", "--help"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0
        text = result.stdout.lower()
        assert "detection" in text
        assert "speaker" in text
        assert "candidate" in text


def test_analyze_caches_and_binds_the_producer(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    scenes = FakeSceneBackend([(0, DURATION_US)])
    frames = FakeFrameReader(_frames())
    faces = FakeFaceBackend({400_000: [face_at(0.30)], 1_000_000: [face_at(0.32)], 1_600_000: [face_at(0.34)]})
    first = _run(database, source_id, work, model, scenes, frames, faces)
    assert first.cache_hit is False
    assert scenes.calls == 1 and frames.calls == 1 and faces.calls > 0
    assert first.scene_count == 1
    assert first.face_track_count == 1
    document = _load(work, source_id)
    assert document.scenes[0].analysis_complete is False
    assert document.scenes[0].transcript_evidence is None
    assert document.scenes[0].visual_evidence
    assert document.face_observations[0].speaker_attribution == "unknown"
    assert document.provenance.inputs_sha256 == first.proxy_sha256
    with database.connect() as connection:
        row = find_artifact(connection, "project-1", source_id, KIND_VISUAL)
        job = get_job(connection, first.job_id)
    assert row is not None and row.job_id == job.job_id == document.provenance.job_id
    assert job.payload["analysis_id"] == document.analysis_id
    sidecar = read_visual_cache(SourceWorkspace(work, "project-1", source_id).vision_sidecar())
    assert sidecar is not None
    assert sidecar.analysis_id == document.analysis_id
    assert sidecar.job_id == job.job_id
    second = _run(database, source_id, work, model, scenes, frames, faces)
    assert second.cache_hit is True
    assert scenes.calls == 1 and frames.calls == 1
    assert second.job_id == first.job_id
    report = _verify(database, source_id, work, model)
    assert report.status == "PASS"


def test_track_resets_at_scene_boundary_and_single_points_stay_samples(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    scenes = FakeSceneBackend([(0, 1_000_000), (1_000_000, DURATION_US)])
    frames = FakeFrameReader(
        [
            solid_frame(200_000),
            solid_frame(500_000, (10, 10, 10)),
            solid_frame(800_000, (20, 20, 20)),
            solid_frame(1_200_000, (30, 30, 30)),
            solid_frame(1_500_000, (40, 40, 40)),
            solid_frame(1_800_000, (50, 50, 50)),
        ]
    )
    box = face_at(0.30)
    faces = FakeFaceBackend(
        {
            200_000: [box],
            500_000: [box],
            1_200_000: [box, face_at(0.75)],
            1_500_000: [box],
        }
    )
    _run(database, source_id, work, model, scenes, frames, faces)
    document = _load(work, source_id)
    ids = {item.track_id for item in document.face_observations}
    assert len(ids) == 2
    prefixes = {item[:10] for item in ids if item is not None}
    assert prefixes == {"scene-0000", "scene-0001"}
    assert {item.speaker_attribution for item in document.face_observations} == {"unknown"}
    singles = [
        item
        for item in document.face_detection_samples
        if item.timestamp_us == 1_200_000 and item.bounding_box.x == pytest.approx(0.75)
    ]
    assert len(singles) == 1
    assert singles[0].track_id not in ids


def test_single_detection_does_not_invent_an_interval(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    scenes = FakeSceneBackend([(0, DURATION_US)])
    frames = FakeFrameReader(_frames())
    faces = FakeFaceBackend({0: [face_at(0.4)]})
    result = _run(database, source_id, work, model, scenes, frames, faces)
    document = _load(work, source_id)
    assert result.face_detection_count == 1
    assert document.face_observations == []
    assert document.summary.face_track_count == 0


def test_several_faces_are_kept_without_a_main_face(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    scenes = FakeSceneBackend([(0, DURATION_US)])
    frames = FakeFrameReader(_frames())
    many = [face_at(0.05 + index * 0.15, confidence=0.5 + index * 0.05) for index in range(5)]
    faces = FakeFaceBackend({400_000: many, 1_000_000: many})
    _run(database, source_id, work, model, scenes, frames, faces)
    document = _load(work, source_id)
    at_400 = [item for item in document.face_detection_samples if item.timestamp_us == 400_000]
    assert len(at_400) == 5
    assert len(document.face_observations) == 5
    assert all(item.speaker_attribution == "unknown" for item in document.face_observations)


def test_invalid_boxes_are_rejected_and_tiny_overflow_is_clamped() -> None:
    assert normalize_box(-1, 0, 10, 10, frame_width=100, frame_height=100) is not None
    clamped = normalize_box(-1, 0, 10, 10, frame_width=100, frame_height=100)
    assert clamped is not None and clamped.clamped is True
    assert normalize_box(-5, 0, 10, 10, frame_width=100, frame_height=100) is None
    assert normalize_box(0, 0, -1, 10, frame_width=100, frame_height=100) is None
    assert normalize_box(0, 0, 10, 0, frame_width=100, frame_height=100) is None
    assert normalize_box(float("nan"), 0, 10, 10, frame_width=100, frame_height=100) is None
    assert normalize_box(0, float("inf"), 10, 10, frame_width=100, frame_height=100) is None
    assert normalize_box(200, 200, 10, 10, frame_width=100, frame_height=100) is None


def test_metrics_order_black_white_and_checkerboards() -> None:
    import numpy as np

    black = np.zeros((32, 32, 3), dtype=np.uint8)
    white = np.full((32, 32, 3), 255, dtype=np.uint8)
    gray = np.full((32, 32, 3), 128, dtype=np.uint8)
    sharp = np.zeros((32, 32, 3), dtype=np.uint8)
    sharp[::2, ::2] = 255
    sharp[1::2, 1::2] = 255
    blurred = np.full((32, 32, 3), 128, dtype=np.uint8)
    black_metrics = measure_frame(black, None)
    white_metrics = measure_frame(white, black)
    same = measure_frame(gray, gray)
    sharp_metrics = measure_frame(sharp, None)
    flat_metrics = measure_frame(blurred, sharp)
    assert white_metrics.mean_luma > black_metrics.mean_luma
    assert sharp_metrics.sharpness_laplacian_variance > flat_metrics.sharpness_laplacian_variance
    assert same.difference_from_previous_sample == 0
    assert white_metrics.difference_from_previous_sample is not None
    assert white_metrics.difference_from_previous_sample > 0


def test_requested_time_is_not_substituted_for_frame_pts(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    scenes = FakeSceneBackend([(0, DURATION_US)])
    frames = FakeFrameReader([solid_frame(5_017)])
    # 2 second scene still needs frames near the representative targets.
    frames = FakeFrameReader(
        [solid_frame(400_000), solid_frame(1_000_000), solid_frame(1_600_017), solid_frame(1_900_000)]
    )
    faces = FakeFaceBackend({1_600_017: [face_at(0.3)]})
    _run(database, source_id, work, model, scenes, frames, faces)
    document = _load(work, source_id)
    matched = [item for item in document.frame_evidence if 1_500_000 in item.matched_requests_us]
    assert matched
    assert matched[0].actual_timestamp_us == 1_600_017
    assert matched[0].requested_us != matched[0].actual_timestamp_us
    samples = [item for item in document.face_detection_samples if item.timestamp_us == 1_600_017]
    assert samples
    assert all(item.timestamp_us != 1_500_000 for item in document.face_detection_samples)


def test_crash_files_are_not_validated_by_the_old_job(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    scenes = FakeSceneBackend([(0, DURATION_US)])
    frames = FakeFrameReader(_frames())
    faces = FakeFaceBackend({})
    _run(database, source_id, work, model, scenes, frames, faces)
    workspace = SourceWorkspace(work, "project-1", source_id)
    document = _load(work, source_id)
    record = read_visual_cache(workspace.vision_sidecar())
    assert record is not None
    other = document.model_copy(
        update={
            "analysis_id": "analysis-other",
            "provenance": document.provenance.model_copy(update={"job_id": "job-other"}),
        }
    )
    run = workspace.vision_run_dir("analysis-other")
    run.mkdir()
    (run / "analysis.json").write_text(other.model_dump_json(), encoding="utf-8")
    stolen = record.model_copy(update={"analysis_id": "analysis-other", "job_id": "job-other"})
    workspace.vision_sidecar().write_text(stolen.model_dump_json(), encoding="utf-8")
    report = _verify(database, source_id, work, model)
    assert report.status == "FAIL"
    before = scenes.calls
    _run(database, source_id, work, model, scenes, frames, faces)
    assert scenes.calls == before + 1


def test_proxy_regeneration_misses_the_cache(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    scenes = FakeSceneBackend([(0, DURATION_US)])
    frames = FakeFrameReader(_frames())
    faces = FakeFaceBackend({})
    _run(database, source_id, work, model, scenes, frames, faces)
    workspace = SourceWorkspace(work, "project-1", source_id)
    proxy = workspace.proxy_file("analysis.mp4")
    proxy.write_bytes(b"proxy-bytes-regenerated")
    digest = hashlib.sha256(b"proxy-bytes-regenerated").hexdigest()
    record = DerivativeCacheRecord.model_validate_json(
        workspace.metadata_file("analysis-proxy.recipe.json").read_text(encoding="utf-8")
    )
    updated = record.model_copy(update={"artifact_sha256": digest, "size_bytes": proxy.stat().st_size})
    sidecar_path = workspace.metadata_file("analysis-proxy.recipe.json")
    sidecar_path.write_text(updated.model_dump_json(), encoding="utf-8")
    with database.transaction() as connection:
        job = get_job(connection, "job-prepare")
        payload = {**job.payload, "analysis_proxy_sha256": digest}
        update_job(connection, job.model_copy(update={"payload": payload}))
    report = _verify(database, source_id, work, model)
    assert report.status == "FAIL"
    _run(database, source_id, work, model, scenes, frames, faces)
    assert scenes.calls == 2


def test_source_mutation_and_failed_prepare_block_analysis(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    source = tmp_path / "source.bin"
    source.write_bytes(b"changed-source")
    scenes = FakeSceneBackend([(0, DURATION_US)])
    with pytest.raises(MediaError, match="source file changed"):
        _run(database, source_id, work, model, scenes, FakeFrameReader(_frames()), FakeFaceBackend({}))
    assert scenes.calls == 0
    database, source_id, work, model = _ready(tmp_path / "second")
    with database.transaction() as connection:
        job = get_job(connection, "job-prepare")
        update_job(
            connection,
            job.model_copy(update={"status": JobStatus.FAILED, "error_message": "prepare failed"}),
        )
    with pytest.raises(MediaError, match="expected succeeded"):
        _run(database, source_id, work, model, scenes, FakeFrameReader(_frames()), FakeFaceBackend({}))
    report = verify_vision(
        database=database,
        source_asset_id=source_id,
        work_root=work,
        model_root=_model_root(model),
    )
    assert report.status == "FAIL"


def test_log_failure_keeps_the_previous_analysis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, source_id, work, model = _ready(tmp_path)
    scenes = FakeSceneBackend([(0, DURATION_US)])
    frames = FakeFrameReader(_frames())
    faces = FakeFaceBackend({})
    _run(database, source_id, work, model, scenes, frames, faces)
    workspace = SourceWorkspace(work, "project-1", source_id)
    before = workspace.vision_sidecar().read_bytes()
    analysis = _load(work, source_id)

    def explode(path: Path, text: str, root: Path) -> None:
        del path, text, root
        raise OSError("log disk full")

    monkeypatch.setattr("clipforge.vision.service._write_log", explode)
    with pytest.raises(OSError, match="log disk full"):
        _run(database, source_id, work, model, scenes, frames, faces, force=True)
    assert workspace.vision_sidecar().read_bytes() == before
    assert _load(work, source_id).analysis_id == analysis.analysis_id
    with database.connect() as connection:
        jobs = list_jobs(connection, "project-1")
    assert any(job.kind == "visual_analyze" and job.status is JobStatus.FAILED for job in jobs)
    report = _verify(database, source_id, work, model)
    assert report.status == "PASS"


def test_cleanup_failure_still_closes_the_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, source_id, work, model = _ready(tmp_path)
    scenes = FakeSceneBackend([(0, DURATION_US)])
    frames = FakeFrameReader(_frames())
    faces = FakeFaceBackend({})
    _run(database, source_id, work, model, scenes, frames, faces)

    def explode_persist(*_args: object, **_kwargs: object) -> None:
        raise StorageError("db write failed")

    def explode_cleanup(*_args: object, **_kwargs: object) -> None:
        raise MediaError("cleanup refused")

    monkeypatch.setattr("clipforge.vision.service._commit_and_publish", explode_persist)
    monkeypatch.setattr("clipforge.vision.service._cleanup_failed_run", explode_cleanup)
    with pytest.raises(StorageError, match="db write failed"):
        _run(database, source_id, work, model, scenes, frames, faces, force=True)
    with database.connect() as connection:
        jobs = list_jobs(connection, "project-1")
    assert all(job.status is not JobStatus.RUNNING for job in jobs)
    failed = [job for job in jobs if job.status is JobStatus.FAILED]
    assert failed
    assert "db write failed" in (failed[-1].error_message or "")
    assert "cleanup refused" in (failed[-1].error_message or "")


def test_active_prepare_and_second_vision_fail_before_a_job(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    workspace = SourceWorkspace(work, "project-1", source_id)
    workspace.prepare_lock_path().touch()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(target=_hold_lock, args=(str(workspace.prepare_lock_path()), ready, release, True))
    holder.start()
    ready.wait(5)
    scenes = FakeSceneBackend([(0, DURATION_US)])
    try:
        with pytest.raises(MediaError, match="media prepare"):
            _run(database, source_id, work, model, scenes, FakeFrameReader(_frames()), FakeFaceBackend({}))
    finally:
        release.set()
        holder.join(5)
    assert scenes.calls == 0
    with database.connect() as connection:
        assert [job for job in list_jobs(connection, "project-1") if job.kind == "visual_analyze"] == []


def test_active_vision_blocks_a_second_analysis(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    workspace = SourceWorkspace(work, "project-1", source_id)
    workspace.prepare_lock_path().touch()
    workspace.vision_lock_path().touch()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_shared_prepare_and_transcribe,
        args=(str(workspace.prepare_lock_path()), str(workspace.vision_lock_path()), ready, release),
    )
    holder.start()
    ready.wait(5)
    scenes = FakeSceneBackend([(0, DURATION_US)])
    try:
        with pytest.raises(MediaError, match="visual analysis"):
            _run(database, source_id, work, model, scenes, FakeFrameReader(_frames()), FakeFaceBackend({}))
    finally:
        release.set()
        holder.join(5)
    assert scenes.calls == 0


def test_vision_can_share_prepare_with_transcription(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    workspace = SourceWorkspace(work, "project-1", source_id)
    workspace.prepare_lock_path().touch()
    workspace.transcribe_lock_path().touch()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_shared_prepare_and_transcribe,
        args=(str(workspace.prepare_lock_path()), str(workspace.transcribe_lock_path()), ready, release),
    )
    holder.start()
    ready.wait(5)
    try:
        result = _run(
            database,
            source_id,
            work,
            model,
            FakeSceneBackend([(0, DURATION_US)]),
            FakeFrameReader(_frames()),
            FakeFaceBackend({}),
        )
    finally:
        release.set()
        holder.join(5)
    assert result.scene_count == 1


def test_stale_running_job_is_failed_after_the_lock(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    now = datetime.now(UTC)
    stale = JobRecord(
        job_id="job-stale-vision",
        project_id="project-1",
        kind="visual_analyze",
        status=JobStatus.RUNNING,
        created_at=now,
        updated_at=now,
        payload={"source_asset_id": source_id},
    )
    with database.transaction() as connection:
        insert_job(connection, stale)
    _run(
        database,
        source_id,
        work,
        model,
        FakeSceneBackend([(0, DURATION_US)]),
        FakeFrameReader(_frames()),
        FakeFaceBackend({}),
    )
    with database.connect() as connection:
        updated = get_job(connection, "job-stale-vision")
    assert updated.status is JobStatus.FAILED


def test_backend_failure_does_not_leave_a_running_job(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)

    class Boom(FakeSceneBackend):
        def detect(self, path: Path, duration_us: int) -> list[tuple[int, int]]:
            self.calls += 1
            raise MediaError("scene detector failed")

    scenes = Boom([])
    with pytest.raises(MediaError, match="scene detector failed"):
        _run(database, source_id, work, model, scenes, FakeFrameReader(_frames()), FakeFaceBackend({}))
    with database.connect() as connection:
        jobs = [job for job in list_jobs(connection, "project-1") if job.kind == "visual_analyze"]
    assert jobs and all(job.status is JobStatus.FAILED for job in jobs)


def test_missing_model_explains_the_fetch_command(tmp_path: Path) -> None:
    database, source_id, work, _model = _ready(tmp_path)
    with pytest.raises(MediaError, match="vision model fetch face-detector --allow-model-download"):
        analyze_source(
            database=database,
            source_asset_id=source_id,
            work_root=work,
            model_root=tmp_path / "empty-models",
            scene_backend=FakeSceneBackend([(0, DURATION_US)]),
            frame_reader=FakeFrameReader(_frames()),
            face_backend=FakeFaceBackend({}),
            proxy_validator=lambda _path, _manifest: None,
            created_by="tester",
        )


def test_verify_does_not_create_a_missing_model_root(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    _run(
        database,
        source_id,
        work,
        model,
        FakeSceneBackend([(0, DURATION_US)]),
        FakeFrameReader(_frames()),
        FakeFaceBackend({}),
    )
    missing = tmp_path / "absent-model-root"
    report = verify_vision(database=database, source_asset_id=source_id, work_root=work, model_root=missing)
    assert report.status == "WARN"
    assert any(line.name == "face_model" for line in report.lines)
    assert not missing.exists()


def test_symlinked_model_root_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = tmp_path / "real_models"
    real.mkdir()
    link = tmp_path / "models_link"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr("clipforge.vision.models.remote_face_model_size", lambda _url: 100)

    def refuse_download(*_args: object, **_kwargs: object) -> FaceModel:
        raise AssertionError("downloaded")

    monkeypatch.setattr("clipforge.vision.models._download", refuse_download)
    with pytest.raises(MediaError, match="symlink"):
        ensure_face_model(link, allow_download=True)
    assert list(real.iterdir()) == []


def test_face_model_download_reserve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_download(url: str, directory: Path, *, expected_bytes: int | None) -> FaceModel:
        del url, expected_bytes
        calls.append("download")
        path = directory / "blaze_face_short_range.tflite"
        path.write_bytes(b"model")
        return FaceModel("blaze_face_short_range.tflite", "ab" * 32, "https://example.invalid", path, 5)

    monkeypatch.setattr("clipforge.vision.models.remote_face_model_size", lambda _url: 2 * 1024**3)
    monkeypatch.setattr("clipforge.vision.models._download", fake_download)
    monkeypatch.setattr(
        "clipforge.vision.models.read_disk",
        lambda root: DiskStatus(root, "test", 20 * 1024**3, 1, 13 * 1024**3, 10 * 1024**3),
    )
    ensure_face_model(tmp_path / "models-ok", allow_download=True)
    assert calls == ["download"]
    calls.clear()
    monkeypatch.setattr("clipforge.vision.models.remote_face_model_size", lambda _url: 4 * 1024**3)
    with pytest.raises(MediaError, match="refusing to download"):
        ensure_face_model(tmp_path / "models-big", allow_download=True)
    assert calls == []
    monkeypatch.setattr("clipforge.vision.models.remote_face_model_size", lambda _url: None)
    with pytest.raises(MediaError, match="could not determine the model download size"):
        ensure_face_model(tmp_path / "models-unknown", allow_download=True)
    assert calls == []
    with pytest.raises(MediaError, match="could not determine the model download size"):
        require_face_download_budget(13 * 1024**3, 10 * 1024**3, None)


def test_document_fingerprint_mismatch_fails_verify(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    _run(
        database,
        source_id,
        work,
        model,
        FakeSceneBackend([(0, DURATION_US)]),
        FakeFrameReader(_frames()),
        FakeFaceBackend({}),
    )
    workspace = SourceWorkspace(work, "project-1", source_id)
    document = _load(work, source_id)
    changed = document.model_copy(update={"adaptive_threshold": document.adaptive_threshold + 1})
    path = workspace.vision_run_dir(document.analysis_id) / "analysis.json"
    path.write_text(changed.model_dump_json(), encoding="utf-8")
    record = read_visual_cache(workspace.vision_sidecar())
    assert record is not None
    encoded = path.read_bytes()
    workspace.vision_sidecar().write_text(
        record.model_copy(
            update={
                "analysis_artifact_sha256": hashlib.sha256(encoded).hexdigest(),
                "analysis_artifact_size": len(encoded),
            }
        ).model_dump_json(),
        encoding="utf-8",
    )
    report = _verify(database, source_id, work, model)
    assert report.status == "FAIL"
    scenes = FakeSceneBackend([(0, DURATION_US)])
    _run(database, source_id, work, model, scenes, FakeFrameReader(_frames()), FakeFaceBackend({}))
    assert scenes.calls == 1


def test_contact_sheet_decodes_and_lists_the_scene(tmp_path: Path) -> None:
    import cv2

    database, source_id, work, model = _ready(tmp_path)
    _run(
        database,
        source_id,
        work,
        model,
        FakeSceneBackend([(0, DURATION_US)]),
        FakeFrameReader(_frames()),
        FakeFaceBackend({}),
    )
    document = _load(work, source_id)
    sheet = document.contact_sheets[0]
    assert sheet.scene_ordinals
    run = SourceWorkspace(work, "project-1", source_id).vision_run_dir(document.analysis_id)
    path = run / sheet.relative_path
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert image is not None
    assert image.shape[1] == sheet.width
    assert image.shape[0] == sheet.height
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sheet.sha256


def test_force_keeps_the_previous_run(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    scenes = FakeSceneBackend([(0, DURATION_US)])
    frames = FakeFrameReader(_frames())
    faces = FakeFaceBackend({})
    first = _run(database, source_id, work, model, scenes, frames, faces)
    workspace = SourceWorkspace(work, "project-1", source_id)
    old_run = workspace.vision_run_dir(first.analysis_id)
    second = _run(database, source_id, work, model, scenes, frames, faces, force=True)
    assert second.analysis_id != first.analysis_id
    assert second.job_id != first.job_id
    assert (old_run / "analysis.json").is_file()
    assert _load(work, source_id).analysis_id == second.analysis_id


def test_cancellation_closes_the_job(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)

    class Stop(FakeSceneBackend):
        def detect(self, path: Path, duration_us: int) -> list[tuple[int, int]]:
            del path, duration_us
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run(database, source_id, work, model, Stop([]), FakeFrameReader(_frames()), FakeFaceBackend({}))
    with database.connect() as connection:
        jobs = [job for job in list_jobs(connection, "project-1") if job.kind == "visual_analyze"]
    assert jobs and jobs[-1].status is JobStatus.CANCELLED


def test_missing_or_modified_evidence_fails_verify(tmp_path: Path) -> None:
    database, source_id, work, model = _ready(tmp_path)
    _run(
        database,
        source_id,
        work,
        model,
        FakeSceneBackend([(0, DURATION_US)]),
        FakeFrameReader(_frames()),
        FakeFaceBackend({}),
    )
    document = _load(work, source_id)
    workspace = SourceWorkspace(work, "project-1", source_id)
    image = workspace.vision_run_dir(document.analysis_id) / document.frame_evidence[0].relative_path
    original = image.read_bytes()
    image.write_bytes(original + b"x")
    assert _verify(database, source_id, work, model).status == "FAIL"
    image.write_bytes(original)
    image.unlink()
    assert _verify(database, source_id, work, model).status == "FAIL"


def test_geometry_tracking_is_deterministic() -> None:
    first = TimedFace(0, 0, face_at(0.30), 0)
    second = TimedFace(0, 500_000, face_at(0.32), 0)
    other = TimedFace(0, 500_000, face_at(0.75), 1)
    tracked, intervals = associate_scene([first, second, other], scene_ordinal=4)
    assert len(intervals) == 2
    assert {item.track_id for item in tracked} == {
        "scene-0004-face-track-0000",
        "scene-0004-face-track-0001",
    }
    moving = next(item for item in intervals if len(item.timestamps) == 2)
    assert moving.end_us > moving.start_us


def _verify(database: Database, source_id: str, work: Path, model: FaceModel) -> object:
    return verify_vision(
        database=database,
        source_asset_id=source_id,
        work_root=work,
        model_root=_model_root(model),
    )


def _run(
    database: Database,
    source_id: str,
    work: Path,
    model: FaceModel,
    scenes: FakeSceneBackend,
    frames: FakeFrameReader,
    faces: FakeFaceBackend,
    *,
    force: bool = False,
) -> object:
    from clipforge.vision.service import VisionResult

    result = analyze_source(
        database=database,
        source_asset_id=source_id,
        work_root=work,
        model_root=model.path.parent,
        scene_backend=scenes,
        frame_reader=frames,
        face_backend=faces,
        face_model=model,
        proxy_validator=lambda _path, _manifest: None,
        created_by="tester",
        force=force,
    )
    assert isinstance(result, VisionResult)
    return result


def _ready(tmp_path: Path) -> tuple[Database, str, Path, FaceModel]:
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    media = tmp_path / "source.bin"
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
    manifest = _manifest(digest, stat.st_size, stat.st_mtime_ns)
    record = license_record(asset_id="source-1", status=RightsStatus.OWNED, evidence_uri="file:///evidence.txt")
    work = tmp_path / "work"
    workspace = SourceWorkspace(work, "project-1", "source-1")
    workspace.ensure()
    proxy = workspace.proxy_file("analysis.mp4")
    proxy.write_bytes(b"proxy-bytes")
    proxy_sha = hashlib.sha256(b"proxy-bytes").hexdigest()
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
        payload={
            "source_asset_id": "source-1",
            "source_sha256": digest,
            "analysis_proxy_sha256": proxy_sha,
        },
    )
    with database.transaction() as connection:
        insert_project(connection, project)
        insert_asset_license_record(connection, record)
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
    model = _model(tmp_path / "models")
    return database, "source-1", work, model


def _manifest(digest: str, size: int, mtime_ns: int) -> SourceIngestManifest:
    video = VideoStreamInfo(
        index=0,
        width=16,
        height=16,
        display_width=16,
        display_height=16,
        avg_frame_rate=RationalNumber(numerator=30, denominator=1),
        r_frame_rate=RationalNumber(numerator=30, denominator=1),
        time_base=RationalNumber(numerator=1, denominator=30),
        duration_us=DURATION_US,
    )
    timeline = MediaTimelineInfo(
        video_origin_us=0,
        video_start_assumed_zero=False,
        audio_start_us=0,
        audio_offset_us=0,
        canonical_duration_us=DURATION_US,
        duration_evidence="selected_video_duration_ts",
    )
    probe = NormalizedMediaProbe(
        format=MediaFormatInfo(duration_us=DURATION_US),
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
        canonical_duration_us=DURATION_US,
        video_origin_us=0,
        ingested_at=datetime.now(UTC),
        probe=probe,
    )


def _frames() -> list[object]:
    return [
        solid_frame(0),
        solid_frame(400_000, (20, 0, 0)),
        solid_frame(1_000_000, (0, 20, 0)),
        solid_frame(1_600_000, (0, 0, 20)),
        solid_frame(1_900_000, (5, 5, 5)),
    ]


def _model(root: Path) -> FaceModel:
    path = root / "vision" / "face-detector" / "blaze_face_short_range.tflite"
    path.parent.mkdir(parents=True)
    payload = b"face-model"
    path.write_bytes(payload)
    return FaceModel(
        filename="blaze_face_short_range.tflite",
        sha256=hashlib.sha256(payload).hexdigest(),
        source_url=(
            "https://storage.googleapis.com/mediapipe-models/face_detector/"
            "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
        ),
        path=path,
        size_bytes=len(payload),
    )


def _model_root(model: FaceModel) -> Path:
    return model.path.parents[2]


def _load(work: Path, source_id: str) -> VisualAnalysisDocument:
    with Database(work.parent / "clipforge.sqlite3").connect() as connection:
        row = find_artifact(connection, "project-1", source_id, KIND_VISUAL)
    assert row is not None
    from clipforge.media.local_file import path_from_file_uri

    return VisualAnalysisDocument.model_validate_json(path_from_file_uri(row.uri).read_text(encoding="utf-8"))


def _hold_lock(path: str, ready: object, release: object, exclusive: bool) -> None:
    import fcntl

    descriptor = os.open(path, os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
    ready.set()  # type: ignore[attr-defined]
    release.wait(30)  # type: ignore[attr-defined]
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def _hold_shared_prepare_and_transcribe(
    prepare_path: str,
    transcribe_path: str,
    ready: object,
    release: object,
) -> None:
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
