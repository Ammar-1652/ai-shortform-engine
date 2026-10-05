"""Rough preview contracts. Captions are provisional. Scores are not render inputs.

``quality_score`` and ``edit_opportunity_score``, when copied, stay editorial
heuristics. They do not change the picture, the captions, or the cache identity.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import ContractModel, EntityId, Microseconds, Versioned
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"


def preview_fingerprint(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class RoughPreviewProfile(Versioned):
    """Every setting that changes preview bytes. ``created_at`` is not a field."""

    profile_id: Literal["rough-preview-v1"] = "rough-preview-v1"
    width: Literal[720] = 720
    height: Literal[1280] = 1280
    fps_numerator: Literal[30] = 30
    fps_denominator: Literal[1] = 1
    video_fit: Literal["contain"] = "contain"
    background: Literal["neutral-dark-v1"] = "neutral-dark-v1"
    caption_algorithm_version: Literal["provisional-caption-v1"] = "provisional-caption-v1"
    caption_style_version: Literal["rough-caption-style-v1"] = "rough-caption-style-v1"
    renderer_recipe_version: Literal["rough-preview-renderer-v1"] = "rough-preview-renderer-v1"
    video_codec: Literal["h264"] = "h264"
    pixel_format: Literal["yuv420p"] = "yuv420p"
    audio_enabled: Literal[True] = True
    h264_crf: int = Field(default=28, ge=0, le=51)
    max_caption_words: Literal[8] = 8
    max_caption_code_points: Literal[42] = 42
    max_caption_duration_us: Literal[3_000_000] = 3_000_000
    max_caption_gap_us: Literal[1_250_000] = 1_250_000

    def fingerprint(self) -> str:
        return preview_fingerprint(self.model_dump(mode="json"))


class RoughCaptionCue(Versioned):
    """One provisional caption. Microseconds are canonical. Frames are a render derivative."""

    cue_id: EntityId
    text: str = Field(min_length=1, max_length=300)
    transcript_segment_ids: list[EntityId] = Field(min_length=1)
    transcript_word_ids: list[EntityId] = Field(default_factory=list)
    source_start_us: Microseconds
    source_end_us: Microseconds
    output_start_us: Microseconds
    output_end_us: Microseconds
    output_start_frame: int = Field(ge=0)
    output_end_frame_exclusive: int = Field(ge=1)
    timing_quality: Literal["provisional"] = "provisional"

    @model_validator(mode="after")
    def ranges_are_half_open(self) -> Self:
        if self.source_end_us <= self.source_start_us:
            raise ValueError("caption source_end_us must be greater than source_start_us")
        if self.output_end_us <= self.output_start_us:
            raise ValueError("caption output_end_us must be greater than output_start_us")
        if self.output_end_frame_exclusive <= self.output_start_frame:
            raise ValueError("caption frame interval must be positive and half-open")
        return self


class RoughPreviewRenderInput(Versioned):
    """Facts the renderer needs. Python already decided that this candidate is valid."""

    composition_id: Literal["RoughPreview"] = "RoughPreview"
    candidate_id: EntityId
    preview_set_id: EntityId
    video_path: str = Field(min_length=1, max_length=4096)
    audio_path: str = Field(min_length=1, max_length=4096)
    media_trim_frame: int = Field(ge=0)
    duration_in_frames: int = Field(ge=1)
    fps_numerator: Literal[30] = 30
    fps_denominator: Literal[1] = 1
    width: Literal[720] = 720
    height: Literal[1280] = 1280
    video_fit: Literal["contain"] = "contain"
    background: Literal["neutral-dark-v1"] = "neutral-dark-v1"
    timing_quality: Literal["provisional"] = "provisional"
    captions: list[RoughCaptionCue] = Field(default_factory=list)
    source_start_us: int = Field(default=0, ge=0)
    source_end_us: int = Field(default=0, ge=0)
    proxy_sha256: str = ""
    staged_video_sha256: str = ""
    staged_audio_sha256: str = ""
    staged_duration_us: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def captions_fit_the_composition(self) -> Self:
        if self.video_path.lower().startswith(("http://", "https://")):
            raise ValueError("rough preview video must be a local file, not an http URL")
        if self.audio_path.lower().startswith(("http://", "https://")):
            raise ValueError("rough preview audio must be a local file, not an http URL")
        for cue in self.captions:
            if cue.output_end_us > self._duration_hint_us():
                raise ValueError("caption output range extends past the candidate duration")
            if cue.output_end_frame_exclusive > self.duration_in_frames:
                raise ValueError("caption frame range extends past duration_in_frames")
        return self

    def _duration_hint_us(self) -> int:
        return (self.duration_in_frames * 1_000_000 * self.fps_denominator) // self.fps_numerator


class CandidateRoughPreview(Versioned):
    """One rendered review file. Quality numbers here are copies for display, not render inputs."""

    candidate_id: EntityId
    rank: int = Field(ge=1)
    time_map_sha256: str = Field(pattern=_SHA)
    source_start_us: Microseconds
    source_end_us: Microseconds
    output_duration_us: Microseconds
    output_frame_count: int = Field(ge=1)
    timing_quality: Literal["provisional"] = "provisional"
    caption_count: int = Field(ge=0)
    render_input_sha256: str = Field(pattern=_SHA)
    preview_relative_path: str = Field(min_length=1, max_length=512)
    preview_sha256: str = Field(pattern=_SHA)
    preview_size_bytes: int = Field(ge=1)
    width: Literal[720] = 720
    height: Literal[1280] = 1280
    output_fps_numerator: Literal[30] = 30
    output_fps_denominator: Literal[1] = 1
    detected_video_codec: str = Field(min_length=1, max_length=40)
    detected_pixel_format: str = Field(min_length=1, max_length=40)
    detected_audio_codec: str = Field(min_length=1, max_length=40)
    detected_duration_us: Microseconds
    duration_error_us: int
    quality_score: float | None = Field(default=None, ge=0, le=1)
    edit_opportunity_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def scores_are_finite(self) -> Self:
        if self.source_end_us <= self.source_start_us:
            raise ValueError("preview source range must be positive")
        if self.output_duration_us <= 0:
            raise ValueError("preview output duration must be positive")
        for label, value in (
            ("quality_score", self.quality_score),
            ("edit_opportunity_score", self.edit_opportunity_score),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{label} must be finite")
        parts = self.preview_relative_path.split("/")
        escaped = parts[1] in {"", ".", ".."} if len(parts) == 3 else True
        bad_shape = len(parts) != 3 or parts[0] != "candidates" or parts[2] != "preview.mp4" or escaped
        if bad_shape:
            raise ValueError("preview_relative_path must be candidates/<id>/preview.mp4")
        if parts[1] != self.candidate_id:
            raise ValueError("preview_relative_path candidate id does not match")
        return self


class RoughPreviewSetSummary(ContractModel):
    selected_candidate_count: int = Field(ge=0)
    rendered_count: int = Field(ge=0)
    total_output_duration_us: Microseconds
    total_preview_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_agree(self) -> Self:
        if self.rendered_count != self.selected_candidate_count:
            raise ValueError("rendered_count must equal selected_candidate_count")
        if self.selected_candidate_count == 0 and (
            self.total_output_duration_us != 0 or self.total_preview_bytes != 0
        ):
            raise ValueError("an empty preview set has zero duration and zero bytes")
        return self


class RoughPreviewSetDocument(Versioned):
    """One immutable rough-preview run for the current candidate set."""

    preview_set_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    mining_id: EntityId
    created_at: AwareDatetime
    source_sha256: str = Field(pattern=_SHA)
    candidate_set_artifact_id: EntityId
    candidate_set_sha256: str = Field(pattern=_SHA)
    transcript_id: EntityId
    transcript_sha256: str = Field(pattern=_SHA)
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    analysis_proxy_sha256: str = Field(pattern=_SHA)
    asr_audio_sha256: str = Field(pattern=_SHA)
    preview_input_sha256: str = Field(pattern=_SHA)
    profile: RoughPreviewProfile
    profile_fingerprint: str = Field(pattern=_SHA)
    renderer_recipe_version: Literal["rough-preview-renderer-v1"] = "rough-preview-renderer-v1"
    caption_algorithm_version: Literal["provisional-caption-v1"] = "provisional-caption-v1"
    tool_version: str = Field(min_length=1, max_length=80)
    previews: list[CandidateRoughPreview] = Field(default_factory=list)
    summary: RoughPreviewSetSummary
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def set_is_consistent(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("preview provenance must include source_asset_id")
        if self.provenance.inputs_sha256 != self.preview_input_sha256:
            raise ValueError("provenance input digest must be the preview input digest")
        if self.profile.fingerprint() != self.profile_fingerprint:
            raise ValueError("profile fingerprint does not match the stored profile")
        if self.summary.rendered_count != len(self.previews):
            raise ValueError("summary rendered_count does not match the preview list")
        if self.summary.selected_candidate_count != len(self.previews):
            raise ValueError("summary selected count does not match the preview list")
        ids = [item.candidate_id for item in self.previews]
        if len(set(ids)) != len(ids):
            raise ValueError("preview candidate ids must be unique")
        ranks = [item.rank for item in self.previews]
        if ranks != list(range(1, len(self.previews) + 1)):
            raise ValueError("preview ranks must be 1..n in list order")
        duration = sum(item.output_duration_us for item in self.previews)
        size = sum(item.preview_size_bytes for item in self.previews)
        if self.summary.total_output_duration_us != duration:
            raise ValueError("summary duration does not match the previews")
        if self.summary.total_preview_bytes != size:
            raise ValueError("summary byte count does not match the previews")
        return self


class RoughPreviewCacheRecord(Versioned):
    """Sidecar for the current rough preview set. ``created_at`` is not identity."""

    project_id: EntityId
    source_asset_id: EntityId
    preview_set_id: EntityId
    job_id: EntityId
    mining_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    candidate_set_artifact_id: EntityId
    candidate_set_sha256: str = Field(pattern=_SHA)
    transcript_id: EntityId
    transcript_sha256: str = Field(pattern=_SHA)
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    analysis_proxy_sha256: str = Field(pattern=_SHA)
    asr_audio_sha256: str = Field(pattern=_SHA)
    preview_input_sha256: str = Field(pattern=_SHA)
    profile_fingerprint: str = Field(pattern=_SHA)
    renderer_recipe_version: Literal["rough-preview-renderer-v1"] = "rough-preview-renderer-v1"
    caption_algorithm_version: Literal["provisional-caption-v1"] = "provisional-caption-v1"
    manifest_sha256: str = Field(pattern=_SHA)
    manifest_size_bytes: int = Field(ge=0)
    rendered_count: int = Field(ge=0)
    validation_status: Literal["passed"]
    created_at: AwareDatetime
