"""Canonical time-map tests. Boundary behavior is locked here."""

from __future__ import annotations

import pytest

from clipforge.errors import (
    FrameOutOfRangeError,
    InvalidFrameRateError,
    InvalidTimeMapError,
    TimeNotMappedError,
)
from clipforge.timeline import (
    FrameRate,
    MappedSegment,
    SegmentSpec,
    TimeMap,
    frame_index_at,
    frame_start_us,
    validate_placement,
)

US = 1_000_000


def _jump() -> TimeMap:
    """10-15s and 20-25s become output 0-5s and 5-10s."""
    return TimeMap.from_source_ranges([(10 * US, 15 * US), (20 * US, 25 * US)])


def test_single_continuous_range_is_identity() -> None:
    timeline = TimeMap.from_source_ranges([(0, 10 * US)])
    assert timeline.total_output_duration() == 10 * US
    assert timeline.source_to_output(0) == 0
    assert timeline.source_to_output(10 * US) == 10 * US
    assert timeline.output_to_source(0) == 0
    assert timeline.output_to_source(10 * US) == 10 * US
    assert timeline.output_to_source(4 * US) == 4 * US


def test_non_zero_source_offset() -> None:
    timeline = TimeMap.from_source_ranges([(10 * US, 12 * US)])
    assert timeline.source_to_output(11 * US) == US
    assert timeline.output_to_source(0) == 10 * US
    assert timeline.output_to_source(2 * US) == 12 * US


def test_jump_cuts_and_exact_boundaries() -> None:
    timeline = _jump()
    assert timeline.total_output_duration() == 10 * US
    assert timeline.source_to_output(12 * US) == 2 * US
    assert timeline.source_to_output(22 * US) == 7 * US
    assert timeline.source_to_output(15 * US) == 5 * US
    assert timeline.source_to_output(20 * US) == 5 * US
    assert timeline.output_to_source(0) == 10 * US
    assert timeline.output_to_source(4_999_999) == 14_999_999
    # The interior cut belongs to the following segment.
    assert timeline.output_to_source(5 * US) == 20 * US
    assert timeline.output_to_source(10 * US) == 25 * US


def test_source_order_is_not_sorted() -> None:
    timeline = TimeMap.from_source_ranges([(20 * US, 25 * US), (0, 2 * US)])
    assert timeline.source_to_output(20 * US) == 0
    assert timeline.source_to_output(US) == 6 * US
    assert timeline.output_to_source(5 * US) == 0


def test_decimal_microsecond_ranges() -> None:
    timeline = TimeMap.from_source_ranges([(1_500_000, 3_250_000)])
    assert timeline.total_output_duration() == 1_750_000
    assert timeline.source_to_output(2_000_000) == 500_000
    assert timeline.output_to_source(500_000) == 2_000_000


def test_touching_source_ranges_share_one_output_instant() -> None:
    timeline = TimeMap.from_source_ranges([(10 * US, 15 * US), (15 * US, 20 * US)])
    assert timeline.source_to_output(15 * US) == 5 * US
    assert timeline.output_to_source(5 * US) == 15 * US


def test_reversed_touching_ranges_are_ambiguous() -> None:
    with pytest.raises(InvalidTimeMapError, match="one output time"):
        TimeMap.from_source_ranges([(15 * US, 20 * US), (10 * US, 15 * US)])


def test_overlapping_source_ranges_are_rejected() -> None:
    with pytest.raises(InvalidTimeMapError, match="overlap"):
        TimeMap.from_source_ranges([(10 * US, 15 * US), (14 * US, 18 * US)])


def test_empty_reversed_negative_and_non_integer_ranges() -> None:
    with pytest.raises(InvalidTimeMapError):
        TimeMap.from_source_ranges([(5, 5)])
    with pytest.raises(InvalidTimeMapError):
        TimeMap.from_source_ranges([(5, 4)])
    with pytest.raises(InvalidTimeMapError):
        TimeMap.from_source_ranges([(-1, 5)])
    with pytest.raises(InvalidTimeMapError):
        TimeMap.from_source_ranges([(0.0, 5)])  # type: ignore[list-item]
    with pytest.raises(InvalidTimeMapError):
        TimeMap([SegmentSpec("ok", True, 5)])  # type: ignore[arg-type]


def test_duplicate_segment_ids_are_rejected() -> None:
    with pytest.raises(InvalidTimeMapError, match="duplicate"):
        TimeMap(
            [
                SegmentSpec("same", 0, US),
                SegmentSpec("same", 2 * US, 3 * US),
            ]
        )


def test_empty_map_lookups_fail() -> None:
    timeline = TimeMap([])
    assert timeline.total_output_duration() == 0
    with pytest.raises(TimeNotMappedError):
        timeline.source_to_output(0)
    with pytest.raises(TimeNotMappedError):
        timeline.output_to_source(0)


