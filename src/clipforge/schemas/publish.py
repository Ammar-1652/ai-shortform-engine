"""Local delivery contracts. A package is not an external publish."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.common import EntityId, Versioned

_SHA = r"^[0-9a-f]{64}$"
DeliveryStatus = Literal["succeeded", "cache_hit", "failed", "blocked", "cancelled"]
CaptionMode = Literal["authoritative", "embedded_or_unavailable"]
Readiness = Literal["passed", "failed", "blocked", "not_run", "unavailable"]
_FORBIDDEN = (
    "/tmp/",
    "/home/",
    "/users/",
    "\\",
    "://",
    "bearer ",
    "password=",
    "viewer_id",
    "token=",
    "file:",
)


def _public(value: str) -> bool:
    lowered = value.lower()
    if any(ord(character) < 32 for character in value):
        return False
    return not any(token in lowered for token in _FORBIDDEN)


def _relative(value: str) -> str:
    if not value or value.startswith(("/", "\\")) or "\\" in value:
        raise ValueError("delivery path must be work-root-relative")
    lowered = value.lower()
    if "://" in lowered or lowered.startswith("file:"):
        raise ValueError("delivery path must be work-root-relative")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("delivery path must be work-root-relative")
    if not _public(value):
        raise ValueError("delivery path contains a forbidden token")
    return value


class PublishProfile(Versioned):
    """Local package settings. This profile does not name a platform."""

    profile_id: Literal["local-delivery-v1"] = "local-delivery-v1"
    destination: Literal["local"] = "local"
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    fps_numerator: Literal[30] = 30
    fps_denominator: Literal[1] = 1
    video_codec: Literal["h264"] = "h264"
    audio_codec: Literal["aac"] = "aac"
    output_use: Literal["commercial"] = "commercial"
    audio_loudness_lufs: float = -16
    audio_true_peak_dbfs: float = -1.5
    audio_lra_lu: float = 11
    audio_mix_version: Literal["advanced-audio-mix-v1"] = "advanced-audio-mix-v1"

    def fingerprint(self) -> str:
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PublishFile(Versioned):
    """One file inside a delivery package. The path is relative to the work root."""

    relative_path: str = Field(min_length=1, max_length=240)
    sha256: str = Field(pattern=_SHA)
    size_bytes: int = Field(ge=1)
    role: Literal["video", "metadata", "captions_srt", "captions_vtt", "narration", "checksums", "manifest"]

    @field_validator("relative_path")
    @classmethod
    def path_is_relative(cls, value: str) -> str:
        return _relative(value)


class PublishPackageDocument(Versioned):
    """The portable manifest for one local delivery. It stores hashes, not absolute paths."""

    delivery_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    candidate_id: EntityId
    candidate_rank: int = Field(ge=1)
    candidate_set_id: EntityId
    candidate_set_sha256: str = Field(pattern=_SHA)
    advanced_set_id: EntityId
    advanced_set_sha256: str = Field(pattern=_SHA)
    advanced_artifact_id: EntityId
    advanced_artifact_sha256: str = Field(pattern=_SHA)
    advanced_artifact_size_bytes: int = Field(ge=1)
    advanced_plan_id: EntityId
    advanced_plan_sha256: str = Field(pattern=_SHA)
    alignment_id: EntityId | None = None
    alignment_sha256: str | None = Field(default=None, pattern=_SHA)
    qa_set_id: EntityId
    qa_set_sha256: str = Field(pattern=_SHA)
    approval_review_id: EntityId
    profile_id: Literal["local-delivery-v1"] = "local-delivery-v1"
    profile_fingerprint: str = Field(pattern=_SHA)
    destination: Literal["local"] = "local"
    reframing_strategy: str = Field(default="contain", min_length=1, max_length=40)
    audio_loudness_lufs: float = -16
    audio_true_peak_dbfs: float = -1.5
    audio_lra_lu: float = 11
    audio_mix_version: Literal["advanced-audio-mix-v1"] = "advanced-audio-mix-v1"
    caption_mode: CaptionMode
    cache_fingerprint: str = Field(pattern=_SHA)
    delivery_status: Literal["succeeded"] = "succeeded"
    files: list[PublishFile] = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def manifest_is_public(self) -> Self:
        text = self.model_dump_json()
        if not _public(text):
            raise ValueError("delivery manifest contains a path, URL, or secret-like token")
        roles = [item.role for item in self.files]
        if roles.count("video") != 1 or roles.count("metadata") != 1:
            raise ValueError("a delivery package needs one video and one metadata file")
        if len({item.relative_path for item in self.files}) != len(self.files):
            raise ValueError("delivery file paths must be unique")
        if (self.alignment_id is None) != (self.alignment_sha256 is None):
            raise ValueError("alignment id and hash must both be present or both be absent")
        return self


class PublishExportInput(Versioned):
    """What an export would bind. Planning with this record does not copy media."""

    project_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId
    destination: Literal["local"] = "local"
    include_narration: bool = False
    narration_artifact_id: EntityId | None = None
    profile_fingerprint: str = Field(pattern=_SHA)
    force: bool = False

    @model_validator(mode="after")
    def narration_is_explicit(self) -> Self:
        if self.include_narration and self.narration_artifact_id is None:
            raise ValueError("narration export requires a narration artifact id")
        if not self.include_narration and self.narration_artifact_id is not None:
            raise ValueError("narration artifact id is set but narration was not requested")
        return self


class PublishCacheRecord(Versioned):
    """Current delivery sidecar. It stores hashes and ids, not filesystem paths."""

    project_id: EntityId
    source_asset_id: EntityId
    delivery_id: EntityId
    job_id: EntityId
    artifact_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    candidate_id: EntityId
    candidate_set_id: EntityId
    candidate_set_sha256: str = Field(pattern=_SHA)
    advanced_set_id: EntityId
    advanced_set_sha256: str = Field(pattern=_SHA)
    advanced_artifact_sha256: str = Field(pattern=_SHA)
    advanced_artifact_size_bytes: int = Field(ge=1)
    video_sha256: str = Field(pattern=_SHA)
    video_size_bytes: int = Field(ge=1)
    plan_sha256: str = Field(pattern=_SHA)
    alignment_sha256: str | None = Field(default=None, pattern=_SHA)
    qa_set_id: EntityId
    qa_set_sha256: str = Field(pattern=_SHA)
    approval_review_id: EntityId
    profile_fingerprint: str = Field(pattern=_SHA)
    destination: Literal["local"] = "local"
    cache_fingerprint: str = Field(pattern=_SHA)
    manifest_sha256: str = Field(pattern=_SHA)
    manifest_size_bytes: int = Field(ge=1)
    checksum_sha256: str = Field(pattern=_SHA)
    checksum_size_bytes: int = Field(ge=1)
    files: list[PublishFile] = Field(min_length=1)
    created_at: AwareDatetime
    delivery_status: Literal["succeeded"] = "succeeded"

    @model_validator(mode="after")
    def sidecar_is_public(self) -> Self:
        if not _public(self.model_dump_json()):
            raise ValueError("delivery sidecar contains a path, URL, or secret-like token")
        return self


_SECRET = ("bearer ", "password=", "token=", "api_key", "authorization:", "cookie=", "secret=")
_MARKUP = ("<", ">", "javascript:", "onerror=", "onload=")
PublishState = Literal[
    "planned",
    "dry_run_passed",
    "queued",
    "uploading",
    "published",
    "failed",
    "cancelled",
    "unknown",
]


def _plain(value: str, *, label: str) -> str:
    stripped = value.strip()
    if stripped != value or not stripped:
        raise ValueError(f"{label} must not be blank or padded")
    lowered = stripped.lower()
    if any(token in lowered for token in _SECRET) or any(token in lowered for token in _MARKUP):
        raise ValueError(f"{label} contains markup or a secret-like token")
    if "\\" in stripped or ".." in stripped.split("/") or stripped.startswith("/") or "://" in lowered:
        raise ValueError(f"{label} contains a path or URL")
    return stripped


class PublishTarget(Versioned):
    """Where a verified local package would be offered. This stores no credentials."""

    platform: str = Field(min_length=1, max_length=40)
    account_label: str = Field(min_length=1, max_length=80)
    destination_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    campaign_id: EntityId
    privacy: Literal["public", "unlisted", "private"] = "public"
    scheduled_at: AwareDatetime | None = None
    delivery_id: EntityId
    manifest_sha256: str = Field(pattern=_SHA)

    @field_validator("platform", "account_label", "destination_id", "title", "description")
    @classmethod
    def text_is_plain(cls, value: str) -> str:
        return _plain(value, label="publish target")

    @field_validator("tags")
    @classmethod
    def tags_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(item, label="tag") for item in values]

    @model_validator(mode="after")
    def destination_is_local(self) -> Self:
        if not self.destination_id.replace(".", "").replace("_", "").replace("-", "").isalnum():
            raise ValueError("destination id is malformed")
        return self


class PublishRequest(Versioned):
    """One request bound to a verified local delivery. Secrets are not fields."""

    request_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    candidate_id: EntityId
    delivery_id: EntityId
    manifest_sha256: str = Field(pattern=_SHA)
    advanced_artifact_sha256: str = Field(pattern=_SHA)
    qa_set_id: EntityId
    qa_set_sha256: str = Field(pattern=_SHA)
    approval_review_id: EntityId
    campaign_profile_id: EntityId
    idempotency_key: EntityId
    created_at: AwareDatetime
    target: PublishTarget

    @model_validator(mode="after")
    def target_matches_delivery(self) -> Self:
        if self.target.delivery_id != self.delivery_id or self.target.manifest_sha256 != self.manifest_sha256:
            raise ValueError("publish target does not match the local delivery")
        if self.target.campaign_id != self.campaign_profile_id:
            raise ValueError("publish target campaign does not match the request")
        return self


class PublishReceipt(Versioned):
    """Safe provenance returned by a provider. Credentials are rejected."""

    platform: str = Field(min_length=1, max_length=40)
    remote_item_id: str | None = Field(default=None, max_length=80)
    public_url: str | None = Field(default=None, max_length=300)
    manifest_sha256: str = Field(pattern=_SHA)
    submitted_at: AwareDatetime
    provider_version: str = Field(min_length=1, max_length=40)
    status: Literal["published"]

    @field_validator("platform", "remote_item_id", "provider_version")
    @classmethod
    def receipt_text_is_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="publish receipt")

    @field_validator("public_url")
    @classmethod
    def url_is_public(cls, value: str | None) -> str | None:
        if value is None:
            return None
        lowered = value.lower()
        if any(token in lowered for token in _SECRET) or any(token in lowered for token in _MARKUP):
            raise ValueError("publish receipt contains a secret-like token")
        if not lowered.startswith("https://"):
            raise ValueError("publish receipt URL must be https")
        if "\\" in value or "/tmp/" in lowered or "/home/" in lowered:
            raise ValueError("publish receipt URL is not public")
        return value


class PublishAttempt(Versioned):
    """One local record of a dry run or upload attempt."""

    attempt_id: EntityId
    request: PublishRequest
    state: PublishState
    provider_version: str = Field(min_length=1, max_length=40)
    error_category: str = Field(default="none", max_length=40)
    receipt: PublishReceipt | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def published_has_a_receipt(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("publish attempt was updated before it was created")
        if self.state == "published":
            if self.receipt is None or self.receipt.manifest_sha256 != self.request.manifest_sha256:
                raise ValueError("a published attempt requires a verified receipt")
        elif self.receipt is not None:
            raise ValueError("only a published attempt stores a receipt")
        _plain(self.provider_version, label="provider")
        _plain(self.error_category, label="error")
        return self


class PublishReadiness(Versioned):
    """Local delivery and external upload are separate."""

    project_id: EntityId
    source_asset_id: EntityId
    technical: Readiness
    editorial: Readiness
    rights: Readiness
    qa: Readiness
    local_delivery: Readiness
    platform_adapter: Literal["passed", "unavailable"]
    platform_dry_run: Readiness
    external_upload: Literal["not_configured", "not_run", "passed", "failed", "blocked", "unavailable"]
    real_source_verified: Readiness
    voicestudio: Readiness
    overall: Literal[
        "passed",
        "failed",
        "blocked",
        "not_run",
        "unavailable",
        "blocked_for_external_publish",
    ]
    reason: str = Field(min_length=1, max_length=160)

    @field_validator("reason")
    @classmethod
    def reason_is_plain(cls, value: str) -> str:
        return _plain(value, label="readiness")


class PublishReadinessReport(Versioned):
    """Local delivery readiness. Platform publishing stays not implemented."""

    project_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId | None = None
    delivery_id: EntityId | None = None
    technical: Readiness
    editorial: Readiness
    rights: Readiness
    qa: Readiness
    local_delivery: Readiness
    platform_publishing: Literal["not_implemented"] = "not_implemented"
    voicestudio: Readiness
    real_source_verified: Readiness
    real_source_reason: str = Field(min_length=1, max_length=120)
    overall: Readiness
    failure_category: str = Field(default="none", max_length=40)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def report_is_public(self) -> Self:
        texts = [self.real_source_reason, self.failure_category, *self.limitations]
        if any(not _public(item) for item in texts):
            raise ValueError("delivery readiness contains a forbidden token")
        if self.platform_publishing != "not_implemented":
            raise ValueError("platform publishing is not implemented")
        return self
