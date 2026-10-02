"""Jobs, render records, and QA. QA status is computed from checks and cannot be upgraded."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.errors import TimelineError
from clipforge.schemas.common import ContractModel, EntityId, Microseconds, Versioned
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.timeline import FrameRate


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class JobRecord(Versioned):
    """A row in the jobs table. ``kind`` names the work. It does not claim the work ran."""

    job_id: EntityId
    project_id: EntityId
    kind: str = Field(min_length=1, max_length=80)
    status: JobStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
    error_message: str | None = None
    payload: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def times_ordered(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at is earlier than created_at")
        if self.status is JobStatus.FAILED and not (self.error_message and self.error_message.strip()):
            raise ValueError("a failed job must store a non-empty error_message")
        return self


class RenderJob(Versioned):
    """A request to render one edit plan. Creating this record does not render video."""

    job_id: EntityId
    project_id: EntityId
    edit_plan_id: EntityId
    stage: Literal["rough", "hero"]
    status: JobStatus
    created_at: AwareDatetime
    provenance: ArtifactProvenance


class RenderArtifact(Versioned):
    """A rendered file's measured properties. Round 1 does not produce the file."""

    artifact_id: EntityId
    project_id: EntityId
    job_id: EntityId
    edit_plan_id: EntityId
    uri: str = Field(min_length=1, max_length=2048)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    frame_rate_numerator: int = Field(gt=0)
    frame_rate_denominator: int = Field(gt=0)
    duration_us: Microseconds
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def measured_facts(self) -> Self:
        if self.duration_us <= 0:
            raise ValueError("render duration_us must be greater than 0")
        try:
            FrameRate(self.frame_rate_numerator, self.frame_rate_denominator)
        except TimelineError as exc:
            raise ValueError(str(exc)) from exc
        if not self.provenance.source_asset_ids:
            raise ValueError("render artifact provenance must list at least one source_asset_id")
        return self


class QAStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class QAKind(StrEnum):
    TECHNICAL = "technical"
    CAMPAIGN_COMPLIANCE = "campaign_compliance"


class QACheck(ContractModel):
    name: str = Field(min_length=1, max_length=200)
    status: QAStatus
    evidence: str = Field(min_length=1)


class QAResult(Versioned):
    """Aggregated QA. The status must match the checks. A pass cannot hide a failure."""

    qa_id: EntityId
    project_id: EntityId
    artifact_id: EntityId
    kind: QAKind
    status: QAStatus
    checks: list[QACheck] = Field(min_length=1)
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def status_matches_checks(self) -> Self:
        statuses = {check.status for check in self.checks}
        if QAStatus.FAIL in statuses:
            expected = QAStatus.FAIL
        elif QAStatus.INSUFFICIENT_EVIDENCE in statuses:
            expected = QAStatus.INSUFFICIENT_EVIDENCE
        else:
            expected = QAStatus.PASS
        if self.status is not expected:
            raise ValueError(
                f"QA status is {self.status.value} but the checks aggregate to {expected.value}. "
                "Do not mark a result passed while a check failed or lacks evidence."
            )
        if not self.provenance.source_asset_ids:
            raise ValueError("QA provenance must list at least one source_asset_id")
        return self
