"""Deterministic sample targets and nearest-frame assignment.

The actual decoded PTS is the timestamp that later records use. A requested
target is kept beside it and is not treated as the time of a detection.
"""

from __future__ import annotations

from collections.abc import Iterator
from fractions import Fraction

from clipforge.errors import MediaError
from clipforge.vision.constants import (
    FACE_SAMPLE_INTERVAL_US,
    REPRESENTATIVE_FRACTIONS,
    SCENE_ENDPOINT_TOLERANCE_US,
    SHORT_SCENE_US,
)
from clipforge.vision.types import AssignedSample, DecodedFrame, SampleRequest

_FRACTIONS = {"1/5": Fraction(1, 5), "1/2": Fraction(1, 2), "4/5": Fraction(4, 5)}
_LABELS = {"1/5": "p20", "1/2": "mid", "4/5": "p80"}


def normalize_scenes(raw: list[tuple[int, int]], duration_us: int) -> list[tuple[int, int]]:
    """Cover ``[0, duration_us)`` exactly. A small final-edge miss is clamped.

    An empty detector result is one scene across the whole proxy. Gaps or
    overlaps larger than ``SCENE_ENDPOINT_TOLERANCE_US`` fail closed.
    """
    if duration_us <= 0:
        raise MediaError("visual analysis requires a positive canonical duration")
    if not raw:
        return [(0, duration_us)]
    ordered = sorted(raw, key=lambda item: (item[0], item[1]))
    first = ordered[0][0]
    if first < 0 or first > SCENE_ENDPOINT_TOLERANCE_US:
        raise MediaError(
            f"first scene starts at {first} us, which is outside {SCENE_ENDPOINT_TOLERANCE_US} us of 0. "
            "The scene list was not clamped."
        )
    spans: list[tuple[int, int]] = []
    cursor = 0
    for start, end in ordered:
        if end <= start:
            raise MediaError(f"scene {start}:{end} does not have a positive duration")
        if spans and abs(start - cursor) > SCENE_ENDPOINT_TOLERANCE_US:
            raise MediaError(
                f"scene boundary {start} us is {abs(start - cursor)} us from {cursor} us. "
                f"Only {SCENE_ENDPOINT_TOLERANCE_US} us of gap or overlap is clamped."
            )
        if end <= cursor:
            raise MediaError(f"scene ending at {end} us does not extend past {cursor} us")
        spans.append((cursor, end))
        cursor = end
    if abs(cursor - duration_us) > SCENE_ENDPOINT_TOLERANCE_US:
        raise MediaError(
            f"last scene ends at {cursor} us and the canonical duration is {duration_us} us. "
            f"The difference is larger than {SCENE_ENDPOINT_TOLERANCE_US} us."
        )
    last_start, _last_end = spans[-1]
    if duration_us <= last_start:
        raise MediaError("clamping the final scene would remove its duration")
    spans[-1] = (last_start, duration_us)
    return spans


def plan_requests(
    spans: list[tuple[int, int]],
    *,
    fractions: tuple[str, ...] = REPRESENTATIVE_FRACTIONS,
    short_scene_us: int = SHORT_SCENE_US,
    face_interval_us: int = FACE_SAMPLE_INTERVAL_US,
) -> list[SampleRequest]:
    """Union of representative targets and the periodic face cadence."""
    if face_interval_us <= 0 or short_scene_us <= 0:
        raise MediaError("sample intervals must be positive")
    requests: list[SampleRequest] = []
    for ordinal, (start, end) in enumerate(spans):
        if end <= start:
            raise MediaError("cannot sample a scene with no duration")
        chosen = ("1/2",) if end - start <= short_scene_us else fractions
        for name in chosen:
            requests.append(
                SampleRequest(
                    scene_ordinal=ordinal,
                    scene_start_us=start,
                    scene_end_us=end,
                    requested_us=_interior(start, end, _FRACTIONS[name]),
                    label=_LABELS[name],
                    face=True,
                )
            )
        for target in _face_targets(start, end, face_interval_us):
            requests.append(
                SampleRequest(
                    scene_ordinal=ordinal,
                    scene_start_us=start,
                    scene_end_us=end,
                    requested_us=target,
                    label=None,
                    face=True,
                )
            )
    return requests


