# ADR 0073: Source-bound native motion graphics

## Status

Accepted for new Advanced Hero production artifacts.

## Context

The directed renderer could animate captions, type rails, a grounded numeric
diagram, and reviewed local media, but it had no contract for a compact native
illustration. Ad-hoc React additions would let an operator turn a decoration
into an unsupported claim, obscure captions, or create output that cache and
review evidence could not distinguish from an older draft.

## Decision

1. A selected `DirectionOption` may contain at most four
   `DirectionMotionGraphic` records. Each selects an audited native Remotion
   template, has a canonical output interval, source evidence ids, a
   `MotionPurpose`, exact evidence text, and integer safe-region geometry.
   It is not an asset placement and cannot include a URL, downloaded media,
   HTML, CSS, SVG, or executable effect payload.
2. The initial allowlist is intentionally small: `credit_card`,
   `travel_postcard`, and `business_spotlight`. The direction validator checks
   that the copied evidence supports the selected concept; it rejects a
   graphic when no template is factual. The illustration region ends above
   the caption lane and graphics cannot overlap each other.
3. Advanced planning maps only the selected, validated direction records to
   `MotionGraphicEvent` records. The typed event participates in plan,
   render-input, fingerprint, QA, review, and delivery bindings. QA compares
   the plan event with its direction record so stale or substituted geometry,
   text, template, or timing fails closed.
4. Remotion draws the allowlisted components with `useCurrentFrame` and
   `useVideoConfig` only. Their entrance, one-pass internal motion, and exit
   are deterministic and bounded; there are no CSS timers, remote fetches,
   random values, music, or looping stock-like interruptions. Captions remain
   the sole complete speech layer, and conflicting decorative typography is
   removed rather than stacked over an illustration.
5. Existing directed-v2 and legacy profiles retain their old fingerprints and
   interpretation. New production defaults use
   `advanced-hero-renderer-directed-v3`, which includes the native graphics
   recipe version in its profile identity.

## Consequences

Operators can request a concise source-grounded illustration without writing
renderer code or downloading unrelated stock. A graphic is optional and a
direction with no factual match remains valid. A changed graphic plan or
renderer recipe produces a distinct artifact and makes prior QA/final-review
evidence inapplicable until it is reviewed again. Adding a new template is an
architecture change: it needs source-evidence semantics, a typed contract,
decoded-frame proof, and an ADR update.
