"""Rational frame rates.

Nominal NTSC rates are exact integer ratios, not binary floats:

- 23.976 means 24000/1001
- 29.97 means 30000/1001
- 59.94 means 60000/1001

``frame_start_us`` truncates toward zero. The value is computed from the
absolute frame index, so the sub-microsecond remainder does not accumulate.
The matching frame index is ``frame_index_at``, which corrects the one-frame
ambiguity that truncation would otherwise introduce.
"""

from __future__ import annotations

from dataclasses import dataclass

from clipforge.errors import FrameOutOfRangeError, InvalidFrameRateError

# Named rates accepted by FrameRate.parse. Floats are rejected on purpose.
NAMED_FRAME_RATES: dict[str, tuple[int, int]] = {
    "24": (24, 1),
    "25": (25, 1),
    "30": (30, 1),
    "60": (60, 1),
    "23.976": (24000, 1001),
    "29.97": (30000, 1001),
    "59.94": (60000, 1001),
}

_MIN_FPS = 1
_MAX_FPS = 480
_CORRECTION_LIMIT = 3


@dataclass(frozen=True, slots=True)
class FrameRate:
    """A frame rate as an integer numerator and denominator."""

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if isinstance(self.numerator, bool) or not isinstance(self.numerator, int):
            raise InvalidFrameRateError(
                f"frame-rate numerator must be an integer, got {type(self.numerator).__name__}"
            )
        if isinstance(self.denominator, bool) or not isinstance(self.denominator, int):
            raise InvalidFrameRateError(
                f"frame-rate denominator must be an integer, got {type(self.denominator).__name__}"
            )
        if self.numerator <= 0 or self.denominator <= 0:
            raise InvalidFrameRateError(
                f"frame rate {self.numerator}/{self.denominator} must use positive integers"
            )
        if self.numerator < _MIN_FPS * self.denominator:
            raise InvalidFrameRateError(
                f"frame rate {self.numerator}/{self.denominator} is below {_MIN_FPS} fps"
            )
        if self.numerator > _MAX_FPS * self.denominator:
            raise InvalidFrameRateError(
                f"frame rate {self.numerator}/{self.denominator} is above {_MAX_FPS} fps"
            )

    @classmethod
    def parse(cls, value: FrameRate | str | tuple[int, int]) -> FrameRate:
        """Parse a FrameRate, a ``(numerator, denominator)`` pair, or a nominal name."""
        if isinstance(value, FrameRate):
            return value
        if isinstance(value, tuple):
            if len(value) != 2:
                raise InvalidFrameRateError(
                    f"frame rate tuple must be (numerator, denominator), got {len(value)} values"
                )
            return cls(value[0], value[1])
        if isinstance(value, str):
            named = NAMED_FRAME_RATES.get(value.strip())
            if named is None:
                known = ", ".join(sorted(NAMED_FRAME_RATES))
                raise InvalidFrameRateError(
                    f"unknown nominal frame rate {value!r}. Pass (numerator, denominator) or one of: {known}."
                )
            return cls(*named)
        raise InvalidFrameRateError(
            "frame rate must be a FrameRate, a nominal string, or (numerator, denominator); "
            f"got {type(value).__name__}. Floats are rejected so 29.97 cannot mean a binary float."
        )

    def __str__(self) -> str:
        return f"{self.numerator}/{self.denominator}"


def frame_start_us(frame: int, fps: FrameRate) -> int:
    """Return the output timestamp, in microseconds, where ``frame`` starts.

    Frame 0 starts at 0. The result truncates toward zero.
    """
    if isinstance(frame, bool) or not isinstance(frame, int):
        raise FrameOutOfRangeError(f"frame must be an integer, got {type(frame).__name__}")
    if frame < 0:
        raise FrameOutOfRangeError(f"frame {frame} is negative")
    return (frame * 1_000_000 * fps.denominator) // fps.numerator


def frame_index_at(output_us: int, fps: FrameRate) -> int:
    """Return the frame whose half-open interval contains ``output_us``.

    Frame ``n`` owns ``[frame_start_us(n), frame_start_us(n + 1))``.
    """
    if isinstance(output_us, bool) or not isinstance(output_us, int):
        raise FrameOutOfRangeError(
            f"output time must be an integer microsecond value, got {type(output_us).__name__}"
        )
    if output_us < 0:
        raise FrameOutOfRangeError(f"output time {output_us} us is negative")

    index = (output_us * fps.numerator) // (fps.denominator * 1_000_000)
    for _ in range(_CORRECTION_LIMIT):
        if frame_start_us(index, fps) > output_us:
            index -= 1
            continue
        if frame_start_us(index + 1, fps) <= output_us:
            index += 1
            continue
        if index < 0:
            raise FrameOutOfRangeError(
                f"output time {output_us} us is before frame 0 at {fps.numerator}/{fps.denominator}"
            )
        return index
    raise FrameOutOfRangeError(
        f"could not resolve a frame index for output {output_us} us "
        f"at {fps.numerator}/{fps.denominator} fps. This is a mapper bug, not a skipped frame."
    )
