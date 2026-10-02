"""Visual-analysis evidence. These are measurements, not editorial judgments.

A scene here is a shot-like interval from the scene detector. It is not a
semantic story scene. ``Scene.analysis_complete`` stays false because Round 4
does not attach transcript evidence. A face detection is not a speaker and
not a person's identity.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import ContractModel, EntityId, Microseconds, Versioned
from clipforge.schemas.media import FaceObservation, Scene
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"
_RELATIVE = r"^(frames|contact-sheets)/[A-Za-z0-9][A-Za-z0-9._-]{0,120}$"


def digest_evidence(files: list[EvidenceFile]) -> str:
    """SHA-256 of sorted relative path, digest, and size. ``created_at`` is absent."""
    rows = sorted((item.relative_path, item.sha256, item.size_bytes) for item in files)
    raw = json.dumps(rows, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class NormalizedBoundingBox(ContractModel):
    """Displayed-proxy coordinates. ``x`` and ``y`` are the top-left corner."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def stays_inside_frame(self) -> Self:
        _finite(self.x, "bounding box x")
        _finite(self.y, "bounding box y")
        _finite(self.width, "bounding box width")
        _finite(self.height, "bounding box height")
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("bounding box extends outside the displayed frame")
        return self


class FaceKeypoint(ContractModel):
    """A detector keypoint. It is not age, emotion, gender, or identity."""

    name: Literal["left_eye", "right_eye", "nose", "mouth_center"]
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def finite_point(self) -> Self:
        _finite(self.x, "keypoint x")
        _finite(self.y, "keypoint y")
        return self


class FrameVisualMetrics(ContractModel):
    """Numeric frame measurements. These are not quality or engagement scores."""

    mean_luma: float = Field(ge=0, le=255)
    luma_stddev: float = Field(ge=0)
    sharpness_laplacian_variance: float = Field(ge=0)
    difference_from_previous_sample: float | None = Field(default=None, ge=0, le=1)
    metrics_version: Literal["1"] = "1"

    @model_validator(mode="after")
    def metrics_are_finite(self) -> Self:
        _finite(self.mean_luma, "mean_luma")
        _finite(self.luma_stddev, "luma_stddev")
        _finite(self.sharpness_laplacian_variance, "sharpness_laplacian_variance")
        if self.difference_from_previous_sample is not None:
            _finite(self.difference_from_previous_sample, "difference_from_previous_sample")
        return self


class EvidenceFile(ContractModel):
    """One persisted evidence file inside the analysis run directory."""

    relative_path: str = Field(pattern=_RELATIVE)
    sha256: str = Field(pattern=_SHA)
    size_bytes: int = Field(ge=0)
    kind: Literal["representative_frame", "contact_sheet"]
    scene_id: EntityId | None = None
    timestamp_us: Microseconds | None = None


class FrameEvidence(Versioned):
    """One representative scene frame. Face-only samples are not stored as images."""

    frame_id: EntityId
    scene_id: EntityId
    requested_us: Microseconds
    matched_requests_us: list[Microseconds] = Field(min_length=1)
    actual_timestamp_us: Microseconds
    labels: list[Literal["p20", "mid", "p80"]] = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    relative_path: str = Field(pattern=_RELATIVE)
    sha256: str = Field(pattern=_SHA)
    size_bytes: int = Field(ge=0)
    metrics: FrameVisualMetrics


class FaceDetectionSample(Versioned):
    """One face box on one sampled frame. ``track_id`` is geometry inside that scene only."""

    detection_id: EntityId
    scene_id: EntityId
    timestamp_us: Microseconds
    confidence: float = Field(ge=0, le=1)
    bounding_box: NormalizedBoundingBox
    center_x: float = Field(ge=0, le=1)
    center_y: float = Field(ge=0, le=1)
    area_ratio: float = Field(gt=0, le=1)
    keypoints: list[FaceKeypoint] = Field(default_factory=list)
    track_id: str | None = Field(default=None, min_length=1, max_length=120)
    clamped: bool = False

    @model_validator(mode="after")
    def geometry_matches_box(self) -> Self:
        _finite(self.confidence, "face confidence")
        _finite(self.center_x, "center_x")
        _finite(self.center_y, "center_y")
        _finite(self.area_ratio, "area_ratio")
        box = self.bounding_box
        center_x = box.x + (box.width / 2)
        center_y = box.y + (box.height / 2)
        if abs(self.center_x - center_x) > 1e-6 or abs(self.center_y - center_y) > 1e-6:
            raise ValueError("face center does not match the bounding box")
        if abs(self.area_ratio - (box.width * box.height)) > 1e-6:
            raise ValueError("face area_ratio does not match the bounding box")
        return self


