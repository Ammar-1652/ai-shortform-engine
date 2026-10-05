"""Build a typed transcript from engine segments.

Timestamps are converted and then checked. The Round 2 audio offset is not
added. Segment text and word text are copied as the engine returned them.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.schemas.media import SegmentDiagnostics, Transcript, TranscriptSegment, TranscriptWord
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.transcription.backend import RawSegment
from clipforge.transcription.constants import TIMING_TOLERANCE_US
from clipforge.transcription.models import ModelIdentity
from clipforge.transcription.profile import DecodingProfile
from clipforge.transcription.runtime import ResolvedRuntime
from clipforge.transcription.timeutil import clamp_endpoint, seconds_to_microseconds


def build_transcript(
    *,
    segments: list[RawSegment],
    canonical_duration_us: int,
    project_id: str,
    source_asset_id: str,
    asr_audio_sha256: str,
    asr_recipe_name: str,
    asr_recipe_version: str,
    model: ModelIdentity,
    runtime: ResolvedRuntime,
    profile: DecodingProfile,
    detected_language: str,
    language_probability: float,
    faster_whisper_version: str,
    ctranslate2_version: str,
    created_at: datetime,
    created_by: str,
    job_id: str,
    tool_version: str,
) -> Transcript:
    _require_probability(language_probability, "language_probability")
    if not detected_language.strip():
        raise MediaError("the engine did not report a detected language")
    adjustments: list[str] = []
    built: list[TranscriptSegment] = []
    transcript_id = str(uuid.uuid4())
    previous_start: int | None = None
    for index, raw in enumerate(segments):
        text = raw.text
        if text == "":
            raise MediaError(f"segment {index} has empty text. Clipforge did not invent words.")
        start_us, end_us, notes = _span(
            raw.start_seconds, raw.end_seconds, canonical_duration_us, f"segment {index}"
        )
        adjustments.extend(notes)
        if previous_start is not None and start_us < previous_start:
            if previous_start - start_us <= TIMING_TOLERANCE_US:
                adjustments.append(f"segment {index} start clamped from {start_us} us to {previous_start} us")
                start_us = previous_start
            else:
                raise MediaError(
                    f"segment {index} starts at {start_us} us, before the previous segment at "
                    f"{previous_start} us, by more than {TIMING_TOLERANCE_US} us. "
                    "The segments were not reordered."
                )
        if end_us <= start_us:
            raise MediaError(f"segment {index} ends at or before it starts after timing checks")
        words, word_notes = _words(
            raw,
            transcript_id=transcript_id,
            ordinal=index,
            segment_start=start_us,
            segment_end=end_us,
            duration_us=canonical_duration_us,
        )
        adjustments.extend(word_notes)
        diagnostics = _diagnostics(raw, index)
        try:
            built.append(
                TranscriptSegment(
                    segment_id=f"{transcript_id}-s{index}",
                    ordinal=index,
                    start_us=start_us,
                    end_us=end_us,
                    text=text,
                    words=words,
                    diagnostics=diagnostics,
                )
            )
        except ValidationError as exc:
            raise MediaError(f"segment {index} failed the transcript contract: {exc}") from exc
        previous_start = start_us
    word_count = sum(len(segment.words) for segment in built)
    speech = bool(built)
    first = built[0].start_us if built else None
    last = built[-1].end_us if built else None
    span = None if first is None or last is None else last - first
    try:
        return Transcript(
            transcript_id=transcript_id,
            project_id=project_id,
            source_asset_id=source_asset_id,
            asr_model=model.requested,
            alignment="approximate",
            segments=built,
            provenance=ArtifactProvenance(
                created_at=created_at,
                created_by=created_by,
                tool="faster-whisper",
                tool_version=tool_version[:80],
                source_asset_ids=[source_asset_id],
                job_id=job_id,
                inputs_sha256=asr_audio_sha256,
            ),
            canonical_duration_us=canonical_duration_us,
            asr_audio_sha256=asr_audio_sha256,
            asr_recipe_name=asr_recipe_name,
            asr_recipe_version=asr_recipe_version,
            engine="faster-whisper",
            faster_whisper_version=faster_whisper_version,
            ctranslate2_version=ctranslate2_version,
            model_revision=model.revision,
            model_source=model.source,
            device_requested=runtime.requested_device,
            device=runtime.device,
            compute_type=runtime.compute_type,
            language_requested=profile.language,
            task="transcribe",
            beam_size=profile.beam_size,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=profile.condition_on_previous_text,
            temperature=profile.temperature,
            detected_language=detected_language,
            language_probability=language_probability,
            speech_detected=speech,
            segment_count=len(built),
            word_count=word_count,
            first_speech_us=first,
            last_speech_us=last,
            speech_span_us=span,
            timing_adjustments=adjustments,
        )
    except ValidationError as exc:
        raise MediaError(f"transcript contract rejected the engine result: {exc}") from exc


def display_text(transcript: Transcript) -> str:
    """Join segment text without stripping or inserting spaces."""
    return "".join(segment.text for segment in transcript.segments)


def _span(start_seconds: float, end_seconds: float, duration_us: int, label: str) -> tuple[int, int, list[str]]:
    start_us = seconds_to_microseconds(start_seconds)
    end_us = seconds_to_microseconds(end_seconds)
    notes: list[str] = []
    start_us, start_note = clamp_endpoint(start_us, low_us=0, high_us=duration_us, label=f"{label} start")
    end_us, end_note = clamp_endpoint(end_us, low_us=0, high_us=duration_us, label=f"{label} end")
    if start_note is not None:
        notes.append(start_note)
    if end_note is not None:
        notes.append(end_note)
    if end_us < start_us:
        raise MediaError(f"{label} ends at or before its start ({start_us} us .. {end_us} us)")
    if end_us == start_us:
        if start_us + 1 > duration_us:
            raise MediaError(f"{label} ends at its start and cannot be extended inside the source")
        notes.append(f"{label} end extended by 1 us from an empty engine span ({start_us} us)")
        end_us += 1
    return start_us, end_us, notes


def _place_word(
    start_us: int,
    end_us: int,
    *,
    segment_start: int,
    segment_end: int,
    previous_start: int | None,
    label: str,
) -> tuple[int, int, list[str]]:
    """Keep a provisional word inside its segment. Text is not an argument."""
    notes: list[str] = []
    if end_us <= start_us:
        if start_us < segment_end:
            notes.append(f"{label} end extended by 1 us after segment containment ({start_us} us)")
            end_us = start_us + 1
        elif segment_end > segment_start:
            notes.append(f"{label} placed on the last microsecond of its segment")
            start_us = segment_end - 1
            end_us = segment_end
    if previous_start is not None and start_us < previous_start:
        notes.append(f"{label} start clamped from {start_us} us to {previous_start} us")
        start_us = previous_start
        if end_us <= start_us:
            if start_us < segment_end:
                notes.append(f"{label} end extended by 1 us after word-order containment ({start_us} us)")
                end_us = start_us + 1
            else:
                raise MediaError(f"{label} does not fit after the previous word")
    if start_us < segment_start or end_us > segment_end or end_us <= start_us:
        raise MediaError(f"{label} has no positive duration after timing checks")
    return start_us, end_us, notes


def _contain(value_us: int, low_us: int, high_us: int, label: str) -> tuple[int, str | None]:
    """Pull a provisional word time into its segment. The source clock was already checked."""
    if value_us < low_us:
        return low_us, f"{label} clamped from {value_us} us to {low_us} us"
    if value_us > high_us:
        return high_us, f"{label} clamped from {value_us} us to {high_us} us"
    return value_us, None


def _words(
    raw: RawSegment,
    *,
    transcript_id: str,
    ordinal: int,
    segment_start: int,
    segment_end: int,
    duration_us: int,
) -> tuple[list[TranscriptWord], list[str]]:
    words: list[TranscriptWord] = []
    notes: list[str] = []
    previous: int | None = None
    for index, raw_word in enumerate(raw.words):
        if raw_word.text == "":
            raise MediaError(f"segment {ordinal} word {index} is empty. The engine text was not rewritten.")
        _require_probability(raw_word.probability, f"segment {ordinal} word {index} probability")
        start_us, end_us, span_notes = _span(
            raw_word.start_seconds,
            raw_word.end_seconds,
            duration_us,
            f"segment {ordinal} word {index}",
        )
        notes.extend(span_notes)
        start_label = f"segment {ordinal} word {index} start"
        end_label = f"segment {ordinal} word {index} end"
        start_us, start_note = _contain(start_us, segment_start, segment_end, start_label)
        end_us, end_note = _contain(end_us, segment_start, segment_end, end_label)
        if start_note is not None:
            notes.append(start_note)
        if end_note is not None:
            notes.append(end_note)
        start_us, end_us, placed = _place_word(
            start_us,
            end_us,
            segment_start=segment_start,
            segment_end=segment_end,
            previous_start=previous,
            label=f"segment {ordinal} word {index}",
        )
        notes.extend(placed)
        try:
            words.append(
                TranscriptWord(
                    word_id=f"{transcript_id}-s{ordinal}-w{index}",
                    text=raw_word.text,
                    start_us=start_us,
                    end_us=end_us,
                    confidence=raw_word.probability,
                )
            )
        except ValidationError as exc:
            raise MediaError(f"segment {ordinal} word {index} failed the word contract: {exc}") from exc
        previous = start_us
    return words, notes


def _diagnostics(raw: RawSegment, index: int) -> SegmentDiagnostics | None:
    if raw.avg_logprob is None or raw.no_speech_prob is None or raw.compression_ratio is None:
        return None
    _require_probability(raw.no_speech_prob, f"segment {index} no_speech_prob")
    if not math.isfinite(raw.avg_logprob):
        raise MediaError(f"segment {index} avg_logprob is not finite")
    if not math.isfinite(raw.compression_ratio) or raw.compression_ratio < 0:
        raise MediaError(f"segment {index} compression_ratio is not a finite non-negative number")
    if raw.temperature is not None and not math.isfinite(raw.temperature):
        raise MediaError(f"segment {index} temperature is not finite")
    try:
        return SegmentDiagnostics(
            avg_logprob=raw.avg_logprob,
            no_speech_prob=raw.no_speech_prob,
            compression_ratio=raw.compression_ratio,
            temperature=raw.temperature,
        )
    except ValidationError as exc:
        raise MediaError(f"segment {index} diagnostics were rejected: {exc}") from exc


def _require_probability(value: float, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise MediaError(f"{label} is not a finite number")
    if value < 0 or value > 1:
        raise MediaError(f"{label} is {value}, outside 0..1. Clipforge did not clamp it.")
