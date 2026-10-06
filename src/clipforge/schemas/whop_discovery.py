"""Live Whop discovery records. Account secrets are not fields."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.campaign import _plain
from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.whop import WhopCampaignRecord, _reject_leaks

_SHA = r"^[0-9a-f]{64}$"
LiveStatus = Literal[
    "public_discovery",
    "authenticated_discovery",
    "not_configured",
    "provider_unavailable",
]
DiscoveryMode = Literal["snapshot", "browser_export", "live_connector", "not_configured"]


class WhopProviderCapability(Versioned):
    """What the connector may do. Mutating Whop operations stay disabled."""

    provider_id: str = Field(min_length=1, max_length=40)
    provider_version: str = Field(min_length=1, max_length=40)
    mode: DiscoveryMode
    live_status: LiveStatus
    public_fields: list[str] = Field(default_factory=list)
    account_fields: list[str] = Field(default_factory=list)
    mutating_operations: Literal["disabled"] = "disabled"
    credentials: Literal["not_stored"] = "not_stored"
    publishing: Literal["deferred"] = "deferred"
    live_smoke: Literal["not_executed"] = "not_executed"
    public_provider: Literal["not_configured", "available", "unavailable"] = "not_configured"
    authenticated_connector: Literal["not_configured", "available", "unavailable"] = "not_configured"

    @field_validator("provider_id", "provider_version")
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="whop provider")

    @field_validator("public_fields", "account_fields")
    @classmethod
    def fields_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(item, label="whop field") for item in values]

    @model_validator(mode="after")
    def body_is_public(self) -> Self:
        _reject_leaks(self.model_dump_json(), label="whop capability")
        return self


class WhopLiveDiscoveryRequest(Versioned):
    """A read-only discovery query. It does not carry an account secret."""

    request_id: EntityId
    query: str | None = Field(default=None, max_length=200)
    provider_id: str = Field(min_length=1, max_length=40)
    provider_version: str = Field(default="0", min_length=1, max_length=40)
    require_status: str | None = Field(default=None, max_length=40)
    allowed_categories: list[str] = Field(default_factory=list)
    prohibited_categories: list[str] = Field(default_factory=list)
    require_policy: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=16)
    require_rights: str | None = Field(default=None, max_length=40)
    max_size_bytes: int | None = Field(default=None, ge=0)
    min_duration_us: int | None = Field(default=None, ge=0)
    max_duration_us: int | None = Field(default=None, ge=0)
    media_format: str | None = Field(default=None, max_length=40)
    max_age_hours: int | None = Field(default=None, ge=0)
    permit_unknown_availability: bool = False
    require_acquisition_reference: bool = False
    created_at: AwareDatetime

    @field_validator(
        "query",
        "provider_id",
        "provider_version",
        "require_status",
        "require_policy",
        "language",
        "require_rights",
        "media_format",
    )
    @classmethod
    def labels_are_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="whop discovery request")

    @field_validator("allowed_categories", "prohibited_categories")
    @classmethod
    def categories_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(item, label="whop category") for item in values]

    @model_validator(mode="after")
    def body_is_public(self) -> Self:
        _reject_leaks(self.model_dump_json(), label="whop discovery request")
        return self


class WhopCampaignCatalogue(Versioned):
    """Normalized campaigns. Membership is not a rights clearance."""

    catalogue_id: EntityId
    provider_id: str = Field(min_length=1, max_length=40)
    provider_version: str = Field(min_length=1, max_length=40)
    live_status: LiveStatus
    campaigns: list[WhopCampaignRecord] = Field(default_factory=list)
    catalogue_fingerprint: str = Field(pattern=_SHA)
    missing_fields: list[str] = Field(default_factory=list)

    @field_validator("provider_id", "provider_version")
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="whop catalogue")

    @field_validator("missing_fields")
    @classmethod
    def missing_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(item, label="whop field") for item in values]

    @model_validator(mode="after")
    def campaigns_are_unique(self) -> Self:
        found = [item.campaign_id for item in self.campaigns]
        if len(found) != len(set(found)):
            raise ValueError("whop campaigns must be unique")
        _reject_leaks(self.model_dump_json(), label="whop catalogue")
        return self


class WhopSourceExclusion(Versioned):
    """One source rejected by the stored request."""

    source_id: EntityId
    reason_code: str = Field(min_length=1, max_length=80)

    @field_validator("reason_code")
    @classmethod
    def reason_is_plain(cls, value: str) -> str:
        return _plain(value, label="whop filter")


class WhopFilterDecision(Versioned):
    """Why one campaign was kept or excluded. The reason is a code, not a secret."""

    campaign_id: EntityId
    included: bool
    reason_code: str = Field(min_length=1, max_length=80)
    included_source_ids: list[EntityId] = Field(default_factory=list)
    excluded_sources: list[WhopSourceExclusion] = Field(default_factory=list)
    filter_fingerprint: str = Field(pattern=_SHA)

    @field_validator("reason_code")
    @classmethod
    def reason_is_plain(cls, value: str) -> str:
        return _plain(value, label="whop filter")

    @model_validator(mode="after")
    def inclusion_matches_sources(self) -> Self:
        if self.included and not self.included_source_ids:
            raise ValueError("an included whop campaign names no source")
        if not self.included and self.included_source_ids:
            raise ValueError("an excluded whop campaign names a source")
        if self.included_source_ids != sorted(set(self.included_source_ids)):
            raise ValueError("whop filter sources must be unique and sorted")
        return self


class WhopDiscoveryAttempt(Versioned):
    """One append-only discovery. A later response gets a new id."""

    discovery_id: EntityId
    project_id: EntityId
    operator_id: EntityId
    mode: DiscoveryMode
    provider_id: str = Field(min_length=1, max_length=40)
    provider_version: str = Field(min_length=1, max_length=40)
    live_status: LiveStatus
    evidence_origin: Literal["test_double", "public_connector", "authenticated_connector"]
    live_claim: Literal["not_claimed", "claimed"] = "not_claimed"
    request_sha256: str = Field(pattern=_SHA)
    filter_fingerprint: str = Field(pattern=_SHA)
    response_sha256: str = Field(pattern=_SHA)
    catalogue_fingerprint: str = Field(pattern=_SHA)
    policy_fingerprint: str = Field(pattern=_SHA)
    identity_sha256: str = Field(pattern=_SHA)
    tool_map_sha256: str = Field(default="0" * 64, pattern=_SHA)
    discovery_request: WhopLiveDiscoveryRequest
    tool_name: str | None = Field(default=None, max_length=80)
    import_id: EntityId | None = None
    campaign_ids: list[EntityId]
    decisions: list[WhopFilterDecision]
    status: Literal["ready", "blocked", "failed", "cancelled"]
    reason_code: str = Field(min_length=1, max_length=80)
    cache_status: Literal["hit", "miss"] = "miss"
    created_at: AwareDatetime
    publishing: Literal["deferred"] = "deferred"

    @field_validator("provider_id", "provider_version", "reason_code", "tool_name")
    @classmethod
    def labels_are_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="whop discovery")

    @model_validator(mode="after")
    def body_is_public(self) -> Self:
        if self.filter_fingerprint != self.request_sha256:
            raise ValueError("whop filter fingerprint does not match the request")
        if self.live_claim == "claimed" and (
            self.evidence_origin != "authenticated_connector" or self.live_status != "authenticated_discovery"
        ):
            raise ValueError("whop live claim is not allowed")
        _reject_leaks(self.model_dump_json(), label="whop discovery")
        return self


class WhopSelectionEvidence(Versioned):
    """The operator's choice of one imported campaign. It is not a license."""

    evidence_id: EntityId
    campaign_id: EntityId
    import_id: EntityId
    discovery_id: EntityId
    project_id: EntityId
    catalogue_fingerprint: str = Field(pattern=_SHA)
    policy_fingerprint: str = Field(pattern=_SHA)
    filter_fingerprint: str = Field(pattern=_SHA)
    source_ids: list[EntityId] = Field(min_length=1)
    source_hashes: list[str | None]
    language: str = Field(min_length=2, max_length=16)
    narration_request: Literal["not_requested", "requested"]
    operator_id: EntityId
    evidence_fingerprint: str = Field(pattern=_SHA)
    created_at: AwareDatetime
    publishing: Literal["deferred"] = "deferred"
    whop_live: Literal["not_configured"] = "not_configured"
    live_claim: Literal["not_claimed"] = "not_claimed"
    hash_basis: Literal["declared"] = "declared"

    @field_validator("language")
    @classmethod
    def language_is_plain(cls, value: str) -> str:
        return _plain(value, label="whop selection")

    @field_validator("source_hashes")
    @classmethod
    def hashes_are_sha256(cls, values: list[str | None]) -> list[str | None]:
        for value in values:
            if value is None:
                continue
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError("whop selection hash is not sha256")
        return values

    @model_validator(mode="after")
    def sources_match_hashes(self) -> Self:
        if len(self.source_ids) != len(self.source_hashes):
            raise ValueError("whop selection sources and hashes must match")
        if self.source_ids != sorted(set(self.source_ids)):
            raise ValueError("whop selection sources must be unique and sorted")
        _reject_leaks(self.model_dump_json(), label="whop selection")
        return self