class SceneVisualEvidence(Versioned):
    """Deterministic aggregates for one detector scene. No subjective label."""

    evidence_id: EntityId
    scene_id: EntityId
    representative_frame_ids: list[EntityId] = Field(min_length=1)
    duration_us: Microseconds
    sample_count: int = Field(ge=1)
    face_sample_count: int = Field(ge=1)
    frames_with_faces: int = Field(ge=0)
    max_face_count: int = Field(ge=0)
    mean_luma: float = Field(ge=0, le=255)
    mean_sharpness: float = Field(ge=0)
    mean_visual_difference: float | None = Field(default=None, ge=0, le=1)
    largest_face_area_ratio_max: float | None = Field(default=None, ge=0, le=1)
    tracked_face_count: int = Field(ge=0)

    @model_validator(mode="after")
    def aggregates_are_finite(self) -> Self:
        if self.duration_us <= 0:
            raise ValueError("scene evidence duration_us must be greater than 0")
        if self.sample_count != self.face_sample_count:
            raise ValueError("every analyzed sample is a face sample")
        _finite(self.mean_luma, "mean_luma")
        _finite(self.mean_sharpness, "mean_sharpness")
        if self.mean_visual_difference is not None:
            _finite(self.mean_visual_difference, "mean_visual_difference")
        if self.largest_face_area_ratio_max is not None:
            _finite(self.largest_face_area_ratio_max, "largest_face_area_ratio_max")
        return self


class ContactSheet(ContractModel):
    """A review image. It is not a timing source."""

    relative_path: str = Field(pattern=_RELATIVE)
    sha256: str = Field(pattern=_SHA)
    size_bytes: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    scene_ordinals: list[int] = Field(min_length=1)


class VisualAnalysisSummary(ContractModel):
    """Counts and durations. There is no best-scene or recommended-clip field."""

    scene_count: int = Field(ge=1)
    representative_frame_count: int = Field(ge=1)
    face_sample_frame_count: int = Field(ge=1)
    face_detection_count: int = Field(ge=0)
    face_track_count: int = Field(ge=0)
    frames_with_faces: int = Field(ge=0)
    max_simultaneous_faces: int = Field(ge=0)
    mean_scene_duration_us: Microseconds
    shortest_scene_duration_us: Microseconds
    longest_scene_duration_us: Microseconds


class VisualAnalysisDocument(Versioned):
    """One immutable visual-analysis run. The direct byte input is the analysis proxy."""

    analysis_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    created_at: AwareDatetime
    canonical_duration_us: Microseconds
    source_sha256: str = Field(pattern=_SHA)
    proxy_sha256: str = Field(pattern=_SHA)
    proxy_recipe_name: str = Field(min_length=1, max_length=80)
    proxy_recipe_version: str = Field(min_length=1, max_length=40)
    proxy_width: int = Field(gt=0)
    proxy_height: int = Field(gt=0)
    recipe_name: str = Field(min_length=1, max_length=80)
    recipe_version: str = Field(min_length=1, max_length=40)
    scene_engine: Literal["pyscenedetect", "fake"]
    pyscenedetect_version: str = Field(min_length=1, max_length=40)
    scene_backend: str = Field(min_length=1, max_length=40)
    scene_detector: str = Field(min_length=1, max_length=80)
    scene_profile_fingerprint: str = Field(pattern=_SHA)
    adaptive_threshold: float
    min_content_val: float
    window_width: int = Field(ge=1)
    min_scene_len_frames: int = Field(ge=1)
    sampling_profile_fingerprint: str = Field(pattern=_SHA)
    representative_fractions: list[Literal["1/5", "1/2", "4/5"]] = Field(min_length=1)
    short_scene_us: Microseconds
    face_sample_interval_us: Microseconds
    jpeg_quality: int = Field(ge=1, le=100)
    jpeg_long_edge: int = Field(gt=0)
    pyav_version: str = Field(min_length=1, max_length=40)
    opencv_version: str = Field(min_length=1, max_length=40)
    face_engine: Literal["mediapipe-tasks-face-detector", "fake"]
    mediapipe_version: str = Field(min_length=1, max_length=40)
    face_model_filename: str = Field(min_length=1, max_length=200)
    face_model_sha256: str = Field(pattern=_SHA)
    face_model_source: str = Field(min_length=1, max_length=500)
    face_profile_fingerprint: str = Field(pattern=_SHA)
    min_detection_confidence: float = Field(ge=0, le=1)
    min_suppression_threshold: float = Field(ge=0, le=1)
    tracking_algorithm: Literal["greedy-iou-v1"] = "greedy-iou-v1"
    tracking_profile_fingerprint: str = Field(pattern=_SHA)
    tracking_iou_threshold: float = Field(ge=0, le=1)
    tracking_center_distance_threshold: float = Field(ge=0, le=2)
    tracking_max_gap_us: Microseconds
    scenes: list[Scene] = Field(min_length=1)
    scene_evidence: list[SceneVisualEvidence] = Field(min_length=1)
    frame_evidence: list[FrameEvidence] = Field(min_length=1)
    face_detection_samples: list[FaceDetectionSample] = Field(default_factory=list)
    face_observations: list[FaceObservation] = Field(default_factory=list)
    contact_sheets: list[ContactSheet] = Field(min_length=1)
    evidence_files: list[EvidenceFile] = Field(min_length=1)
    evidence_manifest_digest: str = Field(pattern=_SHA)
    summary: VisualAnalysisSummary
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def evidence_is_consistent(self) -> Self:
        _check_identity(self)
        _check_scenes(self)
        _check_frames(self)
        _check_faces(self)
        _check_files(self)
        return self


