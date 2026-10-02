# ADR 0008: Canonical time mapping

- Status: Accepted
- Date: 2026-10-02

## Context

Jump cuts make one output instant correspond to two source instants. Captions, graphics, B-roll, SFX, QA, and review notes will all be wrong if each module converts time on its own, especially once 29.97 fps and microsecond cuts are involved.

## Decision

`clipforge.timeline.TimeMap` is the only converter. The persisted document is `TimeMapDocument`: ordered source ranges in integer microseconds. Output intervals are derived, not stored a second time.

Frame rates are rationals. NTSC names map to `1001` denominators. Float frame rates are rejected.

Boundary rules, including "the interior cut belongs to the next segment" and "the exact timeline end is not inside a frame", are specified in `docs/architecture/time-mapping.md` and locked by `tests/test_timeline.py`.

Edit plans store a sha256 of the map. Events that do not match the digest or that fall outside the duration fail validation.

V1 does not retime. A speed change requires a new ADR and a new schema version.

## Alternatives considered

- Float seconds. Rejected. `0.1 + 0.2` style errors show up as drifted captions.
- Milliseconds. Rejected. Frame starts at 29.97 fps are not whole milliseconds (`33366.666...` microseconds). Integer microseconds plus truncating frame starts are defined and round-trip.
- Store both source and output ranges on every event, edited by hand. Rejected. They drift. Events store output intervals only, plus the map digest. B-roll in-points are named as a different clock.

## Consequences

- Later caption and graphics code must call the mapper or consume intervals that were validated against it.
- Changing a boundary rule is an ADR plus new tests, not a quiet tweak inside a renderer.
- The sub-microsecond truncation of `frame_start_us` is accepted and documented. It does not accumulate.
