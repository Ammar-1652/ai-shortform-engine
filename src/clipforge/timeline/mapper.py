"""Piecewise source-to-output map for jump cuts.

V1 does not retime. Each kept source range keeps its duration and is placed
on the output timeline in list order, starting at 0, with no gaps.

See ``docs/architecture/time-mapping.md`` for the normative boundary rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from clipforge.errors import (
    AmbiguousTimeError,
    FrameOutOfRangeError,
    InvalidTimeMapError,
    TimeNotMappedError,
)
from clipforge.timeline.framerate import FrameRate, frame_index_at, frame_start_us

# Seven days. The cap stays inside JavaScript's safe integer range (2^53 - 1)
# so exported microsecond values survive a later TypeScript consumer.
MAX_TIMELINE_US = 7 * 24 * 60 * 60 * 1_000_000


@dataclass(frozen=True, slots=True)
class SegmentSpec:
    """One kept source range, before output placement."""

    segment_id: str
    source_start_us: int
    source_end_us: int


@dataclass(frozen=True, slots=True)
class MappedSegment:
    """One source range and the output interval it occupies.

    ``output_end_us - output_start_us`` equals ``source_end_us - source_start_us``.
    """

    segment_id: str
    source_start_us: int
    source_end_us: int
    output_start_us: int
    output_end_us: int


class TimeMap:
    """Deterministic jump-cut map. Lookups raise. They never return None."""

    def __init__(self, segments: Sequence[SegmentSpec]) -> None:
        raw: object = segments
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise InvalidTimeMapError("segments must be a sequence of SegmentSpec values")
        placed: list[MappedSegment] = []
        cursor = 0
        for spec in segments:
            if not isinstance(spec, SegmentSpec):
                raise InvalidTimeMapError(
                    "each segment must be a SegmentSpec. "
                    f"Got {type(spec).__name__}. Refusing to guess the field order."
                )
            start = _require_us("source_start_us", spec.source_start_us)
            end = _require_us("source_end_us", spec.source_end_us)
            if end <= start:
                raise InvalidTimeMapError(
                    f"segment {spec.segment_id!r} has source_end_us {end} "
                    f"which is not greater than source_start_us {start}"
                )
            duration = end - start
            placed.append(
                MappedSegment(
                    segment_id=spec.segment_id,
                    source_start_us=start,
                    source_end_us=end,
                    output_start_us=cursor,
                    output_end_us=cursor + duration,
                )
            )
            cursor += duration
        validate_placement(placed)
        self._segments = tuple(placed)

    @classmethod
    def from_source_ranges(cls, ranges: Sequence[tuple[int, int]]) -> TimeMap:
        """Build a map from ``(source_start_us, source_end_us)`` pairs, in output order.

        Generated ids are ``seg-0``, ``seg-1``, ... and are stable for the same input order.
        """
        specs: list[SegmentSpec] = []
        for index, pair in enumerate(ranges):
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise InvalidTimeMapError(f"range {index} must be a (start_us, end_us) tuple, got {pair!r}")
            specs.append(
                SegmentSpec(
                    segment_id=f"seg-{index}",
                    source_start_us=pair[0],
                    source_end_us=pair[1],
                )
            )
        return cls(specs)

    @property
    def segments(self) -> tuple[MappedSegment, ...]:
        return self._segments

    def total_output_duration(self) -> int:
        """Return the output duration in integer microseconds."""
        if not self._segments:
            return 0
        return self._segments[-1].output_end_us

    def source_to_output(self, source_us: int) -> int:
        """Map a source timestamp to the output timeline.

        A source endpoint that is also the next range's start maps to one output
        time only when construction proved those outputs are equal.
        """
        source_us = _require_lookup_us("source time", source_us)
        hits = [
            _output_at(segment, source_us)
            for segment in self._segments
            if segment.source_start_us <= source_us <= segment.source_end_us
        ]
        unique = set(hits)
        if len(unique) == 1:
            return next(iter(unique))
        if not unique:
            raise TimeNotMappedError(f"source time {source_us} us is outside every source range in this map")
        raise AmbiguousTimeError(
            f"source time {source_us} us maps to output times {sorted(unique)}. "
            "Construction should have rejected this map."
        )

    def output_to_source(self, output_us: int) -> int:
        """Map an output timestamp back to source.

        Interior cuts belong to the following segment. The exact timeline end
        belongs to the last segment's source end.
        """
        output_us = _require_lookup_us("output time", output_us)
        if not self._segments:
            raise TimeNotMappedError(
                f"output time {output_us} us is not mapped because the time map has no segments"
            )
        duration = self.total_output_duration()
        if output_us > duration:
            raise TimeNotMappedError(f"output time {output_us} us is past the timeline end {duration} us")
        for segment in self._segments:
            if segment.output_start_us <= output_us < segment.output_end_us:
                return segment.source_start_us + (output_us - segment.output_start_us)
            if output_us == duration and output_us == segment.output_end_us:
                return segment.source_end_us
        raise TimeNotMappedError(
            f"output time {output_us} us falls in a gap. Construction should have rejected this map."
        )

    def output_frame_to_source(self, frame: int, fps: FrameRate | str | tuple[int, int]) -> int:
        """Map the start of an output frame to source time.

        The frame must start strictly before the output duration. The frame that
        starts exactly at the endpoint is rejected.
        """
        rate = FrameRate.parse(fps)
        start = frame_start_us(frame, rate)
        duration = self.total_output_duration()
        if start >= duration:
            raise FrameOutOfRangeError(
                f"frame {frame} starts at {start} us, outside the output duration {duration} us at {rate} fps"
            )
        return self.output_to_source(start)

    def source_to_output_frame(self, source_us: int, fps: FrameRate | str | tuple[int, int]) -> int:
        """Map a source time to the output frame that contains the corresponding output time.

        The exact output endpoint is not inside a frame and raises ``FrameOutOfRangeError``.
        """
        rate = FrameRate.parse(fps)
        output_us = self.source_to_output(source_us)
        duration = self.total_output_duration()
        if output_us >= duration:
            raise FrameOutOfRangeError(
                f"source time {source_us} us maps to output {output_us} us, the timeline endpoint "
                f"({duration} us). That instant is not inside a frame."
            )
        return frame_index_at(output_us, rate)

    def output_frame_count(self, fps: FrameRate | str | tuple[int, int]) -> int:
        """Return how many frames start strictly before the output duration."""
        rate = FrameRate.parse(fps)
        duration = self.total_output_duration()
        if duration == 0:
            return 0
        # The integer estimate is at most one frame off because frame starts truncate.
        count = (duration * rate.numerator) // (rate.denominator * 1_000_000)
        for _ in range(3):
            if count > 0 and frame_start_us(count - 1, rate) >= duration:
                count -= 1
                continue
            if frame_start_us(count, rate) < duration:
                count += 1
                continue
            return count
        raise FrameOutOfRangeError(f"could not count frames for duration {duration} us at {rate} fps")


def validate_placement(segments: Sequence[MappedSegment]) -> None:
    """Reject gaps, overlaps, retiming, duplicate ids, and ambiguous source points.

    Output ranges must tile ``[0, duration]`` in the order given. This function
    does not sort and does not drop a bad segment.
    """
    previous_output_end = 0
    seen_ids: set[str] = set()
    compiled: list[MappedSegment] = []
    for segment in segments:
        _validate_id(segment.segment_id)
        for name, value in (
            ("source_start_us", segment.source_start_us),
            ("source_end_us", segment.source_end_us),
            ("output_start_us", segment.output_start_us),
            ("output_end_us", segment.output_end_us),
        ):
            _require_us(name, value)
        if segment.source_end_us <= segment.source_start_us:
            raise InvalidTimeMapError(f"segment {segment.segment_id} source range is empty or reversed")
        if segment.output_end_us <= segment.output_start_us:
            raise InvalidTimeMapError(f"segment {segment.segment_id} output range is empty or reversed")
        source_duration = segment.source_end_us - segment.source_start_us
        output_duration = segment.output_end_us - segment.output_start_us
        if source_duration != output_duration:
            raise InvalidTimeMapError(
                f"segment {segment.segment_id} changes speed: source duration "
                f"{source_duration} us != output duration {output_duration} us. "
                "V1 does not retime."
            )
        if segment.segment_id in seen_ids:
            raise InvalidTimeMapError(f"duplicate segment id {segment.segment_id}")
        seen_ids.add(segment.segment_id)
        if segment.output_start_us != previous_output_end:
            if segment.output_start_us > previous_output_end:
                raise InvalidTimeMapError(
                    f"output gap before segment {segment.segment_id}: expected start "
                    f"{previous_output_end} us, got {segment.output_start_us} us"
                )
            raise InvalidTimeMapError(
                f"output overlap at segment {segment.segment_id}: start "
                f"{segment.output_start_us} us is before the covered end {previous_output_end} us"
            )
        previous_output_end = segment.output_end_us
        compiled.append(segment)

    for index, left in enumerate(compiled):
        for right in compiled[index + 1 :]:
            _reject_source_conflict(left, right)


def _reject_source_conflict(left: MappedSegment, right: MappedSegment) -> None:
    if left.source_end_us < right.source_start_us or right.source_end_us < left.source_start_us:
        return
    overlap_start = max(left.source_start_us, right.source_start_us)
    overlap_end = min(left.source_end_us, right.source_end_us)
    if overlap_start < overlap_end:
        raise InvalidTimeMapError(
            f"source ranges overlap between {left.segment_id} and {right.segment_id}: "
            f"{overlap_start}..{overlap_end} us"
        )
    out_left = _output_at(left, overlap_start)
    out_right = _output_at(right, overlap_start)
    if out_left != out_right:
        raise InvalidTimeMapError(
            f"source time {overlap_start} us is shared by {left.segment_id} and {right.segment_id} "
            f"but maps to output {out_left} us and {out_right} us. "
            "A source instant must have one output time."
        )


def _output_at(segment: MappedSegment, source_us: int) -> int:
    return segment.output_start_us + (source_us - segment.source_start_us)


def _validate_id(segment_id: str) -> None:
    if not isinstance(segment_id, str) or not segment_id.strip():
        raise InvalidTimeMapError(f"segment id must be a non-empty string, got {segment_id!r}")


def _require_us(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidTimeMapError(f"{name} must be an integer microsecond value, got {type(value).__name__}")
    if value < 0:
        raise InvalidTimeMapError(f"{name} must be >= 0, got {value}")
    if value > MAX_TIMELINE_US:
        raise InvalidTimeMapError(f"{name} {value} exceeds the {MAX_TIMELINE_US} us cap (7 days)")
    return value


def _require_lookup_us(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TimeNotMappedError(f"{name} must be an integer microsecond value, got {type(value).__name__}")
    if value < 0:
        raise TimeNotMappedError(f"{name} {value} us is negative and is not on the timeline")
    if value > MAX_TIMELINE_US:
        raise TimeNotMappedError(f"{name} {value} us exceeds the {MAX_TIMELINE_US} us cap")
    return value
