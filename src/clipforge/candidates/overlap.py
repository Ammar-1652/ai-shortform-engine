"""Half-open source ranges in integer microseconds.

``[0, 10)`` and ``[10, 20)`` do not overlap. ``[0, 10)`` and ``[5, 15)`` overlap
by 5 microseconds. Comparisons that decide a duplicate use integer ratios.
"""

from __future__ import annotations


def intersection_us(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def union_us(ranges: list[tuple[int, int]]) -> int:
    """Duration of a half-open union. Overlapping spans are counted once."""
    ordered = sorted((start, end) for start, end in ranges if end > start)
    if not ordered:
        return 0
    total = 0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start >= current_end:
            total += current_end - current_start
            current_start, current_end = start, end
        elif end > current_end:
            current_end = end
    return total + (current_end - current_start)


def milli_threshold(value: float) -> int:
    """``0.80`` becomes ``800``. The value is a one-decimal or two-decimal threshold."""
    return round(value * 1000)


def ratio_at_least(numerator: int, denominator: int, milli: int) -> bool:
    if denominator <= 0:
        return False
    return numerator * 1000 >= denominator * milli
