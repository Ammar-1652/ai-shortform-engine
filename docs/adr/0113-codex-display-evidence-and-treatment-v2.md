# ADR 0113: Codex display evidence and treatment v2 contracts

- Status: Accepted
- Date: 2026-10-29

## Context

Forced alignment provides timing and raw words. It does not prove that the
displayed caption is grammatically correct, contextually correct, or exact for
Quran, quotations, names, numbers, and factual claims. Earlier treatment
records also represented separated speech windows as one union interval, which
could apply audio ducking across a pause. Review evidence was written to one
mutable sidecar path.

## Decision

ClipForge keeps raw ASR and forced alignment immutable and adds a typed Codex
display derivation. A generic speech review may contain source-word-bound
corrections, explicit emotion annotations, and span-bound sensitive-text
verification. The derived display alignment preserves the original word ids,
source times, output times, segment indices, and TimeMap while changing only
reviewed display text.

New reviews are stored as immutable revision files with a hash-bound current
pointer. Legacy `speech-review.json` files remain readable and are never
rewritten by the new path.

Treatment audio v2 stores disjoint speech-overlap and silence windows per cue.
The renderer and decoded evidence consume those windows; v1 receipts remain
readable for old artifacts.

New non-legacy clean production requires a Codex speech review. Exploratory
drafts may remain incomplete, but they cannot pass final review or delivery.

Arabic captions remain whole shaped runs when word-status evidence exists. The
renderer may use line-level status color or emphasis so joining and Quranic
marks are not broken by independently styled spans.

## Compatibility

- Existing Tarteel Quran canonical verification remains authoritative.
- Existing `TarteelSpeechReview` documents without the new optional fields are
  readable.
- Existing render inputs, audio receipts, and approved MP4s remain immutable.
- New hashes include correction, emotion, review-pointer, audio-window,
  renderer, and output-region dependencies.
- No SQLite migration is required; the new records are confined sidecars and
  generated schemas.

## Consequences

The system gains a verifiable distinction between what was heard, what was
aligned, and what Codex chose to display. Review correction, sensitive-text,
audio-window, and stale-artifact failures become explicit gates. Existing
legacy fixtures need no reinterpretation, while new clean production has a
stricter preflight.
