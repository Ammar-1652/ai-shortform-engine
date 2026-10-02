"""The request a caller may change, and the decoding profile they may not casually rewrite."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from clipforge.errors import MediaError
from clipforge.transcription.constants import (
    BEAM_SIZE,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    ENGLISH_ONLY_SUFFIX,
    TASK,
    TEMPERATURE,
)

_DEVICES = frozenset({"auto", "cpu", "cuda"})


@dataclass(frozen=True, slots=True)
class TranscriptionRequest:
    """Caller overrides. Decoding knobs other than these stay on the v1 profile."""

    model: str = DEFAULT_MODEL
    language: str = DEFAULT_LANGUAGE
    device: str = "auto"
    compute_type: str = "auto"
    allow_model_download: bool = False
    force: bool = False


@dataclass(frozen=True, slots=True)
class DecodingProfile:
    task: str
    beam_size: int
    word_timestamps: bool
    vad_filter: bool
    condition_on_previous_text: bool
    temperature: float
    language: str

    def fingerprint(self) -> str:
        payload = {
            "beam_size": self.beam_size,
            "condition_on_previous_text": self.condition_on_previous_text,
            "language": self.language,
            "task": self.task,
            "temperature": format(self.temperature, "f"),
            "vad_filter": self.vad_filter,
            "word_timestamps": self.word_timestamps,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def normalize_request(request: TranscriptionRequest) -> TranscriptionRequest:
    model = request.model.strip()
    language = request.language.strip().lower()
    device = request.device.strip().lower()
    compute_type = request.compute_type.strip().lower()
    if not model:
        raise MediaError("model id is empty")
    if len(model) > 512:
        raise MediaError("model id is longer than 512 characters")
    if device not in _DEVICES:
        raise MediaError("device must be auto, cpu, or cuda")
    if not compute_type:
        raise MediaError("compute type is empty")
    if language in {"translate", "translation"}:
        raise MediaError("Round 3 only transcribes. Translation is not available.")
    letters = language.replace("-", "")
    if language != "auto" and (len(language) < 2 or len(language) > 16 or not letters.isalpha()):
        raise MediaError(
            f"language {language!r} is not 'auto' or a language code such as en. Round 3 does not translate."
        )
    if _english_only(model) and language not in {"en", "auto"}:
        raise MediaError(
            f"model {model} is English-only. It cannot transcribe language {language!r}. "
            "Use --language en, or choose a multilingual model."
        )
    if _english_only(model) and language == "auto":
        raise MediaError(
            f"model {model} is English-only, so language detection would not be multilingual. "
            "Pass --language en. Clipforge will not pretend this model detected a language."
        )
    return TranscriptionRequest(
        model=model,
        language=language,
        device=device,
        compute_type=compute_type,
        allow_model_download=request.allow_model_download,
        force=request.force,
    )


def decoding_profile(language: str) -> DecodingProfile:
    if language in {"translate", "translation"}:
        raise MediaError("task must be transcribe")
    return DecodingProfile(
        task=TASK,
        beam_size=BEAM_SIZE,
        word_timestamps=True,
        vad_filter=False,
        condition_on_previous_text=True,
        temperature=TEMPERATURE,
        language=language,
    )


def _english_only(model: str) -> bool:
    name = model.rsplit("/", 1)[-1]
    return name.endswith(ENGLISH_ONLY_SUFFIX)
