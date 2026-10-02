"""Canonical microseconds for visual analysis.

Analysis-proxy time 0 is canonical source time 0. Round 2 already applied
container start and rotation. This module must not add ``video_origin_us``
or ``audio_offset_us``. Frame ordinal divided by average FPS is not a clock.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from clipforge.errors import MediaError
from clipforge.schemas.common import MAX_TIMELINE_US

_MICRO = Decimal(1_000_000)


def rational_to_us(value: Fraction) -> int:
    """Convert a non-negative rational number of seconds with half-up rounding."""
    if value < 0:
        raise MediaError(f"timestamp {value} is negative")
    micros = value * 1_000_000
    quantized = (Decimal(micros.numerator) / Decimal(micros.denominator)).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    result = int(quantized)
    if result > MAX_TIMELINE_US:
        raise MediaError(f"timestamp {result} us exceeds the supported timeline")
    return result


def seconds_to_us(seconds: float) -> int:
    """Map a decimal-seconds API value with ``Decimal(str(seconds))``.

    ``int(seconds * 1_000_000)`` is not used.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise MediaError(f"timestamp {seconds!r} is not a real number")
    if not math.isfinite(seconds):
        raise MediaError(f"timestamp {seconds!r} is not finite")
    if seconds < 0:
        raise MediaError(f"timestamp {seconds!r} is negative")
    quantized = (Decimal(str(seconds)) * _MICRO).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    result = int(quantized)
    if result > MAX_TIMELINE_US:
        raise MediaError(f"timestamp {result} us exceeds the supported timeline")
    return result


def mean_us(values: list[int]) -> int:
    """Half-up mean of integer microsecond durations."""
    if not values:
        raise MediaError("cannot average an empty duration list")
    quantized = (Decimal(sum(values)) / Decimal(len(values))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantized)
