"""Transcript cache identity. File existence alone is not a hit."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.schemas.media import Transcript
from clipforge.schemas.transcription import TranscriptionCacheRecord
from clipforge.transcription.integrity import document_sidecar_problems
from clipforge.transcription.io import read_text
from clipforge.transcription.models import ModelIdentity
from clipforge.transcription.profile import DecodingProfile
from clipforge.transcription.runtime import ResolvedRuntime


def read_transcript_cache(path: Path) -> TranscriptionCacheRecord | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        return TranscriptionCacheRecord.model_validate_json(read_text(path))
    except (OSError, ValidationError, UnicodeError):
        return None


def cache_identity_matches(
    record: TranscriptionCacheRecord,
    *,
    project_id: str,
    source_asset_id: str,
    source_sha256: str,
    input_audio_sha256: str,
    asr_recipe_name: str,
    asr_recipe_version: str,
    recipe_name: str,
    recipe_version: str,
    faster_whisper_version: str,
    ctranslate2_version: str,
    model: ModelIdentity,
    runtime: ResolvedRuntime,
    profile: DecodingProfile,
    transcript_path: Path,
) -> bool:
    if record.project_id != project_id or record.source_asset_id != source_asset_id:
        return False
    if record.source_sha256 != source_sha256 or record.input_audio_sha256 != input_audio_sha256:
        return False
    if record.asr_recipe_name != asr_recipe_name or record.asr_recipe_version != asr_recipe_version:
        return False
    if record.recipe_name != recipe_name or record.recipe_version != recipe_version:
        return False
    if record.faster_whisper_version != faster_whisper_version:
        return False
    if record.ctranslate2_version != ctranslate2_version:
        return False
    if record.model_requested != model.requested or record.model_revision != model.revision:
        return False
    if record.model_source != model.source:
        return False
    if record.device != runtime.device or record.compute_type != runtime.compute_type:
        return False
    if record.language != profile.language or record.decoding_fingerprint != profile.fingerprint():
        return False
    if not transcript_path.is_file():
        return False
    try:
        size = transcript_path.stat().st_size
        digest = sha256_file(transcript_path)
        document = Transcript.model_validate_json(read_text(transcript_path))
    except (OSError, ValidationError, UnicodeError, MediaError):
        return False
    if size != record.size_bytes or digest != record.artifact_sha256:
        return False
    if document.project_id != project_id or document.source_asset_id != source_asset_id:
        return False
    if document_sidecar_problems(document, record):
        return False
    return document.model_revision == model.revision and document.device == runtime.device
