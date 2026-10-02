"""Build a ``VisualAnalysisDocument`` from one finished run.

Scene rows keep ``transcript_evidence`` empty and ``analysis_complete`` false.
Face observations are means of detector confidence over a multi-sample track.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from clipforge.schemas.media import FaceObservation, Scene
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import SourceTimeRange
from clipforge.schemas.vision import (
    ContactSheet,
    EvidenceFile,
    FaceDetectionSample,
    FaceKeypoint,
    FrameEvidence,
    FrameVisualMetrics,
    NormalizedBoundingBox,
    SceneVisualEvidence,
    VisualAnalysisDocument,
    VisualAnalysisSummary,
    digest_evidence,
)
from clipforge.vision.geometry import NormalizedFace
from clipforge.vision.timeutil import mean_us
from clipforge.vision.tracking import TrackInterval


@dataclass(frozen=True, slots=True)
class StoredDetection:
    face: NormalizedFace
    track_id: str


@dataclass(frozen=True, slots=True)
class StoredSample:
    scene_ordinal: int
    requested_us: int
    matched_requests_us: tuple[int, ...]
    labels: tuple[str, ...]
    timestamp_us: int
    width: int
    height: int
    relative_path: str | None
    sha256: str | None
    size_bytes: int | None
    metrics: FrameVisualMetrics
    detections: tuple[StoredDetection, ...]


def assemble_document(
    *,
    analysis_id: str,
    project_id: str,
    source_asset_id: str,
    created_at: datetime,
    canonical_duration_us: int,
    source_sha256: str,
    proxy_sha256: str,
    proxy_recipe_name: str,
    proxy_recipe_version: str,
    proxy_width: int,
    proxy_height: int,
    recipe_name: str,
    recipe_version: str,
    scene_engine: str,
    pyscenedetect_version: str,
    scene_backend: str,
    scene_detector: str,
    scene_profile_fingerprint: str,
    adaptive_threshold: float,
    min_content_val: float,
    window_width: int,
    min_scene_len_frames: int,
    sampling_profile_fingerprint: str,
    representative_fractions: list[str],
    short_scene_us: int,
    face_sample_interval_us: int,
    jpeg_quality: int,
    jpeg_long_edge: int,
    pyav_version: str,
    opencv_version: str,
    face_engine: str,
    mediapipe_version: str,
    face_model_filename: str,
    face_model_sha256: str,
    face_model_source: str,
    face_profile_fingerprint: str,
    min_detection_confidence: float,
    min_suppression_threshold: float,
    tracking_profile_fingerprint: str,
    tracking_iou_threshold: float,
    tracking_center_distance_threshold: float,
    tracking_max_gap_us: int,
    spans: list[tuple[int, int]],
    samples: list[StoredSample],
    intervals: list[TrackInterval],
    contact_sheets: list[ContactSheet],
    provenance: ArtifactProvenance,
) -> VisualAnalysisDocument:
    scene_ids = [str(uuid.uuid4()) for _ in spans]
    evidence_ids = [str(uuid.uuid4()) for _ in spans]
    frames_by_scene: list[list[FrameEvidence]] = [[] for _ in spans]
    samples_by_scene: list[list[StoredSample]] = [[] for _ in spans]
    for sample in samples:
        samples_by_scene[sample.scene_ordinal].append(sample)
        relative_path = sample.relative_path
        digest = sample.sha256
        size_bytes = sample.size_bytes
        if sample.labels and relative_path is not None and digest is not None and size_bytes is not None:
            frames_by_scene[sample.scene_ordinal].append(
                FrameEvidence(
                    frame_id=str(uuid.uuid4()),
                    scene_id=scene_ids[sample.scene_ordinal],
                    requested_us=sample.requested_us,
                    matched_requests_us=list(sample.matched_requests_us),
                    actual_timestamp_us=sample.timestamp_us,
                    labels=list(sample.labels),  # type: ignore[arg-type]
                    width=sample.width,
                    height=sample.height,
                    relative_path=relative_path,
                    sha256=digest,
                    size_bytes=size_bytes,
                    metrics=sample.metrics,
                )
            )
    observations = _observations(intervals, source_asset_id, provenance)
    observation_ids = {item.track_id for item in observations if item.track_id is not None}
    face_samples: list[FaceDetectionSample] = []
    for sample in samples:
        for detection in sample.detections:
            box = detection.face
            face_samples.append(
                FaceDetectionSample(
                    detection_id=str(uuid.uuid4()),
                    scene_id=scene_ids[sample.scene_ordinal],
                    timestamp_us=sample.timestamp_us,
                    confidence=box.confidence,
                    bounding_box=NormalizedBoundingBox(x=box.x, y=box.y, width=box.width, height=box.height),
                    center_x=box.center_x,
                    center_y=box.center_y,
                    area_ratio=box.area_ratio,
                    keypoints=[FaceKeypoint(name=name, x=x, y=y) for name, x, y in box.keypoints],  # type: ignore[arg-type]
                    track_id=detection.track_id,
                    clamped=box.clamped,
                )
            )
    scene_rows: list[Scene] = []
    evidence_rows: list[SceneVisualEvidence] = []
    evidence_files: list[EvidenceFile] = []
    for index, (start, end) in enumerate(spans):
        scene_frames = frames_by_scene[index]
        scene_samples = samples_by_scene[index]
        scene_rows.append(
            Scene(
                scene_id=scene_ids[index],
                source_asset_id=source_asset_id,
                time_range=SourceTimeRange(start_us=start, end_us=end),
                visual_evidence=evidence_ids[index],
                transcript_evidence=None,
                analysis_complete=False,
                provenance=provenance,
            )
        )
        evidence_rows.append(
            _scene_evidence(
                evidence_ids[index],
                scene_ids[index],
                end - start,
                scene_frames,
                scene_samples,
                observation_ids,
            )
        )
        for frame in scene_frames:
            evidence_files.append(
                EvidenceFile(
                    relative_path=frame.relative_path,
                    sha256=frame.sha256,
                    size_bytes=frame.size_bytes,
                    kind="representative_frame",
                    scene_id=frame.scene_id,
                    timestamp_us=frame.actual_timestamp_us,
                )
            )
    for sheet in contact_sheets:
        evidence_files.append(
            EvidenceFile(
                relative_path=sheet.relative_path,
                sha256=sheet.sha256,
                size_bytes=sheet.size_bytes,
                kind="contact_sheet",
            )
        )
    durations = [end - start for start, end in spans]
    per_frame: dict[tuple[str, int], int] = {}
    for detection_sample in face_samples:
        key = (detection_sample.scene_id, detection_sample.timestamp_us)
        per_frame[key] = per_frame.get(key, 0) + 1
    summary = VisualAnalysisSummary(
        scene_count=len(spans),
        representative_frame_count=sum(len(frames) for frames in frames_by_scene),
        face_sample_frame_count=len(samples),
        face_detection_count=len(face_samples),
        face_track_count=len(observations),
        frames_with_faces=sum(1 for count in per_frame.values() if count > 0),
        max_simultaneous_faces=max(per_frame.values(), default=0),
        mean_scene_duration_us=mean_us(durations),
        shortest_scene_duration_us=min(durations),
        longest_scene_duration_us=max(durations),
    )
    return VisualAnalysisDocument(
        analysis_id=analysis_id,
        project_id=project_id,
        source_asset_id=source_asset_id,
        created_at=created_at,
        canonical_duration_us=canonical_duration_us,
        source_sha256=source_sha256,
        proxy_sha256=proxy_sha256,
        proxy_recipe_name=proxy_recipe_name,
        proxy_recipe_version=proxy_recipe_version,
        proxy_width=proxy_width,
        proxy_height=proxy_height,
        recipe_name=recipe_name,
        recipe_version=recipe_version,
        scene_engine=scene_engine,  # type: ignore[arg-type]
        pyscenedetect_version=pyscenedetect_version,
        scene_backend=scene_backend,
        scene_detector=scene_detector,
        scene_profile_fingerprint=scene_profile_fingerprint,
        adaptive_threshold=adaptive_threshold,
        min_content_val=min_content_val,
        window_width=window_width,
        min_scene_len_frames=min_scene_len_frames,
        sampling_profile_fingerprint=sampling_profile_fingerprint,
        representative_fractions=representative_fractions,  # type: ignore[arg-type]
        short_scene_us=short_scene_us,
        face_sample_interval_us=face_sample_interval_us,
        jpeg_quality=jpeg_quality,
        jpeg_long_edge=jpeg_long_edge,
        pyav_version=pyav_version,
        opencv_version=opencv_version,
        face_engine=face_engine,  # type: ignore[arg-type]
        mediapipe_version=mediapipe_version,
        face_model_filename=face_model_filename,
        face_model_sha256=face_model_sha256,
        face_model_source=face_model_source,
        face_profile_fingerprint=face_profile_fingerprint,
        min_detection_confidence=min_detection_confidence,
        min_suppression_threshold=min_suppression_threshold,
        tracking_profile_fingerprint=tracking_profile_fingerprint,
        tracking_iou_threshold=tracking_iou_threshold,
        tracking_center_distance_threshold=tracking_center_distance_threshold,
        tracking_max_gap_us=tracking_max_gap_us,
        scenes=scene_rows,
        scene_evidence=evidence_rows,
        frame_evidence=[frame for frames in frames_by_scene for frame in frames],
        face_detection_samples=face_samples,
        face_observations=observations,
        contact_sheets=contact_sheets,
        evidence_files=evidence_files,
        evidence_manifest_digest=digest_evidence(evidence_files),
        summary=summary,
        provenance=provenance,
    )


def _observations(
    intervals: list[TrackInterval],
    source_asset_id: str,
    provenance: ArtifactProvenance,
) -> list[FaceObservation]:
    rows: list[FaceObservation] = []
    for interval in intervals:
        times = tuple(sorted(set(interval.timestamps)))
        if len(times) < 2 or times[-1] <= times[0]:
            continue
        rows.append(
            FaceObservation(
                observation_id=str(uuid.uuid4()),
                source_asset_id=source_asset_id,
                time_range=SourceTimeRange(start_us=times[0], end_us=times[-1]),
                track_id=interval.track_id,
                confidence=interval.confidence,
                speaker_attribution="unknown",
                provenance=provenance,
            )
        )
    return rows


def _scene_evidence(
    evidence_id: str,
    scene_id: str,
    duration_us: int,
    frames: list[FrameEvidence],
    samples: list[StoredSample],
    observation_ids: set[str],
) -> SceneVisualEvidence:
    counts: dict[int, int] = {}
    areas: list[float] = []
    tracks: set[str] = set()
    for sample in samples:
        counts[sample.timestamp_us] = counts.get(sample.timestamp_us, 0) + len(sample.detections)
        for detection in sample.detections:
            areas.append(detection.face.area_ratio)
            if detection.track_id in observation_ids:
                tracks.add(detection.track_id)
    differences = [
        sample.metrics.difference_from_previous_sample
        for sample in samples
        if sample.metrics.difference_from_previous_sample is not None
    ]
    return SceneVisualEvidence(
        evidence_id=evidence_id,
        scene_id=scene_id,
        representative_frame_ids=[frame.frame_id for frame in frames],
        duration_us=duration_us,
        sample_count=len(samples),
        face_sample_count=len(samples),
        frames_with_faces=sum(1 for count in counts.values() if count > 0),
        max_face_count=max(counts.values(), default=0),
        mean_luma=_mean([sample.metrics.mean_luma for sample in samples]),
        mean_sharpness=_mean([sample.metrics.sharpness_laplacian_variance for sample in samples]),
        mean_visual_difference=_mean(differences) if differences else None,
        largest_face_area_ratio_max=max(areas) if areas else None,
        tracked_face_count=len(tracks),
    )


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot average an empty metric list")
    return sum(values) / len(values)
