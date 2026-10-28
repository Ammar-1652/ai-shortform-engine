# ADR 0106: Resumable Hero rendering

## Status

Accepted for new Hero renders on 2026-10-24.

## Context

The legacy Hero worker rendered an entire 40–60 second composition in one
Remotion/Chrome session. A browser crash near the end discarded all completed
frames and left no safe recovery path. Advanced Hero already used bounded
global-frame chunks and a single continuous audio render.

## Decision

Hero uses the same checkpointed unit model as Advanced Hero:

- video is rendered in global 120-frame units;
- every unit is written to a private partial path, probed, hashed, and
  receipt-bound before it is promoted;
- the exact staged candidate audio is converted directly to 48 kHz stereo
  PCM, avoiding a second browser session for audio;
- FFmpeg assembles the verified video units and PCM audio once into the final
  MP4;
- input, renderer, style, font, plan, and dependency hashes invalidate stale
  units;
- a browser failure leaves valid unit receipts available to a resumed service
  attempt, while an incomplete unit is rerendered.

The Hero composition, TimeMap, caption contract, and approval gates are
unchanged. This is a recovery and process-boundary change, not a second
renderer.

## Consequences

Hero renders use more short browser launches, but each launch has bounded
memory and failure scope. Audio remains continuous and is never concatenated
from independently encoded AAC chunks. `clipforge hero render --resume
RUN_ID` reuses a failed run after checking its source, plan, renderer, and
dependency hashes; `--force` still creates a fresh draft set. Human review and
delivery gates remain unchanged.
