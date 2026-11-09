"""Envato discovery records. A search result is not a downloaded file."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field, field_validator

from clipforge.schemas.campaign import PolicyOutcome, _plain, _relative
from clipforge.schemas.common import EntityId, Versioned

_SHA = r"^[0-9a-f]{64}$"
AssetType = Literal["video", "audio", "image", "graphic", "template", "font", "unknown"]
CommercialUse = Literal["unknown", "allowed", "prohibited"]
SelectionStatus = Literal["candidate", "selected", "rejected"]


class AssetSearchHit(Versioned):
    """Normalized provider metadata. Missing fields stay null."""

    request_id: EntityId
    provider: Literal["envato_mcp", "fake", "dry_run"]
    item_id: str | None = Field(default=None, max_length=80)
    title: str | None = Field(default=None, max_length=300)
    item_url: str | None = Field(default=None, max_length=300)
    asset_type: AssetType = "unknown"
    category: str | None = Field(default=None, max_length=80)
    format: list[str] = Field(default_factory=list)
    compatible_software: list[str] = Field(default_factory=list)
    genre: str | None = Field(default=None, max_length=80)
    style: str | None = Field(default=None, max_length=80)
    duration_seconds: float | None = Field(default=None, ge=0)
    dimensions: str | None = Field(default=None, max_length=40)
    frame_rate: str | None = Field(default=None, max_length=20)
    metadata: dict[str, str] = Field(default_factory=dict)
    license_url: str | None = Field(default=None, max_length=300)
    license_evidence: str | None = Field(default=None, max_length=200)
    commercial_use: CommercialUse = "unknown"
    campaign_policy_decision: PolicyOutcome | Literal["pending"] = "pending"
    selection_status: SelectionStatus = "candidate"
    rejection_reason: str | None = Field(default=None, max_length=120)
    download_status: Literal["manual_download_required", "acquired", "rejected"] = "manual_download_required"
    direct_download_url: str | None = None
    local_path: str | None = None
    sha256: str | None = Field(default=None, pattern=_SHA)
    operator_confirmation: bool = False
    created_at: AwareDatetime

    @field_validator(
        "item_id",
        "title",
        "category",
        "genre",
        "style",
        "dimensions",
        "frame_rate",
        "license_evidence",
        "rejection_reason",
    )
    @classmethod
    def optional_text_is_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="asset field")

    @field_validator("item_url", "license_url", "direct_download_url")
    @classmethod
    def optional_url_is_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="asset url", allow_https=True)

    @field_validator("format", "compatible_software")
    @classmethod
    def lists_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(item, label="asset list") for item in values]

    @field_validator("local_path")
    @classmethod
    def local_path_is_relative(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _relative(value)

    @field_validator("metadata")
    @classmethod
    def metadata_is_plain(cls, values: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, value in values.items():
            cleaned[_plain(key, label="metadata key")] = _plain(value, label="metadata")
        return cleaned


class AssetDownloadRequest(Versioned):
    """Instructions for a person to download one item. Clipforge does not fetch it."""

    request_id: EntityId
    campaign_id: EntityId
    query: str = Field(min_length=1, max_length=200)
    filters: dict[str, str] = Field(default_factory=dict)
    hit: AssetSearchHit
    requested_format: str | None = Field(default=None, max_length=40)
    operator_confirmation_required: bool = True

    @field_validator("query", "requested_format")
    @classmethod
    def request_text_is_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="asset request")

    @field_validator("filters")
    @classmethod
    def filters_are_plain(cls, values: dict[str, str]) -> dict[str, str]:
        return {_plain(key, label="filter"): _plain(value, label="filter") for key, value in values.items()}
