"""Openverse discovery and independent rights-evidence contracts."""

from __future__ import annotations

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.editorial_knowledge import _relative
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"


class OpenverseSearchRequest(Versioned):
    media_type: Literal["image", "audio"]
    query: str = Field(min_length=1, max_length=200)
    page: int = Field(default=1, ge=1, le=500)
    page_size: int = Field(default=10, ge=1, le=20)
    license_filter: list[str] = Field(default_factory=list, max_length=8)
    category: str | None = Field(default=None, max_length=80)
    length: Literal["shortest", "short", "medium", "long"] | None = None

    @field_validator("query", "category")
    @classmethod
    def search_text_is_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or any(ord(char) < 32 for char in cleaned):
            raise ValueError("Openverse search text must be plain and non-empty")
        return cleaned


class OpenverseMediaRecord(Versioned):
    provider: Literal["openverse"] = "openverse"
    media_id: EntityId
    media_type: Literal["image", "audio"]
    title: str = Field(min_length=1, max_length=300)
    creator: str | None = Field(default=None, max_length=200)
    creator_url: str | None = None
    source_name: str | None = Field(default=None, max_length=120)
    landing_url: str
    direct_download_url: str | None = None
    license_code: str | None = Field(default=None, max_length=80)
    license_version: str | None = Field(default=None, max_length=40)
    license_url: str | None = None
    attribution: str | None = Field(default=None, max_length=1000)
    duration_us: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    file_type: str | None = Field(default=None, max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=64)
    source_response_sha256: str = Field(pattern=_SHA)
    discovered_at: AwareDatetime
    rights_status: Literal["unverified", "eligible_pending_verification", "blocked"] = "unverified"
    policy_reason: str | None = Field(default=None, max_length=500)

    @field_validator("landing_url", "direct_download_url", "creator_url", "license_url")
    @classmethod
    def urls_are_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Openverse URLs must be HTTPS without credentials or fragments")
        return value

    @model_validator(mode="after")
    def audio_duration_is_known(self) -> Self:
        if self.media_type == "audio" and self.duration_us is None:
            raise ValueError("Openverse audio records require duration_us")
        return self


class OpenverseSearchResponse(Versioned):
    request: OpenverseSearchRequest
    result_count: int = Field(ge=0)
    page_count: int = Field(ge=0)
    page: int = Field(ge=1)
    results: list[OpenverseMediaRecord] = Field(max_length=20)
    response_sha256: str = Field(pattern=_SHA)
    warnings: list[str] = Field(default_factory=list, max_length=16)


class OpenverseLicenseEvidence(Versioned):
    media_id: EntityId
    landing_url: str
    license_code: str
    license_url: str
    attribution: str | None = Field(default=None, max_length=1000)
    captured_response_sha256: str = Field(pattern=_SHA)
    verification_method: Literal["landing_page", "operator_statement", "source_provider"]
    verification_status: Literal["verified", "insufficient_evidence", "blocked"]
    checked_at: AwareDatetime
    captured_evidence_path: str | None = None
    captured_evidence_sha256: str | None = Field(default=None, pattern=_SHA)

    @field_validator("captured_evidence_path")
    @classmethod
    def evidence_path(cls, value: str | None) -> str | None:
        return _relative(value, label="license capture") if value is not None else value

    @field_validator("landing_url", "license_url")
    @classmethod
    def evidence_urls_are_https(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("license evidence URLs must be HTTPS without credentials or fragments")
        return value


class OpenverseSelection(Versioned):
    selection_id: EntityId
    media: OpenverseMediaRecord
    selected_for: Literal["image", "audio"]
    policy_status: Literal["pending", "allowed", "blocked"]
    policy_reason: str = Field(min_length=1, max_length=500)
    license_evidence: OpenverseLicenseEvidence | None = None
    policy_fingerprint: str = Field(pattern=_SHA)
    campaign_id: EntityId | None = None
    intended_role: Literal["image", "sfx", "ambience"] | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def selected_type_matches(self) -> Self:
        if self.media.media_type != self.selected_for:
            raise ValueError("Openverse selection media type does not match selected_for")
        if self.policy_status == "allowed" and self.license_evidence is None:
            raise ValueError("allowed Openverse selection requires license evidence")
        return self


class OpenverseAcquisitionManifest(Versioned):
    """One promoted Openverse byte acquisition under the local work root."""

    acquisition_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    campaign_id: EntityId
    selection_id: EntityId
    media_id: EntityId
    media_type: Literal["image", "audio"]
    relative_path: str = Field(pattern=r"^assets/openverse/acquisitions/[A-Za-z0-9._:-]+/media$")
    file_sha256: str = Field(pattern=_SHA)
    size_bytes: int = Field(gt=0)
    landing_url: str
    license_url: str
    attribution: str | None = Field(default=None, max_length=1000)
    policy_fingerprint: str = Field(pattern=_SHA)
    selection_response_sha256: str = Field(pattern=_SHA)
    selection_sha256: str = Field(pattern=_SHA)
    evidence_sha256: str = Field(pattern=_SHA)
    asset_id: EntityId
    license_record_id: EntityId
    manifest_sha256: str = Field(pattern=_SHA)
    provenance: ArtifactProvenance
    status: Literal["verified"] = "verified"
    acquired_at: AwareDatetime

    @field_validator("landing_url", "license_url")
    @classmethod
    def acquisition_urls_are_https(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("acquisition URLs must be HTTPS without credentials or fragments")
        return value
