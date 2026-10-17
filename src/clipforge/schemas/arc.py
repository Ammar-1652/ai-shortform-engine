"""Source-grounded editorial arcs for reviewed Advanced Hero recuts."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.schemas.time import TimeMapDocument, digest_time_map

_SHA = r"^[0-9a-f]{64}$"


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
        return self
