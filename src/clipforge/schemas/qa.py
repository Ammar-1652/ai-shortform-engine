"""QA set binding. The aggregate status cannot hide a failed or incomplete check."""

from __future__ import annotations

from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.jobs import QAKind, QAResult, QAStatus
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"


class PolicyDigest(Versioned):
    """One resolved policy and its canonical hash. The path is not stored."""

    policy_id: EntityId
    sha256: str = Field(pattern=_SHA)


class QASetDocument(Versioned):
    """Technical and campaign QA bound to one current artifact."""

    qa_set_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    target_artifact_id: EntityId
    target_artifact_kind: str = Field(min_length=1, max_length=80)
    target_manifest_sha256: str = Field(pattern=_SHA)
    profile_id: EntityId
    profile_sha256: str = Field(pattern=_SHA)
    policies: list[PolicyDigest] = Field(min_length=1)
    technical: QAResult
    campaign: QAResult
    status: QAStatus
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def set_is_bound(self) -> Self:
        if self.technical.kind is not QAKind.TECHNICAL:
            raise ValueError("technical result must use kind technical")
        if self.campaign.kind is not QAKind.CAMPAIGN_COMPLIANCE:
            raise ValueError("campaign result must use kind campaign_compliance")
        for result in (self.technical, self.campaign):
            if result.artifact_id != self.target_artifact_id:
                raise ValueError("QA results must reference the target artifact")
            if result.project_id != self.project_id:
                raise ValueError("QA results must reference the project")
            if self.source_asset_id not in result.provenance.source_asset_ids:
                raise ValueError("QA result provenance must include the source asset")
            if not result.checks:
                raise ValueError("a QA result cannot pass with an empty check list")
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("QA provenance must include the source asset")
        if self.target_artifact_id not in self.provenance.parent_artifact_ids:
            raise ValueError("QA provenance must include the parent artifact")
        ids = [item.policy_id for item in self.policies]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("policy digests must be unique and sorted by policy id")
        expected = aggregate_status(self.technical.status, self.campaign.status)
        if self.status is not expected:
            raise ValueError(
                f"QA aggregate status is {self.status.value} but the results aggregate to "
                f"{expected.value}. Do not upgrade a failed or incomplete QA set."
            )
        return self


class QACacheRecord(Versioned):
    """Sidecar for the current QA set. It stores hashes, not filesystem paths."""

    project_id: EntityId
    source_asset_id: EntityId
    qa_set_id: EntityId
    artifact_id: EntityId
    target_artifact_id: EntityId
    target_artifact_kind: str = Field(min_length=1, max_length=80)
    target_manifest_sha256: str = Field(pattern=_SHA)
    profile_id: EntityId
    profile_sha256: str = Field(pattern=_SHA)
    manifest_sha256: str = Field(pattern=_SHA)
    manifest_size_bytes: int = Field(ge=1)
    status: QAStatus
    created_at: AwareDatetime


def aggregate_status(*statuses: QAStatus) -> QAStatus:
    """Return the worst status. An empty list is not a pass."""
    if not statuses:
        return QAStatus.INSUFFICIENT_EVIDENCE
    if QAStatus.FAIL in statuses:
        return QAStatus.FAIL
    if QAStatus.INSUFFICIENT_EVIDENCE in statuses:
        return QAStatus.INSUFFICIENT_EVIDENCE
    return QAStatus.PASS
