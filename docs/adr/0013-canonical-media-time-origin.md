# ADR 0013: Canonical media time origin

- Status: Accepted
- Date: 2026-10-02

## Context

Container timestamps and stream timestamps do not share one zero. A file can start before zero, at zero, or after zero. The selected audio can start before the selected video, with it, or after it. Round 3 will place transcript words on the source clock. That clock has to be defined before any proxy or ASR audio is written, or later words will not line up with the picture.

`MediaProbe` remains the older summary contract. It is not the place for this clock. A normalized probe stores the clocks that were actually read.

## Decision

Clipforge canonical source time `t=0` is the first presentation timestamp of the selected primary video stream.

`video_origin_us` is that timestamp on the container clock. It may be negative. Canonical time is microseconds after that origin. If ffprobe omits the video start, the origin is treated as zero and `video_start_assumed_zero` is true. The assumption is stored. It is not a silent default.

Audio offset is `audio_start_us - video_origin_us`.

- Positive: the audio starts later. ASR audio is prefixed with that much silence.
- Negative: the audio starts earlier. The lead-in is trimmed.
- Absent audio start: stored as zero with `audio_start_assumed_zero`, and the duration evidence names that assumption.

Duration uses the selected video as the authority, in this order:

1. `duration_ts` times the stream `time_base`, when both are present and the result is positive.
2. The video stream duration, when it is positive.
3. The container duration, only when the video start is zero or absent.
4. Otherwise fail. A duration is not invented.

Stream time bases and frame rates stay rational. `30000/1001` is not stored as `29.97`. `avg_frame_rate` and `r_frame_rate` stay separate. Comparing them yields `cfr_likely`, `vfr_possible`, or `unknown`. Packet scanning is not part of ingest. A VFR file is not rejected.

Seconds text from ffprobe is converted with decimal half-up rounding to integer microseconds. PTS conversion uses the same half-up rule on the exact rational product.

## Alternatives considered

- Use the container start as `t=0`. Rejected. Audio and video would still need a second correction, and the picture would not start at zero.
- Trust one ffprobe duration field. Rejected. The fields disagree often enough that the choice has to be ordered and recorded.
- Classify CFR by reading every frame. Rejected for Round 2. It is expensive and not required to build a timestamp-preserving proxy.

## Consequences

ASR audio and the analysis proxy are built so their `t=0` matches this video origin. Transcript work in a later round must use the same origin. Changing it is an architecture change, not a filter tweak.
