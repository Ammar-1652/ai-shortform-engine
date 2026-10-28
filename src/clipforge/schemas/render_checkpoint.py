"""Verified render units. Frame indexes are execution boundaries, not editorial time."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"


class RenderAuthorizationItem(Versioned):
    """One service-issued composition input accepted by the renderer."""

    candidate_id: EntityId
    input_sha256: str = Field(pattern=_SHA)
    output_relative_path: str = Field(min_length=1, max_length=512)
    staged_sha256: dict[str, str]

    @model_validator(mode="after")
    def output_is_relative(self) -> Self:
        path = self.output_relative_path
        if path.startswith("/") or "\\" in path or any(part in {"", ".", ".."} for part in path.split("/")):
            raise ValueError("render authorization output must be run relative")
        for name, digest in self.staged_sha256.items():
            import re

            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", name) is None:
                raise ValueError("authorized staged input must be a local file name")
            if re.fullmatch(_SHA, digest) is None:
                raise ValueError("authorized staged input requires a sha256")
        if not self.staged_sha256:
            raise ValueError("render authorization requires staged input hashes")
        return self


class AdvancedRenderAuthorization(Versioned):
    """Service-issued proof binding a renderer batch to its persisted inputs.

    The renderer is a worker. It may consume this record, but it cannot create
    one. Parent hashes are carried by the canonical render input and are bound
    here through each input digest.
    """

    recipe: Literal["advanced-render-authorization-v1"] = "advanced-render-authorization-v1"
    authorization_id: EntityId
    advanced_set_id: EntityId
    source_asset_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    batch_sha256: str = Field(pattern=_SHA)
    renderer_dependency_sha256: str = Field(pattern=_SHA)
    renderer_dependency_files: dict[str, str] = Field(min_length=1)
    items: list[RenderAuthorizationItem] = Field(min_length=1)
    created_at: AwareDatetime
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def items_are_unique(self) -> Self:
        ids = [item.candidate_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("render authorization candidate ids must be unique")
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("render authorization provenance must include its source")
        return self


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
