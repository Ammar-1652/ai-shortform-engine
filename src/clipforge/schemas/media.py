"""Source media, probes, transcripts, scenes, and face observations.

A face observation does not identify the speaker. ``speaker_attribution`` is
fixed to ``unknown`` in schema 1.0.0. A scene cannot be marked complete from
a transcript alone.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from clipforge.errors import TimelineError
from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import SourceTimeRange
from clipforge.timeline import FrameRate


def _require_source(provenance: ArtifactProvenance, label: str) -> None:
    if not provenance.source_asset_ids:
        raise ValueError(f"{label} provenance must list at least one source_asset_id")


class SourceAsset(Versioned):
    """An ingested long-form file. Round 1 stores the record. It does not ingest bytes."""

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
    """One word on the source clock. ``clock`` cannot be switched to output time."""

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
        return self


class TranscriptSegment(Versioned):
    """A source-clock transcript span. Words must sit inside the span."""

    segment_id: EntityId
    start_us: Microseconds
    end_us: Microseconds
    text: str = Field(min_length=1)
    words: list[TranscriptWord] = Field(default_factory=list)
    clock: Literal["source"] = "source"

    @model_validator(mode="after")
    def words_fit(self) -> Self:
        if self.end_us <= self.start_us:
            raise ValueError("transcript segment end_us must be greater than start_us")
        for word in self.words:
            if word.start_us < self.start_us or word.end_us > self.end_us:
                raise ValueError(f"word {word.word_id} is outside segment {self.segment_id}")
        return self


class Transcript(Versioned):
    """A transcript document.

    ``alignment`` is ``approximate`` for first-pass ASR timestamps and
    ``forced`` only after a later alignment pass on a selected clip.
    """

    transcript_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    asr_model: str = Field(min_length=1, max_length=200)
    alignment: Literal["approximate", "forced"]
    segments: list[TranscriptSegment]
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def links_source(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("transcript provenance.source_asset_ids must include source_asset_id")
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
        _require_source(self.provenance, "scene")
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
        _require_source(self.provenance, "face observation")
        return self
