"""Provider capability matrix. Unsupported languages fail before a render job."""

from __future__ import annotations

import hashlib

from clipforge.campaign.policy import language_decision
from clipforge.schemas.language import (
    LanguageAlignmentDocument,
    LanguageCapability,
    LanguageCaptionProfile,
    LanguageProfile,
    TranslatedTranscript,
)

_PROFILES: tuple[tuple[str, str, str, str, str], ...] = (
    ("en-US", "en", "Latn", "ltr", "en-US"),
    ("en-GB", "en", "Latn", "ltr", "en-GB"),
    ("fr-FR", "fr", "Latn", "ltr", "fr-FR"),
    ("es-ES", "es", "Latn", "ltr", "es-ES"),
    ("de-DE", "de", "Latn", "ltr", "de-DE"),
    ("ar", "ar", "Arab", "rtl", "ar"),
    ("ja", "ja", "Jpan", "ltr", "ja"),
)


def profiles() -> list[LanguageProfile]:
    rows: list[LanguageProfile] = []
    for language, iso, script, direction, locale in _PROFILES:
        rows.append(
            LanguageProfile(
                language=language,
                iso_code=iso,
                script=script,
                text_direction=direction,  # type: ignore[arg-type]
                caption_locale=locale,
                alignment_provider="whisperx" if not language.startswith("ar") else "unspecified",
                voice_provider="voicestudio",
                supported_status="supported",
                campaign_policy_status=language_decision(language),
            )
        )
    return rows


def capabilities() -> list[LanguageCapability]:
    rows: list[LanguageCapability] = []
    for language, _iso, _script, _direction, _locale in _PROFILES:
        whisper = "optional" if language.startswith("en") else "not_claimed"
        rows.append(
            LanguageCapability(
                provider_id="whisperx",
                language=language,
                capability="alignment",
                supported_status=whisper,  # type: ignore[arg-type]
            )
        )
        rows.append(
            LanguageCapability(
                provider_id="clipforge",
                language=language,
                capability="captions",
                supported_status="supported",
            )
        )
    return rows


def require_language(language: str) -> LanguageProfile:
    for profile in profiles():
        if profile.language == language:
            return profile
    raise ValueError("unsupported_language")


def separate_translation(
    *,
    source_asset_id: str,
    source_language: str,
    target_language: str,
    source_text: str,
    translated_text: str,
) -> TranslatedTranscript:
    """Keep the canonical words. The translation is a different field."""
    source_profile = require_language(source_language)
    target_profile = require_language(target_language)
    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    return TranslatedTranscript(
        translation_id=f"tr-{digest[:16]}",
        source_asset_id=source_asset_id,
        source_language=source_profile.language,
        target_language=target_profile.language,
        source_text=source_text,
        translated_text=translated_text,
        source_sha256=digest,
        text_direction=target_profile.text_direction,
    )


def alignment_document(source_asset_id: str, language: str, source_sha256: str) -> LanguageAlignmentDocument:
    profile = require_language(language)
    status = "optional" if language.startswith("en") else "not_claimed"
    return LanguageAlignmentDocument(
        alignment_id=f"align-{language.lower()}",
        source_asset_id=source_asset_id,
        language=profile.language,
        provider_id="whisperx",
        provider_status=status,  # type: ignore[arg-type]
        source_sha256=source_sha256,
    )


def caption_profile(language: str) -> LanguageCaptionProfile:
    profile = require_language(language)
    return LanguageCaptionProfile(
        profile_id=f"captions-{profile.language}",
        language=profile.language,
        text_direction=profile.text_direction,
        max_characters=100,
        effects=["static"],
        review_required=True,
    )
