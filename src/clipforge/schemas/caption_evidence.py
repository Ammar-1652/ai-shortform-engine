"""Persisted evidence that rendered captions occupy the effective output clock."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from clipforge.schemas.common import ContractModel, EntityId, Microseconds, Versioned
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"
_RELATIVE = (
    r"^candidates/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}/"
    r"caption-frames/[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.png$"
)
_SPEECH_REVIEW_RELATIVE = (
    r"^candidates/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}/"
    r"speech-review\.json$"
)


class CaptionFrameObservation(ContractModel):
    """A frame may simultaneously own several cue/word boundary roles."""

    phase: Literal["before", "start", "middle", "end", "after", "first", "last", "word_start", "word_end"]
    cue_id: EntityId | None = None
    word_id: EntityId | None = None


class CaptionCoverageFrame(Versioned):
    """One decoded frame at a caption edge or word-highlight boundary."""

    frame_id: EntityId
    frame_index: int = Field(ge=0)
    output_time_us: Microseconds
    observations: list[CaptionFrameObservation] = Field(min_length=1)
    relative_path: str = Field(pattern=_RELATIVE)
    sha256: str = Field(pattern=_SHA)


class CaptionAudioCoverageReport(Versioned):
    """Caption coverage and decoded cue-edge proof for one encoded draft."""

    report_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    alignment_sha256: str = Field(pattern=_SHA)
    time_map_sha256: str = Field(pattern=_SHA)
    render_input_sha256: str = Field(pattern=_SHA)
    encoded_media_sha256: str = Field(pattern=_SHA)
    staged_audio_sha256: str = Field(pattern=_SHA)
    output_duration_us: Microseconds
    output_frame_count: int = Field(ge=1)
    forced_word_ids: list[EntityId] = Field(min_length=1)
    caption_cue_ids: list[EntityId] = Field(min_length=1)
    frames: list[CaptionCoverageFrame] = Field(min_length=1)
    decoded_frames_status: Literal["complete"] = "complete"
    # Decoding caption edges cannot prove speech absent from ASR is covered.
    # R5's reviewed speech inventory is required before that claim is possible.
    speech_coverage_status: Literal["insufficient_evidence", "complete"] = "insufficient_evidence"
    speech_review_relative_path: str = Field(default="", pattern=r"^$|" + _SPEECH_REVIEW_RELATIVE)
    speech_review_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def is_complete(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("caption coverage provenance must include its source")
        if len(self.forced_word_ids) != len(set(self.forced_word_ids)):
            raise ValueError("caption coverage forced word ids must be unique")
        if len(self.caption_cue_ids) != len(set(self.caption_cue_ids)):
            raise ValueError("caption coverage cue ids must be unique")
        if any(frame.frame_index >= self.output_frame_count for frame in self.frames):
            raise ValueError("caption coverage frame is outside the output")
        indexes = [frame.frame_index for frame in self.frames]
        if indexes != sorted(set(indexes)):
            raise ValueError("decoded caption frames must be unique and ordered")
        for frame in self.frames:
            if frame.relative_path != (
                f"candidates/{self.candidate_id}/caption-frames/frame-{frame.frame_index:06d}.png"
            ):
                raise ValueError("caption frame must belong to its candidate and frame index")
        if bool(self.speech_review_relative_path) != bool(self.speech_review_sha256):
            raise ValueError("speech review path and hash must be supplied together")
        if self.speech_coverage_status == "complete" and not self.speech_review_relative_path:
            raise ValueError("complete speech coverage requires a reviewed speech inventory")
        return self
