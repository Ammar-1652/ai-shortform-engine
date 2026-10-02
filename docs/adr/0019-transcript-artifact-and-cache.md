# ADR 0019: Transcript artifact and cache

- Status: Accepted
- Date: 2026-10-02

## Context

A transcript is a derived document, not a new SQLite table of words. Round 2 already has `jobs` and `artifacts`. Putting every word in SQL would duplicate the typed document and invite a second clock.

A second run with the same model, device, and ASR bytes should not call the model again. A copied sidecar, a changed model revision, or a failed producer job must not count as a hit.

## Decision

The transcript is the existing `Transcript` contract, extended with engine identity, the ASR audio hash, the selected device and compute type, language metadata, and segment diagnostics. `alignment` stays `approximate` and `timing_quality` is `provisional`. Segment text is the canonical text. Word text keeps the engine's leading spaces. No second rewritten `full_text` is stored.

The file is `transcript/transcript.json`. The cache sidecar is `metadata/transcript.recipe.json`, a `TranscriptionCacheRecord`, not a media `DerivativeCacheRecord`. The artifact kind is `transcript_json` in the existing `artifacts` table. `provenance.inputs_sha256` is the ASR FLAC SHA-256. The source SHA-256 is on the transcript and the sidecar.

Cache identity includes project, source, source SHA-256, ASR SHA-256, ASR recipe, transcription recipe `transcription` version `1`, faster-whisper version, CTranslate2 version, model revision, device, compute type, language, and the decoding fingerprint. `created_at` is not part of identity. A hit also requires the file hash, a valid transcript document, an artifact row, and a `transcribe` job in `succeeded`.

A cache hit returns the existing job and does not insert a fake inference job. `--force` runs the model, inserts a new job, and points the artifact at that job. Older jobs stay.

Writes go to a partial file, then a validated hash, then an atomic rename of the transcript and the sidecar. If the database update fails, the previous transcript and sidecar are restored and the new job is `failed`. A generator exception does the same: no new final file, and a previous valid transcript stays.

A missing local model after the fact does not fail `transcript verify`. That check can warn. It does not download.

No migration 5. Schema version stays 4.

## Alternatives considered

- A `transcript_words` table. Rejected. The typed JSON is the document Round 5 can read without loading the model.
- Reuse `DerivativeCacheRecord`. Rejected. Device, model revision, and decoding options do not fit a media recipe sidecar cleanly.
- Insert a succeeded job on every cache hit. Rejected. That job would look like inference that did not run.

## Consequences

A formatting change in the JSON changes the file hash and misses the cache once. An engine upgrade misses on purpose. Verify can pass when the model directory is gone. Hero alignment will read this document and replace timing only for a selected range.
