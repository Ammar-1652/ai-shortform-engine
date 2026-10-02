"""Persisted timing documents. Output placement is derived, not stored twice."""

from __future__ import annotations

import hashlib
import json
from typing import Self

from pydantic import ConfigDict, model_validator

from clipforge.errors import TimelineError
from clipforge.schemas.common import ContractModel, EntityId, Microseconds, Versioned
from clipforge.timeline import SegmentSpec, TimeMap


class SourceTimeRange(ContractModel):
    """A source-clock interval. Both ends are integer microseconds and ``end_us`` is later than ``start_us``."""

    start_us: Microseconds
    end_us: Microseconds

    @model_validator(mode="after")
    def end_after_start(self) -> Self:
        if self.end_us <= self.start_us:
            raise ValueError("end_us must be greater than start_us")
        return self


class TimelineSegment(Versioned):
    """One kept source range. Output position is the index of this segment in its time map."""

    segment_id: EntityId
    source_start_us: Microseconds
    source_end_us: Microseconds

    @model_validator(mode="after")
    def end_after_start(self) -> Self:
        if self.source_end_us <= self.source_start_us:
            raise ValueError("source_end_us must be greater than source_start_us")
        return self


class TimeMapDocument(Versioned):
    """Ordered source ranges. This is the only persisted jump-cut map.

    The JSON Schema title is ``TimeMap``. Output intervals are a pure function
    of this list via ``to_time_map`` and are not stored separately.
    """

    model_config = ConfigDict(extra="forbid", title="TimeMap")

    time_map_id: EntityId
    segments: list[TimelineSegment]

    @model_validator(mode="after")
    def placement_is_legal(self) -> Self:
        try:
            self.to_time_map()
        except TimelineError as exc:
            raise ValueError(str(exc)) from exc
        return self

    def to_time_map(self) -> TimeMap:
        """Build the runtime map. Raises ``TimelineError`` when the ranges are illegal."""
        return TimeMap(
            [
                SegmentSpec(
                    segment_id=segment.segment_id,
                    source_start_us=segment.source_start_us,
                    source_end_us=segment.source_end_us,
                )
                for segment in self.segments
            ]
        )


def digest_time_map(document: TimeMapDocument) -> str:
    """SHA-256 of the canonical JSON for a time map.

    Edit plans store this digest so a timing edit cannot leave captions and
    graphics attached to a map they were not built for.
    """
    payload = document.model_dump(mode="json")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
