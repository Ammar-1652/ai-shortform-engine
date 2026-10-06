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
    source_url: str | None = Field(default=None, max_length=300)
    media_download_url: str | None = Field(default=None, max_length=300)
    content_sha256: str | None = Field(default=None, pattern=_SHA)
    declared_content_sha256: str | None = Field(default=None, pattern=_SHA)
    acquired_file_sha256: str | None = Field(default=None, pattern=_SHA)
    acquired_file_size: int | None = Field(default=None, ge=0)
    acquired_ffprobe_fingerprint: str | None = Field(default=None, pattern=_SHA)
    size_bytes: int | None = Field(default=None, ge=0)
    duration_us: int | None = Field(default=None, ge=0)
    media_format: str | None = Field(default=None, max_length=40)
    availability: str = Field(default="unknown", min_length=1, max_length=40)
    acquisition_reference: str | None = Field(default=None, max_length=200)
    acquisition_status: str = Field(default="unknown", min_length=1, max_length=40)
    direct_download: str = Field(default="unknown", min_length=1, max_length=40)

    @field_validator(
        "display_name",
        "rights_state",
        "policy_state",
        "media_format",
        "availability",
        "acquisition_reference",
        "acquisition_status",
        "direct_download",
    )
    @classmethod
    def labels_are_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="whop source")

    @field_validator("source_url", "media_download_url")
    @classmethod
    def source_url_is_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="whop source url", allow_https=True)

    @model_validator(mode="after")
    def declared_hash_is_not_acquired(self) -> Self:
        if self.declared_content_sha256 is None and self.content_sha256 is not None:
            self.declared_content_sha256 = self.content_sha256
        return self


class WhopCampaignRecord(Versioned):
    """One campaign inside a snapshot. Policy text is not rights evidence."""

    campaign_id: EntityId
    title: str = Field(min_length=1, max_length=200)
    policy_state: str = Field(min_length=1, max_length=80)
    sources: list[WhopCampaignSourceRecord] = Field(min_length=1)
    campaign_url: str | None = Field(default=None, max_length=300)
    status: str = Field(default="unknown", min_length=1, max_length=40)
    category: str | None = Field(default=None, max_length=80)
    payout_text: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, max_length=16)
    campaign_type: str | None = Field(default=None, max_length=40)
    business_id: str | None = Field(default=None, max_length=80)
    platforms: list[str] = Field(default_factory=list)
    reward_rate_text: str | None = Field(default=None, max_length=80)
    currency: str | None = Field(default=None, max_length=16)
    budget_text: str | None = Field(default=None, max_length=80)
    minimum_payout_text: str | None = Field(default=None, max_length=80)
    maximum_payout_text: str | None = Field(default=None, max_length=80)
    flat_fee_text: str | None = Field(default=None, max_length=80)
    footage_references: list[str] = Field(default_factory=list)
    requirements_text: str | None = Field(default=None, max_length=500)
    prohibited_text: str | None = Field(default=None, max_length=500)
    required_messaging: str | None = Field(default=None, max_length=300)
    required_duration_text: str | None = Field(default=None, max_length=80)
    required_format: str | None = Field(default=None, max_length=40)
    policy_evidence: str | None = Field(default=None, max_length=200)
    provider_updated_at: str | None = Field(default=None, max_length=40)

    @field_validator(
        "title",
        "policy_state",
        "status",
        "category",
        "payout_text",
        "language",
        "campaign_type",
        "business_id",
        "reward_rate_text",
        "currency",
        "budget_text",
        "minimum_payout_text",
        "maximum_payout_text",
        "flat_fee_text",
        "requirements_text",
        "prohibited_text",
        "required_messaging",
        "required_duration_text",
        "required_format",
        "policy_evidence",
        "provider_updated_at",
    )
    @classmethod
    def campaign_text_is_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="whop campaign")

    @field_validator("platforms", "footage_references")
    @classmethod
    def lists_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(item, label="whop campaign", allow_https=True) for item in values]

    @field_validator("campaign_url")
    @classmethod
    def campaign_url_is_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="whop campaign url", allow_https=True)

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
    intake_label: Literal["local_snapshot", "authenticated_operator_snapshot"] = "local_snapshot"
    credentials_stored: Literal["not_stored"] = "not_stored"
    live_transport: Literal["not_claimed"] = "not_claimed"

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
