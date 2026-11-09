"""Append-only execution receipts for resumable production runs."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.campaign_run import CampaignSourceRun
from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"

ExecutionStatus = Literal[
    "planned",
    "running",
    "succeeded",
    "failed",
    "blocked",
    "cancelled",
    "stale",
    "needs_review",
]


class RunStageReceipt(Versioned):
    """One verified stage result. It carries facts, never a filesystem path."""

    run_id: EntityId
    source_id: EntityId
    stage: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    status: ExecutionStatus
    attempt: int = Field(ge=1)
    input_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    dependency_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    output_artifact_id: EntityId | None = None
    output_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    reason_code: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    updated_at: AwareDatetime
    provenance: ArtifactProvenance | None = None


class ProductionExecutionCheckpoint(Versioned):
    """Durable progress for one production request.

    The checkpoint is a recovery index. The campaign production manifest and
    existing artifact rows remain the delivery authority.
    """

    checkpoint_id: EntityId
    run_id: EntityId
    campaign_id: EntityId
    project_id: EntityId
    request_fingerprint: str = Field(pattern=_SHA)
    release_id: EntityId | None = None
    release_fingerprint: str = Field(default="", pattern=r"^$|" + _SHA)
    language: str = "en-US"
    narration_enabled: bool = False
    source_locales: dict[EntityId, str] = Field(default_factory=dict)
    source_ids: list[EntityId] = Field(min_length=1)
    completed_source_ids: list[EntityId] = Field(default_factory=list)
    sources: list[CampaignSourceRun] = Field(default_factory=list)
    stage_receipts: list[RunStageReceipt] = Field(default_factory=list)
    status: ExecutionStatus
    current_source_id: EntityId | None = None
    current_stage: str | None = None
    final_campaign_run_id: EntityId | None = None
    checkpoint_sha256: str = Field(pattern=_SHA)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    provenance: ArtifactProvenance | None = None

    @model_validator(mode="after")
    def checkpoint_is_consistent(self) -> Self:
        if self.source_ids != sorted(self.source_ids) or len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("execution source ids must be unique and deterministic")
        if any(source_id not in self.source_ids for source_id in self.completed_source_ids):
            raise ValueError("execution checkpoint completed source is not requested")
        if self.completed_source_ids != sorted(self.completed_source_ids):
            raise ValueError("execution completed source ids must be deterministic")
        if len(set(self.completed_source_ids)) != len(self.completed_source_ids):
            raise ValueError("execution completed source ids must be unique")
        found = [source.source_id for source in self.sources]
        if len(set(found)) != len(found):
            raise ValueError("execution sources must be unique")
        if set(self.completed_source_ids) != {
            source.source_id for source in self.sources if source.status == "succeeded"
        }:
            raise ValueError("completed source ids must match succeeded source records")
        if any(source.source_id not in self.source_ids for source in self.sources):
            raise ValueError("execution checkpoint contains an unknown source")
        if self.current_source_id is not None and self.current_source_id not in self.source_ids:
            raise ValueError("execution current source is not requested")
        if self.final_campaign_run_id is not None and self.status in {"planned", "running"}:
            raise ValueError("final campaign run id requires a completed controller attempt")
        if self.status == "succeeded" and set(self.completed_source_ids) != set(self.source_ids):
            raise ValueError("succeeded checkpoint requires all sources")
        if any(
            receipt.run_id != self.run_id or receipt.source_id not in self.source_ids
            for receipt in self.stage_receipts
        ):
            raise ValueError("execution receipt belongs to another run or source")
        lowered = self.model_dump_json().lower()
        if any(token in lowered for token in ("/home/", "/tmp/", "/users/", "file://", "bearer ", "token=")):
            raise ValueError("execution checkpoint contains a path or secret")
        return self