class VisualAnalysisCacheRecord(Versioned):
    """Sidecar for one published visual analysis. ``created_at`` is not identity."""

    project_id: EntityId
    source_asset_id: EntityId
    analysis_id: EntityId
    job_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    proxy_sha256: str = Field(pattern=_SHA)
    proxy_recipe_name: str = Field(min_length=1, max_length=80)
    proxy_recipe_version: str = Field(min_length=1, max_length=40)
    recipe_name: str = Field(min_length=1, max_length=80)
    recipe_version: str = Field(min_length=1, max_length=40)
    pyscenedetect_version: str = Field(min_length=1, max_length=40)
    scene_backend: str = Field(min_length=1, max_length=40)
    scene_profile_fingerprint: str = Field(pattern=_SHA)
    pyav_version: str = Field(min_length=1, max_length=40)
    opencv_version: str = Field(min_length=1, max_length=40)
    mediapipe_version: str = Field(min_length=1, max_length=40)
    face_model_sha256: str = Field(pattern=_SHA)
    face_profile_fingerprint: str = Field(pattern=_SHA)
    sampling_profile_fingerprint: str = Field(pattern=_SHA)
    tracking_profile_fingerprint: str = Field(pattern=_SHA)
    analysis_artifact_sha256: str = Field(pattern=_SHA)
    analysis_artifact_size: int = Field(ge=0)
    evidence_manifest_digest: str = Field(pattern=_SHA)
    validation_status: Literal["passed"]
    created_at: AwareDatetime


