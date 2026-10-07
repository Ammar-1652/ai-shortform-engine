# ADR 0067: Ordered TimeMap render staging

- Status: Accepted
- Date: 2026-10-07

## Context

Advanced Hero staging used only the first segment of an ordered `TimeMap`.
An operator who authored a jump-cut plan therefore received one source moment;
external demo code then filled a requested duration by repeating that moment.
That is not an edit and it breaks the canonical timing contract.

## Decision

The media staging layer exposes `stage_time_map`, which trims every validated
source range on the source clock and concatenates them in persisted list order.
It writes a frame-accurate H.264 picture, a matching FLAC speech track, and a
recipe containing the integer-microsecond ranges. Advanced Hero uses this path
whenever its plan contains more than one segment; the existing single-span path
remains unchanged for candidate mining and legacy artifacts.

No caller may repeat a staged span to manufacture duration. Candidate mining
continues to produce one contiguous candidate in its current contract. A future
operator-authored multi-segment plan must use `TimeMapDocument`, forced word
alignment, and the existing approval/provenance gates before it can be rendered.

## Consequences

The renderer receives the actual ordered program clock and cannot silently
replace a jump cut with `segments[0]`. The recipe and TimeMap digest make the
source ranges part of the render identity. Existing single-span artifacts remain
immutable and reproducible. The implementation does not authorize third-party
media or bypass campaign policy.
