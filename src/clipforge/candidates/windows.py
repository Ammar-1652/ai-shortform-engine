"""Bounded windows over ordered transcript segments.

For each start segment the walk stops once the padded range passes the hard
maximum. Endpoints are the hard limits, the preferred limits, about 30 seconds,
and a segment whose text already ends with observed punctuation. Identical
source ranges are emitted once. The walk stops at the raw-hypothesis cap and
reports that the enumeration was not exhaustive.
"""

from __future__ import annotations

from dataclasses import dataclass

from clipforge.candidates.constants import EXCERPT_CHARS, MID_TARGET_US
from clipforge.candidates.tokenize import token_set, tokenize
from clipforge.schemas.candidates import CandidateMiningProfile
from clipforge.schemas.media import Transcript, TranscriptSegment, TranscriptWord

_CLOSING = frozenset(".?!…\u3002\uff1f\uff01:")


@dataclass(frozen=True, slots=True)
class RawWindow:
    """One source range built from consecutive transcript segments."""

    start_us: int
    end_us: int
    segment_ids: tuple[str, ...]
    segment_ordinals: tuple[int, ...]
    word_ids: tuple[str, ...]
    word_count: int
    text: str
    excerpt: str
    tokens: frozenset[str]


def generate_windows(
    transcript: Transcript,
    profile: CandidateMiningProfile,
    *,
    duration_us: int,
) -> tuple[list[RawWindow], bool]:
    """Return windows and whether ``maximum_raw_hypotheses`` stopped the walk."""
    segments = list(transcript.segments)
    words = [word for segment in segments for word in segment.words]
    targets = _targets(profile)
    seen: set[tuple[int, int]] = set()
    windows: list[RawWindow] = []
    limit = profile.maximum_raw_hypotheses
    for start_index in range(len(segments)):
        emitted: set[int] = set()
        last_choice: tuple[list[TranscriptSegment], int, int] | None = None
        for end_index in range(start_index, len(segments)):
            chosen = segments[start_index : end_index + 1]
            start_us, end_us = source_bounds(
                chosen,
                padding_us=profile.boundary_padding_us,
                duration_us=duration_us,
                known_words=words,
            )
            if end_us <= start_us:
                continue
            span = end_us - start_us
            if span > profile.hard_max_duration_us:
                break
            last_choice = (chosen, start_us, end_us)
            if span < profile.hard_min_duration_us:
                continue
            text = _join(chosen)
            crossed = [target for target in targets if span >= target and target not in emitted]
            if not crossed and not _closes(text):
                continue
            emitted.update(crossed)
            _add(windows, seen, chosen, start_us, end_us, text)
            if len(windows) >= limit:
                return windows, True
        if last_choice is None:
            continue
        chosen, start_us, end_us = last_choice
        if end_us - start_us < profile.hard_min_duration_us:
            continue
        _add(windows, seen, chosen, start_us, end_us, _join(chosen))
        if len(windows) >= limit:
            return windows, True
    return windows, False


def source_bounds(
    segments: list[TranscriptSegment],
    *,
    padding_us: int,
    duration_us: int,
    known_words: list[TranscriptWord],
) -> tuple[int, int]:
    """Place the range on word edges when words exist, otherwise on segment edges.

    Padding is clamped to the source and snapped out of any known word so the
    cut is not left inside a timed word. Missing word times are not invented.
    """
    words = [word for segment in segments for word in segment.words]
    if words:
        start = words[0].start_us - padding_us
        end = words[-1].end_us + padding_us
        included = {word.word_id for word in words}
        for other in known_words:
            if other.word_id in included:
                continue
            if other.start_us < start < other.end_us:
                start = other.end_us
            if other.start_us < end < other.end_us:
                end = other.start_us
    else:
        start = segments[0].start_us
        end = segments[-1].end_us
    return max(0, start), min(duration_us, end)


def _add(
    windows: list[RawWindow],
    seen: set[tuple[int, int]],
    segments: list[TranscriptSegment],
    start_us: int,
    end_us: int,
    text: str,
) -> None:
    key = (start_us, end_us)
    if key in seen or end_us <= start_us or not segments:
        return
    seen.add(key)
    words = [word for segment in segments for word in segment.words]
    if words:
        word_count = len(words)
        word_ids = tuple(word.word_id for word in words)
    else:
        word_count = len(tokenize(text))
        word_ids = ()
    windows.append(
        RawWindow(
            start_us=start_us,
            end_us=end_us,
            segment_ids=tuple(segment.segment_id for segment in segments),
            segment_ordinals=tuple(segment.ordinal for segment in segments),
            word_ids=word_ids,
            word_count=word_count,
            text=text,
            excerpt=_excerpt(text),
            tokens=token_set(text),
        )
    )


def _targets(profile: CandidateMiningProfile) -> tuple[int, ...]:
    values = (
        profile.hard_min_duration_us,
        profile.preferred_min_duration_us,
        MID_TARGET_US,
        profile.preferred_max_duration_us,
        profile.hard_max_duration_us,
    )
    ordered: list[int] = []
    for value in values:
        if profile.hard_min_duration_us <= value <= profile.hard_max_duration_us and value not in ordered:
            ordered.append(value)
    return tuple(sorted(ordered))


def _join(segments: list[TranscriptSegment]) -> str:
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip())


def _excerpt(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:EXCERPT_CHARS]


def _closes(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in _CLOSING
