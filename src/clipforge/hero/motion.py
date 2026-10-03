"""Motion library v1. Events are deterministic and do not move the TimeMap."""

from __future__ import annotations

import uuid

from clipforge.hero.constants import MOTION_LIBRARY_VERSION
from clipforge.schemas.editorial import MotionEvent, MotionPurpose, OutputInterval
from clipforge.schemas.hero import AlignedWord

_OPENING_US = 266_666
_CLOSING_US = 266_666


def hero_motion_events(
    *,
    candidate_id: str,
    duration_us: int,
    words: list[AlignedWord],
) -> list[MotionEvent]:
    """Opening fade, caption emphasis, and closing fade. No randomness and no reframing."""
    events: list[MotionEvent] = []
    opening_end = min(_OPENING_US, duration_us)
    if opening_end > 0:
        events.append(
            _event(
                candidate_id,
                0,
                "opening",
                0,
                opening_end,
                MotionPurpose.VISUAL_REVEAL,
                "opening-fade-v1",
            )
        )
    for index, word in enumerate(words):
        if not _emphasize(word.text):
            continue
        events.append(
            _event(
                candidate_id,
                index,
                "emphasis",
                word.output_start_us,
                word.output_end_us,
                MotionPurpose.KEY_PHRASE,
                "caption-emphasis-v1",
            )
        )
    closing_start = max(0, duration_us - _CLOSING_US)
    if duration_us > closing_start:
        events.append(
            _event(
                candidate_id,
                0,
                "closing",
                closing_start,
                duration_us,
                MotionPurpose.VISUAL_REVEAL,
                "closing-fade-v1",
            )
        )
    return events


def motion_library_version() -> str:
    return MOTION_LIBRARY_VERSION


def _emphasize(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return False
    if stripped[-1] in ".?!…。？！:":  # noqa: RUF001
        return True
    return any(character.isdigit() for character in stripped)


def _event(
    candidate_id: str,
    index: int,
    kind: str,
    start: int,
    end: int,
    purpose: MotionPurpose,
    component_id: str,
) -> MotionEvent:
    if end <= start:
        raise ValueError(f"motion event {kind} has no positive duration")
    token = f"clipforge-hero|{candidate_id}|{kind}|{index}|{start}|{end}"
    return MotionEvent(
        event_id=str(uuid.uuid5(uuid.NAMESPACE_URL, token)),
        interval=OutputInterval(output_start_us=start, output_end_us=end),
        purpose=purpose,
        component_id=component_id,
        payload={"library": MOTION_LIBRARY_VERSION},
    )
