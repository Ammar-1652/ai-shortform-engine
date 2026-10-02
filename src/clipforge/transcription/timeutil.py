"""Convert faster-whisper seconds onto the canonical integer-microsecond clock.

ASR audio time 0 is canonical source time 0. Round 2 already applied the
container and stream offsets when it wrote the FLAC. This module must not
add ``audio_offset_us`` or ``video_origin_us`` again.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

from clipforge.errors import MediaError
from clipforge.transcription.constants import TIMING_TOLERANCE_US

_MICRO = Decimal(1_000_000)


def seconds_to_microseconds(seconds: float) -> int:
    """Map one timestamp with ``Decimal(str(seconds))`` and half-up rounding.

    ``int(seconds * 1_000_000)`` is not used. Binary float multiplication can
    land on the wrong side of an integer microsecond.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise MediaError(f"timestamp {seconds!r} is not a real number")
    if not math.isfinite(seconds):
        raise MediaError(f"timestamp {seconds!r} is not finite")
    quantized = (Decimal(str(seconds)) * _MICRO).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantized)


def clamp_endpoint(
    value_us: int,
    *,
    low_us: int,
    high_us: int,
    label: str,
) -> tuple[int, str | None]:
    """Clamp a tiny undershoot or overshoot. A larger miss fails closed."""
    if value_us < low_us:
        if low_us - value_us <= TIMING_TOLERANCE_US:
            return low_us, f"{label} clamped from {value_us} us to {low_us} us"
        raise MediaError(
            f"{label} is {value_us} us, which is more than {TIMING_TOLERANCE_US} us "
            f"before {low_us} us. The transcript was not published."
        )
    if value_us > high_us:
        if value_us - high_us <= TIMING_TOLERANCE_US:
            return high_us, f"{label} clamped from {value_us} us to {high_us} us"
        raise MediaError(
            f"{label} is {value_us} us, which is more than {TIMING_TOLERANCE_US} us "
            f"past {high_us} us. The transcript was not published."
        )
    return value_us, None
