"""Analyze one source from its current analysis proxy.

The SQLite write transaction is closed before scene detection and face
detection. Shared ``prepare.lock`` is acquired before exclusive ``vision.lock``.
A failed run does not replace a visual analysis that was already current.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import ValidationError

from clipforge.errors import MediaError, StorageError
from clipforge.media import recipes
from clipforge.media.cache import cache_identity_matches as media_cache_matches
from clipforge.media.cache import read_cache_record as read_media_cache
from clipforge.media.clock import proxy_pixel_size
from clipforge.media.disk import read_disk, require_disk_budget
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri, path_to_file_uri
from clipforge.media.mutation import inspect_mutation
from clipforge.media.process import ProcessRunner
from clipforge.media.validate import validate_proxy
from clipforge.media.workspace import (
    SourceWorkspace,
    ensure_within,
    prepare_read_lock,
    vision_lock,
)
from clipforge.schemas.governance import require_rights_cleared
from clipforge.schemas.ingest import SourceIngestManifest
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import SourceAsset
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.vision import (
    ContactSheet,
    VisualAnalysisCacheRecord,
    VisualAnalysisDocument,
)
from clipforge.storage import (
    Database,
    find_artifact,
    get_asset_license_record,
    get_job,
    get_source_asset,
    get_source_manifest,
    insert_artifact,
    insert_job,
    list_jobs,
    update_artifact,
    update_job,
    update_source_manifest_stats,
)
from clipforge.transcription.io import publish_json
from clipforge.vision.cache import cache_identity_matches, read_visual_cache
from clipforge.vision.constants import (
    ADAPTIVE_THRESHOLD,
    CONTACT_COLUMNS,
    CONTACT_ROWS,
    FACE_SAMPLE_INTERVAL_US,
    JOB_VISUAL,
    JPEG_LONG_EDGE,
    JPEG_QUALITY,
    KIND_VISUAL,
    MIN_CONTENT_VAL,
    MIN_DETECTION_CONFIDENCE,
    MIN_SCENE_LEN_FRAMES,
    MIN_SUPPRESSION_THRESHOLD,
    RECIPE_NAME,
    RECIPE_VERSION,
    REPRESENTATIVE_FRACTIONS,
    SCENE_ENDPOINT_TOLERANCE_US,
    SHORT_SCENE_US,
    TRACKING_CENTER_DISTANCE,
    TRACKING_IOU_THRESHOLD,
    TRACKING_MAX_GAP_US,
    WINDOW_WIDTH,
)
from clipforge.vision.document import StoredDetection, StoredSample, assemble_document
from clipforge.vision.face_backend import MediaPipeFaceDetectionBackend
from clipforge.vision.frame_reader import PyAVFrameReader
from clipforge.vision.geometry import NormalizedFace
from clipforge.vision.images import write_contact_sheet, write_jpeg
from clipforge.vision.integrity import visual_problems
from clipforge.vision.metrics import measure_frame
from clipforge.vision.models import FaceModel, ensure_face_model
from clipforge.vision.profile import (
    face_fingerprint,
    sampling_fingerprint,
    scene_fingerprint,
    tracking_fingerprint,
)
from clipforge.vision.runtime import installed_versions
from clipforge.vision.sampling import assign_samples, normalize_scenes, plan_requests
from clipforge.vision.scene_backend import PySceneDetectBackend
from clipforge.vision.tracking import TimedFace, TrackInterval, associate_scene
from clipforge.vision.types import (
    AssignedSample,
    DecodedFrame,
    FaceDetectionBackend,
    FrameReader,
    SceneDetectionBackend,
)

ProxyValidator = Callable[[Path, SourceIngestManifest], None]


@dataclass(frozen=True, slots=True)
class VisionResult:
    job_id: str
    analysis_id: str
    source_asset_id: str
    project_id: str
    proxy_sha256: str
    scene_count: int
    representative_frame_count: int
    face_sample_frame_count: int
    face_detection_count: int
    face_track_count: int
    contact_sheet_count: int
    analysis_path: Path
    analysis_sha256: str
    cache_hit: bool
    runtime_seconds: float
    warning: str | None


def analyze_source(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    model_root: Path,
    allow_model_download: bool = False,
    force: bool = False,
    scene_backend: SceneDetectionBackend | None = None,
    frame_reader: FrameReader | None = None,
    face_backend: FaceDetectionBackend | None = None,
    face_model: FaceModel | None = None,
    proxy_validator: ProxyValidator | None = None,
    created_by: str | None = None,
) -> VisionResult:
    """Analyze ``source_asset_id``. An arbitrary video path is not accepted."""
    root = work_root.resolve()
    validator = proxy_validator or _validate_proxy
    context = _preflight(
        database=database,
        source_asset_id=source_asset_id,
        root=root,
        proxy_validator=validator,
    )
    model = face_model or ensure_face_model(model_root, allow_download=allow_model_download)
    scenes = scene_backend if scene_backend is not None else PySceneDetectBackend()
    if frame_reader is not None:
        reader = frame_reader
    else:
        reader = PyAVFrameReader(duration_us=context.manifest.canonical_duration_us)
    actor = created_by.strip()[:200] if created_by and created_by.strip() else _actor()
    busy = (
        f"another media prepare is already active for source {source_asset_id}. "
        "Clipforge refused to start visual analysis so the analysis proxy cannot be replaced."
    )
    started = perf_counter()
    with prepare_read_lock(context.workspace, busy=busy), vision_lock(context.workspace):
        context = _revalidate(database, context, validator)
        return _locked(
            database=database,
            context=context,
            root=root,
            model=model,
            scenes=scenes,
            reader=reader,
            faces=face_backend,
            actor=actor,
            force=force,
            started=started,
        )


@dataclass(frozen=True, slots=True)
class _Context:
    source: SourceAsset
    manifest: SourceIngestManifest
    workspace: SourceWorkspace
    proxy_path: Path
    proxy_sha256: str
    media_job_id: str
    width: int
    height: int


def _preflight(
    *,
    database: Database,
    source_asset_id: str,
    root: Path,
    proxy_validator: ProxyValidator,
) -> _Context:
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
        manifest = get_source_manifest(connection, source_asset_id)
        license_record = get_asset_license_record(connection, source.license_record_id)
    if source.project_id != manifest.project_id:
        raise MediaError(
            f"source {source_asset_id} is in project {source.project_id} but its manifest is in "
            f"{manifest.project_id}. Refusing to analyze across projects."
        )
    require_rights_cleared(license_record)
    manifest = _refresh_mutation(database, source, manifest)
    workspace = SourceWorkspace(root, source.project_id, source_asset_id)
    workspace.ensure()
    proxy_path, proxy_sha, media_job, width, height = _require_proxy(
        database, source, manifest, workspace, proxy_validator
    )
    return _Context(source, manifest, workspace, proxy_path, proxy_sha, media_job, width, height)


def _locked(
    *,
    database: Database,
    context: _Context,
    root: Path,
    model: FaceModel,
    scenes: SceneDetectionBackend,
    reader: FrameReader,
    faces: FaceDetectionBackend | None,
    actor: str,
    force: bool,
    started: float,
) -> VisionResult:
    _fail_stale(database, context)
    pyav_version, opencv_version, mediapipe_version = installed_versions()[1:]
    fingerprints = _fingerprints(scenes)
    cached = not force and _cache_ready(
        database,
        context,
        scenes,
        model,
        pyav_version,
        opencv_version,
        mediapipe_version,
        fingerprints,
    )
    if cached:
        return _cache_result(database, context, started)
    _require_visual_budget(root, context.manifest.canonical_duration_us)
    now = datetime.now(UTC)
    job = _running_job(
        context,
        scenes,
        model,
        pyav_version,
        opencv_version,
        mediapipe_version,
        fingerprints,
        now,
    )
    with database.transaction() as connection:
        insert_job(connection, job)
    analysis_id = str(uuid.uuid4())
    run_dir: Path | None = None
    opened: MediaPipeFaceDetectionBackend | None = None
    try:
        active: FaceDetectionBackend
        if faces is None:
            opened = MediaPipeFaceDetectionBackend(model.path)
            active = opened
        else:
            active = faces
        run_dir = context.workspace.make_vision_run(analysis_id)
        document, analysis_path = _analyze(
            context=context,
            root=root,
            run_dir=run_dir,
            analysis_id=analysis_id,
            job=job,
            model=model,
            scenes=scenes,
            reader=reader,
            faces=active,
            actor=actor,
            pyav_version=pyav_version,
            opencv_version=opencv_version,
            mediapipe_version=mediapipe_version,
            fingerprints=fingerprints,
        )
        _write_log(run_dir / "logs" / f"{job.job_id}.log", _log_text(document), root)
        digest, size = sha256_file(analysis_path), analysis_path.stat().st_size
        record = _cache_record(
            context,
            document,
            job_id=job.job_id,
            scenes=scenes,
            model=model,
            pyav_version=pyav_version,
            opencv_version=opencv_version,
            mediapipe_version=mediapipe_version,
            fingerprints=fingerprints,
            digest=digest,
            size=size,
            created_at=document.created_at,
        )
        _commit_and_publish(database, context, job, document, analysis_path, record, actor, root)
    except KeyboardInterrupt:
        _abandon(database, job, JobStatus.CANCELLED, "visual analysis cancelled", run_dir, root)
        raise
    except (MediaError, StorageError, OSError, ValidationError) as exc:
        _abandon(database, job, JobStatus.FAILED, str(exc), run_dir, root)
        raise
    finally:
        if opened is not None:
            with suppress(Exception):
                opened.close()
    return _result_from_document(
        document,
        job_id=job.job_id,
        path=analysis_path,
        digest=digest,
        cache_hit=False,
        started=started,
    )


def _analyze(
    *,
    context: _Context,
    root: Path,
    run_dir: Path,
    analysis_id: str,
    job: JobRecord,
    model: FaceModel,
    scenes: SceneDetectionBackend,
    reader: FrameReader,
    faces: FaceDetectionBackend,
    actor: str,
    pyav_version: str,
    opencv_version: str,
    mediapipe_version: str,
    fingerprints: tuple[str, str, str, str],
) -> tuple[VisualAnalysisDocument, Path]:
    duration = context.manifest.canonical_duration_us
    raw = scenes.detect(context.proxy_path, duration)
    spans = normalize_scenes(raw, duration)
    requests = plan_requests(spans)
    samples: list[StoredSample] = []
    representative: list[tuple[Path, int, int]] = []
    previous_scene = -1
    previous_rgb: object | None = None
    for assigned in assign_samples(
        _guard_frames(reader.frames(context.proxy_path), duration, context.width, context.height),
        requests,
    ):
        if assigned.scene_ordinal != previous_scene:
            previous_rgb = None
            previous_scene = assigned.scene_ordinal
        metrics = measure_frame(assigned.frame.rgb, previous_rgb)
        previous_rgb = assigned.frame.rgb
        relative, digest, size, width, height = _maybe_jpeg(run_dir, root, assigned)
        if assigned.face:
            detections = tuple(faces.detect(assigned.frame.rgb, assigned.frame.timestamp_us))
        else:
            detections = ()
        if relative is not None:
            representative.append((run_dir / relative, assigned.scene_ordinal, assigned.frame.timestamp_us))
        samples.append(
            StoredSample(
                scene_ordinal=assigned.scene_ordinal,
                requested_us=assigned.requested_us,
                matched_requests_us=assigned.matched_requests_us,
                labels=assigned.labels,
                timestamp_us=assigned.frame.timestamp_us,
                width=width,
                height=height,
                relative_path=relative,
                sha256=digest,
                size_bytes=size,
                metrics=metrics,
                detections=_stored_faces(detections),
            )
        )
    tracked_samples, intervals = _track(samples)
    sheets = _contact_sheets(run_dir, root, representative)
    source = context.source
    finished = datetime.now(UTC)
    provenance = ArtifactProvenance(
        created_at=finished,
        created_by=actor,
        tool="clipforge-vision",
        tool_version=RECIPE_VERSION,
        source_asset_ids=[source.source_asset_id],
        job_id=job.job_id,
        inputs_sha256=context.proxy_sha256,
    )
    scene_fp, sampling_fp, face_fp, tracking_fp = fingerprints
    document = assemble_document(
        analysis_id=analysis_id,
        project_id=source.project_id,
        source_asset_id=source.source_asset_id,
        created_at=finished,
        canonical_duration_us=duration,
        source_sha256=context.manifest.content_sha256,
        proxy_sha256=context.proxy_sha256,
        proxy_recipe_name=recipes.ANALYSIS_PROXY_NAME,
        proxy_recipe_version=recipes.ANALYSIS_PROXY_VERSION,
        proxy_width=context.width,
        proxy_height=context.height,
        recipe_name=RECIPE_NAME,
        recipe_version=RECIPE_VERSION,
        scene_engine=scenes.engine,
        pyscenedetect_version=scenes.version,
        scene_backend=scenes.backend,
        scene_detector=scenes.detector,
        scene_profile_fingerprint=scene_fp,
        adaptive_threshold=ADAPTIVE_THRESHOLD,
        min_content_val=MIN_CONTENT_VAL,
        window_width=WINDOW_WIDTH,
        min_scene_len_frames=MIN_SCENE_LEN_FRAMES,
        sampling_profile_fingerprint=sampling_fp,
        representative_fractions=list(REPRESENTATIVE_FRACTIONS),
        short_scene_us=SHORT_SCENE_US,
        face_sample_interval_us=FACE_SAMPLE_INTERVAL_US,
        jpeg_quality=JPEG_QUALITY,
        jpeg_long_edge=JPEG_LONG_EDGE,
        pyav_version=pyav_version,
        opencv_version=opencv_version,
        face_engine=faces.engine,
        mediapipe_version=mediapipe_version,
        face_model_filename=model.filename,
        face_model_sha256=model.sha256,
        face_model_source=model.source_url,
        face_profile_fingerprint=face_fp,
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_suppression_threshold=MIN_SUPPRESSION_THRESHOLD,
        tracking_profile_fingerprint=tracking_fp,
        tracking_iou_threshold=TRACKING_IOU_THRESHOLD,
        tracking_center_distance_threshold=TRACKING_CENTER_DISTANCE,
        tracking_max_gap_us=TRACKING_MAX_GAP_US,
        spans=spans,
        samples=tracked_samples,
        intervals=intervals,
        contact_sheets=sheets,
        provenance=provenance,
    )
    final = run_dir / "analysis.json"
    partial = context.workspace.partial_for(final)
    publish_json(final, document, root, partial)
    return document, final


def _stored_faces(detections: object) -> tuple[StoredDetection, ...]:
    if not isinstance(detections, tuple):
        raise MediaError("face backend did not return a tuple of faces")
    stored: list[StoredDetection] = []
    for item in detections:
        if not isinstance(item, NormalizedFace):
            raise MediaError("face backend returned a value that is not normalized face geometry")
        stored.append(StoredDetection(face=item, track_id=""))
    return tuple(stored)


def _track(samples: list[StoredSample]) -> tuple[list[StoredSample], list[TrackInterval]]:
    grouped: dict[int, list[StoredSample]] = {}
    for sample in samples:
        grouped.setdefault(sample.scene_ordinal, []).append(sample)
    intervals: list[TrackInterval] = []
    updated: list[StoredSample] = []
    for ordinal in sorted(grouped):
        timed: list[TimedFace] = []
        ordinals: list[tuple[int, int]] = []
        detection_ordinal = 0
        for sample_index, sample in enumerate(grouped[ordinal]):
            for face_index, detection in enumerate(sample.detections):
                timed.append(
                    TimedFace(
                        scene_ordinal=ordinal,
                        timestamp_us=sample.timestamp_us,
                        face=detection.face,
                        detection_ordinal=detection_ordinal,
                    )
                )
                ordinals.append((sample_index, face_index))
                detection_ordinal += 1
        tracked, scene_intervals = associate_scene(timed, scene_ordinal=ordinal)
        intervals.extend(scene_intervals)
        by_ordinal = {item.detection_ordinal: item.track_id for item in tracked}
        rebuilt: list[list[StoredDetection]] = [[] for _ in grouped[ordinal]]
        for index, (sample_index, _face_index) in enumerate(ordinals):
            face = grouped[ordinal][sample_index].detections[_face_index].face
            track_id = by_ordinal.get(index)
            if track_id is None:
                raise MediaError("face tracking dropped a detection")
            rebuilt[sample_index].append(StoredDetection(face=face, track_id=track_id))
        for sample_index, sample in enumerate(grouped[ordinal]):
            updated.append(
                StoredSample(
                    scene_ordinal=sample.scene_ordinal,
                    requested_us=sample.requested_us,
                    matched_requests_us=sample.matched_requests_us,
                    labels=sample.labels,
                    timestamp_us=sample.timestamp_us,
                    width=sample.width,
                    height=sample.height,
                    relative_path=sample.relative_path,
                    sha256=sample.sha256,
                    size_bytes=sample.size_bytes,
                    metrics=sample.metrics,
                    detections=tuple(rebuilt[sample_index]),
                )
            )
    return updated, intervals


def _maybe_jpeg(
    run_dir: Path,
    root: Path,
    assigned: AssignedSample,
) -> tuple[str | None, str | None, int | None, int, int]:
    if not assigned.labels:
        return None, None, None, assigned.frame.width, assigned.frame.height
    label = assigned.labels[0]
    relative = f"frames/scene-{assigned.scene_ordinal:04d}-{label}.jpg"
    path = run_dir / relative
    ensure_within(root, path)
    width, height = write_jpeg(path, assigned.frame.rgb)
    return relative, sha256_file(path), path.stat().st_size, width, height


def _contact_sheets(run_dir: Path, root: Path, tiles: list[tuple[Path, int, int]]) -> list[ContactSheet]:
    if not tiles:
        raise MediaError("visual analysis produced no representative frames")
    page_size = CONTACT_COLUMNS * CONTACT_ROWS
    sheets: list[ContactSheet] = []
    for page, start in enumerate(range(0, len(tiles), page_size), start=1):
        chunk = tiles[start : start + page_size]
        relative = f"contact-sheets/contact-{page:04d}.jpg"
        path = run_dir / relative
        ensure_within(root, path)
        width, height = write_contact_sheet(path, chunk)
        sheets.append(
            ContactSheet(
                relative_path=relative,
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
                width=width,
                height=height,
                scene_ordinals=[ordinal for _path, ordinal, _timestamp in chunk],
            )
        )
    return sheets


def _guard_frames(
    frames: Iterator[DecodedFrame],
    duration_us: int,
    width: int,
    height: int,
) -> Iterator[DecodedFrame]:
    previous = -1
    for frame in frames:
        if frame.timestamp_us < previous:
            raise MediaError("decoded frame timestamps are not monotonic")
        if frame.timestamp_us > duration_us + SCENE_ENDPOINT_TOLERANCE_US:
            raise MediaError(
                f"frame at {frame.timestamp_us} us is outside the canonical duration {duration_us} us"
            )
        if frame.timestamp_us >= duration_us:
            continue
        if frame.width != width or frame.height != height:
            raise MediaError(
                f"decoded frame is {frame.width}x{frame.height}, expected the analysis proxy {width}x{height}"
            )
        previous = frame.timestamp_us
        yield frame


def _commit_and_publish(
    database: Database,
    context: _Context,
    job: JobRecord,
    document: VisualAnalysisDocument,
    analysis_path: Path,
    record: VisualAnalysisCacheRecord,
    actor: str,
    root: Path,
) -> None:
    previous = _artifact_snapshot(database, context)
    provenance = ArtifactProvenance(
        created_at=document.created_at,
        created_by=actor,
        tool="clipforge-vision",
        tool_version=RECIPE_VERSION,
        source_asset_ids=[context.source.source_asset_id],
        job_id=job.job_id,
        inputs_sha256=context.proxy_sha256,
    )
    payload = dict(job.payload)
    payload["analysis_id"] = document.analysis_id
    payload["cache"] = "miss"
    succeeded = job.model_copy(
        update={
            "status": JobStatus.SUCCEEDED,
            "updated_at": document.created_at,
            "error_message": None,
            "payload": payload,
        }
    )
    with database.transaction() as connection:
        existing = find_artifact(
            connection,
            context.source.project_id,
            context.source.source_asset_id,
            KIND_VISUAL,
        )
        uri = path_to_file_uri(analysis_path)
        if existing is None:
            insert_artifact(
                connection,
                artifact_id=str(uuid.uuid4()),
                project_id=context.source.project_id,
                job_id=job.job_id,
                source_asset_id=context.source.source_asset_id,
                kind=KIND_VISUAL,
                uri=uri,
                provenance=provenance,
            )
        else:
            update_artifact(
                connection,
                artifact_id=existing.artifact_id,
                project_id=context.source.project_id,
                job_id=job.job_id,
                source_asset_id=context.source.source_asset_id,
                kind=KIND_VISUAL,
                uri=uri,
                provenance=provenance,
            )
        update_job(connection, succeeded)
    try:
        partial = context.workspace.partial_for(context.workspace.vision_sidecar())
        publish_json(context.workspace.vision_sidecar(), record, root, partial)
    except (OSError, MediaError) as exc:
        _revert_artifact(database, context, previous, job, str(exc))
        raise MediaError(
            f"visual analysis sidecar was not published: {exc}. The previous analysis remains current."
        ) from exc


def _artifact_snapshot(
    database: Database,
    context: _Context,
) -> tuple[str, str | None, str, ArtifactProvenance] | None:
    with database.connect() as connection:
        row = find_artifact(connection, context.source.project_id, context.source.source_asset_id, KIND_VISUAL)
    if row is None:
        return None
    return row.artifact_id, row.job_id, row.uri, row.provenance


def _revert_artifact(
    database: Database,
    context: _Context,
    previous: tuple[str, str | None, str, ArtifactProvenance] | None,
    job: JobRecord,
    reason: str,
) -> None:
    failed = job.model_copy(
        update={
            "status": JobStatus.FAILED,
            "updated_at": datetime.now(UTC),
            "error_message": f"sidecar publish failed: {reason}"[:2000],
        }
    )
    with database.transaction() as connection:
        if previous is not None:
            artifact_id, job_id, uri, provenance = previous
            update_artifact(
                connection,
                artifact_id=artifact_id,
                project_id=context.source.project_id,
                job_id=job_id,
                source_asset_id=context.source.source_asset_id,
                kind=KIND_VISUAL,
                uri=uri,
                provenance=provenance,
            )
        update_job(connection, failed)


def _cache_ready(
    database: Database,
    context: _Context,
    scenes: SceneDetectionBackend,
    model: FaceModel,
    pyav_version: str,
    opencv_version: str,
    mediapipe_version: str,
    fingerprints: tuple[str, str, str, str],
) -> bool:
    record = read_visual_cache(context.workspace.vision_sidecar())
    if record is None:
        return False
    with database.connect() as connection:
        row = find_artifact(connection, context.source.project_id, context.source.source_asset_id, KIND_VISUAL)
        if row is None or row.job_id is None:
            return False
        try:
            job = get_job(connection, row.job_id)
        except StorageError:
            return False
    try:
        analysis_path = path_from_file_uri(row.uri)
    except MediaError:
        return False
    scene_fp, sampling_fp, face_fp, tracking_fp = fingerprints
    if not cache_identity_matches(
        record,
        project_id=context.source.project_id,
        source_asset_id=context.source.source_asset_id,
        source_sha256=context.manifest.content_sha256,
        proxy_sha256=context.proxy_sha256,
        proxy_recipe_name=recipes.ANALYSIS_PROXY_NAME,
        proxy_recipe_version=recipes.ANALYSIS_PROXY_VERSION,
        recipe_name=RECIPE_NAME,
        recipe_version=RECIPE_VERSION,
        pyscenedetect_version=scenes.version,
        scene_backend=scenes.backend,
        scene_profile_fingerprint=scene_fp,
        pyav_version=pyav_version,
        opencv_version=opencv_version,
        mediapipe_version=mediapipe_version,
        face_model_sha256=model.sha256,
        face_profile_fingerprint=face_fp,
        sampling_profile_fingerprint=sampling_fp,
        tracking_profile_fingerprint=tracking_fp,
        analysis_path=analysis_path,
    ):
        return False
    try:
        document = VisualAnalysisDocument.model_validate_json(analysis_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return False
    problems = visual_problems(
        document,
        record,
        analysis_path=analysis_path,
        work_root=context.workspace.root,
        current_proxy_sha256=context.proxy_sha256,
        artifact_job_id=row.job_id,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
    )
    return not problems


def _cache_result(database: Database, context: _Context, started: float) -> VisionResult:
    with database.connect() as connection:
        row = find_artifact(connection, context.source.project_id, context.source.source_asset_id, KIND_VISUAL)
    if row is None or row.job_id is None:
        raise MediaError("visual analysis cache matched but the artifact row disappeared before reuse")
    path = path_from_file_uri(row.uri)
    document = VisualAnalysisDocument.model_validate_json(path.read_text(encoding="utf-8"))
    return _result_from_document(
        document,
        job_id=row.job_id,
        path=path,
        digest=sha256_file(path),
        cache_hit=True,
        started=started,
    )


def _result_from_document(
    document: VisualAnalysisDocument,
    *,
    job_id: str,
    path: Path,
    digest: str,
    cache_hit: bool,
    started: float,
) -> VisionResult:
    return VisionResult(
        job_id=job_id,
        analysis_id=document.analysis_id,
        source_asset_id=document.source_asset_id,
        project_id=document.project_id,
        proxy_sha256=document.proxy_sha256,
        scene_count=document.summary.scene_count,
        representative_frame_count=document.summary.representative_frame_count,
        face_sample_frame_count=document.summary.face_sample_frame_count,
        face_detection_count=document.summary.face_detection_count,
        face_track_count=document.summary.face_track_count,
        contact_sheet_count=len(document.contact_sheets),
        analysis_path=path,
        analysis_sha256=digest,
        cache_hit=cache_hit,
        runtime_seconds=perf_counter() - started,
        warning=None,
    )


def _running_job(
    context: _Context,
    scenes: SceneDetectionBackend,
    model: FaceModel,
    pyav_version: str,
    opencv_version: str,
    mediapipe_version: str,
    fingerprints: tuple[str, str, str, str],
    now: datetime,
) -> JobRecord:
    del pyav_version, opencv_version
    scene_fp, sampling_fp, _face_fp, tracking_fp = fingerprints
    return JobRecord(
        job_id=str(uuid.uuid4()),
        project_id=context.source.project_id,
        kind=JOB_VISUAL,
        status=JobStatus.RUNNING,
        created_at=now,
        updated_at=now,
        payload={
            "source_asset_id": context.source.source_asset_id,
            "source_sha256": context.manifest.content_sha256,
            "proxy_sha256": context.proxy_sha256,
            "scene_detector_version": scenes.version,
            "scene_profile_fingerprint": scene_fp,
            "mediapipe_version": mediapipe_version,
            "face_model_sha256": model.sha256,
            "sampling_profile_fingerprint": sampling_fp,
            "tracking_profile_fingerprint": tracking_fp,
            "recipe_version": RECIPE_VERSION,
            "cache": "miss",
        },
    )


def _cache_record(
    context: _Context,
    document: VisualAnalysisDocument,
    *,
    job_id: str,
    scenes: SceneDetectionBackend,
    model: FaceModel,
    pyav_version: str,
    opencv_version: str,
    mediapipe_version: str,
    fingerprints: tuple[str, str, str, str],
    digest: str,
    size: int,
    created_at: datetime,
) -> VisualAnalysisCacheRecord:
    scene_fp, sampling_fp, face_fp, tracking_fp = fingerprints
    return VisualAnalysisCacheRecord(
        project_id=context.source.project_id,
        source_asset_id=context.source.source_asset_id,
        analysis_id=document.analysis_id,
        job_id=job_id,
        source_sha256=context.manifest.content_sha256,
        proxy_sha256=context.proxy_sha256,
        proxy_recipe_name=recipes.ANALYSIS_PROXY_NAME,
        proxy_recipe_version=recipes.ANALYSIS_PROXY_VERSION,
        recipe_name=RECIPE_NAME,
        recipe_version=RECIPE_VERSION,
        pyscenedetect_version=scenes.version,
        scene_backend=scenes.backend,
        scene_profile_fingerprint=scene_fp,
        pyav_version=pyav_version,
        opencv_version=opencv_version,
        mediapipe_version=mediapipe_version,
        face_model_sha256=model.sha256,
        face_profile_fingerprint=face_fp,
        sampling_profile_fingerprint=sampling_fp,
        tracking_profile_fingerprint=tracking_fp,
        analysis_artifact_sha256=digest,
        analysis_artifact_size=size,
        evidence_manifest_digest=document.evidence_manifest_digest,
        validation_status="passed",
        created_at=created_at,
    )


def _fingerprints(scenes: SceneDetectionBackend) -> tuple[str, str, str, str]:
    return (
        scene_fingerprint(detector=scenes.detector, backend=scenes.backend),
        sampling_fingerprint(),
        face_fingerprint(),
        tracking_fingerprint(),
    )


def _require_visual_budget(root: Path, duration_us: int) -> None:
    if duration_us <= 0:
        raise MediaError("cannot estimate storage for a non-positive duration")
    seconds = duration_us / 1_000_000
    frames = int(seconds * 3) + 4
    estimate = frames * 200 * 1024 * 2 + 8 * 1024 * 1024
    status = read_disk(root)
    try:
        require_disk_budget(status.free_bytes, status.reserve_bytes, estimate)
    except MediaError as exc:
        text = (
            str(exc)
            .replace("this prepare", "this visual analysis")
            .replace(
                "ffmpeg was not started.",
                "Scene detection was not started.",
            )
        )
        raise MediaError(text) from exc


def _revalidate(database: Database, context: _Context, proxy_validator: ProxyValidator) -> _Context:
    manifest = _refresh_mutation(database, context.source, context.manifest)
    proxy_path, proxy_sha, media_job, width, height = _require_proxy(
        database, context.source, manifest, context.workspace, proxy_validator
    )
    return _Context(
        context.source,
        manifest,
        context.workspace,
        proxy_path,
        proxy_sha,
        media_job,
        width,
        height,
    )


def _refresh_mutation(
    database: Database,
    source: SourceAsset,
    manifest: SourceIngestManifest,
) -> SourceIngestManifest:
    path = path_from_file_uri(source.uri)
    drift = inspect_mutation(path, manifest)
    if drift is None:
        return manifest
    with database.transaction() as connection:
        update_source_manifest_stats(
            connection,
            source_asset_id=source.source_asset_id,
            project_id=source.project_id,
            size_bytes=drift.size_bytes,
            mtime_ns=drift.mtime_ns,
        )
    return manifest.model_copy(update={"size_bytes": drift.size_bytes, "mtime_ns": drift.mtime_ns})


def _require_proxy(
    database: Database,
    source: SourceAsset,
    manifest: SourceIngestManifest,
    workspace: SourceWorkspace,
    proxy_validator: ProxyValidator,
) -> tuple[Path, str, str, int, int]:
    path = workspace.proxy_file("analysis.mp4")
    sidecar = workspace.metadata_file("analysis-proxy.recipe.json")
    if not path.is_file() or not sidecar.is_file():
        raise MediaError(
            f"analysis proxy for source {source.source_asset_id} is missing. "
            f"Run `clipforge media prepare {source.source_asset_id}`. "
            "Visual analysis does not create or rebuild the proxy."
        )
    record = read_media_cache(sidecar)
    if record is None or not media_cache_matches(
        record,
        recipe_name=recipes.ANALYSIS_PROXY_NAME,
        recipe_version=recipes.ANALYSIS_PROXY_VERSION,
        source_sha256=manifest.content_sha256,
        project_id=manifest.project_id,
        source_asset_id=manifest.source_asset_id,
        video_stream_index=manifest.video_stream_index,
        audio_stream_index=manifest.audio_stream_index,
        artifact_path=path,
    ):
        raise MediaError(
            "analysis proxy hash or recipe does not match this source. "
            f"Run `clipforge media prepare {source.source_asset_id}`. "
            "Visual analysis will not rebuild it."
        )
    with database.connect() as connection:
        row = find_artifact(connection, source.project_id, source.source_asset_id, recipes.KIND_PROXY)
        if row is None or row.job_id is None or row.provenance.job_id != row.job_id:
            raise MediaError(
                "analysis proxy has no artifact row from a succeeded prepare. "
                f"Run `clipforge media prepare {source.source_asset_id}`."
            )
        if source.source_asset_id not in row.provenance.source_asset_ids or row.project_id != source.project_id:
            raise MediaError("analysis proxy artifact row is not in this project and source")
        job = get_job(connection, row.job_id)
    if job.project_id != source.project_id or job.kind != recipes.JOB_MEDIA_PREPARE:
        raise MediaError(f"analysis proxy was produced by job kind {job.kind}, not media_prepare")
    if job.status is not JobStatus.SUCCEEDED:
        raise MediaError(
            f"analysis proxy producing job {job.job_id} is {job.status.value}, expected succeeded. "
            f"Run `clipforge media prepare {source.source_asset_id}`."
        )
    payload_source = job.payload.get("source_asset_id")
    if payload_source is not None and payload_source != source.source_asset_id:
        raise MediaError("analysis proxy producing job names a different source")
    payload_sha = job.payload.get("source_sha256")
    if payload_sha is not None and payload_sha != manifest.content_sha256:
        raise MediaError("analysis proxy producing job names a different source sha256")
    payload_proxy = job.payload.get("analysis_proxy_sha256")
    if payload_proxy is not None and payload_proxy != record.artifact_sha256:
        raise MediaError("analysis proxy producing job names a different proxy sha256")
    width, height = _proxy_size(manifest)
    proxy_validator(path, manifest)
    return path, record.artifact_sha256, job.job_id, width, height


def _proxy_size(manifest: SourceIngestManifest) -> tuple[int, int]:
    video = None
    for stream in manifest.probe.video_streams:
        if stream.index == manifest.video_stream_index:
            video = stream
            break
    if video is None or video.display_width is None or video.display_height is None:
        raise MediaError("selected video has no display dimensions, so the analysis proxy cannot be checked")
    return proxy_pixel_size(video.display_width, video.display_height)


def _validate_proxy(path: Path, manifest: SourceIngestManifest) -> None:
    video = None
    for stream in manifest.probe.video_streams:
        if stream.index == manifest.video_stream_index:
            video = stream
            break
    if video is None or video.display_width is None or video.display_height is None:
        raise MediaError("selected video has no display dimensions")
    output_width, output_height = proxy_pixel_size(video.display_width, video.display_height)
    validate_proxy(
        path,
        ProcessRunner(),
        canonical_duration_us=manifest.canonical_duration_us,
        rate=video.avg_frame_rate or video.r_frame_rate,
        output_width=output_width,
        output_height=output_height,
        display_width=video.display_width,
        display_height=video.display_height,
        expect_audio=manifest.audio_stream_index is not None,
        log_path=None,
    )


def _fail_stale(database: Database, context: _Context) -> None:
    now = datetime.now(UTC)
    with database.transaction() as connection:
        for existing in list_jobs(connection, context.source.project_id):
            if existing.kind != JOB_VISUAL or existing.status is not JobStatus.RUNNING:
                continue
            if existing.payload.get("source_asset_id") != context.source.source_asset_id:
                continue
            update_job(
                connection,
                existing.model_copy(
                    update={
                        "status": JobStatus.FAILED,
                        "updated_at": now,
                        "error_message": (
                            "interrupted before completion. The vision lock was free, so no live "
                            "visual analysis owned this running job. Partial outputs were not promoted."
                        ),
                    }
                ),
            )


def _abandon(
    database: Database,
    job: JobRecord,
    status: JobStatus,
    message: str,
    run_dir: Path | None,
    root: Path,
) -> None:
    """Best-effort cleanup, then always try to close the job."""
    notes: list[str] = []
    try:
        _cleanup_failed_run(run_dir, root)
    except (OSError, MediaError) as exc:
        notes.append(str(exc))
    detail = message if not notes else f"{message} Cleanup also failed: {'; '.join(notes)}"
    try:
        _close(database, job, status, detail)
    except Exception:
        return


def _close(database: Database, job: JobRecord, status: JobStatus, message: str) -> None:
    updated = job.model_copy(
        update={"status": status, "updated_at": datetime.now(UTC), "error_message": message[:2000]}
    )
    with database.transaction() as connection:
        update_job(connection, updated)


def _cleanup_failed_run(run_dir: Path | None, root: Path) -> None:
    """Delete partial files inside this run directory and nowhere else."""
    if run_dir is None or not run_dir.exists():
        return
    ensure_within(root, run_dir)
    if run_dir.is_symlink():
        raise MediaError(f"refusing to clean a symlinked visual analysis run {run_dir}")
    for path in sorted(run_dir.rglob("*")):
        if path.is_symlink():
            raise MediaError(f"refusing to clean symlink {path}")
        ensure_within(root, path)
        if path.is_file() and ".partial." in path.name:
            path.unlink()


def _write_log(path: Path, text: str, root: Path) -> None:
    ensure_within(root, path)
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _log_text(document: VisualAnalysisDocument) -> str:
    summary = document.summary
    return (
        f"analysis_id {document.analysis_id}\n"
        f"scenes {summary.scene_count}\n"
        f"representative_frames {summary.representative_frame_count}\n"
        f"face_samples {summary.face_sample_frame_count}\n"
        f"face_detections {summary.face_detection_count}\n"
        f"face_tracks {summary.face_track_count}\n"
    )


def _actor() -> str:
    import getpass

    try:
        return getpass.getuser()
    except OSError as exc:
        raise MediaError(f"could not determine the OS user for provenance: {exc}") from exc
