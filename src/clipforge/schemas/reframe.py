"""Face-follow reframing contracts. A face box is geometry, not an identity or a speaker."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal, Self

from pydantic import Field, model_validator

from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.timeline.framerate import FrameRate, frame_start_us

_OUTPUT_RATE = FrameRate(30, 1)

_SHA = r"^[0-9a-f]{64}$"


def _finite(value: float, label: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")


def _reject_unsafe_text(value: str, label: str) -> None:
    if not value:
        return
    lowered = value.lower()
    if (
        "\\" in value
        or value.startswith("/")
        or ".." in value.split("/")
        or "://" in lowered
        or "<" in value
        or ">" in value
    ):
        raise ValueError(f"{label} contains unsafe text")


class FaceFollowSample(Versioned):
    """One output sample and the source crop that contains the tracked face."""

    sample_index: int = Field(ge=0)
    output_us: Microseconds
    source_us: Microseconds
    crop_x: int = Field(ge=0)
    crop_y: int = Field(ge=0)
    crop_width: int = Field(ge=1)
    crop_height: int = Field(ge=1)
    face_x: int = Field(ge=0)
    face_y: int = Field(ge=0)
    face_width: int = Field(ge=1)
    face_height: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)
    frame_width: int = Field(ge=1)
    frame_height: int = Field(ge=1)

    @model_validator(mode="after")
    def crop_is_inside(self) -> Self:
        _finite(self.confidence, "face confidence")
        if self.crop_x + self.crop_width > self.frame_width:
            raise ValueError("face-follow crop extends past the source width")
        if self.crop_y + self.crop_height > self.frame_height:
            raise ValueError("face-follow crop extends past the source height")
        if self.face_x + self.face_width > self.frame_width:
            raise ValueError("face box extends past the source width")
        if self.face_y + self.face_height > self.frame_height:
            raise ValueError("face box extends past the source height")
        return self


class FaceFollowTrajectory(Versioned):
    """Deterministic crop path. Samples are monotonic in output time."""

    track_id: EntityId
    samples: list[FaceFollowSample] = Field(min_length=1)
    smoothing_divisor: int = Field(ge=1, le=16)
    max_step_px: int = Field(ge=1, le=200)
    headroom_permille: int = Field(ge=0, le=400)
    source_width: int = Field(ge=1)
    source_height: int = Field(ge=1)
    output_width: int = Field(ge=1)
    output_height: int = Field(ge=1)

    @model_validator(mode="after")
    def samples_are_monotonic(self) -> Self:
        previous = -1
        for index, sample in enumerate(self.samples):
            if sample.sample_index != index:
                raise ValueError("face-follow sample index is not sequential")
            if sample.output_us <= previous:
                raise ValueError("face-follow samples are not strictly increasing")
            expected = frame_start_us(index, _OUTPUT_RATE)
            if sample.output_us != expected:
                raise ValueError("face-follow sample is not on a 30/1 frame start")
            previous = sample.output_us
            if sample.frame_width != self.source_width or sample.frame_height != self.source_height:
                raise ValueError("face-follow sample frame does not match the trajectory")
        return self

    def digest(self) -> str:
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class FaceTrackEvidence(Versioned):
    """Coverage summary for one track. It does not name a person."""

    track_id: EntityId
    sample_count: int = Field(ge=1)
    mean_confidence_permille: int = Field(ge=0, le=1000)
    coverage_permille: int = Field(ge=0, le=1000)
    max_gap_us: Microseconds
    face_sample_interval_us: int = Field(ge=1)
    gap_tolerance_us: int = Field(ge=0)


class ReframePlanDocument(Versioned):
    """The crop plan bound to one visual-analysis artifact."""

    plan_id: EntityId
    source_asset_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    producer_job_id: EntityId
    time_map_sha256: str = Field(pattern=_SHA)
    profile_fingerprint: str = Field(pattern=_SHA)
    face_sample_interval_us: int = Field(ge=1)
    gap_tolerance_us: int = Field(ge=0)
    smoothing_divisor: int = Field(ge=1, le=16)
    max_step_px: int = Field(ge=1, le=200)
    headroom_permille: int = Field(ge=0, le=400)
    source_width: int = Field(ge=1)
    source_height: int = Field(ge=1)
    output_width: int = Field(ge=1)
    output_height: int = Field(ge=1)
    fps_numerator: int = Field(ge=1)
    fps_denominator: int = Field(ge=1)
    requested_strategy: Literal["contain", "face_follow"]
    applied_strategy: Literal["contain", "face_follow"]
    fallback_reason: str = ""
    face_track_id: str = ""
    evidence: FaceTrackEvidence | None = None
    trajectory: FaceFollowTrajectory | None = None
    trajectory_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    safe_margin_px: int = Field(ge=0)
    created_by: str = Field(min_length=1, max_length=80)
    tool_version: str = Field(min_length=1, max_length=40)
    plan_fingerprint: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def strategy_matches_trajectory(self) -> Self:
        if self.applied_strategy == "face_follow":
            if self.trajectory is None or self.evidence is None:
                raise ValueError("face_follow requires a trajectory")
            if self.trajectory_sha256 != self.trajectory.digest():
                raise ValueError("trajectory hash does not match the trajectory")
            if (
                self.trajectory.source_width != self.source_width
                or self.trajectory.source_height != self.source_height
            ):
                raise ValueError("trajectory source dimensions do not match the plan")
            if (
                self.trajectory.output_width != self.output_width
                or self.trajectory.output_height != self.output_height
            ):
                raise ValueError("trajectory output dimensions do not match the plan")
            if self.evidence.track_id != self.face_track_id:
                raise ValueError("face track evidence does not match the plan")
            if (
                self.evidence.face_sample_interval_us != self.face_sample_interval_us
                or self.evidence.gap_tolerance_us != self.gap_tolerance_us
            ):
                raise ValueError("face cadence evidence does not match the plan")
            if (
                self.trajectory.smoothing_divisor != self.smoothing_divisor
                or self.trajectory.max_step_px != self.max_step_px
                or self.trajectory.headroom_permille != self.headroom_permille
            ):
                raise ValueError("trajectory smoothing does not match the plan")
        if self.applied_strategy == "contain" and (self.trajectory is not None or self.trajectory_sha256):
            raise ValueError("contain does not store a face trajectory")
        for label, value in (
            ("fallback reason", self.fallback_reason),
            ("created_by", self.created_by),
            ("tool version", self.tool_version),
            ("face track id", self.face_track_id),
        ):
            _reject_unsafe_text(value, label)
        return self


class ReframeEvidenceDigest(Versioned):
    """Hashes that bind a reframe plan to its inputs. Paths are absent."""

    source_sha256: str = Field(pattern=_SHA)
    visual_analysis_sha256: str = Field(pattern=_SHA)
    time_map_sha256: str = Field(pattern=_SHA)
    trajectory_sha256: str = Field(pattern=_SHA)
    plan_fingerprint: str = Field(pattern=_SHA)
