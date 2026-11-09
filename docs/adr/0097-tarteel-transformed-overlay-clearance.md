# ADR 0097: Tarteel transformed overlay clearance evidence

## Status

Accepted for new clean Tarteel Advanced Hero renders.

## Context

The campaign CTA solver previously checked sampled face boxes and caption
timing. That left important collisions unproved: a CTA could cover a child's
body, the tablet, source branding, the upper context line, or a platform crop
rail. A placement that was safe in source coordinates could also become unsafe
after the final crop trajectory.

## Decision

Require a typed `OverlayExclusionEvidence` sidecar for every clean Tarteel
render. The sidecar binds the source, candidate, TimeMap, final transform,
campaign overlay specification, and reviewed decision. It contains entrance,
hold, exit, and maximum-extent samples. Every sample records output-space CTA
bounds and one reviewed region for faces, child/body, tablet, captions,
context, source logo, watermark, and platform rails.

The Python service copies the verified sidecar into the run, places its digest
in `AdvancedHeroRenderInput` and the output manifest, and rejects missing,
stale, blocked, unknown, or colliding evidence. The Remotion worker enforces
the presence of the digest, while cache lookup and technical QA recheck the
sidecar hash and all source/transform/overlay bindings. Historical legacy
artifacts remain readable and are not reinterpreted.

## Consequences

- CTA safety is checked after the final transform in output coordinates.
- A reviewed sidecar is required before a real clean Tarteel render can run;
  source analysis cannot silently treat missing body/tablet evidence as empty.
- Changing the crop, overlay spec, TimeMap, or sidecar invalidates the render
  input, cache, QA, and downstream review bindings.
- A real source-bound sidecar is now recorded for the current Tarteel draft
  under the ignored campaign work root. It is still a draft review artifact;
  independent human playback remains required before delivery.
