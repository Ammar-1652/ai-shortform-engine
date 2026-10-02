"""Profiles, hard compliance gates, rights, and human review.

Compliance is not a weight. ``require_compliance_cleared`` fails closed when
evidence is missing or any rule fails.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.errors import ComplianceGateError
from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.provenance import ArtifactProvenance


class CampaignMode(StrEnum):
    ORGANIC = "organic"
    PAID_CAMPAIGN = "paid_campaign"


class CampaignProfile(Versioned):
    """Configuration for organic or paid work. Both modes use the same core."""

    profile_id: EntityId
    name: str = Field(min_length=1, max_length=200)
    mode: CampaignMode
    objective: str = Field(min_length=1)
    policy_ids: list[EntityId] = Field(min_length=1)


class ComplianceRule(Versioned):
    """A restriction that blocks. Severity cannot be downgraded to a weight."""

    rule_id: EntityId
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    severity: Literal["block"] = "block"


class ComplianceStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ComplianceResult(Versioned):
    """One rule applied to one subject. ``evidence`` is required for every status."""

    result_id: EntityId
    rule_id: EntityId
    status: ComplianceStatus
    evidence: str = Field(min_length=1)


class RightsStatus(StrEnum):
    OWNED = "owned"
    LICENSED = "licensed"
    CAMPAIGN_PROVIDED = "campaign_provided"
    UNKNOWN = "unknown"
    PROHIBITED = "prohibited"


class AssetKind(StrEnum):
    SOURCE_VIDEO = "source_video"
    CAMPAIGN = "campaign"
    LOCAL = "local"
    ENVATO = "envato"
    GRAPHIC = "graphic"
    AUDIO = "audio"
    FONT = "font"


class AssetLicenseRecord(Versioned):
    """Rights for one asset. ``unknown`` and ``prohibited`` cannot be used in an edit."""

    license_record_id: EntityId
    asset_id: EntityId
    status: RightsStatus
    license_name: str | None = None
    evidence_uri: str | None = None
    notes: str = ""


class AssetReference(Versioned):
    """A pointer to an asset plus the license record that must be checked before use."""

    asset_id: EntityId
    project_id: EntityId
    uri: str = Field(min_length=1, max_length=2048)
    kind: AssetKind
    license_record_id: EntityId
    provenance: ArtifactProvenance


class ReviewDecision(Versioned):
    """A human review. ``automated`` cannot be true in this schema version."""

    review_id: EntityId
    project_id: EntityId
    artifact_id: EntityId | None = None
    candidate_id: EntityId | None = None
    subject_kind: Literal["candidate", "hero", "caption", "framing", "final"]
    decision: Literal["approved", "rejected", "changes_requested"]
    reviewer_id: str = Field(min_length=1, max_length=200)
    created_at: AwareDatetime
    notes: str = ""
    automated: Literal[False] = False

    @model_validator(mode="after")
    def subject_present(self) -> Self:
        if self.artifact_id is None and self.candidate_id is None:
            raise ValueError("review must reference an artifact_id or a candidate_id")
        if self.subject_kind == "final" and self.decision == "approved" and self.artifact_id is None:
            raise ValueError("final approval must name the artifact_id that was reviewed")
        if not self.reviewer_id.strip():
            raise ValueError("reviewer_id must not be blank")
        return self


def is_compliance_cleared(results: Sequence[ComplianceResult]) -> bool:
    """Return whether every result passed. An empty list is not a pass."""
    if len(results) == 0:
        return False
    return all(result.status is ComplianceStatus.PASS for result in results)


def require_compliance_cleared(results: Sequence[ComplianceResult]) -> None:
    """Raise when compliance is missing or any rule did not pass."""
    if not results:
        raise ComplianceGateError(
            "compliance gate failed: no compliance results were supplied. "
            "Missing evidence is not a pass, and a creative score cannot fill the gap."
        )
    blocked = [result.rule_id for result in results if result.status is not ComplianceStatus.PASS]
    if blocked:
        raise ComplianceGateError(
            "compliance gate failed for rules: "
            + ", ".join(blocked)
            + ". A creative score cannot override a block or missing evidence."
        )


def require_rights_cleared(record: AssetLicenseRecord) -> None:
    """Raise when an asset is not cleared for editorial use."""
    if record.status in {RightsStatus.UNKNOWN, RightsStatus.PROHIBITED}:
        raise ComplianceGateError(
            f"asset {record.asset_id} rights status is {record.status.value}. Editorial use is blocked."
        )
    if record.evidence_uri is None or not record.evidence_uri.strip():
        raise ComplianceGateError(
            f"asset {record.asset_id} has no rights evidence URI. Editorial use is blocked "
            "until the license or ownership evidence is recorded."
        )


def is_vertical_9_16(width: int, height: int) -> bool:
    """Return whether ``width`` and ``height`` are a 9:16 frame.

    1080x1920 matches. 1920x1080 does not. This does not render anything.
    """
    if width <= 0 or height <= 0:
        return False
    return width * 16 == height * 9
