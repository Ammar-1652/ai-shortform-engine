"""Optional narration. Generated audio is an input asset, not an approval."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"
VoiceType = Literal["designed", "cloned", "preset"]
LicenseState = Literal["allowed", "prohibited", "unknown", "cc_by_nc"]
TimingPolicy = Literal["preserve_duration", "bounded_time_stretch", "reject_if_out_of_range"]
OutputUse = Literal["commercial", "internal"]


def _reject_text(value: str, label: str) -> str:
    stripped = value.strip()
    lowered = stripped.lower()
    if stripped != value:
        raise ValueError(f"{label} must not have surrounding space")
    if any(ord(character) < 32 for character in stripped):
        raise ValueError(f"{label} must not contain control characters")
    tokens = (
        "<",
        ">",
        "javascript:",
        "://",
        "bearer ",
        "password=",
        "/tmp/",
        "/home/",
        "/users/",
        "viewer_id",
        "token=",
    )
    if any(token in lowered for token in tokens):
        raise ValueError(f"{label} contains markup, a path, or a secret-like token")
    if "\\" in stripped or stripped.startswith("/") or ".." in stripped.split("/"):
        raise ValueError(f"{label} contains a filesystem path")
    return stripped


class VoiceProviderProfile(Versioned):
    """Who spoke, and whether that voice may be used. Reference audio is not stored."""

    provider_id: EntityId
    provider_version: str = Field(min_length=1, max_length=40)
    engine_id: str = Field(min_length=1, max_length=40)
    model_id: str = Field(min_length=1, max_length=80)
    model_revision: str = Field(min_length=1, max_length=80)
    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    voice_profile_id: EntityId
    voice_type: VoiceType
    consent_record_id: EntityId
    commercial_use: LicenseState
    model_license: LicenseState
    license_evidence_id: EntityId
    clone_permission: bool
    provenance: ArtifactProvenance

    @field_validator("provider_version", "engine_id", "model_id", "model_revision")
    @classmethod
    def labels_are_public(cls, value: str) -> str:
        return _reject_text(value, "voice profile")

    @model_validator(mode="after")
    def clone_has_permission(self) -> Self:
        if self.voice_type == "cloned" and not self.clone_permission:
            raise ValueError("a cloned voice requires recorded clone permission")
        return self


class NarrationRequest(Versioned):
    """An explicit script. A raw transcript is not accepted as this script."""

    project_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId | None = None
    hero_id: EntityId | None = None
    script_text: str = Field(min_length=1, max_length=2000)
    script_sha256: str = Field(pattern=_SHA)
    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    provider_id: EntityId
    voice_profile_id: EntityId
    sample_rate: int = Field(ge=8000, le=96000)
    channels: int = Field(ge=1, le=2)
    timing_policy: TimingPolicy
    target_duration_us: int = Field(gt=0)
    duration_tolerance_us: int = Field(default=100_000, ge=0, le=2_000_000)
    output_format: Literal["wav"] = "wav"
    output_use: OutputUse
    conversion_recipe: str = "identity"
    profile: VoiceProviderProfile
    created_by: str = Field(min_length=1, max_length=80)
    provenance: ArtifactProvenance

    @field_validator("script_text", "created_by", "conversion_recipe")
    @classmethod
    def script_is_public(cls, value: str) -> str:
        return _reject_text(value, "narration script")

    @model_validator(mode="after")
    def script_hash_matches(self) -> Self:
        import hashlib

        digest = hashlib.sha256(self.script_text.encode("utf-8")).hexdigest()
        if digest != self.script_sha256:
            raise ValueError("script hash does not match the script text")
        same_provider = self.profile.provider_id == self.provider_id
        same_voice = self.profile.voice_profile_id == self.voice_profile_id
        if not same_provider or not same_voice:
            raise ValueError("narration request does not match its voice profile")
        if self.profile.commercial_use in {"unknown", "prohibited"}:
            raise ValueError("unknown or prohibited voice rights fail closed")
        if self.profile.model_license in {"unknown", "prohibited"}:
            raise ValueError("unknown or prohibited model rights fail closed")
        if self.output_use == "commercial" and self.profile.commercial_use != "allowed":
            raise ValueError("commercial narration requires an explicitly allowed license")
        if self.output_use == "commercial" and self.profile.model_license != "allowed":
            raise ValueError("commercial narration rejects a CC-BY-NC or unlicensed model")
        if self.output_use == "commercial" and self.profile.model_id.lower().startswith("k2-fsa/"):
            raise ValueError("the default VoiceStudio model is not marked commercially permitted")
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("narration provenance must include the source asset")
        return self


class NarrationAudioArtifact(Versioned):
    """Measured narration audio. The file path and the waveform are not stored."""

    artifact_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    hero_id: EntityId | None = None
    advanced_plan_id: EntityId | None = None
    provider_id: EntityId
    voice_profile_id: EntityId
    engine_id: str = Field(min_length=1, max_length=40)
    model_id: str = Field(min_length=1, max_length=80)
    model_revision: str = Field(min_length=1, max_length=80)
    script_sha256: str = Field(pattern=_SHA)
    script_label: str = Field(min_length=1, max_length=80)
    audio_sha256: str = Field(pattern=_SHA)
    size_bytes: int = Field(ge=1)
    duration_us: int = Field(gt=0)
    sample_rate: int = Field(ge=8000, le=96000)
    channels: int = Field(ge=1, le=2)
    codec: str = Field(min_length=1, max_length=40)
    language: str | None = None
    provider_version: str | None = None
    consent_record_id: EntityId
    license_evidence_id: EntityId
    model_license: LicenseState | None = None
    commercial_use: LicenseState | None = None
    cache_id: str = Field(pattern=_SHA)
    job_id: EntityId
    provenance: ArtifactProvenance

    @field_validator("script_label", "engine_id", "model_id", "model_revision", "codec")
    @classmethod
    def narration_text_is_public(cls, value: str) -> str:
        return _reject_text(value, "narration")

    @field_validator("language", "provider_version")
    @classmethod
    def optional_labels_are_public(cls, value: str | None) -> str | None:
        if value is None:
            return None
        checked = _reject_text(value, "narration")
        if len(checked) > 40:
            raise ValueError("narration label is too long")
        return checked

    @model_validator(mode="after")
    def lineage_is_present(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("narration provenance must include the source asset")
        if self.provenance.job_id != self.job_id:
            raise ValueError("narration provenance must name its producing job")
        return self


class NarrationPlan(Versioned):
    """An operator decision to narrate, or an explicit choice not to."""

    plan_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId
    enabled: bool
    operator_reason: str = Field(min_length=1, max_length=400)
    campaign_policy_decision: str = Field(min_length=1, max_length=80)
    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    voice_id: EntityId
    voice_type: VoiceType = "preset"
    provider: str = Field(min_length=1, max_length=40)
    provider_version: str = Field(min_length=1, max_length=40)
    engine_id: str = Field(default="fake-engine", min_length=1, max_length=40)
    model_id: str = Field(min_length=1, max_length=80)
    model_revision: str = Field(default="rev-1", min_length=1, max_length=80)
    model_license: LicenseState
    commercial_use: LicenseState = "allowed"
    output_use: OutputUse = "internal"
    license_evidence_id: str = Field(default="evidence-voice", min_length=1, max_length=80)
    consent_record_id: str = Field(default="consent-1", min_length=1, max_length=80)
    conversion_recipe: str = "identity"
    duration_tolerance_us: int = Field(default=100_000, ge=0, le=2_000_000)
    consent_status: Literal["recorded", "missing"]
    source_script_sha256: str = Field(pattern=_SHA)
    artifact_id: EntityId | None = None
    generated_audio_sha256: str | None = Field(default=None, pattern=_SHA)
    target_duration_us: int = Field(gt=0)
    actual_duration_us: int | None = Field(default=None, gt=0)
    sample_rate: int = Field(ge=8000, le=96000)
    channels: int = Field(ge=1, le=2)
    loudness_lufs: float | None = None
    gain_db: float = 0
    ducking_policy: Literal["none", "duck_source"] = "none"
    timing_policy: TimingPolicy

    @field_validator(
        "operator_reason",
        "campaign_policy_decision",
        "provider",
        "provider_version",
        "engine_id",
        "model_id",
        "model_revision",
        "license_evidence_id",
        "consent_record_id",
        "conversion_recipe",
    )
    @classmethod
    def plan_text_is_public(cls, value: str) -> str:
        return _reject_text(value, "narration plan")
