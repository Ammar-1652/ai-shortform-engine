# ADR 0092: Tarteel readable Quran caption preset

## Status

Accepted for new Tarteel public-readable drafts.

## Context

The compact Quran editorial treatment preserved the full portrait composition,
but its lower captions were too small for a public mobile review. Matching an
active word by visible text also failed when Arabic words repeated or carried
Uthmani pause marks.

## Decision

Add the versioned `quran-readable-v2` preset. It uses the same local Amiri font,
canonical Quran evidence, portrait-safe blur/foreground treatment, and
integer-microsecond TimeMap as the compact preset, but declares centered large
lower caption cards, a larger centered upper context line, and zero additional
caption scale motion. Active coloring is bound to the forced `word_id`; visible
text matching remains only the ordered fallback for legacy inputs.

The current pilot candidate's public-readable editorial arc starts at the
reviewed `احنا اليوم بإذن الله` boundary, keeps the readiness exchange, and
then carries the complete reviewed recitation. This source boundary belongs to
that candidate's arc evidence; future Tarteel candidates must bind their own
reviewed opening and are not required to reuse it. The preset is immutable and
part of style, renderer, cache, QA, and stale-approval identity. It is still a
review draft; human final approval is required before local delivery.

When the platform-resilient portrait region is selected, the upper context line
uses the smaller campaign title size, starts at the persisted `y=280` title
anchor, and is capped at two centered lines so it stays below TikTok's top
search/header area while fitting the inner horizontal safe band without
clipping.

## Consequences

- Large Arabic glyphs and diacritics stay inside a measured lower blur lane.
- Repeated words cannot steal each other's active color.
- Compact historical renders remain immutable under `quran-editorial-v1`.
- A changed preset or arc produces a new plan and render artifact.
