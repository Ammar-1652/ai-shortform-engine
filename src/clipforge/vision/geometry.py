"""Normalize detector boxes into displayed-frame coordinates.

A few pixels of overflow are clipped. Broken geometry is rejected. Nothing
here labels a person or a speaker.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from clipforge.vision.constants import PIXEL_CLAMP


@dataclass(frozen=True, slots=True)
class NormalizedFace:
    confidence: float
    x: float
    y: float
    width: float
    height: float
    clamped: bool
    keypoints: tuple[tuple[str, float, float], ...]

    @property
    def center_x(self) -> float:
        return self.x + (self.width / 2)

    @property
    def center_y(self) -> float:
        return self.y + (self.height / 2)

    @property
    def area_ratio(self) -> float:
        return self.width * self.height


def normalize_box(
    origin_x: float,
    origin_y: float,
    width: float,
    height: float,
    *,
    frame_width: int,
    frame_height: int,
) -> NormalizedFace | None:
    """Return a frame-bounded box, or None when the geometry is unusable.

    ``confidence`` and keypoints are filled by the caller via ``with_score``.
    This helper returns a zero-confidence box so the clip decision stays here.
    """
    if frame_width <= 0 or frame_height <= 0:
        return None
    if not _real(origin_x) or not _real(origin_y) or not _real(width) or not _real(height):
        return None
    if width <= 0 or height <= 0:
        return None
    x2 = origin_x + width
    y2 = origin_y + height
    if x2 <= 0 or y2 <= 0 or origin_x >= frame_width or origin_y >= frame_height:
        return None
    if (
        origin_x < -PIXEL_CLAMP
        or origin_y < -PIXEL_CLAMP
        or x2 > frame_width + PIXEL_CLAMP
        or y2 > frame_height + PIXEL_CLAMP
    ):
        return None
    clamped = origin_x < 0 or origin_y < 0 or x2 > frame_width or y2 > frame_height
    left = min(max(origin_x, 0.0), float(frame_width))
    top = min(max(origin_y, 0.0), float(frame_height))
    right = min(max(x2, 0.0), float(frame_width))
    bottom = min(max(y2, 0.0), float(frame_height))
    clipped_w = right - left
    clipped_h = bottom - top
    if clipped_w <= 0 or clipped_h <= 0:
        return None
    return NormalizedFace(
        confidence=0.0,
        x=left / frame_width,
        y=top / frame_height,
        width=clipped_w / frame_width,
        height=clipped_h / frame_height,
        clamped=clamped,
        keypoints=(),
    )


def with_score(
    box: NormalizedFace,
    confidence: float,
    keypoints: tuple[tuple[str, float, float], ...],
) -> NormalizedFace | None:
    if not _real(confidence) or confidence < 0 or confidence > 1:
        return None
    kept: list[tuple[str, float, float]] = []
    for name, x, y in keypoints:
        if not _real(x) or not _real(y) or x < 0 or x > 1 or y < 0 or y > 1:
            continue
        kept.append((name, x, y))
    return NormalizedFace(
        confidence=confidence,
        x=box.x,
        y=box.y,
        width=box.width,
        height=box.height,
        clamped=box.clamped,
        keypoints=tuple(kept),
    )


def _real(value: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
