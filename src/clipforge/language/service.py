"""Full-source language alignment and narration. Fake runs stay unverified."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from clipforge.errors import ClipforgeError, StorageError
from clipforge.language.matrix import require_language
from clipforge.language.registry import (
    ENGLISH_ALIGNMENT_CHECKPOINT,
    ENGLISH_ALIGNMENT_MODEL,
    ENGLISH_ALIGNMENT_REVISION,
    ENGLISH_NARRATION_ENGINE,
    ENGLISH_NARRATION_LICENSE,
    ENGLISH_NARRATION_MODEL,
    ENGLISH_NARRATION_REVISION,
    ENGLISH_NARRATION_VOICE,
    LanguageCapabilityEntry,
    alignment_claim,
    alignment_identity_matches,
    capability_for,
    language_capability_fingerprint,
)
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import mkdir_contained
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.multilingual import (
    CapabilityStatus,
    LanguageCapabilityCacheRecord,
    MultilingualAlignedWord,
    MultilingualAlignmentDocument,
    MultilingualNarrationDocument,
    NarrationCapability,
)
from clipforge.storage import Database, get_job, insert_job, update_job

_ModelT = TypeVar("_ModelT", bound=BaseModel)
_ALIGN_KIND = "language_alignment"
_NARRATION_KIND = "language_narration"
_ALIGN_ROOT = ("languages", "alignments")
_NARRATION_ROOT = ("languages", "narration")


class LanguageError(ClipforgeError):
    """A language operation failed before it could claim a result."""

    def __init__(self, message: str, *, code: str = "language_error") -> None:
        super().__init__(message)
        self.code = code


class FullSourceAligner(Protocol):
    """Assign word times. Implementations must not relabel the transcript text."""

    provider_id: str
    provider_version: str
    model_id: str
    model_revision: str
    checkpoint_sha256: str
    runtime_version: str
    device: str
    sample_rate: int
    live_execution: bool

    def prepare(self) -> None:
        """Fail before a job when the runtime is missing."""

    def align(self, count: int, duration_us: int) -> list[tuple[int, int]]:
        """Return source ``(start_us, end_us)`` for each word."""


class FakeLanguageAligner:
    """Deterministic times for tests. This is never a live execution."""

    live_execution = False
    provider_id = "fake"
    provider_version = "fake"
    runtime_version = "fake"
    device = "cpu"
    sample_rate = 16000

    def __init__(self, language: str) -> None:
        self.language = language
        self.model_id = "fake-" + language
        self.model_revision = "0"
        self.checkpoint_sha256 = hashlib.sha256(b"fake-alignment").hexdigest()

    def prepare(self) -> None:
        return None

    def align(self, count: int, duration_us: int) -> list[tuple[int, int]]:
        return _even_spans(count, duration_us)


class UnavailableAligner(FakeLanguageAligner):
    """Report a missing runtime. No job is inserted."""

    provider_id = "unavailable"

    def __init__(self) -> None:
        super().__init__("en-US")
        self.model_id = "unavailable"

    def prepare(self) -> None:
        raise LanguageError("alignment runtime is not configured", code="not_configured")


class WhisperXFullSourceAligner:
    """Optional full-source WhisperX. Normal runs do not download or execute it."""

    provider_id = "whisperx"
    provider_version = ENGLISH_ALIGNMENT_REVISION
    model_id = ENGLISH_ALIGNMENT_MODEL
    model_revision = ENGLISH_ALIGNMENT_REVISION
    checkpoint_sha256 = ENGLISH_ALIGNMENT_CHECKPOINT
    runtime_version = ENGLISH_ALIGNMENT_REVISION
    device = "cpu"
    sample_rate = 16000
    live_execution = False

    def prepare(self) -> None:
        raise LanguageError(
            "full-source WhisperX alignment is not configured",
            code="not_configured",
        )

    def align(self, count: int, duration_us: int) -> list[tuple[int, int]]:
        del count, duration_us
        raise LanguageError(
            "full-source WhisperX alignment is not configured. Even spans are not an alignment.",
            code="not_configured",
        )


def doctor_text() -> str:
    """Public capability matrix. Whop crawling and publishing stay out of this round."""
    lines = [
        "whop_live: not_configured",
        "publishing: deferred",
        "full_source_runtime: not_configured",
    ]
    for entry in (
        capability_for("en-US"),
        capability_for("en-GB"),
        capability_for("fr-FR"),
        capability_for("es-ES"),
        capability_for("de-DE"),
        capability_for("ar"),
        capability_for("ja"),
    ):
        claim = alignment_claim(entry.language)
        lines.append(f"{entry.language} alignment: {claim} evidence: {entry.alignment_evidence}")
        lines.append(f"{entry.language} narration: {entry.narration_evidence} reason: {entry.narration_reason}")
    lines.append("zh-CN: unsupported_language")
    return "\n".join(lines)


def list_languages() -> list[dict[str, object]]:
    return [_language_row(entry.language) for entry in _known_entries()]


def align_language(
    work_root: Path,
    database: Database,
    source_id: str,
    *,
    project_id: str,
    language: str,
    transcript_id: str,
    transcript_sha256: str,
    source_sha256: str,
    words: Sequence[tuple[str, str]],
    duration_us: int,
    provider: FullSourceAligner | None = None,
    force: bool = False,
) -> MultilingualAlignmentDocument:
    """Align one source. Unsupported languages and missing runtimes fail before a job."""
    _reject_language(language)
    chosen = provider if provider is not None else WhisperXFullSourceAligner()
    if chosen.provider_id == "whisperx":
        from clipforge.language.providers import provider_for

        record = provider_for(language)
        if record.live_status != "verified_live":
            raise LanguageError(record.unavailable_reason, code=record.live_status)
    chosen.prepare()
    if not words or duration_us <= 0:
        raise LanguageError("alignment has no words", code="missing_alignment")
    identity = _alignment_identity(
        source_sha256=source_sha256,
        transcript_sha256=transcript_sha256,
        language=language,
        provider_id=chosen.provider_id,
        model_id=chosen.model_id,
        model_revision=chosen.model_revision,
        checkpoint_sha256=chosen.checkpoint_sha256,
        runtime_version=chosen.runtime_version,
        device=chosen.device,
    )
    root = work_root.resolve()
    if not force:
        cached = _alignment_hit(root, database, identity, source_sha256)
        if cached is not None:
            return cached
    spans = chosen.align(len(words), duration_us)
    status = _alignment_status(chosen, language)
    timing = "forced" if status == "verified_live" else "approximate"
    aligned = _words(source_id, transcript_id, words, spans)
    alignment_id = "align-" + identity[:20]
    if force:
        alignment_id = f"align-{identity[:12]}-{uuid4().hex[:8]}"
    artifact = json.dumps([word.model_dump(mode="json") for word in aligned], sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(artifact).hexdigest()
    relative = f"languages/alignments/{alignment_id}/artifact.json"
    document = MultilingualAlignmentDocument(
        alignment_id=alignment_id,
        source_asset_id=source_id,
        source_sha256=source_sha256,
        transcript_id=transcript_id,
        transcript_sha256=transcript_sha256,
        language=language,
        language_tag=language,
        provider_id=chosen.provider_id,
        provider_version=chosen.provider_version,
        model_id=chosen.model_id,
        model_revision=chosen.model_revision,
        checkpoint_sha256=chosen.checkpoint_sha256,
        runtime_version=chosen.runtime_version,
        device=chosen.device,
        sample_rate=chosen.sample_rate,
        word_count=len(aligned),
        alignment_status=status,  # type: ignore[arg-type]
        timing_quality=timing,  # type: ignore[arg-type]
        artifact_sha256=digest,
        producer_job_id=str(uuid4()),
        project_id=project_id,
        relative_path=relative,
        language_capability_fingerprint=language_capability_fingerprint(),
        identity_sha256=identity,
        words=aligned,
    )
    _write_alignment(root, database, document, artifact)
    return document


def show_alignment(work_root: Path, alignment_id: str) -> MultilingualAlignmentDocument:
    return _load_alignment(work_root.resolve(), alignment_id)


def verify_alignment(
    work_root: Path,
    database: Database,
    alignment_id: str,
    *,
    source_sha256: str | None = None,
    transcript_sha256: str | None = None,
) -> str:
    """Re-check one alignment. This does not write."""
    root = work_root.resolve()
    document = _load_alignment(root, alignment_id)
    if source_sha256 is not None and source_sha256 != document.source_sha256:
        raise LanguageError("source hash changed", code="stale_source")
    if transcript_sha256 is not None and transcript_sha256 != document.transcript_sha256:
        raise LanguageError("transcript hash changed", code="stale_transcript")
    if document.language_capability_fingerprint != language_capability_fingerprint():
        raise LanguageError("language profile changed", code="stale_profile")
    _require_artifact(root, document)
    _require_job(database, document.producer_job_id, document.project_id)
    return f"PASS alignment {document.alignment_id} {document.alignment_status}"


def list_alignments(work_root: Path, source_id: str | None = None) -> list[MultilingualAlignmentDocument]:
    rows = _read_alignments(work_root.resolve())
    if source_id is None:
        return rows
    return [item for item in rows if item.source_asset_id == source_id]


def bind_verified_alignment(document: MultilingualAlignmentDocument) -> dict[str, str]:
    """Return a Hero binding only for a verified live alignment. Fakes are refused."""
    if document.alignment_status != "verified_live" or document.timing_quality != "forced":
        raise LanguageError("unverified alignment is not substituted", code="alignment_not_claimed")
    if document.provider_id != "whisperx" or not alignment_identity_matches(
        revision=document.model_revision,
        checkpoint=document.checkpoint_sha256,
        language=document.language,
    ):
        raise LanguageError(
            "alignment checkpoint is not the verified English runtime",
            code="alignment_not_claimed",
        )
    return {
        "alignment_id": document.alignment_id,
        "alignment_sha256": document.artifact_sha256,
        "source_asset_id": document.source_asset_id,
        "transcript_id": document.transcript_id,
        "transcript_sha256": document.transcript_sha256,
        "language": document.language,
    }


def narration_capabilities() -> list[NarrationCapability]:
    rows: list[NarrationCapability] = []
    for entry in _known_entries():
        rows.append(
            NarrationCapability(
                language=entry.language,
                provider_id="voicestudio" if entry.narration_evidence == "verified_live" else "none",
                status=_capability_status(entry.narration_evidence, entry.narration_reason),
                engine_id=ENGLISH_NARRATION_ENGINE if entry.narration_model else None,
                model_id=entry.narration_model,
                model_revision=entry.narration_revision,
                voice_id=ENGLISH_NARRATION_VOICE if entry.narration_model else None,
                commercial_use="allowed" if entry.license_status == "allowed" else "not_applicable",
                reason_code=entry.narration_reason,
            )
        )
    return rows


def assert_narration_request(language: str, requested: bool) -> str:
    """Unsupported requested narration fails before a render job. Omission does not."""
    if not requested:
        return "narration_not_requested"
    _reject_language(language)
    entry = capability_for(language)
    if entry.narration_evidence != "verified_live":
        raise LanguageError(entry.narration_reason, code=entry.narration_reason)
    return "verified_live"


def narrate_language(
    work_root: Path,
    database: Database,
    *,
    project_id: str,
    source_id: str,
    language: str,
    script_text: str,
    provider_id: str,
    engine_id: str,
    model_id: str,
    model_revision: str,
    voice_id: str,
    license_name: str,
    commercial_use: str,
    sample_rate: int,
    channels: int,
    duration_us: int,
    audio_sha256: str,
    force: bool = False,
    source_sha256: str = "",
    transcript_sha256: str = "",
) -> MultilingualNarrationDocument:
    """Record narration capability. A fake provider cannot become verified live."""
    assert_narration_request(language, True)
    if not provider_id or provider_id == "none":
        raise LanguageError("narration provider is missing", code="provider_unavailable")
    if license_name.strip().lower() in {"", "unknown"}:
        raise LanguageError("narration license is unknown", code="model_license_unknown")
    if commercial_use == "allowed" and model_id.lower().startswith("k2-fsa/"):
        raise LanguageError("k2-fsa models are not commercially permitted", code="license_not_permitted")
    if commercial_use != "allowed":
        raise LanguageError("narration license is not permitted", code="license_not_permitted")
    script_sha = hashlib.sha256(script_text.encode("utf-8")).hexdigest()
    from clipforge.language.providers import narration_cache_key

    identity = narration_cache_key(
        engine_id=engine_id,
        language=language,
        license_name=license_name,
        model_id=model_id,
        model_revision=model_revision,
        provider_id=provider_id,
        script_sha256=script_sha,
        source_sha256=source_sha256,
        transcript_sha256=transcript_sha256,
        voice_id=voice_id,
    )
    root = work_root.resolve()
    if not force:
        cached = _narration_hit(root, database, identity, script_sha)
        if cached is not None:
            return cached
    status = "verified_live"
    if provider_id == "fake" or engine_id != ENGLISH_NARRATION_ENGINE or model_id != ENGLISH_NARRATION_MODEL:
        status = "available_not_smoked"
    if model_revision != ENGLISH_NARRATION_REVISION or voice_id != ENGLISH_NARRATION_VOICE:
        status = "available_not_smoked"
    if license_name != ENGLISH_NARRATION_LICENSE:
        status = "available_not_smoked"
    narration_id = "narr-" + identity[:20] if not force else f"narr-{identity[:12]}-{uuid4().hex[:8]}"
    document = MultilingualNarrationDocument(
        narration_id=narration_id,
        project_id=project_id,
        source_asset_id=source_id,
        language=language,
        provider_id=provider_id,
        service_version="0.1.0",
        engine_id=engine_id,
        model_id=model_id,
        model_revision=model_revision,
        voice_id=voice_id,
        license_name=license_name,
        commercial_use="allowed",
        script_sha256=script_sha,
        audio_sha256=audio_sha256,
        sample_rate=sample_rate,
        channels=channels,
        duration_us=duration_us,
        producer_job_id=str(uuid4()),
        status=status,  # type: ignore[arg-type]
        relative_path=f"languages/narration/{narration_id}/manifest.json",
        identity_sha256=identity,
    )
    _write_narration(root, database, document)
    return document


def list_narrations(work_root: Path, source_id: str | None = None) -> list[MultilingualNarrationDocument]:
    rows = _read_narrations(work_root.resolve())
    if source_id is None:
        return rows
    return [item for item in rows if item.source_asset_id == source_id]


def verify_narration(work_root: Path, narration_id: str, *, script_sha256: str | None = None) -> str:
    document = _load_narration(work_root.resolve(), narration_id)
    if script_sha256 is not None and script_sha256 != document.script_sha256:
        raise LanguageError("script hash changed", code="stale_script")
    return f"PASS narration {document.narration_id} {document.status}"


def languages_text() -> str:
    return json.dumps([item.model_dump(mode="json") for item in narration_capabilities()], sort_keys=True)


def board_languages() -> dict[str, object]:
    payload: dict[str, object] = {
        "languages": list_languages(),
        "whop_live": "not_configured",
        "publishing": "deferred",
    }
    _reject_public(payload)
    return payload


def board_source_alignments(work_root: Path, source_id: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_id": source_id,
        "alignments": [_alignment_public(item) for item in list_alignments(work_root, source_id)],
        "publishing": "deferred",
    }
    _reject_public(payload)
    return payload


def board_source_narration(work_root: Path, source_id: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_id": source_id,
        "narrations": [_narration_public(item) for item in list_narrations(work_root, source_id)],
        "publishing": "deferred",
    }
    _reject_public(payload)
    return payload


def board_production_language(
    language: str,
    *,
    narration_enabled: bool,
    source_sha256: str | None,
    transcript_sha256: str | None,
) -> dict[str, object]:
    _reject_language(language)
    entry = capability_for(language)
    payload: dict[str, object] = {
        "language": entry.language,
        "alignment_status": alignment_claim(language),
        "alignment_evidence": entry.alignment_evidence,
        "provider_id": entry.alignment,
        "model_id": entry.alignment_model,
        "checkpoint_sha256": entry.alignment_checkpoint_sha256,
        "timing_quality": "forced" if alignment_claim(language) == "whisperx" else "unavailable",
        "narration_status": _narration_status(
            narration_enabled, entry.narration_evidence, entry.narration_reason
        ),
        "narration_evidence": entry.narration_evidence,
        "cache_status": "recorded",
        "source_sha256": source_sha256,
        "transcript_sha256": transcript_sha256,
        "whop_live": "not_configured",
        "publishing": "deferred",
    }
    _reject_public(payload)
    return payload


def _known_entries() -> tuple[LanguageCapabilityEntry, ...]:
    return (
        capability_for("en-US"),
        capability_for("en-GB"),
        capability_for("fr-FR"),
        capability_for("es-ES"),
        capability_for("de-DE"),
        capability_for("ar"),
        capability_for("ja"),
    )


def _capability_status(evidence: str, reason: str) -> CapabilityStatus:
    if evidence == "verified_live":
        return "verified_live"
    if reason == "locale_not_smoked":
        return "locale_not_smoked"
    if reason == "alignment_not_claimed":
        return "alignment_not_claimed"
    if reason == "unsupported_language":
        return "unsupported_language"
    if evidence == "available_not_smoked":
        return "available_not_smoked"
    return "not_configured"


def _narration_status(enabled: bool, evidence: str, reason: str) -> str:
    if not enabled:
        return "narration_not_requested"
    if evidence == "verified_live":
        return "verified_live"
    return reason


def _language_row(language: str) -> dict[str, object]:
    entry = capability_for(language)
    return {
        "language": entry.language,
        "alignment_status": alignment_claim(language),
        "alignment_evidence": entry.alignment_evidence,
        "provider_id": entry.alignment,
        "model_id": entry.alignment_model,
        "checkpoint_sha256": entry.alignment_checkpoint_sha256,
        "narration_status": entry.narration_evidence,
        "narration_reason": entry.narration_reason,
        "text_direction": entry.text_direction,
    }


def _reject_language(language: str) -> None:
    if language in {"zh-CN", "zh"}:
        raise LanguageError("unsupported_language", code="unsupported_language")
    try:
        require_language(language)
    except ValueError as exc:
        raise LanguageError("unsupported_language", code="unsupported_language") from exc


def _alignment_status(provider: FullSourceAligner, language: str) -> str:
    """Even spans are not a live alignment. ``verified_live`` requires a real provider run."""
    del language
    if provider.provider_id == "fake" or not provider.live_execution:
        return "available_not_smoked"
    return "alignment_not_claimed"


def _even_spans(count: int, duration_us: int) -> list[tuple[int, int]]:
    if count < 1 or duration_us < count:
        raise LanguageError("the source is too short to align every word", code="zero_length")
    spans: list[tuple[int, int]] = []
    for index in range(count):
        start = (duration_us * index) // count
        end = (duration_us * (index + 1)) // count
        if end <= start:
            raise LanguageError("alignment produced a zero-length word", code="zero_length")
        spans.append((start, end))
    return spans


def _words(
    source_id: str,
    transcript_id: str,
    words: Sequence[tuple[str, str]],
    spans: list[tuple[int, int]],
) -> list[MultilingualAlignedWord]:
    if len(words) != len(spans):
        raise LanguageError("alignment word count changed", code="corrupt_alignment")
    aligned: list[MultilingualAlignedWord] = []
    for (word_id, text), (start, end) in zip(words, spans, strict=True):
        frame_start = start * 30 // 1_000_000
        frame_end = end * 30 // 1_000_000
        if frame_end <= frame_start:
            frame_end = frame_start + 1
        aligned.append(
            MultilingualAlignedWord(
                word_id=word_id,
                text=text,
                source_start_us=start,
                source_end_us=end,
                output_start_us=start,
                output_end_us=end,
                output_start_frame=frame_start,
                output_end_frame_exclusive=frame_end,
                source_asset_id=source_id,
                transcript_id=transcript_id,
            )
        )
    return aligned


def _alignment_identity(**parts: str) -> str:
    raw = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _alignment_hit(
    root: Path, database: Database, identity: str, source_sha256: str
) -> MultilingualAlignmentDocument | None:
    for document in _read_alignments(root):
        if document.identity_sha256 != identity or document.source_sha256 != source_sha256:
            continue
        _require_artifact(root, document)
        _require_job(database, document.producer_job_id, document.project_id)
        return document.model_copy(update={"cache_status": "hit"})
    return None


def _write_alignment(
    root: Path, database: Database, document: MultilingualAlignmentDocument, artifact: bytes
) -> None:
    directory = root.joinpath(*_ALIGN_ROOT, document.alignment_id)
    mkdir_contained(root, directory)
    artifact_path = directory / "artifact.json"
    manifest_path = directory / "manifest.json"
    _insert_job(database, document.project_id, document.producer_job_id, document.alignment_id, _ALIGN_KIND)
    artifact_path.write_bytes(artifact)
    manifest_path.write_text(document.model_dump_json() + "\n", encoding="utf-8")
    _finish_job(database, document.producer_job_id, JobStatus.SUCCEEDED, None)
    cache = LanguageCapabilityCacheRecord(
        cache_id="cache-" + document.alignment_id,
        subject_id=document.alignment_id,
        kind="alignment",
        identity_sha256=document.identity_sha256,
        source_sha256=document.source_sha256,
        status="miss",
    )
    (directory / "cache.json").write_text(cache.model_dump_json() + "\n", encoding="utf-8")


def _narration_hit(
    root: Path, database: Database, identity: str, script_sha256: str
) -> MultilingualNarrationDocument | None:
    for document in _read_narrations(root):
        if document.identity_sha256 != identity or document.script_sha256 != script_sha256:
            continue
        _require_job(database, document.producer_job_id, document.project_id)
        return document.model_copy(update={"cache_status": "hit"})
    return None


def _write_narration(root: Path, database: Database, document: MultilingualNarrationDocument) -> None:
    directory = root.joinpath(*_NARRATION_ROOT, document.narration_id)
    mkdir_contained(root, directory)
    _insert_job(database, document.project_id, document.producer_job_id, document.narration_id, _NARRATION_KIND)
    (directory / "manifest.json").write_text(document.model_dump_json() + "\n", encoding="utf-8")
    _finish_job(database, document.producer_job_id, JobStatus.SUCCEEDED, None)


def _load_alignment(root: Path, alignment_id: str) -> MultilingualAlignmentDocument:
    path = root.joinpath(*_ALIGN_ROOT, alignment_id, "manifest.json")
    if path.is_symlink() or not path.is_file():
        raise LanguageError("alignment is missing", code="missing_alignment")
    try:
        return MultilingualAlignmentDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise LanguageError("alignment is corrupt", code="corrupt_alignment") from exc


def _load_narration(root: Path, narration_id: str) -> MultilingualNarrationDocument:
    path = root.joinpath(*_NARRATION_ROOT, narration_id, "manifest.json")
    if path.is_symlink() or not path.is_file():
        raise LanguageError("narration is missing", code="missing_narration")
    try:
        return MultilingualNarrationDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise LanguageError("narration is corrupt", code="corrupt_alignment") from exc


def _read_alignments(root: Path) -> list[MultilingualAlignmentDocument]:
    return _read_models(root, _ALIGN_ROOT, MultilingualAlignmentDocument)


def _read_narrations(root: Path) -> list[MultilingualNarrationDocument]:
    return _read_models(root, _NARRATION_ROOT, MultilingualNarrationDocument)


def _read_models(root: Path, parts: tuple[str, ...], model: type[_ModelT]) -> list[_ModelT]:
    base = root.joinpath(*parts)
    if base.is_symlink() or not base.is_dir():
        return []
    found: list[_ModelT] = []
    for child in sorted(base.iterdir()):
        path = child / "manifest.json"
        if child.is_symlink() or path.is_symlink() or not path.is_file():
            continue
        try:
            found.append(model.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, ValidationError):
            continue
    return found


def _require_artifact(root: Path, document: MultilingualAlignmentDocument) -> None:
    path = root / document.relative_path
    if path.is_symlink():
        raise LanguageError("alignment artifact is a symlink", code="symlink")
    if not path.is_file():
        raise LanguageError("alignment artifact is missing", code="missing_alignment")
    if sha256_file(path) != document.artifact_sha256:
        raise LanguageError("alignment artifact changed", code="corrupt_alignment")


def _require_job(database: Database, job_id: str, project_id: str) -> None:
    try:
        with database.connect() as connection:
            job = get_job(connection, job_id)
    except StorageError as exc:
        raise LanguageError("alignment producer job is missing", code="corrupt_alignment") from exc
    if job.status is not JobStatus.SUCCEEDED or job.project_id != project_id:
        raise LanguageError("alignment producer job did not succeed", code="corrupt_alignment")


def _insert_job(database: Database, project_id: str, job_id: str, subject_id: str, kind: str) -> None:
    now = datetime.now(UTC)
    record = JobRecord(
        job_id=job_id,
        project_id=project_id,
        kind=kind,
        status=JobStatus.RUNNING,
        created_at=now,
        updated_at=now,
        payload={"subject_id": subject_id},
    )
    with database.transaction() as connection:
        insert_job(connection, record)


def _finish_job(database: Database, job_id: str, status: JobStatus, error_code: str | None) -> None:
    now = datetime.now(UTC)
    with database.transaction() as connection:
        current = get_job(connection, job_id)
        update_job(
            connection,
            current.model_copy(
                update={
                    "status": status,
                    "updated_at": now,
                    "error_message": error_code if status is JobStatus.FAILED else None,
                }
            ),
        )


def _alignment_public(document: MultilingualAlignmentDocument) -> dict[str, object]:
    return {
        "alignment_id": document.alignment_id,
        "language": document.language,
        "alignment_status": document.alignment_status,
        "provider_id": document.provider_id,
        "model_id": document.model_id,
        "model_revision": document.model_revision,
        "checkpoint_sha256": document.checkpoint_sha256,
        "timing_quality": document.timing_quality,
        "cache_status": document.cache_status,
        "source_sha256": document.source_sha256,
        "transcript_sha256": document.transcript_sha256,
        "relative_path": document.relative_path,
    }


def _narration_public(document: MultilingualNarrationDocument) -> dict[str, object]:
    return {
        "narration_id": document.narration_id,
        "language": document.language,
        "status": document.status,
        "provider_id": document.provider_id,
        "engine_id": document.engine_id,
        "model_id": document.model_id,
        "model_revision": document.model_revision,
        "voice_id": document.voice_id,
        "cache_status": document.cache_status,
        "script_sha256": document.script_sha256,
        "audio_sha256": document.audio_sha256,
        "relative_path": document.relative_path,
    }


def _reject_public(payload: dict[str, object]) -> None:
    text = json.dumps(payload).lower()
    if any(token in text for token in ("/home/", "/tmp/", "/users/", "file:", "bearer ", "token=", "cookie=")):
        raise LanguageError("language board payload is not public", code="invalid_document")
