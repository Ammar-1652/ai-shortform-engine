"""Verified render units. Frame indexes are execution boundaries, not editorial time."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import Versioned


class RenderUnitReceipt(Versioned):
    unit_id: str = Field(pattern=r"^(video-[0-9]{6}|audio)$")
    start_frame: int = Field(ge=0)
    end_frame_exclusive: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def positive_range(self) -> Self:
        if self.end_frame_exclusive <= self.start_frame:
            raise ValueError("render unit range must be positive")
        return self


class CandidateRenderCheckpoint(Versioned):
    recipe: Literal["remotion-chunks-continuous-audio-v1"] = "remotion-chunks-continuous-audio-v1"
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependency_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_in_frames: int = Field(ge=1)
    chunk_frames: int = Field(ge=1, le=300)
    receipts: list[RenderUnitReceipt] = Field(default_factory=list)
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def receipts_are_unique(self) -> Self:
        if len({item.unit_id for item in self.receipts}) != len(self.receipts):
            raise ValueError("render checkpoint unit ids must be unique")
        for item in self.receipts:
            if item.end_frame_exclusive > self.duration_in_frames:
                raise ValueError("checkpoint receipt extends beyond composition")
        return self
