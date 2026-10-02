"""Canonical timeline mapping. Other modules must not invent a second conversion."""

from clipforge.timeline.framerate import (
    NAMED_FRAME_RATES,
    FrameRate,
    frame_index_at,
    frame_start_us,
)
from clipforge.timeline.mapper import MappedSegment, SegmentSpec, TimeMap, validate_placement

__all__ = [
    "NAMED_FRAME_RATES",
    "FrameRate",
    "MappedSegment",
    "SegmentSpec",
    "TimeMap",
    "frame_index_at",
    "frame_start_us",
    "validate_placement",
]
