"""Operator selection for one campaign. The document stores ids and hashes only."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.campaign import _plain
from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"
SelectionStatus = Literal["ready", "blocked", "stale"]
NarrationPolicy = Literal["disabled", "optional_english"]


class CampaignSourceChoice(Versioned):
    """One catalogue source named by an operator selection."""

    source_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    rights_state: str = Field(min_length=1, max_length=80)

    @field_validator("rights_state")
    @classmethod
    def rights_are_plain(cls, value: str) -> str:
        return _plain(value, label="rights state")


class CampaignSelectionDocument(Versioned):
    """Append-only record of which sources an operator asked the runner to use."""

    selection_id: EntityId
    campaign_id: EntityId
    project_id: EntityId
    source_ids: list[EntityId] = Field(min_length=1)
    sources: list[CampaignSourceChoice] = Field(min_length=1)
    language: str = Field(min_length=2, max_length=16)
    narration_enabled: bool
    narration_policy: NarrationPolicy
    operator_id: EntityId
    created_at: AwareDatetime
    catalogue_fingerprint: str = Field(pattern=_SHA)
    policy_fingerprint: str = Field(pattern=_SHA)
    evidence_fingerprint: str = Field(pattern=_SHA)
    status: SelectionStatus
    reason_code: str = Field(min_length=1, max_length=80)
    publishing: Literal["deferred"] = "deferred"
    whop_live: Literal["not_configured"] = "not_configured"
    provenance: ArtifactProvenance

    @field_validator("language", "reason_code")
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="selection label")

    @model_validator(mode="after")
    def sources_match_ids(self) -> Self:
        found = [item.source_id for item in self.sources]
        if found != self.source_ids or found != sorted(set(found)):
            raise ValueError("selection sources must be unique and sorted")
        text = self.model_dump_json().lower()
        if any(token in text for token in ("/home/", "/tmp/", "/users/", "file://", "bearer ", "token=")):
            raise ValueError("selection contains a path or a secret")
        return self


class CampaignImportSnapshot(Versioned):
    """Operator-supplied catalogue snapshot. It is not a live account crawl.

    A remote reference is metadata. This document does not download it.
    """

    campaign_id: EntityId
    source_ids: list[EntityId] = Field(min_length=1)
    language: str = "en-US"
    narration_enabled: bool = False
    operator_id: EntityId
    policy_state: str = Field(min_length=1, max_length=80)
    selection_state: Literal["selected", "withheld"]
    remote_media_ref: str | None = None

    @field_validator("language", "policy_state")
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="import label")

    @field_validator("remote_media_ref")
    @classmethod
    def remote_is_metadata(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="remote media", allow_https=True)

    @model_validator(mode="after")
    def ids_are_unique(self) -> Self:
        if self.source_ids != sorted(set(self.source_ids)):
            raise ValueError("import sources must be unique and sorted")
        text = self.model_dump_json().lower()
        if any(token in text for token in ("/home/", "/tmp/", "/users/", "file://", "bearer ", "token=")):
            raise ValueError("import contains a path or a secret")
        return self
