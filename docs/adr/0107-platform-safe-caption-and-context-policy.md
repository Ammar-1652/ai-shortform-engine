# ADR 0107: Platform-safe captions and upper context

## Status

Accepted for new directed production on 2026-10-24.

## Context

The production Advanced Hero path had the correct caption evidence and
platform-resilient framing, but the contract made the upper context sentence
optional for non-Quran styles and allowed modern captions to wrap to multiple
lines. A wrapped caption or a title placed near the top or bottom can be
covered by search/header, side-rail, description, or action UI after the same
1080×1920 file is viewed in TikTok, Instagram, or YouTube.

The campaign reference material also establishes a scene-specific upper hook,
continuous speech captions, and a clean separation between the upper hook and
the lower caption field. Platform UI changes by device and caption length, so
the renderer cannot claim one universal platform rectangle.

## Decision

1. New direction documents use `direction-v2`. The selected option must carry
   one reviewed, source-grounded `context_line` covering the complete output.
   The line is declarative text with an allowlisted emoji; it is not arbitrary
   HTML or executable copy. Historical `direction-v1` documents remain
   readable but cannot be used for new clean production without this line.
2. Every modern production style carries a one-line caption contract. The
   planner groups complete forced words using the style's word and character
   budgets. Remotion receives `caption_max_lines=1` and fails if the measured
   local font cannot fit the line at a readable size.
3. Modern styles reserve an inner portrait band of 96px left, 160px right,
   270px top, and 360px bottom. The upper context is placed at the lower edge
   of the top band. Caption, graphic, CTA, logo, and animated motion bounds
   are checked against this band and the stored platform exclusion evidence.
4. New platform-resilient directions are the default for new direction
   documents. Explicit legacy regions remain valid only for historical or
   deliberately reviewed compatibility output.
5. The safe region is a conservative production policy, not a guarantee of
   every device UI. Viewer-evidence bundles continue to include platform crop
   previews, and human playback remains required.

## Consequences

- Caption lines may become shorter and more frequent, but no spoken words are
  hidden by a renderer wrap or silently discarded.
- A direction with no defensible upper context or a line that cannot fit fails
  before browser rendering rather than producing a visually incomplete draft.
- Style fingerprints, render-input hashes, QA, final-review, and delivery
  identities change when these geometry or caption policies change.
- Existing approved artifacts are immutable and are not reinterpreted with
  the new defaults.
