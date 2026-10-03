# ADR 0031: Analysis proxy and ASR audio for rough previews

- Status: Accepted
- Date: 2026-10-03

## Context

Round 2 already produced a deterministic analysis proxy and an ASR FLAC whose sample 0 is canonical source t=0. Round 6 needs a cheap review picture and a speech track for every selected candidate. Reopening the original master would copy a large file and ignore the clock those derivatives already share.

## Decision

Rough previews read `proxy/analysis.mp4` for the picture and `audio/asr.flac` for speech. The original source is not copied and is not the visual input. The proxy is review quality. It is not a Hero master.

Both files are hard-linked into `previews/runs/<preview_set_id>/staging/` for one Remotion bundle. A copy is used only when the hard link fails. Staging is deleted after the run validates. It is not an artifact.

Video and audio use the same preview-grid trim. `media_trim_frame` is the 30/1 frame that contains the candidate's canonical start, so the seek can be up to one output frame early. Stored source bounds stay the TimeMap microseconds. They are not rewritten to that grid.

If the proxy or the ASR file is missing, mutated, or not produced by a succeeded `media_prepare` job, rendering fails and names `clipforge media prepare`. Silent speech is not invented.

## Alternatives considered

- Render from the original. Rejected. It is slower and the proxy already bakes display rotation onto the canonical timeline.
- Normalize or replace the ASR audio. Rejected. Rough review must not change the speech.

## Consequences

A preview duration can differ from the canonical duration by less than the preview tolerance, which is `max(100 ms, two 30 fps frame periods)` and therefore 100 ms. `duration_error_us` records the difference. x264 may tag the 4:2:0 output `yuvj420p`. That tag is accepted as the same planar layout as the requested `yuv420p`.
