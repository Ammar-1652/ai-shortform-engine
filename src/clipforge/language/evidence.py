"""Current alignment evidence. A stored JSON status is not proof."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.constants import FAKE_MODEL_NAME
from clipforge.schemas.hero import ForcedAlignmentDocument

_NONE = "none"


@dataclass(frozen=True, slots=True)
class SpeechFacts:
    """WAV facts measured from the external speech file."""

    sample_rate: int
    channels: int
    duration_us: int
    token_count: int
    transcript: str


@dataclass(frozen=True, slots=True)
class AlignmentEvidence:
    """The alignment identity that is true on this machine right now."""

    status: str
    blocker: str
    canonical_locale: str
    normalized_language: str
    model_id: str
    model_revision: str
    checkpoint_sha256: str
    manifest_sha256: str
    whisperx_version: str
    device: str
    speech_filename: str
    speech_sha256: str
    speech_facts: SpeechFacts | None
    evidence_digest: str
    alignment_id: str = ""
    alignment_sha256: str = ""
    provider_name: str = _NONE


def classify_speech_evidence(
    locale: str,
    *,
    model_id: str,
    model_revision: str,
    checkpoint_sha256: str,
    manifest_sha256: str,
    whisperx_version: str,
    device: str,
) -> str:
    """Empty means the external file matches this measured model.

    ``no_record`` means the packaged catalog has no speech file for the locale.
    """
    from clipforge.language.model_manifest import (
        measured_whisperx_version,
        packaged_speech_record,
        resolve_speech_audio,
        sha256_file,
        speech_evidence_grants_live,
        speech_evidence_root,
        wav_signature,
    )

    packaged = packaged_speech_record(locale)
    if packaged is None:
        return "no_record"
    root = speech_evidence_root()
    if root is None:
        return "speech_evidence_missing"
    audio = resolve_speech_audio(root, packaged.audio_filename)
    if audio is None:
        return "speech_evidence_missing"
    if sha256_file(audio) != packaged.audio_sha256:
        return "speech_evidence_changed"
    signature = wav_signature(audio)
    expected = (packaged.sample_rate, packaged.channels, packaged.duration_us)
    if signature != expected or packaged.token_count < 3 or not packaged.transcript.strip():
        return "speech_evidence_changed"
    if not measured_whisperx_version():
        return "runtime_unreadable"
    if not speech_evidence_grants_live(
        locale,
        model_id=model_id,
        model_revision=model_revision,
        checkpoint_sha256=checkpoint_sha256,
        manifest_sha256=manifest_sha256,
        whisperx_version=whisperx_version,
        device=device,
    ):
        return "stale_alignment"
    return ""


def validate_current_alignment_evidence(
    path: Path | None = None,
    *,
    document: ForcedAlignmentDocument | None = None,
    project_id: str | None = None,
    source_asset_id: str | None = None,
    candidate_id: str | None = None,
    transcript_sha256: str | None = None,
    asr_audio_sha256: str | None = None,
    time_map_sha256: str | None = None,
    rough_preview_artifact_id: str | None = None,
    review_id: str | None = None,
    review_digest: str | None = None,
    source_sha256: str = "",
    file_sha256: str = "",
) -> AlignmentEvidence:
    """Revalidate one alignment against the current model and speech file."""
    loaded, digest = _load(path, document)
    if loaded is None:
        return _result("stale_alignment", "stale_alignment", file_sha256=digest)
    mismatch = _binding_mismatch(
        loaded,
        project_id=project_id,
        source_asset_id=source_asset_id,
        candidate_id=candidate_id,
        transcript_sha256=transcript_sha256,
        asr_audio_sha256=asr_audio_sha256,
        time_map_sha256=time_map_sha256,
        rough_preview_artifact_id=rough_preview_artifact_id,
        review_id=review_id,
        review_digest=review_digest,
    )
    if mismatch:
        return _from_document(loaded, "stale_alignment", mismatch, file_sha256=digest)
    if loaded.model_name == FAKE_MODEL_NAME:
        return _fake(loaded, source_sha256=source_sha256, file_sha256=digest)
    return _production(loaded, source_sha256=source_sha256, file_sha256=digest)


def _load(
    path: Path | None,
    document: ForcedAlignmentDocument | None,
) -> tuple[ForcedAlignmentDocument | None, str]:
    if document is not None:
        return document, ""
    if path is None or path.is_symlink() or not path.is_file():
        return None, ""
    from clipforge.language.model_manifest import sha256_file

    digest = sha256_file(path)
    try:
        return ForcedAlignmentDocument.model_validate_json(path.read_text(encoding="utf-8")), digest
    except (OSError, UnicodeError, ValidationError, ValueError):
        return None, digest


def _binding_mismatch(document: ForcedAlignmentDocument, **expected: str | None) -> str:
    pairs = {
        "project_id": document.project_id,
        "source_asset_id": document.source_asset_id,
        "candidate_id": document.candidate_id,
        "transcript_sha256": document.transcript_sha256,
        "asr_audio_sha256": document.asr_audio_sha256,
        "time_map_sha256": document.time_map_sha256,
        "rough_preview_artifact_id": document.rough_preview_artifact_id,
        "review_id": document.review_id,
        "review_digest": document.review_digest,
    }
    for key, actual in pairs.items():
        wanted = expected.get(key)
        if wanted is not None and wanted != actual:
            return "stale_alignment"
    return ""


def _fake(
    document: ForcedAlignmentDocument,
    *,
    source_sha256: str,
    file_sha256: str,
) -> AlignmentEvidence:
    fresh = _recomputed(document, source_sha256=source_sha256)
    if document.binding_sha256 and fresh != document.binding_sha256:
        return _from_document(document, "stale_alignment", "stale_alignment", file_sha256=file_sha256)
    return _from_document(document, "available_not_smoked", "none", file_sha256=file_sha256, provider="fake")


def _production(
    document: ForcedAlignmentDocument,
    *,
    source_sha256: str,
    file_sha256: str,
) -> AlignmentEvidence:
    from clipforge.hero.alignment import _measure_checkpoint_and_manifest
    from clipforge.language.providers import canonical_locale, normalized_language, provider_for

    locale = canonical_locale(document.locale)
    if not locale:
        return _from_document(document, "unsupported_language", "unsupported_language", file_sha256=file_sha256)
    record = provider_for(locale)
    if record.live_status == "unsupported_language" or record.provider_name == "none":
        status = record.live_status if record.live_status == "unsupported_language" else "alignment_not_claimed"
        return _from_document(document, status, status, file_sha256=file_sha256)
    if record.live_status == "model_missing":
        return _from_document(document, "model_missing", "model_missing", file_sha256=file_sha256)
    try:
        checkpoint, manifest = _measure_checkpoint_and_manifest(
            record.model_id,
            record.normalized_language,
            record.model_revision,
            record.checkpoint_sha256,
        )
    except MediaError as exc:
        code = str(exc)
        status = code if code in {"model_missing", "stale_alignment"} else "stale_alignment"
        return _from_document(document, status, status, file_sha256=file_sha256)
    speech = classify_speech_evidence(
        locale,
        model_id=record.model_id,
        model_revision=record.model_revision,
        checkpoint_sha256=checkpoint,
        manifest_sha256=manifest,
        whisperx_version=record.provider_version,
        device=record.device,
    )
    facts = _speech_facts(locale)
    identity_changed = (
        document.model_name != record.model_id
        or document.model_revision != record.model_revision
        or document.checkpoint_sha256 != checkpoint
        or document.manifest_sha256 != manifest
        or document.whisperx_version != record.provider_version
        or document.device != record.device
        or normalized_language(document.locale) != record.normalized_language
    )
    binding_changed = (
        bool(document.binding_sha256)
        and _recomputed(
            document,
            source_sha256=source_sha256,
            checkpoint_sha256=checkpoint,
            manifest_sha256=manifest,
            model_id=record.model_id,
            model_revision=record.model_revision,
            provider_version=record.provider_version,
            normalized=record.normalized_language,
        )
        != document.binding_sha256
    )
    if not document.binding_sha256 or identity_changed or binding_changed:
        blocker = "stale_alignment"
    elif speech == "no_record":
        blocker = "speech_evidence_missing" if document.alignment_status == "verified_live" else "none"
    elif speech:
        blocker = speech
    else:
        blocker = "none"
    status = "verified_live" if blocker == "none" else blocker
    if blocker == "none" and document.alignment_status not in {"verified_live", ""}:
        status = document.alignment_status or "verified_live"
    return _from_document(
        document,
        status,
        blocker,
        file_sha256=file_sha256,
        provider=record.provider_name,
        checkpoint=checkpoint,
        manifest=manifest,
        revision=record.model_revision,
        whisperx=record.provider_version,
        device=record.device,
        facts=facts,
        locale=locale,
        normalized=record.normalized_language,
        model_id=record.model_id,
    )


def _speech_facts(locale: str) -> SpeechFacts | None:
    from clipforge.language.model_manifest import (
        packaged_speech_record,
        resolve_speech_audio,
        speech_evidence_root,
    )

    packaged = packaged_speech_record(locale)
    root = speech_evidence_root()
    if packaged is None or root is None or resolve_speech_audio(root, packaged.audio_filename) is None:
        return None
    return SpeechFacts(
        sample_rate=packaged.sample_rate,
        channels=packaged.channels,
        duration_us=packaged.duration_us,
        token_count=packaged.token_count,
        transcript=packaged.transcript,
    )


def _recomputed(
    document: ForcedAlignmentDocument,
    *,
    source_sha256: str,
    checkpoint_sha256: str | None = None,
    manifest_sha256: str | None = None,
    model_id: str | None = None,
    model_revision: str | None = None,
    provider_version: str | None = None,
    normalized: str | None = None,
) -> str:
    from clipforge.hero.alignment import alignment_binding_sha256
    from clipforge.language.providers import canonical_locale, normalized_language

    locale = canonical_locale(document.locale) or document.locale
    language = normalized or normalized_language(locale) or document.normalized_language
    provider = "fake" if document.model_name == FAKE_MODEL_NAME else "whisperx"
    return alignment_binding_sha256(
        alignment_recipe=document.alignment_recipe or "hero-align-v1",
        asr_audio_sha256=document.asr_audio_sha256,
        candidate_id=document.candidate_id,
        checkpoint_sha256=checkpoint_sha256 if checkpoint_sha256 is not None else document.checkpoint_sha256,
        locale=locale,
        manifest_sha256=manifest_sha256 if manifest_sha256 is not None else document.manifest_sha256,
        model_id=model_id or document.model_name,
        model_revision=model_revision if model_revision is not None else document.model_revision,
        normalized_language=language,
        provider_name=provider,
        provider_version=provider_version or document.whisperx_version,
        source_asset_id=document.source_asset_id,
        source_sha256=source_sha256,
        time_map_sha256=document.time_map_sha256,
        transcript_language=language,
        transcript_sha256=document.transcript_sha256,
    )


def _from_document(
    document: ForcedAlignmentDocument,
    status: str,
    blocker: str,
    *,
    file_sha256: str,
    provider: str = "whisperx",
    checkpoint: str | None = None,
    manifest: str | None = None,
    revision: str | None = None,
    whisperx: str | None = None,
    device: str | None = None,
    facts: SpeechFacts | None = None,
    locale: str | None = None,
    normalized: str | None = None,
    model_id: str | None = None,
) -> AlignmentEvidence:
    from clipforge.language.model_manifest import packaged_speech_record
    from clipforge.language.providers import canonical_locale, normalized_language

    stored_locale = locale or canonical_locale(document.locale) or "missing"
    packaged = packaged_speech_record(stored_locale) if stored_locale != "missing" else None
    speech_name = packaged.audio_filename if packaged is not None and facts is not None else ""
    speech_sha = packaged.audio_sha256 if packaged is not None and facts is not None else ""
    return _result(
        status,
        blocker,
        locale=stored_locale,
        normalized=(
            normalized or normalized_language(stored_locale) or document.normalized_language or "missing"
        ),
        model_id=model_id or document.model_name,
        revision=revision if revision is not None else document.model_revision,
        checkpoint=checkpoint if checkpoint is not None else document.checkpoint_sha256,
        manifest=manifest if manifest is not None else document.manifest_sha256,
        whisperx=whisperx if whisperx is not None else document.whisperx_version,
        device=device or document.device,
        speech_filename=speech_name,
        speech_sha256=speech_sha,
        facts=facts,
        alignment_id=document.alignment_id,
        alignment_sha256=file_sha256,
        provider=provider,
    )


def _result(
    status: str,
    blocker: str,
    *,
    locale: str = "missing",
    normalized: str = "missing",
    model_id: str = _NONE,
    revision: str = _NONE,
    checkpoint: str = _NONE,
    manifest: str = _NONE,
    whisperx: str = _NONE,
    device: str = _NONE,
    speech_filename: str = "",
    speech_sha256: str = "",
    facts: SpeechFacts | None = None,
    alignment_id: str = "",
    alignment_sha256: str = "",
    provider: str = _NONE,
    file_sha256: str = "",
) -> AlignmentEvidence:
    payload = {
        "alignment_sha256": alignment_sha256 or file_sha256,
        "blocker": blocker,
        "checkpoint_sha256": checkpoint,
        "device": device,
        "locale": locale,
        "manifest_sha256": manifest,
        "model_id": model_id,
        "model_revision": revision,
        "speech_sha256": speech_sha256,
        "status": status,
        "whisperx_version": whisperx,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return AlignmentEvidence(
        status=status,
        blocker=blocker,
        canonical_locale=locale,
        normalized_language=normalized,
        model_id=model_id,
        model_revision=revision,
        checkpoint_sha256=checkpoint,
        manifest_sha256=manifest,
        whisperx_version=whisperx,
        device=device,
        speech_filename=speech_filename,
        speech_sha256=speech_sha256,
        speech_facts=facts,
        evidence_digest=hashlib.sha256(raw).hexdigest(),
        alignment_id=alignment_id,
        alignment_sha256=alignment_sha256 or file_sha256,
        provider_name=provider,
    )
