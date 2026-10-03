"""Preview-grid frame indexes. Canonical microseconds stay authoritative.

A caption frame is the first output frame whose start is at or after the cue.
That frame is never earlier than the canonical cue. Media trim uses the output
frame that contains the candidate start, so the seek can be up to one preview
frame earlier than the exact microsecond. Both choices use 30/1 integer math.
"""

from __future__ import annotations

from clipforge.timeline.framerate import FrameRate, frame_start_us


def preview_rate() -> FrameRate:
    return FrameRate(30, 1)


def frame_at_or_after(output_us: int, frame_count: int) -> int:
    """Smallest frame index whose start is >= ``output_us``, capped at ``frame_count``."""
    rate = preview_rate()
    if output_us <= 0:
        return 0
    index = 0
    # Jump close, then correct. The estimate can be one frame low because of truncation.
    if output_us > 0:
        index = (output_us * rate.numerator) // (rate.denominator * 1_000_000)
    while index > 0 and frame_start_us(index, rate) >= output_us:
        index -= 1
    while index < frame_count and frame_start_us(index, rate) < output_us:
        index += 1
    return index


def media_trim_frame(source_start_us: int) -> int:
    """Output-grid frame that contains ``source_start_us`` on a timeline that starts at 0."""
    from clipforge.timeline.framerate import frame_index_at

    if source_start_us <= 0:
        return 0
    return frame_index_at(source_start_us, preview_rate())
