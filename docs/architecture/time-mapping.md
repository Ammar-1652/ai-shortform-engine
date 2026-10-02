# Canonical time mapping

Module: `clipforge.timeline`. Persisted form: `TimeMapDocument` (JSON Schema title `TimeMap`).

## Units

Every canonical timestamp is an integer count of microseconds. The Python type is `int`. The Pydantic constraint is `Microseconds` (`0` through seven days).

Seven days in microseconds is `604_800_000_000`, which is below JavaScript `Number.MAX_SAFE_INTEGER` (`2^53 - 1`). A later TypeScript consumer can store these values in a `number` only if it does integer arithmetic. It must not convert them through a binary float second.

Do not persist seconds, milliseconds, or frame indexes as the canonical clock. Frames are derived.

`total_output_duration()` returns microseconds.

## What is stored

A time map stores ordered source ranges:

- `segment_id`
- `source_start_us`
- `source_end_us`

Output placement is not stored. `TimeMap` lays ranges back-to-back from output `0` in list order. Duration is preserved. V1 does not retime: a segment whose output duration differs from its source duration is illegal.

List order is output order. The mapper does not sort by source time. A later moment may be placed before an earlier one when the edit calls for that.

## Lookup rules

`source_to_output(source_us)` and `output_to_source(output_us)` raise `TimeNotMappedError` when the time is outside the map. They never return `None`.

Output segments tile `[0, duration]`. Each interior segment owns `[output_start, output_end)`. The exact endpoint `duration` belongs to the last segment and maps to that segment's `source_end_us`.

At an interior cut, `output_to_source(cut)` returns the **next** segment's `source_start_us`.

`source_to_output` of the previous segment's `source_end_us` returns that same output instant. Two source instants therefore meet at one output instant. That is the jump cut. It is the only place the map is not a bijection. Callers that need the outgoing source endpoint must read the segment, not reverse the cut frame.

Source ranges may touch at a single endpoint when both segments map that instant to the same output time (a continuous split placed in order). A positive-duration overlap is rejected. A shared endpoint that would map to two different output times is rejected. Construction raises `InvalidTimeMapError`. The mapper does not drop or repair the range.

## Frames

A frame rate is a positive rational `numerator/denominator` between 1 and 480 fps inclusive.

Named strings:

| Name | Ratio |
| --- | --- |
| `24` | 24/1 |
| `25` | 25/1 |
| `30` | 30/1 |
| `60` | 60/1 |
| `23.976` | 24000/1001 |
| `29.97` | 30000/1001 |
| `59.94` | 60000/1001 |

Floats are rejected. `29.97` is not the IEEE value `29.97`.

```text
frame_start_us(n) = (n * 1_000_000 * denominator) // numerator
```

The division truncates toward zero. It is computed from the absolute index, so the sub-microsecond remainder does not accumulate. The error on any one start is less than 1 microsecond.

Frame `n` owns `[frame_start_us(n), frame_start_us(n + 1))`.

`output_frame_to_source(n, fps)` maps `frame_start_us(n)` and rejects a frame whose start is greater than or equal to the output duration.

`source_to_output_frame(source_us, fps)` maps the source time to output time, then finds the frame that contains that output time. The exact output endpoint raises `FrameOutOfRangeError` because it is not inside a frame.

`frame_index_at` uses integer division and then moves at most a few frames so the truncated start still round-trips. If that correction cannot finish, it raises. It does not guess.

## Edit plans

`EditPlan.time_map_sha256` is the SHA-256 of the canonical JSON of the embedded `TimeMapDocument`. Events (`CaptionCue`, `MotionEvent`, `BrollEvent`, `AudioEvent`) use `OutputInterval` on the output clock. Validation rejects a stale digest and any interval that ends after the map duration.

`broll_source_in_us` is an in-point on the B-roll file. It is not converted by the program time map.
