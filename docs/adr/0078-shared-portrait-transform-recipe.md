# ADR 0078: Shared portrait transform recipe

## Status

Accepted

## Context

Hero and Advanced Hero render 16:9 source media inside a 1080×1920 portrait
composition. The previous implementation placed the contained foreground in
Remotion's `AbsoluteFill` and used `objectFit: fill`. The browser's implicit
100% height could therefore stretch the source vertically while technical
dimensions and safe-area checks still passed.

## Decision

Both production compositions use the same deterministic `containRect` helper.
It calculates integer output-space bounds from source and portrait dimensions.
The contained foreground is a normal nested element with explicit `left`,
`top`, `width`, and `height`; the video uses `objectFit: contain`. Crop and
face-follow paths continue to use their reviewed output-space windows. The
blurred background is a separate, explicit review treatment and never supplies
the geometry for the foreground.

The Hero renderer recipe advances to `hero-draft-renderer-v2`, and the clean
Advanced recipe advances to `advanced-hero-renderer-directed-v4`. These values
are part of profile fingerprints and cache identity. Existing v1/v3 artifacts
remain readable and immutable under their recorded recipe.

## Consequences

- A 16:9 source preserves its aspect ratio in both production compositions.
- Caption, graphic, face, and safe-region calculations can use one final output
  coordinate system.
- Existing approved artifacts cannot be silently reinterpreted with the new
  geometry; new plans and renders receive new fingerprints.
- Explicit contain remains available for review, while delivery strategies
  still require an intentional crop or reviewed trajectory.
