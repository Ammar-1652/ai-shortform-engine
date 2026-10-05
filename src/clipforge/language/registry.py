"""One capability record per language. A missing model is unavailable, not a pass."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from clipforge.language.matrix import require_language

ENGLISH_ALIGNMENT_MODEL = "WAV2VEC2_ASR_BASE_960H"
ENGLISH_ALIGNMENT_REVISION = "3.4.5"
ENGLISH_ALIGNMENT_CHECKPOINT = "488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d"
ENGLISH_NARRATION_ENGINE = "kittentts"
ENGLISH_NARRATION_MODEL = "KittenML/kitten-tts-mini-0.8"
ENGLISH_NARRATION_REVISION = "c02725660cea441db4c383af69f1f26f5cd00947"
ENGLISH_NARRATION_VOICE = "expr-voice-2-f"
ENGLISH_NARRATION_LICENSE = "Apache-2.0"
ENGLISH_NARRATION_SCRIPT = "Café costs $12.50 today."
ENGLISH_NARRATION_SCRIPT_SHA256 = hashlib.sha256(ENGLISH_NARRATION_SCRIPT.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LanguageCapabilityEntry:
    """What this install may claim. Live, fake, and unavailable stay distinct."""

    language: str
    text_direction: str
    caption_policy: str
    transcription: str
    transcription_evidence: str
    alignment: str
    alignment_evidence: str
    alignment_model: str | None
    alignment_revision: str | None
    alignment_checkpoint_sha256: str | None
    narration_engines: tuple[str, ...]
    narration_evidence: str
    narration_model: str | None
    narration_revision: str | None
    license_status: str
    reason_code: str
    narration_reason: str


def capability_registry() -> tuple[LanguageCapabilityEntry, ...]:
    """Supported profiles. zh-CN is absent and must be rejected by the caller."""
    rows: list[LanguageCapabilityEntry] = []
    for profile in ("en-US", "en-GB", "fr-FR", "es-ES", "de-DE", "ar", "ja"):
        language = require_language(profile)
        english = language.language.startswith("en")
        narrated = language.language == "en-US"
        if narrated:
            narration_reason = "none"
        elif english:
            narration_reason = "locale_not_smoked"
        else:
            narration_reason = "unsupported_language"
        if language.text_direction == "rtl":
            caption_policy = "rtl_logical_order"
        elif language.language == "ja":
            caption_policy = "character_wrap"
        else:
            caption_policy = "ltr_wrap"
        rows.append(
            LanguageCapabilityEntry(
                language=language.language,
                text_direction=language.text_direction,
                caption_policy=caption_policy,
                transcription="faster_whisper" if english else "none",
                transcription_evidence="verified_live" if english else "unavailable",
                alignment="whisperx" if english else "none",
                alignment_evidence="verified_live" if english else "unavailable",
                alignment_model=ENGLISH_ALIGNMENT_MODEL if english else None,
                alignment_revision=ENGLISH_ALIGNMENT_REVISION if english else None,
                alignment_checkpoint_sha256=ENGLISH_ALIGNMENT_CHECKPOINT if english else None,
                narration_engines=(ENGLISH_NARRATION_ENGINE,) if narrated else (),
                narration_evidence="verified_live" if narrated else "unavailable",
                narration_model=ENGLISH_NARRATION_MODEL if narrated else None,
                narration_revision=ENGLISH_NARRATION_REVISION if narrated else None,
                license_status="allowed" if narrated else "not_applicable",
                reason_code="none" if english else "alignment_not_claimed",
                narration_reason=narration_reason,
            )
        )
    return tuple(rows)


def capability_for(language: str) -> LanguageCapabilityEntry:
    """Return one entry. An unknown tag fails before a render or a campaign stage."""
    require_language(language)
    for entry in capability_registry():
        if entry.language == language:
            return entry
    raise ValueError("unsupported_language")


def alignment_claim(language: str) -> str:
    """The status a production run may record. Fake alignment is not a claim."""
    entry = capability_for(language)
    if entry.alignment_evidence == "verified_live" and entry.alignment == "whisperx":
        return "whisperx"
    return "alignment_not_claimed"


def alignment_identity_matches(*, revision: str, checkpoint: str) -> bool:
    """True only for the English checkpoint this install has already run."""
    return revision == ENGLISH_ALIGNMENT_REVISION and checkpoint == ENGLISH_ALIGNMENT_CHECKPOINT
