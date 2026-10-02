# ADR 0026: Transcript plus visual candidate evidence

- Status: Accepted
- Date: 2026-10-02

## Context

Round 3 stores a provisional full-source transcript. Round 4 stores shot-like scenes, representative frames, and geometry-only face tracks. A short-form candidate needs both. A transcript interval with no overlapping visual evidence is not ready to review, and a face track is not a speaker or a person identity.

Candidate mining must not decode the analysis proxy or the ASR FLAC, and it must not load Whisper or MediaPipe weights. Those weights can be absent after the artifacts were published.

## Decision

`clipforge candidate mine SOURCE_ID` reads the current transcript artifact and the current visual-analysis artifact for that source. Both must agree with the source manifest on project, source id, and canonical duration. The combined input digest is the SHA-256 of compact JSON `{"transcript_sha256","visual_analysis_sha256"}` with sorted keys.

Each selected candidate is one half-open source range on the canonical clock. Its time map has one segment. Boundaries prefer timed words plus 250 ms of context, clamped to the source and snapped out of a known neighboring word. Segments without words use the segment edges. Timing stays `approximate` / `provisional`.

The candidate keeps transcript segment and word ids, scene ids, representative frame ids, and face-observation ids in `CandidateEvidenceBundle`. Prose on `CandidateEvidence` does not carry those ids alone. A frame supports a candidate only when its stored PTS is inside `[start, end)`.

## Alternatives considered

- Mine from the transcript alone. Rejected. Ready for review already requires visual evidence.
- Re-decode the proxy to refresh frame times. Rejected. Round 4 already stored the PTS.
- Call a remote model to propose moments. Rejected for this round. A later proposer can consume the same artifacts.

## Consequences

A missing, stale, failed, or cross-source upstream artifact blocks mining before a candidate job is inserted. A missing model file does not. Zero eligible candidates is a successful document with `selected_count = 0`.
