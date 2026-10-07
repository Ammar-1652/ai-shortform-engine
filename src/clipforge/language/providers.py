"""Alignment providers. A catalog row is not a live run.

The original locale stays on the stored document. Provider lookup uses the
normalized language code. ``verified_live`` is reserved for a checkpoint this
install has already executed. A missing weight file is ``model_missing``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

WHISPERX_VERSION = "3.4.5"
ALIGNMENT_RECIPE = "hero-align-v1"
_DEVICE = "cpu"
_SCOPE = "selected_clip"

# Hugging Face commit ids for the Apache-2.0 wav2vec2 checkpoints WhisperX can
# load by model id. They are not checkpoint file hashes and are not live claims.
JAPANESE_ALIGNMENT_MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-japanese"
JAPANESE_ALIGNMENT_REVISION = "cf031e020336460d15a417eba710bbc5bb43be9a"
JAPANESE_ALIGNMENT_CHECKPOINT = "4f6821dcd79770fcd4c11487c4ee5c040b3a7e1863425224014ba5ea8fbc1b67"
FRENCH_ALIGNMENT_MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-french"
FRENCH_ALIGNMENT_REVISION = "7c79e105a6525d38e1e69f640b974b4a679723cc"
FRENCH_ALIGNMENT_CHECKPOINT = "2fc4760bab7bf7d0d6c06e9b7f829a27a3e66eefee3733f53c88dbedf6607f2e"
SPANISH_ALIGNMENT_MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-spanish"
SPANISH_ALIGNMENT_REVISION = "96d7e9b4e4a78af515a3c6d3cee7c0826045d276"
GERMAN_ALIGNMENT_MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-german"
GERMAN_ALIGNMENT_REVISION = "4b8a02957378d0f2da2ef74091156b032c485a89"

_PROHIBITED_MODELS = frozenset(
    {
        "VOXPOPULI_ASR_BASE_10K_FR",
        "VOXPOPULI_ASR_BASE_10K_DE",
        "VOXPOPULI_ASR_BASE_10K_ES",
        "VOXPOPULI_ASR_BASE_10K_IT",
    }
)
_PROHIBITED_LICENSES = frozenset({"", "unknown", "prohibited", "cc-by-nc", "cc-by-nc-4.0"})

_CANONICAL = {
    "en": "en-US",
    "en-us": "en-US",
    "en-gb": "en-GB",
    "fr": "fr-FR",
    "fr-fr": "fr-FR",
    "es": "es-ES",
    "es-es": "es-ES",
    "de": "de-DE",
    "de-de": "de-DE",
    "ja": "ja",
    "ja-jp": "ja",
    "ar": "ar",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
}
_NORMALIZED = {
    "en-US": "en",
    "en-GB": "en",
    "fr-FR": "fr",
    "es-ES": "es",
    "de-DE": "de",
    "ja": "ja",
    "ar": "ar",
    "zh-CN": "zh",
}


@dataclass(frozen=True, slots=True)
class AlignmentProviderRecord:
    """One locale's aligner. ``live_status`` is never a generic available flag."""

    locale: str
    normalized_language: str
    provider_name: str
    provider_version: str
    model_id: str
    model_revision: str
    checkpoint_sha256: str
    model_license: str
    runtime_version: str
    device: str
    alignment_scope: str
    live_status: str
    unavailable_reason: str


def canonical_locale(locale: str) -> str:
    """Map accepted spellings onto one stored locale. Unknown tags stay unsupported."""
    return _CANONICAL.get(locale.strip().lower(), "")


def normalized_language(locale: str) -> str:
    """Language code used only for provider lookup."""
    canonical = canonical_locale(locale)
    return _NORMALIZED.get(canonical, "")


def _whisperx(
    locale: str,
    *,
    model_id: str,
    model_revision: str,
    checkpoint_sha256: str,
    live_status: str,
    reason: str,
    license_name: str = "Apache-2.0",
) -> AlignmentProviderRecord:
    return AlignmentProviderRecord(
        locale=locale,
        normalized_language=_NORMALIZED[locale],
        provider_name="whisperx",
        provider_version=WHISPERX_VERSION,
        model_id=model_id,
        model_revision=model_revision,
        checkpoint_sha256=checkpoint_sha256,
        model_license=license_name,
        runtime_version=WHISPERX_VERSION,
        device=_DEVICE,
        alignment_scope=_SCOPE,
        live_status=live_status,
        unavailable_reason=reason,
    )


def _unclaimed(locale: str, status: str) -> AlignmentProviderRecord:
    return AlignmentProviderRecord(
        locale=locale,
        normalized_language=_NORMALIZED[locale],
        provider_name="none",
        provider_version="none",
        model_id="none",
        model_revision="none",
        checkpoint_sha256="",
        model_license="not_applicable",
        runtime_version="none",
        device=_DEVICE,
        alignment_scope=_SCOPE,
        live_status=status,
        unavailable_reason=status,
    )


