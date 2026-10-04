"""Language profiles stay beside the canonical transcript. They do not replace it."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from clipforge.schemas.campaign import PolicyOutcome, _plain
from clipforge.schemas.common import EntityId, Versioned

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
