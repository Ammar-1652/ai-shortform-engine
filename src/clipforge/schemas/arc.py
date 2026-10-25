"""Source-grounded editorial arcs for reviewed Advanced Hero recuts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimeMapDocument, digest_time_map

_SHA = r"^[0-9a-f]{64}$"


class EditorialArcReviewBeat(Versioned):
    """Inspectible evidence for one source-grounded story beat."""

    beat_id: EntityId
    segment_id: EntityId
    beat: Literal["hook", "body", "punch"]
    source_start_us: Microseconds
    source_end_us: Microseconds
    transcript_word_ids: list[EntityId] = Field(min_length=1)
    representative_frame_relative_path: str = Field(min_length=1, max_length=512)
    representative_frame_sha256: str = Field(pattern=_SHA)
    subject_label: str = Field(min_length=1, max_length=120)
    event_label: str = Field(min_length=1, max_length=160)
    continuity_to_next: Literal["accepted", "requires_review", "not_applicable"]
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def range_is_positive(self) -> Self:
        if self.source_end_us <= self.source_start_us:
            raise ValueError("arc review beat must have a positive source range")
        if self.representative_frame_relative_path.startswith(
            "/"
        ) or ".." in self.representative_frame_relative_path.split("/"):
            raise ValueError("arc review frame path must be work-root relative")
        return self


class EditorialArcReview(Versioned):
    """Immutable editorial review of hook/body/punch continuity and closure."""

    review_id: EntityId
    campaign: Literal["tarteel", "generic"] = "generic"
    source_asset_id: EntityId
    candidate_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    transcript_sha256: str = Field(pattern=_SHA)
    visual_analysis_sha256: str = Field(pattern=_SHA)
    arc_sha256: str = Field(pattern=_SHA)
    hook_promise: str = Field(min_length=1, max_length=300)
    body_development: str = Field(min_length=1, max_length=500)
    punch_payoff: str = Field(min_length=1, max_length=300)
    beats: list[EditorialArcReviewBeat] = Field(min_length=3)
    decision: Literal["accepted", "rejected"]
    reviewer: str = Field(min_length=1, max_length=120)
    reviewer_role: Literal["codex_operator", "human_reviewer"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    reviewed_at: AwareDatetime
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def beats_are_ordered(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("arc review provenance must include its source")
        order = [beat.beat for beat in self.beats]
        if order[0] != "hook" or order[-1] != "punch" or any(item != "body" for item in order[1:-1]):
            raise ValueError("arc review beats must be ordered hook, body, punch")
        if len({beat.beat_id for beat in self.beats}) != len(self.beats):
            raise ValueError("arc review beat ids must be unique")
        if self.decision == "accepted" and any(
            beat.continuity_to_next == "requires_review" for beat in self.beats[:-1]
        ):
            raise ValueError("accepted arc review cannot retain unresolved continuity")
        return self


class EditorialArcSegment(Versioned):
    """One ordered source range and the exact forced words it carries."""

    segment_id: EntityId
    source_start_us: Microseconds
    source_end_us: Microseconds
    word_ids: list[EntityId] = Field(min_length=1)
    beat: Literal["hook", "body", "punch"]
    purpose: str = Field(min_length=1, max_length=240)
    continuation: bool = False
    claim_closure: Literal["complete", "requires_review"] = "requires_review"

    @model_validator(mode="after")
    def range_is_positive(self) -> Self:
        if self.source_end_us <= self.source_start_us:
            raise ValueError("editorial arc segment must have a positive source range")
        if len(set(self.word_ids)) != len(self.word_ids):
            raise ValueError("editorial arc segment word ids must be unique")
        return self


class EditorialArcDocument(Versioned):
    """A reviewed declarative hook/body/punch source assembly."""

    arc_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    hero_plan_sha256: str = Field(pattern=_SHA)
    alignment_sha256: str = Field(pattern=_SHA)
    time_map: TimeMapDocument
    time_map_sha256: str = Field(pattern=_SHA)
    segments: list[EditorialArcSegment] = Field(min_length=3, max_length=12)
    # Explicitly records the first forced word selected by editorial review.
    # The field is optional for old non-campaign arcs, but Tarteel production
    # requires it so a filler opener cannot be introduced implicitly.
    opening_word_id: EntityId | None = None
    opening_boundary_note: str = Field(default="", max_length=240)
    selection_mode: Literal["operator_override", "reviewed"] = "operator_override"
    transition_style: Literal[
        "none",
        "clean_cut_v1",
        "concat_push_v1",
        "concat_blur_dissolve_v1",
    ] = "none"

    @model_validator(mode="after")
    def is_ordered_and_source_bound(self) -> Self:
        if digest_time_map(self.time_map) != self.time_map_sha256:
            raise ValueError("editorial arc time_map_sha256 does not match time_map")
        if len(self.segments) != len(self.time_map.segments):
            raise ValueError("editorial arc segments must match the TimeMap segments")
        if [item.segment_id for item in self.segments] != [item.segment_id for item in self.time_map.segments]:
            raise ValueError("editorial arc segment order must match the TimeMap")
        for arc, mapped in zip(self.segments, self.time_map.segments, strict=True):
            if arc.source_start_us != mapped.source_start_us or arc.source_end_us != mapped.source_end_us:
                raise ValueError("editorial arc segment range must match its TimeMap segment")
        beats = [item.beat for item in self.segments]
        if beats[0] != "hook" or beats[-1] != "punch" or any(item != "body" for item in beats[1:-1]):
            raise ValueError("editorial arc must be ordered hook, body, punch")
        for index, left in enumerate(self.segments):
            for right in self.segments[index + 1 :]:
                if left.source_start_us < right.source_end_us and right.source_start_us < left.source_end_us:
                    raise ValueError("editorial arc source ranges overlap")
        words = [word_id for segment in self.segments for word_id in segment.word_ids]
        if len(set(words)) != len(words):
            raise ValueError("editorial arc cannot reuse a forced word")
        if self.opening_word_id is not None and self.opening_word_id != self.segments[0].word_ids[0]:
            raise ValueError("editorial arc opening_word_id must match the first hook word")
        if self.opening_word_id is not None and not self.opening_boundary_note.strip():
            raise ValueError("editorial arc opening boundary requires a review note")
        return self
