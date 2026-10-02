"""Source media, probes, transcripts, scenes, and face observations.

A face observation does not identify the speaker. ``speaker_attribution`` is
fixed to ``unknown`` in schema 1.0.0. A scene cannot be marked complete from
a transcript alone.

Round 3 stores a first-pass faster-whisper transcript on the canonical source
clock. ``alignment`` stays ``approximate``. Word times are provisional.
"""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import Field, model_validator

from clipforge.errors import TimelineError
from clipforge.schemas.common import ContractModel, EntityId, Microseconds, Versioned
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import SourceTimeRange
from clipforge.timeline import FrameRate


def _require_this_source(provenance: ArtifactProvenance, source_asset_id: str, label: str) -> None:
    if source_asset_id not in provenance.source_asset_ids:
        raise ValueError(
            f"{label} provenance.source_asset_ids must include source_asset_id {source_asset_id}. "
            "A different source id is not lineage for this record."
        )


class SourceAsset(Versioned):
    """An ingested long-form file. The bytes stay at ``uri``. Ingest does not copy them."""

    source_asset_id: EntityId
    project_id: EntityId
    uri: str = Field(min_length=1, max_length=2048)
    license_record_id: EntityId
    provenance: ArtifactProvenance


class MediaProbe(Versioned):
    """ffprobe facts for one source. Duration is microseconds, not a float from ffprobe."""

    probe_id: EntityId
    source_asset_id: EntityId
    duration_us: Microseconds
    frame_rate_numerator: int | None = Field(default=None, gt=0)
    frame_rate_denominator: int | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    video_codec: str | None = None
    audio_codec: str | None = None
    container: str | None = None
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def probe_is_usable(self) -> Self:
        if self.duration_us <= 0:
            raise ValueError("duration_us must be greater than 0")
        numerator = self.frame_rate_numerator
        denominator = self.frame_rate_denominator
        if (numerator is None) != (denominator is None):
            raise ValueError("frame_rate_numerator and frame_rate_denominator must be set together")
        if numerator is not None and denominator is not None:
            try:
                FrameRate(numerator, denominator)
            except TimelineError as exc:
                raise ValueError(str(exc)) from exc
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("probe provenance.source_asset_ids must include source_asset_id")
        return self


class TranscriptWord(Versioned):
    """One word on the source clock. ``clock`` cannot be switched to output time.

    ``text`` is the engine token, including leading spaces. ``confidence`` is
    the engine word probability when the engine reported one. It is not an
    accuracy percentage.
    """

    word_id: EntityId
    text: str = Field(min_length=1)
    start_us: Microseconds
    end_us: Microseconds
    confidence: float | None = Field(default=None, ge=0, le=1)
    clock: Literal["source"] = "source"

    @model_validator(mode="after")
    def end_after_start(self) -> Self:
        if self.end_us <= self.start_us:
            raise ValueError("word end_us must be greater than start_us")
        if self.confidence is not None and not math.isfinite(self.confidence):
            raise ValueError("word confidence must be a finite probability")
        return self


class SegmentDiagnostics(ContractModel):
    """Engine evidence for one segment. These are not quality scores."""

    avg_logprob: float
    no_speech_prob: float = Field(ge=0, le=1)
    compression_ratio: float = Field(ge=0)
    temperature: float | None = None

    @model_validator(mode="after")
    def diagnostics_are_finite(self) -> Self:
        if not math.isfinite(self.avg_logprob):
            raise ValueError("avg_logprob must be finite")
        if not math.isfinite(self.no_speech_prob):
            raise ValueError("no_speech_prob must be finite")
        if not math.isfinite(self.compression_ratio):
            raise ValueError("compression_ratio must be finite")
        if self.temperature is not None and not math.isfinite(self.temperature):
            raise ValueError("segment temperature must be finite")
        return self


class TranscriptSegment(Versioned):
    """A source-clock transcript span. Words must sit inside the span."""

    segment_id: EntityId
    ordinal: int = Field(default=0, ge=0)
    start_us: Microseconds
    end_us: Microseconds
    text: str = Field(min_length=1)
    words: list[TranscriptWord] = Field(default_factory=list)
    diagnostics: SegmentDiagnostics | None = None
    clock: Literal["source"] = "source"

    @model_validator(mode="after")
    def words_fit(self) -> Self:
        if self.end_us <= self.start_us:
            raise ValueError("transcript segment end_us must be greater than start_us")
        previous: int | None = None
        for word in self.words:
            if word.start_us < self.start_us or word.end_us > self.end_us:
                raise ValueError(f"word {word.word_id} is outside segment {self.segment_id}")
            if previous is not None and word.start_us < previous:
                raise ValueError(f"word {word.word_id} starts before the previous word")
            previous = word.start_us
        return self


