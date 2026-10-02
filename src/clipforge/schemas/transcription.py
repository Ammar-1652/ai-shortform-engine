"""Transcription cache and the fixed first-pass profile.

The cache record is not a media derivative sidecar. Device, model revision,
and engine versions are part of identity. ``created_at`` is not.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from clipforge.schemas.common import EntityId, Versioned


class TranscriptionProfile(Versioned):
    """Decoding choices that change transcript bytes.

    VAD stays off. The task is transcribe. Translation is not a valid profile.
    """

    profile_id: Literal["transcription-v1"] = "transcription-v1"
    model: str = Field(min_length=1, max_length=512)
    language: str = Field(min_length=2, max_length=16)
    task: Literal["transcribe"] = "transcribe"
    beam_size: int = Field(default=5, ge=1, le=16)
    word_timestamps: Literal[True] = True
    vad_filter: Literal[False] = False
    condition_on_previous_text: bool = True
    temperature: float = 0.0


class TranscriptionCacheRecord(Versioned):
    """Sidecar for one published transcript. A hit requires every identity field."""

    project_id: EntityId
    source_asset_id: EntityId
    transcript_id: EntityId
    job_id: EntityId
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_audio_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    asr_recipe_name: str = Field(min_length=1, max_length=80)
    asr_recipe_version: str = Field(min_length=1, max_length=40)
    recipe_name: str = Field(min_length=1, max_length=80)
    recipe_version: str = Field(min_length=1, max_length=40)
    faster_whisper_version: str = Field(min_length=1, max_length=40)
    ctranslate2_version: str = Field(min_length=1, max_length=40)
    model_requested: str = Field(min_length=1, max_length=512)
    model_revision: str = Field(min_length=1, max_length=128)
    model_source: Literal["hub_snapshot", "local_directory"]
    device: Literal["cpu", "cuda"]
    compute_type: str = Field(min_length=1, max_length=40)
    language: str = Field(min_length=2, max_length=16)
    decoding_fingerprint: str = Field(min_length=1, max_length=200)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    validation_status: Literal["passed"]
    created_at: AwareDatetime
