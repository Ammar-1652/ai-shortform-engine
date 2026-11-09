# ADR 0054: Candidate-local render staging

- Status: Accepted
- Date: 2026-10-05

## Context

Rough preview, Hero, and Advanced Hero asked Remotion to open the full analysis proxy and seek with `trimBefore`. On a 10–14 minute H.264 proxy that seek failed even when ffmpeg could decode the same timestamp. A retry then lost the Chrome session. Raising the Node heap does not give the extractor a frame it cannot seek.

WhisperX stays out of the default project lock. The production adapter still has to run when the package is installed in a separate interpreter.

## Decision

A browser render derives a short clip from the candidate TimeMap before Chrome starts. A fast seek lands near the previous keyframe. An accurate seek and a 30/1 H.264 re-encode then write a clip that starts at frame 0. The same window is cut from the ASR audio as FLAC. `media_trim_frame` for that staged pair is 0. The render input still stores the canonical source start and end, the proxy SHA-256, and the staged-media SHA-256. The Remotion output remains H.264/AAC in the portrait profile. Stream copy is not used, because a non-keyframe start would keep the wrong frame.

Staging rejects a symlink, a remote URL, a traversing name, and a path outside the work root. ffmpeg and ffprobe versions are recorded in the staging recipe. The staged duration must stay within the existing preview tolerance. Staging is removed after success, failure, and cancellation. A partial MP4 is not promoted. The React timeout is bounded by the candidate frame count and is not unlimited. The compositions do not call `delayRender`. Remotion's own media wait uses that timeout. Node starts a new session and the process group is reaped. The outer Node/bundle process has an independent frame-budgeted deadline (120–600 seconds) so a stalled bundle or browser launch cannot hold the shared render lock indefinitely.

Fake render backends still link the full proxy and keep the source-start trim frame. They do not read the staged clip.

When WhisperX cannot be imported, alignment uses `CLIPFORGE_ALIGN_PYTHON` or the optional side interpreter. That process is still the production WhisperX adapter. A missing interpreter fails closed. Provisional timings are not substituted. Normal runs set the offline hub variables. Model download still requires `--allow-model-download`.

## Alternatives considered

- Only raise the Node memory limit. Rejected. The extractor still could not seek the long proxy.
- Stream-copy the candidate span. Rejected. A start between keyframes would not be frame-accurate.
- Add WhisperX to the default lock. Rejected. Alignment stays optional and CPU-side.

## Consequences

Browser renders no longer seek the full proxy. A one-candidate preview whose id is in the current set can be reviewed. A reordered or shortened full set still fails. Arabic and Japanese captions stay `alignment_not_claimed` unless a production model for that language runs.
