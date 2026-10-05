"""Manual Envato handoff. A catalogue URL is not a local media file."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.acquisition import ProbeFacts
from clipforge.schemas.campaign import _plain, _relative
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
MediaKind = Literal["video", "audio", "image", "graphic", "unknown"]
RightsWord = Literal["allowed", "unknown", "prohibited", "missing"]
AcquisitionWord = Literal["verified", "failed", "cancelled"]


def _reject_leaks(text: str, *, label: str) -> None:
    lowered = text.lower()
    if any(token in lowered for token in _LEAKS):
        raise ValueError(f"{label} contains a path or a secret")


class EnvatoAssetRequest(Versioned):
    """A request the operator downloads. Clipforge does not fetch the item."""

    request_id: EntityId
    provider: Literal["envato_mcp", "fake", "dry_run"]
    provider_version: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=200)
    supported_filters: dict[str, str] = Field(default_factory=dict)
    deferred_filters: dict[str, str] = Field(default_factory=dict)
    item_page_url: str | None = Field(default=None, max_length=300)
    item_id: str | None = Field(default=None, max_length=80)
    direct_download_url: str | None = Field(default=None, max_length=300)
    media_kind: MediaKind = "unknown"
    intended_use: str = Field(min_length=1, max_length=80)
    campaign_id: EntityId
    policy_fingerprint: str = Field(pattern=_SHA)
    requested_format: str | None = Field(default=None, max_length=40)
    requested_resolution: str | None = Field(default=None, max_length=40)
    requested_duration: str | None = Field(default=None, max_length=40)
    expected_codec: str | None = Field(default=None, max_length=40)
    expected_width: int | None = Field(default=None, ge=1)
    expected_height: int | None = Field(default=None, ge=1)
    expected_frame_rate: str | None = Field(default=None, pattern=r"^[0-9]+/[0-9]+$")
    download_status: Literal["manual_download_required"] = "manual_download_required"
    max_bytes: int = Field(default=200_000_000, gt=0)
    created_at: AwareDatetime

    @field_validator("provider_version", "query", "intended_use", "requested_format", "requested_resolution")
    @classmethod
    def labels_are_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="envato request")

    @field_validator("requested_duration", "expected_codec", "item_id")
    @classmethod
    def optional_labels_are_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="envato request")

    @field_validator("item_page_url", "direct_download_url")
    @classmethod
    def urls_are_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="envato url", allow_https=True)

    @field_validator("supported_filters", "deferred_filters")
    @classmethod
    def filters_are_plain(cls, values: dict[str, str]) -> dict[str, str]:
        return {_plain(key, label="filter"): _plain(value, label="filter") for key, value in values.items()}

    @model_validator(mode="after")
    def body_is_public(self) -> Self:
        _reject_leaks(self.model_dump_json(), label="envato request")
        return self


class EnvatoAssetRegistration(Versioned):
    """One manually supplied file after confinement, hash, probe, and rights checks."""

    asset_id: EntityId
    request_id: EntityId
    campaign_id: EntityId
    project_id: EntityId
    item_page_url: str | None = Field(default=None, max_length=300)
    item_id: str | None = Field(default=None, max_length=80)
    relative_path: str | None = None
    byte_size: int = Field(ge=0)
    sha256: str | None = Field(default=None, pattern=_SHA)
    probe: ProbeFacts | None = None
    license_evidence: str | None = None
    rights_status: RightsWord
    provider_version: str = Field(min_length=1, max_length=80)
    acquisition_status: AcquisitionWord
    producer_job_id: EntityId
    policy_fingerprint: str = Field(pattern=_SHA)
    media_kind: MediaKind
    download_status: Literal["manual_download_required"] = "manual_download_required"
    direct_download_url: str | None = Field(default=None, max_length=300)
    cache_status: Literal["hit", "miss"] = "miss"
    failure_code: str | None = None
    incoming_relative: str | None = None
    created_at: AwareDatetime

    @field_validator("provider_version", "item_id", "failure_code")
    @classmethod
    def labels_are_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="envato registration")

    @field_validator("item_page_url", "direct_download_url")
    @classmethod
    def urls_are_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="envato url", allow_https=True)

    @field_validator("relative_path", "license_evidence", "incoming_relative")
    @classmethod
    def paths_are_relative(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _relative(value)

    @model_validator(mode="after")
    def verified_is_complete(self) -> Self:
        if self.acquisition_status == "verified":
            if self.rights_status != "allowed":
                raise ValueError("a verified envato asset requires allowed rights")
            if self.sha256 is None or self.probe is None or self.relative_path is None:
                raise ValueError("a verified envato asset requires a hash, probe, and path")
            if not self.license_evidence:
                raise ValueError("a verified envato asset requires license evidence")
        _reject_leaks(self.model_dump_json(), label="envato registration")
        return self


class EnvatoAssetVerification(Versioned):
    """A read-only check. It does not rewrite the asset or the database."""

    asset_id: EntityId
    status: Literal["verified", "stale", "failed", "missing"]
    reason_code: str = Field(min_length=1, max_length=80)
    sha256: str | None = Field(default=None, pattern=_SHA)
    byte_size: int | None = Field(default=None, ge=0)
    probe: ProbeFacts | None = None
    rights_status: str = Field(min_length=1, max_length=80)
    renderable: bool
    failure_reason: str | None = None
    relative_path: str | None = None

    @field_validator("reason_code", "rights_status", "failure_reason")
    @classmethod
    def labels_are_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="envato verification")

    @field_validator("relative_path")
    @classmethod
    def path_is_relative(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _relative(value)

    @model_validator(mode="after")
    def body_is_public(self) -> Self:
        _reject_leaks(self.model_dump_json(), label="envato verification")
        return self


class EnvatoAssetCacheRecord(Versioned):
    """Why a registration was reused or written again."""

    cache_id: EntityId
    asset_id: EntityId
    request_id: EntityId
    content_sha256: str = Field(pattern=_SHA)
    byte_size: int = Field(ge=0)
    policy_fingerprint: str = Field(pattern=_SHA)
    status: Literal["hit", "miss"]
    created_at: AwareDatetime

    @model_validator(mode="after")
    def body_is_public(self) -> Self:
        _reject_leaks(self.model_dump_json(), label="envato cache")
        return self
