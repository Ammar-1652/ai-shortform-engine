"""Normalized ingest facts. Canonical timing is integer microseconds, not binary floats.

``NormalizedMediaProbe`` is the application source of truth after ingest.
The raw ffprobe JSON file is a debugging artifact and is not consulted for
duration or stream choice once this model has been stored.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import ContractModel, EntityId, Microseconds, Versioned


class RationalNumber(ContractModel):
    """An exact integer ratio. ``30000/1001`` is not stored as ``29.97``."""

    numerator: int
    denominator: int = Field(gt=0)


class StreamDisposition(ContractModel):
    default: bool = False
    attached_pic: bool = False


class ColorMetadata(ContractModel):
    color_range: str | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None


class RotationMetadata(ContractModel):
    """Encoded rotation in degrees. ``None`` means ffprobe did not report one."""

    degrees: int | None = None


class FrameTimingClass(StrEnum):
    CFR_LIKELY = "cfr_likely"
    VFR_POSSIBLE = "vfr_possible"
    UNKNOWN = "unknown"


class HdrSignal(StrEnum):
    """HDR evidence. ``none`` means no PQ/HLG tag, not a confirmed SDR grade."""

    NONE = "none"
    PQ = "pq"
    HLG = "hlg"


class MediaFormatInfo(Versioned):
    format_name: str | None = None
    format_long_name: str | None = None
    duration_us: int | None = None
    start_time_us: int | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    bit_rate: int | None = Field(default=None, ge=0)
    tags: dict[str, str] = Field(default_factory=dict)


class VideoStreamInfo(Versioned):
    index: int = Field(ge=0)
    codec_name: str | None = None
    codec_long_name: str | None = None
    profile: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    display_width: int | None = Field(default=None, gt=0)
    display_height: int | None = Field(default=None, gt=0)
    pix_fmt: str | None = None
    sample_aspect_ratio: RationalNumber | None = None
    display_aspect_ratio: RationalNumber | None = None
    avg_frame_rate: RationalNumber | None = None
    r_frame_rate: RationalNumber | None = None
    time_base: RationalNumber | None = None
    start_pts: int | None = None
    start_time_us: int | None = None
    duration_ts: int | None = None
    duration_us: int | None = None
    bit_rate: int | None = Field(default=None, ge=0)
    disposition: StreamDisposition = Field(default_factory=StreamDisposition)
    language: str | None = None
    color: ColorMetadata = Field(default_factory=ColorMetadata)
    rotation: RotationMetadata = Field(default_factory=RotationMetadata)
    field_order: str | None = None


class AudioStreamInfo(Versioned):
    index: int = Field(ge=0)
    codec_name: str | None = None
    sample_rate: int | None = Field(default=None, gt=0)
    channels: int | None = Field(default=None, gt=0)
    channel_layout: str | None = None
    sample_fmt: str | None = None
    time_base: RationalNumber | None = None
    start_pts: int | None = None
    start_time_us: int | None = None
    duration_ts: int | None = None
    duration_us: int | None = None
    bit_rate: int | None = Field(default=None, ge=0)
    disposition: StreamDisposition = Field(default_factory=StreamDisposition)
    language: str | None = None


class StreamSelection(ContractModel):
    video_stream_index: int = Field(ge=0)
    audio_stream_index: int | None = Field(default=None, ge=0)
    video_selection: Literal["automatic", "explicit"]
    audio_selection: Literal["automatic", "explicit", "none"]


class MediaTimelineInfo(ContractModel):
    """Container and stream clocks, plus the Clipforge source clock.

    ``video_origin_us`` is the container timestamp of canonical ``t=0``.
    It may be negative. Canonical source time is microseconds after that origin.
    """

    video_origin_us: int
    video_start_assumed_zero: bool
    audio_start_us: int | None = None
    audio_start_assumed_zero: bool = False
    audio_offset_us: int | None = None
    canonical_duration_us: Microseconds
    duration_evidence: str = Field(min_length=1)

    @model_validator(mode="after")
    def duration_positive(self) -> Self:
        if self.canonical_duration_us <= 0:
            raise ValueError("canonical_duration_us must be greater than 0")
        return self


class MediaClassification(ContractModel):
    frame_timing: FrameTimingClass
    hdr: HdrSignal
    transcription_eligible: bool


class NormalizedMediaProbe(Versioned):
    format: MediaFormatInfo
    video_streams: list[VideoStreamInfo]
    audio_streams: list[AudioStreamInfo]
    chapter_count: int = Field(ge=0)
    ffprobe_version: str = Field(min_length=1)
    selection: StreamSelection
    timeline: MediaTimelineInfo
    classification: MediaClassification


class DerivativeCacheRecord(Versioned):
    """Sidecar that decides whether a derived file can be reused.

    ``created_at`` is recorded for provenance. It is not part of cache identity.
    A later run with the same recipe, source hash, and streams keeps the file
    even though the timestamp differs.
    """

    recipe_name: str = Field(min_length=1, max_length=80)
    recipe_version: str = Field(min_length=1, max_length=40)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_id: EntityId
    source_asset_id: EntityId
    video_stream_index: int = Field(ge=0)
    audio_stream_index: int | None = Field(default=None, ge=0)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    ffmpeg_version: str = Field(min_length=1, max_length=200)
    arguments: list[str] = Field(min_length=1)
    validation_status: Literal["passed"]
    created_at: AwareDatetime


class SourceIngestManifest(Versioned):
    """Durable, queryable identity for one referenced source. Not a copied file."""

    source_asset_id: EntityId
    project_id: EntityId
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    mtime_ns: int = Field(ge=0)
    original_filename: str = Field(min_length=1, max_length=512)
    storage_mode: Literal["referenced"] = "referenced"
    transcription_eligible: bool
    video_stream_index: int = Field(ge=0)
    audio_stream_index: int | None = Field(default=None, ge=0)
    canonical_duration_us: Microseconds
    video_origin_us: int
    ingested_at: AwareDatetime
    probe: NormalizedMediaProbe

    @model_validator(mode="after")
    def duration_matches_probe(self) -> Self:
        if self.canonical_duration_us != self.probe.timeline.canonical_duration_us:
            raise ValueError("manifest duration must match the normalized probe timeline")
        if self.canonical_duration_us <= 0:
            raise ValueError("canonical_duration_us must be greater than 0")
        if self.video_stream_index != self.probe.selection.video_stream_index:
            raise ValueError("manifest video stream must match the probe selection")
        if self.audio_stream_index != self.probe.selection.audio_stream_index:
            raise ValueError("manifest audio stream must match the probe selection")
        return self
