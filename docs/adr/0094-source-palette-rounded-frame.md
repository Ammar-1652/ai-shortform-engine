# ADR 0094: Source-palette rounded frame for platform-resilient Tarteel drafts

## Status

Accepted for new Tarteel Advanced Hero drafts using
`platform-resilient-portrait-v1`.

## Context

The existing portrait composition contained a 16:9 source card over a blurred
copy of the same frame. A rounded border added around the card did not remove
the lateral blur, so the result still read as letterboxing on platform
previews. A fixed brand colour also ignored the source scene and could clash
with it.

## Decision

New Tarteel plans deterministically sample five frames from the authorized
analysis proxy. The analyzer records the dominant source colour and maps its
hue/value to one reviewed family: olive, sage, or charcoal. The plan persists
the source hash, analyzer version, sample timestamps, measured colour, frame
colours, and `auto-source-palette-v1` identity.

The Remotion composition renders the source in a rounded, aspect-correct card
with the selected frame treatment. Its remaining canvas uses a restrained
palette gradient, not a blurred duplicate of the source. This prevents the
side rails from being mistaken for accidental letterboxing while retaining
the approved inner-band geometry for TikTok and Instagram.

The `platform-bleed-v1` layout uses the full 1080px output width. A 1280x720
source therefore produces a 1080x608 card centered at y=656 in the 1080x1920
canvas. The same geometry is used for the palette and blurred-background
variants; only the backdrop policy differs. Platform crop-mask checks must
verify the rounded frame, not merely the encoded dimensions.

When the blurred variant is selected, Remotion applies a fixed 34% black
overlay only to the blurred backdrop. The foreground source, frame, captions,
CTA, and watermark remain at their authored brightness.

The palette and backdrop are part of the Advanced plan and render input. A
source hash, palette analyzer, frame recipe, or selected family change must
therefore miss the render cache and invalidate downstream QA/review evidence.
Existing plans remain immutable and retain their recorded backdrop behavior.

## Consequences

- Frame colour follows the actual scene instead of a global fixed default.
- New framed Tarteel renders contain no source-blur side rails.
- The source remains fully visible inside the rounded card; no content is
  cropped solely to create the design.
- Other campaigns and legacy plans are unchanged unless they explicitly opt
  into the typed frame treatment.