def assign_samples(frames: Iterator[DecodedFrame], requests: list[SampleRequest]) -> Iterator[AssignedSample]:
    """Pick the closest in-scene frame for each target and merge shared PTS values.

    Only the previous frame and the current frame are retained while deciding.
    """
    pending = sorted(requests, key=lambda item: (item.requested_us, item.scene_ordinal, item.label or ""))
    previous: DecodedFrame | None = None
    index = 0
    group_frame: DecodedFrame | None = None
    group: list[SampleRequest] = []

    def emit() -> AssignedSample | None:
        nonlocal group_frame, group
        if group_frame is None or not group:
            return None
        labels = tuple(item.label for item in group if item.label is not None)
        representative = [item.requested_us for item in group if item.label is not None]
        requested = representative[0] if representative else group[0].requested_us
        matched = tuple(sorted({item.requested_us for item in group}))
        assigned = AssignedSample(
            scene_ordinal=group[0].scene_ordinal,
            scene_start_us=group[0].scene_start_us,
            scene_end_us=group[0].scene_end_us,
            requested_us=requested,
            matched_requests_us=matched,
            labels=labels,
            face=any(item.face for item in group),
            frame=group_frame,
        )
        group_frame = None
        group = []
        return assigned

    def push(frame: DecodedFrame, request: SampleRequest) -> AssignedSample | None:
        nonlocal group_frame, group
        ready: AssignedSample | None = None
        if group_frame is not None and (
            frame.timestamp_us != group_frame.timestamp_us or request.scene_ordinal != group[0].scene_ordinal
        ):
            ready = emit()
        group_frame = frame
        group.append(request)
        return ready

    for current in frames:
        if current.timestamp_us < 0:
            raise MediaError("decoded frame timestamp is negative")
        if previous is not None and current.timestamp_us < previous.timestamp_us:
            raise MediaError("decoded frame timestamps are not monotonic")
        if previous is not None and current.timestamp_us == previous.timestamp_us:
            continue
        while index < len(pending):
            request = pending[index]
            if current.timestamp_us < request.requested_us and current.timestamp_us < request.scene_end_us:
                break
            chosen = _closest(previous, current, request)
            past_scene = current.timestamp_us >= request.scene_end_us
            reached = current.timestamp_us >= request.requested_us
            if chosen is not None and (reached or past_scene):
                ready = push(chosen, request)
                if ready is not None:
                    yield ready
                index += 1
                continue
            if past_scene:
                raise MediaError(
                    f"no decoded frame inside scene {request.scene_ordinal} "
                    f"for requested time {request.requested_us} us"
                )
            break
        previous = current
    while index < len(pending):
        request = pending[index]
        if previous is not None and request.scene_start_us <= previous.timestamp_us < request.scene_end_us:
            ready = push(previous, request)
            if ready is not None:
                yield ready
            index += 1
            continue
        raise MediaError(
            f"no decoded frame inside scene {request.scene_ordinal} "
            f"for requested time {request.requested_us} us"
        )
    last = emit()
    if last is not None:
        yield last


def _interior(start: int, end: int, fraction: Fraction) -> int:
    duration = end - start
    target = start + int(fraction * duration)
    if target <= start:
        target = start + 1 if duration > 1 else start
    if target >= end:
        target = end - 1
    return target


def _face_targets(start: int, end: int, interval: int) -> list[int]:
    cursor = start if start == 0 else min(start + 1, end - 1)
    targets: list[int] = []
    while cursor < end:
        targets.append(cursor)
        cursor += interval
    if not targets:
        targets.append(_interior(start, end, Fraction(1, 2)))
    return targets


def _closest(
    previous: DecodedFrame | None,
    current: DecodedFrame,
    request: SampleRequest,
) -> DecodedFrame | None:
    candidates = [
        frame
        for frame in (previous, current)
        if frame is not None and request.scene_start_us <= frame.timestamp_us < request.scene_end_us
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda frame: (abs(frame.timestamp_us - request.requested_us), frame.timestamp_us),
    )