def _catalog() -> dict[str, AlignmentProviderRecord]:
    from clipforge.language.registry import (
        ENGLISH_ALIGNMENT_CHECKPOINT,
        ENGLISH_ALIGNMENT_MODEL,
        ENGLISH_ALIGNMENT_REVISION,
    )

    english = _whisperx(
        "en-US",
        model_id=ENGLISH_ALIGNMENT_MODEL,
        model_revision=ENGLISH_ALIGNMENT_REVISION,
        checkpoint_sha256=ENGLISH_ALIGNMENT_CHECKPOINT,
        live_status="available_not_smoked",
        reason="available_not_smoked",
    )
    british = _whisperx(
        "en-GB",
        model_id=ENGLISH_ALIGNMENT_MODEL,
        model_revision=ENGLISH_ALIGNMENT_REVISION,
        checkpoint_sha256=ENGLISH_ALIGNMENT_CHECKPOINT,
        live_status="available_not_smoked",
        reason="available_not_smoked",
    )
    return {
        "en-US": english,
        "en-GB": british,
        "fr-FR": _whisperx(
            "fr-FR",
            model_id=FRENCH_ALIGNMENT_MODEL,
            model_revision=FRENCH_ALIGNMENT_REVISION,
            checkpoint_sha256=FRENCH_ALIGNMENT_CHECKPOINT,
            live_status="available_not_smoked",
            reason="available_not_smoked",
        ),
        "es-ES": _whisperx(
            "es-ES",
            model_id=SPANISH_ALIGNMENT_MODEL,
            model_revision=SPANISH_ALIGNMENT_REVISION,
            checkpoint_sha256="",
            live_status="model_missing",
            reason="model_missing",
        ),
        "de-DE": _whisperx(
            "de-DE",
            model_id=GERMAN_ALIGNMENT_MODEL,
            model_revision=GERMAN_ALIGNMENT_REVISION,
            checkpoint_sha256="",
            live_status="model_missing",
            reason="model_missing",
        ),
        "ja": _whisperx(
            "ja",
            model_id=JAPANESE_ALIGNMENT_MODEL,
            model_revision=JAPANESE_ALIGNMENT_REVISION,
            checkpoint_sha256=JAPANESE_ALIGNMENT_CHECKPOINT,
            live_status="available_not_smoked",
            reason="available_not_smoked",
        ),
        "ar": _unclaimed("ar", "alignment_not_claimed"),
        "zh-CN": _unclaimed("zh-CN", "unsupported_language"),
    }


def provider_for(locale: str) -> AlignmentProviderRecord:
    """Resolve one locale. Live status is measured. It is not copied from a table."""
    canonical = canonical_locale(locale)
    row = _catalog().get(canonical)
    if row is None:
        return _unclaimed("zh-CN", "unsupported_language")
    status = _measured_status(row)
    if status == row.live_status:
        return row
    reason = "none" if status == "verified_live" else status
    return AlignmentProviderRecord(
        locale=row.locale,
        normalized_language=row.normalized_language,
        provider_name=row.provider_name,
        provider_version=row.provider_version,
        model_id=row.model_id,
        model_revision=row.model_revision,
        checkpoint_sha256=row.checkpoint_sha256,
        model_license=row.model_license,
        runtime_version=row.runtime_version,
        device=row.device,
        alignment_scope=row.alignment_scope,
        live_status=status,
        unavailable_reason=reason,
    )


def _measured_status(row: AlignmentProviderRecord) -> str:
    """Promote a row only when the local bytes, and any speech record, agree."""
    if row.provider_name != "whisperx":
        return row.live_status
    from clipforge.language.model_manifest import (
        english_checkpoint_file,
        huggingface_snapshot,
        measure_english_checkpoint,
        measure_tree,
        sha256_file,
    )

    if row.normalized_language == "en":
        path = english_checkpoint_file()
        if path is None:
            return "model_missing"
        if sha256_file(path) != row.checkpoint_sha256:
            return "stale_alignment"
        english_model = measure_english_checkpoint(path)
        return _speech_status(
            row,
            manifest=english_model.manifest_sha256,
            checkpoint=english_model.checkpoint_sha256,
        )
    snapshot = huggingface_snapshot(row.model_id, row.model_revision)
    if snapshot is None:
        return "model_missing"
    tree = measure_tree(snapshot, model_id=row.model_id, revision=row.model_revision)
    if tree is None:
        return "model_missing"
    if row.checkpoint_sha256 and tree.checkpoint_sha256 != row.checkpoint_sha256:
        return "stale_alignment"
    return _speech_status(row, manifest=tree.manifest_sha256, checkpoint=tree.checkpoint_sha256)


def _speech_status(row: AlignmentProviderRecord, *, manifest: str, checkpoint: str) -> str:
    """Live only when the external speech file and the measured model are one identity."""
    from clipforge.language.evidence import classify_speech_evidence

    kind = classify_speech_evidence(
        row.locale,
        model_id=row.model_id,
        model_revision=row.model_revision,
        checkpoint_sha256=checkpoint,
        manifest_sha256=manifest,
        whisperx_version=row.provider_version,
        device=row.device,
    )
    if kind == "":
        return "verified_live"
    if kind in {"no_record", "runtime_unreadable"}:
        return "available_not_smoked"
    return kind


def provider_for_model(model_id: str) -> AlignmentProviderRecord | None:
    """Return the catalog row that names this model, if one does."""
    for row in _catalog().values():
        if row.model_id == model_id:
            return row
    return None


def license_is_allowed(license_name: str, model_id: str) -> bool:
    """Require an explicit Apache-2.0 allow. A blacklist is not a license."""
    from clipforge.language.model_manifest import license_explicitly_allowed

    if model_id in _PROHIBITED_MODELS or model_id.lower().startswith("k2-fsa/"):
        return False
    if license_name.strip().lower() in _PROHIBITED_LICENSES:
        return False
    return license_explicitly_allowed(license_name)


def alignment_cache_key(**parts: str) -> str:
    """Hash every identity component. One changed value is a different alignment."""
    raw = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def narration_cache_key(**parts: str) -> str:
    """Hash narration identity. Locale and license are part of the key."""
    return alignment_cache_key(**parts)
