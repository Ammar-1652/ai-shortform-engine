"""Whop campaign snapshots. Credentials are not fields."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.campaign import _plain
from clipforge.schemas.common import EntityId, Versioned

_SHA = r"^[0-9a-f]{64}$"
_LEAKS = (
    "/home/",
    "/tmp/",
    "/users/",
    "file:",
    "bearer ",
    "token=",
    "cookie=",
    "password=",
    "api_key",
    "api-key",
    "apikey",
    "authorization:",
    "secret=",
    "<script",
    "javascript:",
)


def _reject_leaks(text: str, *, label: str) -> None:
    lowered = text.lower()
    if any(token in lowered for token in _LEAKS):
        raise ValueError(f"{label} contains a path or a secret")


class WhopCampaignSourceRecord(Versioned):
    """One source named by an operator-exported snapshot. The row is not a license."""

    source_id: EntityId
    display_name: str = Field(min_length=1, max_length=300)
    rights_state: str = Field(min_length=1, max_length=80)
    policy_state: str = Field(min_length=1, max_length=80)
    selected: bool

    @field_validator("display_name", "rights_state", "policy_state")
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="whop source")


class WhopCampaignRecord(Versioned):
    """One campaign inside a snapshot. Policy text is not rights evidence."""

    campaign_id: EntityId
    title: str = Field(min_length=1, max_length=200)
    policy_state: str = Field(min_length=1, max_length=80)
    sources: list[WhopCampaignSourceRecord] = Field(min_length=1)

    @field_validator("title", "policy_state")
    @classmethod
    def campaign_text_is_plain(cls, value: str) -> str:
        return _plain(value, label="whop campaign")

    @model_validator(mode="after")
    def sources_are_unique(self) -> Self:
        found = [item.source_id for item in self.sources]
        if len(found) != len(set(found)):
            raise ValueError("whop sources must be unique")
        return self


class WhopCampaignSnapshot(Versioned):
    """Operator-exported campaign metadata. This is not a live account crawl."""

    operator_id: EntityId
    exported_at: AwareDatetime
    campaigns: list[WhopCampaignRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def campaigns_are_unique(self) -> Self:
        found = [item.campaign_id for item in self.campaigns]
        if len(found) != len(set(found)):
            raise ValueError("whop campaigns must be unique")
        _reject_leaks(self.model_dump_json(), label="whop snapshot")
        return self


class WhopImportAttempt(Versioned):
    """One accepted snapshot. A later export gets a new id."""

    import_id: EntityId
    project_id: EntityId
    snapshot_sha256: str = Field(pattern=_SHA)
    policy_fingerprint: str = Field(pattern=_SHA)
    operator_id: EntityId
    campaigns: list[WhopCampaignRecord]
    selectable_source_ids: list[EntityId]
    status: Literal["ready", "blocked"]
    reason_code: str = Field(min_length=1, max_length=80)
    created_at: AwareDatetime
    whop_live: Literal["not_configured"] = "not_configured"
    publishing: Literal["deferred"] = "deferred"

    @field_validator("reason_code")
    @classmethod
    def reason_is_plain(cls, value: str) -> str:
        return _plain(value, label="whop import")

    @model_validator(mode="after")
    def body_is_public(self) -> Self:
        _reject_leaks(self.model_dump_json(), label="whop import")
        return self
