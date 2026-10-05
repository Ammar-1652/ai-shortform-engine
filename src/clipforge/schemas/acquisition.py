"""Acquisition requests and results. Paths are relative to the work root."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.campaign import _plain, _relative
from clipforge.schemas.common import EntityId, Versioned

_SHA = r"^[0-9a-f]{64}$"
AcquisitionStatus = Literal["succeeded", "failed", "blocked", "cancelled", "partial"]
CacheStatus = Literal["hit", "miss"]


class MediaConstraints(Versioned):
    """What an acquired file must satisfy. Empty codec lists mean any decodable codec."""

    require_video: bool = True
    require_audio: bool = True
    allowed_video_codecs: list[str] = Field(default_factory=lambda: ["h264"])
    allowed_audio_codecs: list[str] = Field(default_factory=lambda: ["aac"])
    min_width: int = Field(default=2, ge=1)
    min_height: int = Field(default=2, ge=1)
    max_width: int = Field(default=7680, ge=1)
    max_height: int = Field(default=4320, ge=1)
    min_duration_us: int = Field(default=1, ge=0)
    max_duration_us: int = Field(default=6 * 60 * 60 * 1_000_000, ge=1)
    frame_rate_numerator: int | None = Field(default=None, gt=0)
    frame_rate_denominator: int | None = Field(default=None, gt=0)
    sample_rate: int | None = Field(default=None, gt=0)

    @field_validator("allowed_video_codecs", "allowed_audio_codecs")
    @classmethod
    def codecs_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(item, label="codec") for item in values]


class ProbeFacts(Versioned):
    """ffprobe measurements with no filesystem path."""

    duration_us: int = Field(ge=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    video_codec: str | None = None
    audio_codec: str | None = None
    frame_rate: str | None = Field(default=None, pattern=r"^[0-9]+/[0-9]+$")
    sample_rate: int | None = Field(default=None, ge=1)
    format_name: str | None = None

    @field_validator("video_codec", "audio_codec", "format_name")
    @classmethod
    def names_are_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="probe fact")


class CampaignAcquisitionRequest(Versioned):
    """One source the operator asked to acquire. It does not copy the file."""

    campaign_id: EntityId
    selection_id: EntityId
    project_id: EntityId
    source_id: EntityId
    display_name: str = Field(min_length=1, max_length=300)
    origin: str = Field(min_length=1, max_length=40)
    expected_sha256: str | None = Field(default=None, pattern=_SHA)
    expected_size_bytes: int | None = Field(default=None, ge=0)
    max_bytes: int = Field(gt=0)
    media_constraints: MediaConstraints
    policy_fingerprint: str = Field(pattern=_SHA)
    selection_fingerprint: str = Field(pattern=_SHA)
    catalogue_fingerprint: str = Field(pattern=_SHA)
    operator_id: EntityId
    created_at: AwareDatetime

    @field_validator("display_name", "origin")
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="acquisition request")


class CampaignAcquisitionResult(Versioned):
    """The outcome for one source. A failure does not remove another source."""

    acquisition_id: EntityId
    campaign_id: EntityId
    selection_id: EntityId
    project_id: EntityId
    source_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    byte_size: int = Field(ge=0)
    probe: ProbeFacts | None = None
    relative_path: str | None = None
    status: AcquisitionStatus
    cache_status: CacheStatus = "miss"
    job_id: EntityId | None = None
    source_fingerprint: str = Field(pattern=_SHA)
    policy_fingerprint: str = Field(pattern=_SHA)
    selection_fingerprint: str = Field(pattern=_SHA)
    failure_code: str | None = None
    created_at: AwareDatetime
    completed_at: AwareDatetime | None = None

    @field_validator("failure_code")
    @classmethod
    def failure_is_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="failure code")

    @field_validator("relative_path")
    @classmethod
    def path_is_relative(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _relative(value)

    @model_validator(mode="after")
    def success_has_proof(self) -> Self:
        if self.status == "succeeded" and (
            self.probe is None or self.relative_path is None or self.job_id is None
        ):
            raise ValueError("a succeeded acquisition needs probe facts, a relative path, and a job")
        if self.status != "succeeded" and not self.failure_code:
            raise ValueError("an unsuccessful acquisition needs a failure code")
        text = self.model_dump_json().lower()
        if any(token in text for token in ("/home/", "/tmp/", "/users/", "file://", "bearer ", "token=")):
            raise ValueError("acquisition result contains a path or a secret")
        return self


class CampaignSourceBinding(Versioned):
    """One source as the operator run handed it to the production runner."""

    source_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    status: str = Field(min_length=1, max_length=40)
    cache_status: str = Field(min_length=1, max_length=40)
    reason_code: str = Field(min_length=1, max_length=80)
    delivery_id: str | None = None
    acquisition_id: EntityId | None = None

    @field_validator("status", "cache_status", "reason_code", "delivery_id")
    @classmethod
    def binding_text_is_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="run binding")


class CampaignOperatorBinding(Versioned):
    """Links one production run to the selection and acquisitions that authorized it."""

    campaign_run_id: EntityId
    campaign_id: EntityId
    selection_id: EntityId
    selection_sha256: str = Field(pattern=_SHA)
    selection_fingerprint: str = Field(pattern=_SHA)
    policy_fingerprint: str = Field(pattern=_SHA)
    catalogue_fingerprint: str = Field(pattern=_SHA)
    language: str = Field(min_length=2, max_length=16)
    narration_enabled: bool
    sources: list[CampaignSourceBinding] = Field(min_length=1)
    publishing: Literal["deferred"] = "deferred"

    @field_validator("language")
    @classmethod
    def language_is_plain(cls, value: str) -> str:
        return _plain(value, label="binding language")


class CampaignAcquisitionAttempt(Versioned):
    """One acquisition attempt for a selection. Older attempts stay on disk."""

    acquisition_id: EntityId
    campaign_id: EntityId
    selection_id: EntityId
    project_id: EntityId
    selection_sha256: str = Field(pattern=_SHA)
    selection_fingerprint: str = Field(pattern=_SHA)
    policy_fingerprint: str = Field(pattern=_SHA)
    catalogue_fingerprint: str = Field(pattern=_SHA)
    operator_id: EntityId
    created_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    status: AcquisitionStatus
    reason_code: str = Field(min_length=1, max_length=80)
    requests: list[CampaignAcquisitionRequest]
    results: list[CampaignAcquisitionResult]
    publishing: Literal["deferred"] = "deferred"

    @field_validator("reason_code")
    @classmethod
    def reason_is_plain(cls, value: str) -> str:
        return _plain(value, label="acquisition attempt")

    @model_validator(mode="after")
    def sources_are_unique(self) -> Self:
        found = [item.source_id for item in self.results]
        if len(found) != len(set(found)):
            raise ValueError("acquisition results must be unique per source")
        text = self.model_dump_json().lower()
        if any(token in text for token in ("/home/", "/tmp/", "/users/", "file://", "bearer ", "token=")):
            raise ValueError("acquisition attempt contains a path or a secret")
        return self