class Transcript(Versioned):
    """A transcript document.

    ``alignment`` is ``approximate`` for first-pass ASR timestamps and
    ``forced`` only after a later alignment pass on a selected clip.
    Round 3 writes ``approximate`` and ``timing_quality = provisional``.
    Display text is the segment texts in order. There is no second rewritten copy.
    """

    transcript_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    asr_model: str = Field(min_length=1, max_length=200)
    alignment: Literal["approximate", "forced"]
    segments: list[TranscriptSegment]
    provenance: ArtifactProvenance
    canonical_duration_us: Microseconds | None = None
    clock: Literal["canonical_video_t0"] = "canonical_video_t0"
    timing_quality: Literal["provisional"] = "provisional"
    asr_audio_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    asr_recipe_name: str | None = None
    asr_recipe_version: str | None = None
    engine: Literal["faster-whisper"] | None = None
    faster_whisper_version: str | None = None
    ctranslate2_version: str | None = None
    model_revision: str | None = None
    model_source: Literal["hub_snapshot", "local_directory"] | None = None
    device_requested: str | None = None
    device: str | None = None
    compute_type: str | None = None
    language_requested: str | None = None
    task: Literal["transcribe"] = "transcribe"
    beam_size: int | None = Field(default=None, ge=1)
    word_timestamps: bool = True
    vad_filter: bool = False
    condition_on_previous_text: bool = True
    temperature: float | None = None
    detected_language: str | None = None
    language_probability: float | None = Field(default=None, ge=0, le=1)
    speech_detected: bool | None = None
    segment_count: int | None = Field(default=None, ge=0)
    word_count: int | None = Field(default=None, ge=0)
    first_speech_us: Microseconds | None = None
    last_speech_us: Microseconds | None = None
    speech_span_us: Microseconds | None = None
    timing_adjustments: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def links_source(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("transcript provenance.source_asset_ids must include source_asset_id")
        if self.alignment == "approximate" and self.timing_quality != "provisional":
            raise ValueError("approximate alignment is provisional and cannot be marked final")
        if self.vad_filter:
            raise ValueError("Round 3 transcripts keep vad_filter false so silence stays on the clock")
        if self.temperature is not None and not math.isfinite(self.temperature):
            raise ValueError("temperature must be finite")
        if self.language_probability is not None and not math.isfinite(self.language_probability):
            raise ValueError("language_probability must be finite")
        previous: int | None = None
        for index, segment in enumerate(self.segments):
            if segment.ordinal != index:
                raise ValueError(f"segment ordinal {segment.ordinal} is not position {index}")
            if previous is not None and segment.start_us < previous:
                raise ValueError(f"segment {segment.segment_id} starts before the previous segment")
            previous = segment.start_us
        if self.segment_count is not None and self.segment_count != len(self.segments):
            raise ValueError("segment_count does not match the segments")
        words = sum(len(segment.words) for segment in self.segments)
        if self.word_count is not None and self.word_count != words:
            raise ValueError("word_count does not match the words")
        if self.speech_detected is True and not self.segments:
            raise ValueError("speech_detected cannot be true when there are no segments")
        if self.speech_detected is False and self.segments:
            raise ValueError("speech_detected cannot be false when segments exist")
        return self


class Scene(Versioned):
    """A visual scene. Completeness requires visual evidence and transcript evidence."""

    scene_id: EntityId
    source_asset_id: EntityId
    time_range: SourceTimeRange
    visual_evidence: str | None = None
    transcript_evidence: str | None = None
    analysis_complete: bool = False
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def completeness(self) -> Self:
        _require_this_source(self.provenance, self.source_asset_id, "scene")
        if self.analysis_complete and (not self.visual_evidence or not self.transcript_evidence):
            raise ValueError(
                "analysis_complete requires visual_evidence and transcript_evidence. "
                "Transcript-only analysis cannot be marked complete."
            )
        return self


class FaceObservation(Versioned):
    """A detected face over a source interval.

    Schema 1.0.0 cannot record this face as the active speaker.
    """

    observation_id: EntityId
    source_asset_id: EntityId
    time_range: SourceTimeRange
    track_id: str | None = Field(default=None, min_length=1, max_length=120)
    confidence: float = Field(ge=0, le=1)
    speaker_attribution: Literal["unknown"] = "unknown"
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def links_source(self) -> Self:
        _require_this_source(self.provenance, self.source_asset_id, "face observation")
        return self