def _finite(value: float, label: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")


def _check_identity(document: VisualAnalysisDocument) -> None:
    if document.canonical_duration_us <= 0:
        raise ValueError("canonical_duration_us must be greater than 0")
    if document.source_asset_id not in document.provenance.source_asset_ids:
        raise ValueError("visual analysis provenance must include source_asset_id")
    _finite(document.adaptive_threshold, "adaptive_threshold")
    _finite(document.min_content_val, "min_content_val")
    _finite(document.min_detection_confidence, "min_detection_confidence")
    _finite(document.min_suppression_threshold, "min_suppression_threshold")
    _finite(document.tracking_iou_threshold, "tracking_iou_threshold")
    _finite(document.tracking_center_distance_threshold, "tracking_center_distance_threshold")
    if document.short_scene_us <= 0 or document.face_sample_interval_us <= 0:
        raise ValueError("sampling intervals must be greater than 0")
    if document.tracking_max_gap_us <= 0:
        raise ValueError("tracking_max_gap_us must be greater than 0")


def _check_scenes(document: VisualAnalysisDocument) -> None:
    evidence_by_scene = {item.scene_id: item for item in document.scene_evidence}
    if len(evidence_by_scene) != len(document.scene_evidence):
        raise ValueError("scene evidence ids must be unique per scene")
    cursor = 0
    durations: list[int] = []
    for scene in document.scenes:
        if scene.source_asset_id != document.source_asset_id:
            raise ValueError("scene source_asset_id does not match the analysis")
        if scene.transcript_evidence is not None or scene.analysis_complete:
            raise ValueError("Round 4 scenes keep transcript_evidence empty and analysis_complete false")
        if scene.visual_evidence is None:
            raise ValueError("scene visual_evidence is required")
        evidence = evidence_by_scene.get(scene.scene_id)
        if evidence is None or evidence.evidence_id != scene.visual_evidence:
            raise ValueError("scene visual_evidence does not match its evidence record")
        start = scene.time_range.start_us
        end = scene.time_range.end_us
        if start != cursor:
            raise ValueError("scene ranges must start at 0 and leave no gaps or overlaps")
        if end <= start:
            raise ValueError("scene duration must be positive")
        if evidence.duration_us != end - start:
            raise ValueError("scene evidence duration does not match the scene range")
        durations.append(end - start)
        cursor = end
    if cursor != document.canonical_duration_us:
        raise ValueError("scenes must end at the canonical duration")
    if document.summary.scene_count != len(document.scenes):
        raise ValueError("summary scene_count does not match the scenes")
    if document.summary.shortest_scene_duration_us != min(durations):
        raise ValueError("summary shortest scene duration does not match")
    if document.summary.longest_scene_duration_us != max(durations):
        raise ValueError("summary longest scene duration does not match")
    mean = int((Decimal(sum(durations)) / Decimal(len(durations))).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if document.summary.mean_scene_duration_us != mean:
        raise ValueError("summary mean scene duration does not match")
    sampled = sum(item.face_sample_count for item in document.scene_evidence)
    if document.summary.face_sample_frame_count != sampled:
        raise ValueError("summary face_sample_frame_count does not match the scene evidence")


def _check_frames(document: VisualAnalysisDocument) -> None:
    scenes = {scene.scene_id: scene for scene in document.scenes}
    if len(scenes) != len(document.scenes):
        raise ValueError("scene ids must be unique")
    by_scene: dict[str, list[FrameEvidence]] = {scene_id: [] for scene_id in scenes}
    seen_paths: set[str] = set()
    for frame in document.frame_evidence:
        scene = scenes.get(frame.scene_id)
        if scene is None:
            raise ValueError("frame evidence scene_id is unknown")
        start = scene.time_range.start_us
        end = scene.time_range.end_us
        if not start <= frame.actual_timestamp_us < end:
            raise ValueError("frame evidence timestamp is outside its scene")
        if frame.actual_timestamp_us >= document.canonical_duration_us:
            raise ValueError("frame evidence timestamp is outside the source duration")
        if frame.requested_us >= end:
            raise ValueError("requested frame target is outside its scene")
        if frame.requested_us not in frame.matched_requests_us:
            raise ValueError("requested_us must be one of the matched requests")
        if frame.relative_path in seen_paths:
            raise ValueError("representative frame paths must be unique")
        seen_paths.add(frame.relative_path)
        by_scene[frame.scene_id].append(frame)
    for scene_id, frames in by_scene.items():
        if not frames:
            raise ValueError(f"scene {scene_id} has no representative frame")
        evidence = next(item for item in document.scene_evidence if item.scene_id == scene_id)
        ids = [frame.frame_id for frame in frames]
        if evidence.representative_frame_ids != ids:
            raise ValueError("scene evidence frame ids do not match the frame records")
    if document.summary.representative_frame_count != len(document.frame_evidence):
        raise ValueError("summary representative_frame_count does not match")


def _check_faces(document: VisualAnalysisDocument) -> None:
    scenes = {scene.scene_id: scene for scene in document.scenes}
    grouped: dict[str, list[FaceDetectionSample]] = {}
    per_frame: dict[tuple[str, int], int] = {}
    for sample in document.face_detection_samples:
        scene = scenes.get(sample.scene_id)
        if scene is None:
            raise ValueError("face sample scene_id is unknown")
        start = scene.time_range.start_us
        end = scene.time_range.end_us
        if not start <= sample.timestamp_us < end:
            raise ValueError("face sample timestamp is outside its scene")
        if sample.track_id is None:
            raise ValueError("face sample is missing its scene-local track id")
        grouped.setdefault(sample.track_id, []).append(sample)
        key = (sample.scene_id, sample.timestamp_us)
        per_frame[key] = per_frame.get(key, 0) + 1
    observations: dict[str, FaceObservation] = {}
    for item in document.face_observations:
        if item.track_id is None:
            raise ValueError("face observation is missing track_id")
        observations[item.track_id] = item
    if len(observations) != len(document.face_observations):
        raise ValueError("face observation track ids must be unique")
    for track_id, samples in grouped.items():
        scene_ids = {sample.scene_id for sample in samples}
        if len(scene_ids) != 1:
            raise ValueError("a face track must stay inside one scene")
        times = sorted({sample.timestamp_us for sample in samples})
        observation = observations.get(track_id)
        if len(times) == 1:
            if observation is not None:
                raise ValueError("a single-frame face must not become a FaceObservation")
            continue
        if observation is None:
            raise ValueError("a multi-frame face track is missing its FaceObservation")
        if observation.source_asset_id != document.source_asset_id:
            raise ValueError("face observation source does not match the analysis")
        if observation.speaker_attribution != "unknown":
            raise ValueError("face observation speaker_attribution must stay unknown")
        if observation.time_range.start_us != times[0] or observation.time_range.end_us != times[-1]:
            raise ValueError("face observation range must be the first and last detection timestamps")
        if any(sample.timestamp_us < observation.time_range.start_us for sample in samples):
            raise ValueError("face sample falls outside its observation")
        if any(sample.timestamp_us > observation.time_range.end_us for sample in samples):
            raise ValueError("face sample falls outside its observation")
    for track_id in observations:
        if track_id not in grouped:
            raise ValueError("face observation has no detection samples")
    if document.summary.face_detection_count != len(document.face_detection_samples):
        raise ValueError("summary face_detection_count does not match")
    if document.summary.face_track_count != len(document.face_observations):
        raise ValueError("summary face_track_count does not match")
    frames_with_faces = sum(1 for count in per_frame.values() if count > 0)
    max_faces = max(per_frame.values(), default=0)
    if document.summary.frames_with_faces != frames_with_faces:
        raise ValueError("summary frames_with_faces does not match the samples")
    if document.summary.max_simultaneous_faces != max_faces:
        raise ValueError("summary max_simultaneous_faces does not match the samples")
    for evidence in document.scene_evidence:
        scene_samples = [
            sample for sample in document.face_detection_samples if sample.scene_id == evidence.scene_id
        ]
        counts: dict[int, int] = {}
        for sample in scene_samples:
            counts[sample.timestamp_us] = counts.get(sample.timestamp_us, 0) + 1
        frames_with = sum(1 for count in counts.values() if count > 0)
        max_count = max(counts.values(), default=0)
        if evidence.frames_with_faces != frames_with or evidence.max_face_count != max_count:
            raise ValueError("scene face counts do not match the detection samples")
        areas = [sample.area_ratio for sample in scene_samples]
        largest = max(areas) if areas else None
        if evidence.largest_face_area_ratio_max != largest:
            raise ValueError("scene largest face area does not match the detection samples")
        tracks: set[str] = set()
        for sample in scene_samples:
            sample_track = sample.track_id
            if sample_track is None or sample_track not in observations:
                continue
            if len({item.timestamp_us for item in grouped[sample_track]}) >= 2:
                tracks.add(sample_track)
        if evidence.tracked_face_count != len(tracks):
            raise ValueError("scene tracked_face_count does not match the FaceObservations")


def _check_files(document: VisualAnalysisDocument) -> None:
    if digest_evidence(document.evidence_files) != document.evidence_manifest_digest:
        raise ValueError("evidence_manifest_digest does not match the evidence files")
    listed = {item.relative_path: item for item in document.evidence_files}
    if len(listed) != len(document.evidence_files):
        raise ValueError("evidence paths must be unique")
    for frame in document.frame_evidence:
        item = listed.get(frame.relative_path)
        if item is None or item.sha256 != frame.sha256 or item.size_bytes != frame.size_bytes:
            raise ValueError("frame evidence is missing from the evidence manifest")
        if item.kind != "representative_frame" or item.scene_id != frame.scene_id:
            raise ValueError("frame evidence manifest kind or scene does not match")
        if item.timestamp_us != frame.actual_timestamp_us:
            raise ValueError("frame evidence manifest timestamp does not match")
    ordinals: list[int] = []
    for sheet in document.contact_sheets:
        item = listed.get(sheet.relative_path)
        if item is None or item.sha256 != sheet.sha256 or item.size_bytes != sheet.size_bytes:
            raise ValueError("contact sheet is missing from the evidence manifest")
        if item.kind != "contact_sheet":
            raise ValueError("contact sheet manifest kind does not match")
        ordinals.extend(sheet.scene_ordinals)
    expected = set(range(len(document.scenes)))
    if set(ordinals) != expected:
        raise ValueError("contact sheets must account for every scene ordinal")
    for ordinal in ordinals:
        if ordinal not in expected:
            raise ValueError("contact sheet scene ordinal is outside the scene list")
