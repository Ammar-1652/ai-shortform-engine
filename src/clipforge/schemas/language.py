"""Language profiles stay beside the canonical transcript. They do not replace it."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from clipforge.schemas.campaign import PolicyOutcome, _plain, _relative
from clipforge.schemas.common import MAX_TIMELINE_US, EntityId, Versioned

_SHA = r"^[0-9a-f]{64}$"
Support = Literal["supported", "optional", "not_claimed", "unsupported"]


class LanguageProfile(Versioned):
    """One BCP-47 language the operator can select."""

    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    iso_code: str = Field(pattern=r"^[a-z]{2}$")
    script: str = Field(min_length=3, max_length=8)
    text_direction: Literal["ltr", "rtl"]
    caption_locale: str = Field(min_length=2, max_length=16)
    alignment_provider: str = Field(min_length=1, max_length=40)
    voice_provider: str = Field(min_length=1, max_length=40)
    supported_status: Support
    campaign_policy_status: PolicyOutcome

    @field_validator("script", "caption_locale", "alignment_provider", "voice_provider")
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="language profile")


class LanguageCapability(Versioned):
    """What a named provider claims. Absence is not support."""

    provider_id: EntityId
    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    capability: Literal["transcript", "alignment", "captions", "narration"]
    supported_status: Support


class TranslatedTranscript(Versioned):
    """A translation kept apart from the canonical source words."""

    translation_id: EntityId
    source_asset_id: EntityId
    source_language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    target_language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    source_text: str = Field(min_length=1, max_length=8000)
    translated_text: str = Field(min_length=1, max_length=8000)
    source_sha256: str = Field(pattern=_SHA)
    text_direction: Literal["ltr", "rtl"]

    @field_validator("source_text", "translated_text")
    @classmethod
    def text_keeps_unicode(cls, value: str) -> str:
        if any(ord(character) < 32 and character not in "\n\t" for character in value):
            raise ValueError("transcript text contains a control character")
        lowered = value.lower()
        if "bearer " in lowered or "token=" in lowered or "password=" in lowered:
            raise ValueError("transcript text contains a secret-like token")
        return value


class LanguageAlignmentDocument(Versioned):
    """Alignment for one language. It does not claim the speaker's identity."""

    alignment_id: EntityId
    source_asset_id: EntityId
    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    provider_id: EntityId
    provider_status: Support
    source_sha256: str = Field(pattern=_SHA)


class SpeechEvidenceRecord(Versioned):
    """One external speech file bound to one alignment model. Metadata alone is not proof."""

    locale: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    audio_class: Literal["recorded_speech", "tts_speech"]
    audio_filename: str = Field(min_length=1, max_length=80)
    audio_sha256: str = Field(pattern=_SHA)
    sample_rate: int = Field(ge=8000, le=96000)
    channels: int = Field(ge=1, le=2)
    duration_us: int = Field(gt=0, le=MAX_TIMELINE_US)
    transcript: str = Field(min_length=1, max_length=400)
    token_count: int = Field(ge=3, le=200)
    whisperx_version: str = Field(min_length=1, max_length=40)
    model_id: str = Field(min_length=1, max_length=120)
    model_revision: str = Field(min_length=1, max_length=80)
    checkpoint_sha256: str = Field(pattern=_SHA)
    manifest_sha256: str = Field(pattern=_SHA)
    device: Literal["cpu", "cuda"]
    provenance: str = Field(min_length=1, max_length=400)

    @field_validator("audio_filename")
    @classmethod
    def filename_stays_in_the_evidence_root(cls, value: str) -> str:
        relative = _relative(value)
        if "/" in relative or relative in {".", ".."}:
            raise ValueError("speech audio filename must be one path segment")
        return relative

    @field_validator(
        "transcript",
        "whisperx_version",
        "model_id",
        "model_revision",
        "provenance",
    )
    @classmethod
    def speech_text_is_plain(cls, value: str) -> str:
        return _plain(value, label="speech evidence")


class SpeechEvidenceCatalog(Versioned):
    """Index of speech evidence. The audio files stay outside the repository."""

    records: list[SpeechEvidenceRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def locales_are_unique(self) -> Self:
        locales = [item.locale for item in self.records]
        if len(locales) != len(set(locales)):
            raise ValueError("speech evidence locales must be unique")
        return self


class LanguageCaptionProfile(Versioned):
    """How captions are drawn. Glow and emoji are not styles this campaign allows."""

    profile_id: EntityId
    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    text_direction: Literal["ltr", "rtl"]
    max_characters: int = Field(ge=1, le=200)
    effects: list[str] = Field(default_factory=list)
    review_required: bool = True

    @field_validator("effects")
    @classmethod
    def effects_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(item, label="caption effect") for item in values]
