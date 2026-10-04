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
