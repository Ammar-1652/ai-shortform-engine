# ADR 0021: Analysis proxy as the visual source

- Status: Accepted
- Date: 2026-10-02

## Context

Round 2 already normalizes orientation, bounds the long edge, and puts canonical time zero at the first video PTS. Running scene detection on the original file would repeat that work and could disagree with the proxy later rounds crop from.

## Decision

`clipforge vision analyze` accepts a source id. The bytes it decodes are `proxy/analysis.mp4` from recipe `analysis-proxy` v1. The proxy must exist, match its sidecar, and come from a succeeded `media_prepare` job for that source. Rights and source-mutation checks still run. A missing or stale proxy is a hard failure. Visual analysis does not call `media prepare`.

Proxy time zero is canonical source time zero. `video_origin_us` and `audio_offset_us` are not added again. The artifact's direct input digest is the proxy SHA-256. The original source SHA stays in the document and the cache record so a mutated source is rejected even when the proxy file is still on disk.

Visual cache identity does not include the transcript SHA. Regenerating ASR must not force another scene pass. Round 5 joins the two artifacts.

## Alternatives considered

- Decode the original source. Rejected. Orientation and scale would be a second implementation.
- Auto-run media prepare when the proxy is missing. Rejected. Preparation is explicit and can replace the file this round is reading.
- Key the visual cache on the transcript. Rejected. The picture did not change.

## Consequences

Operators run `clipforge media prepare` first. A regenerated proxy invalidates the visual cache even if the source SHA is unchanged. Scenes stay `analysis_complete = false` because transcript evidence is still empty.
