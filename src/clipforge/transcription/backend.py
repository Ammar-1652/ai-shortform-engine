"""ASR backends. Production uses faster-whisper. Tests inject another implementation.

The faster-whisper generator is consumed by the caller while the source locks
are still held. This module does not publish a transcript.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from clipforge.errors import MediaError
from clipforge.transcription.models import ModelIdentity
from clipforge.transcription.profile import DecodingProfile
from clipforge.transcription.runtime import ResolvedRuntime


@dataclass(frozen=True, slots=True)
class RawWord:
    text: str
    start_seconds: float
    end_seconds: float
    probability: float


@dataclass(frozen=True, slots=True)
class RawSegment:
    text: str
    start_seconds: float
    end_seconds: float
    words: tuple[RawWord, ...]
    avg_logprob: float | None
    no_speech_prob: float | None
    compression_ratio: float | None
    temperature: float | None


@dataclass(frozen=True, slots=True)
class InferenceInfo:
    language: str
    language_probability: float
    model_load_seconds: float


@dataclass(frozen=True, slots=True)
class InferenceHandle:
    """``segments`` may still be running the model. Exhaust it before releasing locks."""

    info: InferenceInfo
    segments: Iterator[RawSegment]


class TranscriptionBackend(Protocol):
    def transcribe(
        self,
        audio_path: Path,
        *,
        model: ModelIdentity,
        runtime: ResolvedRuntime,
        profile: DecodingProfile,
    ) -> InferenceHandle:
        """Load one model and return a segment iterator. Do not translate."""


class FasterWhisperBackend:
    """One ``WhisperModel`` per call. Sequential ``transcribe``, not the batched pipeline."""

    def transcribe(
        self,
        audio_path: Path,
        *,
        model: ModelIdentity,
        runtime: ResolvedRuntime,
        profile: DecodingProfile,
    ) -> InferenceHandle:
        if profile.task != "transcribe":
            raise MediaError("task must be transcribe")
        if profile.vad_filter:
            raise MediaError("Round 3 does not enable VAD")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise MediaError("faster-whisper is not installed. Run uv sync.") from exc
        started = time.perf_counter()
        try:
            whisper = WhisperModel(
                model.local_path,
                device=runtime.device,
                compute_type=runtime.compute_type,
                local_files_only=True,
            )
        except Exception as exc:
            raise MediaError(
                "could not load the faster-whisper model "
                f"{model.requested} on {runtime.device}/{runtime.compute_type}: "
                f"{exc.__class__.__name__}: {exc}"
            ) from exc
        load_seconds = time.perf_counter() - started
        language = None if profile.language == "auto" else profile.language
        try:
            segments, info = whisper.transcribe(
                str(audio_path),
                language=language,
                task="transcribe",
                beam_size=profile.beam_size,
                word_timestamps=True,
                vad_filter=False,
                condition_on_previous_text=profile.condition_on_previous_text,
                temperature=profile.temperature,
                log_progress=False,
            )
        except Exception as exc:
            raise MediaError(
                f"faster-whisper failed before the first segment: {exc.__class__.__name__}: {exc}"
            ) from exc
        detected = str(getattr(info, "language", "") or "")
        probability = getattr(info, "language_probability", None)
        if not isinstance(probability, (int, float)):
            raise MediaError("faster-whisper did not report a language probability")

        def iterate() -> Iterator[RawSegment]:
            try:
                for segment in segments:
                    yield _segment(segment)
            except MediaError:
                raise
            except Exception as exc:
                raise MediaError(
                    f"faster-whisper failed while reading segments: {exc.__class__.__name__}: {exc}"
                ) from exc

        return InferenceHandle(
            info=InferenceInfo(
                language=detected,
                language_probability=float(probability),
                model_load_seconds=load_seconds,
            ),
            segments=iterate(),
        )


def _segment(segment: object) -> RawSegment:
    words_raw = getattr(segment, "words", None) or []
    words: list[RawWord] = []
    for word in words_raw:
        probability = getattr(word, "probability", None)
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            raise MediaError("faster-whisper word is missing a numeric probability")
        words.append(
            RawWord(
                text=str(getattr(word, "word", "")),
                start_seconds=float(getattr(word, "start", 0.0)),
                end_seconds=float(getattr(word, "end", 0.0)),
                probability=float(probability),
            )
        )
    temperature = getattr(segment, "temperature", None)
    return RawSegment(
        text=str(getattr(segment, "text", "")),
        start_seconds=float(getattr(segment, "start", 0.0)),
        end_seconds=float(getattr(segment, "end", 0.0)),
        words=tuple(words),
        avg_logprob=_float_or_none(getattr(segment, "avg_logprob", None)),
        no_speech_prob=_float_or_none(getattr(segment, "no_speech_prob", None)),
        compression_ratio=_float_or_none(getattr(segment, "compression_ratio", None)),
        temperature=None if temperature is None else float(temperature),
    )


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MediaError(f"segment diagnostic {value!r} is not a number")
    return float(value)