def test_unmapped_and_negative_lookups_fail() -> None:
    timeline = _jump()
    with pytest.raises(TimeNotMappedError):
        timeline.source_to_output(16 * US)
    with pytest.raises(TimeNotMappedError):
        timeline.output_to_source(10 * US + 1)
    with pytest.raises(TimeNotMappedError):
        timeline.source_to_output(-1)
    with pytest.raises(TimeNotMappedError):
        timeline.source_to_output(1.5)  # type: ignore[arg-type]


def test_output_gap_overlap_and_retiming_are_rejected() -> None:
    with pytest.raises(InvalidTimeMapError, match="gap"):
        validate_placement(
            [
                MappedSegment("a", 0, 1000, 0, 1000),
                MappedSegment("b", 2000, 3000, 1500, 2500),
            ]
        )
    with pytest.raises(InvalidTimeMapError, match="overlap"):
        validate_placement(
            [
                MappedSegment("a", 0, 1000, 0, 1000),
                MappedSegment("b", 2000, 3000, 500, 1500),
            ]
        )
    with pytest.raises(InvalidTimeMapError, match="speed"):
        validate_placement([MappedSegment("a", 0, 1000, 0, 500)])


@pytest.mark.parametrize(
    ("nominal", "ratio"),
    [("24", (24, 1)), ("25", (25, 1)), ("30", (30, 1)), ("60", (60, 1)), ("29.97", (30000, 1001))],
)
def test_named_frame_rates_and_one_second_round_trip(nominal: str, ratio: tuple[int, int]) -> None:
    rate = FrameRate.parse(nominal)
    assert (rate.numerator, rate.denominator) == ratio
    timeline = TimeMap.from_source_ranges([(0, US)])
    assert timeline.output_frame_to_source(0, nominal) == 0
    assert timeline.source_to_output_frame(0, nominal) == 0
    with pytest.raises(FrameOutOfRangeError):
        timeline.source_to_output_frame(US, nominal)
    count = timeline.output_frame_count(nominal)
    for frame in range(count):
        start = frame_start_us(frame, rate)
        assert start < US
        assert frame_index_at(start, rate) == frame
        assert timeline.output_frame_to_source(frame, nominal) == start
        if frame > 0:
            assert frame_index_at(start - 1, rate) == frame - 1
    with pytest.raises(FrameOutOfRangeError):
        timeline.output_frame_to_source(count, nominal)


def test_29_97_frame_boundaries_use_the_rational_not_a_float() -> None:
    rate = FrameRate.parse("29.97")
    assert frame_start_us(1, rate) == 33_366
    assert frame_start_us(30, rate) == 1_001_000
    timeline = TimeMap.from_source_ranges([(0, 1_001_000)])
    assert timeline.output_frame_count("29.97") == 30
    assert timeline.output_frame_to_source(29, "29.97") == frame_start_us(29, rate)
    with pytest.raises(FrameOutOfRangeError):
        timeline.output_frame_to_source(30, "29.97")


def test_cut_boundary_frame_belongs_to_the_next_source_range() -> None:
    timeline = _jump()
    assert frame_start_us(150, FrameRate.parse("30")) == 5 * US
    assert timeline.output_frame_to_source(150, "30") == 20 * US
    assert timeline.output_frame_to_source(149, "30") == 10 * US + frame_start_us(149, FrameRate.parse("30"))
    # The outgoing source endpoint and the frame that starts on the cut are not inverses.
    assert timeline.source_to_output_frame(15 * US, "30") == 150
    assert timeline.source_to_output_frame(20 * US, "30") == 150
    with pytest.raises(FrameOutOfRangeError):
        timeline.source_to_output_frame(25 * US, "30")


def test_integer_rates_place_an_exact_second_on_a_frame() -> None:
    for nominal, frame in (("24", 24), ("25", 25), ("30", 30), ("60", 60)):
        assert frame_start_us(frame, FrameRate.parse(nominal)) == US


def test_float_and_impossible_frame_rates_are_rejected() -> None:
    with pytest.raises(InvalidFrameRateError):
        FrameRate.parse(29.97)  # type: ignore[arg-type]
    with pytest.raises(InvalidFrameRateError):
        FrameRate(0, 1)
    with pytest.raises(InvalidFrameRateError):
        FrameRate(30000, 0)
    with pytest.raises(InvalidFrameRateError):
        FrameRate(1, 2)
    with pytest.raises(InvalidFrameRateError):
        FrameRate(481, 1)
    with pytest.raises(FrameOutOfRangeError):
        frame_start_us(-1, FrameRate.parse("24"))
