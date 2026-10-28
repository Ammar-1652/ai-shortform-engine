# ADR 0099: Reviewed speech and immutable caption derivation

- Status: Accepted for new clean Tarteel plans
- Date: 2026-10-22

## Context

An interval covering the same time as ASR did not prove that its audible
words were captioned. A review could omit a laugh or nasheed, mark retained
speech excluded, or provide different text. Canonical Quran display can merge
ASR tokens, so comparing that display with the unmodified raw alignment also
produced false missing-word failures. Review evidence was not consistently
bound through planning, rendering, cache and QA.

## Decision

The production planner requires a source/audio/transcript-bound speech
inventory for clean Tarteel work. Every retained audible interval must have
reviewed observed text matching the derived caption words. Retained uncertain
speech, excluded audible speech, false silence, word omissions, and cuts
through reviewed audible intervals fail before rendering. Intervals removed
from the TimeMap remain review history; exclusion cannot erase retained sound.

Ordinary Arabic corrections are a separate typed, source-window and
forced-word-bound derivation. They preserve raw alignment bytes, word ids,
measured timing and provider/live-evidence status. Canonical Quran display
remains a separate derivation using the existing canonical-source evidence.
An inventory with retained recitation requires it; dialogue-only clips do not
need an unrelated Quran sidecar. Text matching is not pronunciation proof.

The exact derived `caption-alignment.json`, speech review and optional ordinary
correction hashes flow through the Advanced plan, input, output and render
dependency identity. QA compares visible caption text, word ids, timings and
verification treatment with that derivation. Raw alignment remains the
authority for live-alignment checks at every existing caller.

Arc review validates exact ordered segments, forced-word ids and interior
continuity before publishing new plan dependencies. Copying a review preserves
its bytes. Transformed CTA evidence must describe the actual renderer geometry,
include first/last visible frames, hash actual decoded sample images, and allow
multiple independently identified child/face exclusion boxes. Positive cue and
CTA intervals use the shared frame-window convention.

## Consequences

No SQLite migration is needed. Additive hash fields keep old documents readable;
an old artifact gains neither new review evidence nor a stronger live status.
New clean plans without current evidence must be replanned. Changing a caption
derivation, speech inventory, correction, transform or evidence recipe misses
the render cache and invalidates downstream QA/approval reuse. A proposal built
from ASR cannot be relabeled as a listened-to inventory by automation.
