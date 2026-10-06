"""Full-source alignment and narration capability. A fake run is not a live claim."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

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
    "authorization:",
    "secret=",
    "<script",
    "javascript:",
    "viewer_id",
)
CapabilityStatus = Literal[
    "verified_live",
    "available_not_smoked",
    "not_configured",
    "unsupported_language",
    "alignment_not_claimed",
    "locale_not_smoked",
]
TimingQuality = Literal["forced", "approximate", "unavailable"]


def _reject_leaks(text: str, *, label: str) -> None:
    lowered = text.lower()
    if any(token in lowered for token in _LEAKS):
        raise ValueError(f"{label} contains a path or a secret")


def _unicode_text(value: str, *, label: str) -> str:
    if value.strip() != value or not value:
        raise ValueError(f"{label} must not be blank or padded")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} contains a control character")
    if "<" in value or ">" in value:
        raise ValueError(f"{label} contains markup")
    _reject_leaks(value, label=label)
    return value


class AlignmentRuntimeIdentity(Versioned):
    """The runtime that produced one alignment. Paths and credentials are absent."""

    provider_version: str = Field(min_length=1, max_length=40)
    runtime_version: str = Field(min_length=1, max_length=40)
    device: str = Field(min_length=1, max_length=40)
    sample_rate: int = Field(ge=8000, le=96000)

    @field_validator("provider_version", "runtime_version", "device")
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="alignment runtime")


class AlignmentProfile(Versioned):
    """Which aligner a language may use. Unverified is not a live claim."""

    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    provider_id: str = Field(min_length=1, max_length=40)
    model_id: str = Field(min_length=1, max_length=80)
    model_revision: str = Field(min_length=1, max_length=80)
    checkpoint_sha256: str = Field(pattern=_SHA)
    status: CapabilityStatus

    @field_validator("provider_id", "model_id", "model_revision")
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="alignment profile")


class MultilingualAlignedWord(Versioned):
    """One aligned word. The Unicode text is the transcript text."""

    word_id: EntityId
    text: str = Field(min_length=1, max_length=80)
    source_start_us: int = Field(ge=0)
    source_end_us: int = Field(ge=0)
    output_start_us: int = Field(ge=0)
    output_end_us: int = Field(ge=0)
    output_start_frame: int = Field(ge=0)
    output_end_frame_exclusive: int = Field(ge=0)
    source_asset_id: EntityId
    transcript_id: EntityId

    @field_validator("text")
    @classmethod
    def text_is_unicode(cls, value: str) -> str:
        return _unicode_text(value, label="aligned word")

    @model_validator(mode="after")
    def duration_is_positive(self) -> Self:
        if self.source_end_us <= self.source_start_us or self.output_end_us <= self.output_start_us:
            raise ValueError("aligned word duration must be positive")
        if self.output_end_frame_exclusive <= self.output_start_frame:
            raise ValueError("aligned word frames must be half-open")
        return self


class MultilingualAlignmentDocument(Versioned):
    """One full-source alignment. It does not replace selected-clip Hero alignment."""

    alignment_id: EntityId
    source_asset_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    transcript_id: EntityId
    transcript_sha256: str = Field(pattern=_SHA)
    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    language_tag: str = Field(min_length=2, max_length=16)
    provider_id: str = Field(min_length=1, max_length=40)
    provider_version: str = Field(min_length=1, max_length=40)
    model_id: str = Field(min_length=1, max_length=80)
    model_revision: str = Field(min_length=1, max_length=80)
    checkpoint_sha256: str = Field(pattern=_SHA)
    runtime_version: str = Field(min_length=1, max_length=40)
    device: str = Field(min_length=1, max_length=40)
    sample_rate: int = Field(ge=8000, le=96000)
    word_count: int = Field(ge=1)
    alignment_status: CapabilityStatus
    timing_quality: TimingQuality
    artifact_sha256: str = Field(pattern=_SHA)
    producer_job_id: EntityId
    project_id: EntityId
    relative_path: str
    language_capability_fingerprint: str = Field(pattern=_SHA)
    identity_sha256: str = Field(pattern=_SHA)
    words: list[MultilingualAlignedWord] = Field(min_length=1)
    cache_status: Literal["hit", "miss"] = "miss"

    @field_validator(
        "provider_id",
        "provider_version",
        "model_id",
        "model_revision",
        "runtime_version",
        "device",
    )
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="alignment document")

    @field_validator("relative_path")
    @classmethod
    def path_is_relative(cls, value: str) -> str:
        from clipforge.schemas.campaign import _relative

        return _relative(value)

    @model_validator(mode="after")
    def words_are_ordered(self) -> Self:
        if self.word_count != len(self.words):
            raise ValueError("word count does not match the aligned words")
        if self.alignment_status == "verified_live" and self.provider_id == "fake":
            raise ValueError("a fake alignment cannot be verified live")
        previous_source = -1
        previous_output = -1
        for word in self.words:
            if word.source_asset_id != self.source_asset_id or word.transcript_id != self.transcript_id:
                raise ValueError("aligned word provenance does not match the document")
            if word.source_start_us < previous_source or word.output_start_us < previous_output:
                raise ValueError("aligned words must be monotonic and must not overlap")
            previous_source = word.source_end_us
            previous_output = word.output_end_us
        _reject_leaks(self.model_dump_json(), label="alignment document")
        return self


class NarrationCapability(Versioned):
    """What narration this install may claim for one language."""

    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    provider_id: str = Field(min_length=1, max_length=40)
    status: CapabilityStatus
    engine_id: str | None = None
    model_id: str | None = None
    model_revision: str | None = None
    voice_id: str | None = None
    commercial_use: Literal["allowed", "prohibited", "unknown", "not_applicable"]
    reason_code: str = Field(min_length=1, max_length=80)

    @field_validator("provider_id", "engine_id", "model_id", "model_revision", "voice_id", "reason_code")
    @classmethod
    def labels_are_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="narration capability")


class MultilingualNarrationDocument(Versioned):
    """One narration result. It does not approve a candidate or a Hero."""

    narration_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    provider_id: str = Field(min_length=1, max_length=40)
    service_version: str = Field(min_length=1, max_length=40)
    engine_id: str = Field(min_length=1, max_length=40)
    model_id: str = Field(min_length=1, max_length=80)
    model_revision: str = Field(min_length=1, max_length=80)
    voice_id: str = Field(min_length=1, max_length=80)
    license_name: str = Field(min_length=1, max_length=80)
    commercial_use: Literal["allowed", "prohibited", "unknown"]
    script_sha256: str = Field(pattern=_SHA)
    audio_sha256: str = Field(pattern=_SHA)
    sample_rate: int = Field(ge=8000, le=96000)
    channels: int = Field(ge=1, le=2)
    duration_us: int = Field(gt=0)
    producer_job_id: EntityId
    status: CapabilityStatus
    relative_path: str
    identity_sha256: str = Field(pattern=_SHA)
    cache_status: Literal["hit", "miss"] = "miss"

    @field_validator(
        "provider_id",
        "service_version",
        "engine_id",
        "model_id",
        "model_revision",
        "voice_id",
        "license_name",
    )
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="narration document")

    @field_validator("relative_path")
    @classmethod
    def path_is_relative(cls, value: str) -> str:
        from clipforge.schemas.campaign import _relative

        return _relative(value)

    @model_validator(mode="after")
    def live_claim_is_real(self) -> Self:
        if self.status == "verified_live" and self.provider_id == "fake":
            raise ValueError("a fake narration cannot be verified live")
        if self.commercial_use == "allowed" and self.model_id.lower().startswith("k2-fsa/"):
            raise ValueError("k2-fsa models are not commercially permitted")
        _reject_leaks(self.model_dump_json(), label="narration document")
        return self


class LanguageCapabilityCacheRecord(Versioned):
    """Why an alignment or narration was reused."""

    cache_id: EntityId
    subject_id: EntityId
    kind: Literal["alignment", "narration"]
    identity_sha256: str = Field(pattern=_SHA)
    source_sha256: str = Field(pattern=_SHA)
    status: Literal["hit", "miss"]
