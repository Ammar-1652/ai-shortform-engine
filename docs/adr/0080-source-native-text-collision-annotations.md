# ADR 0080: Source-native text collision annotations

## Status

Accepted

## Context

Campaign footage can already contain a title, quote, or branding phrase. The
renderer previously knew only about generated typography, so it could paint a
duplicate hook card over source-native text while still passing caption and
geometry checks.

## Decision

A reviewed direction option must record a source-native text status. It may
declare `reviewed_absent` when inspection found no relevant baked text, or
`annotated` with `SourceNativeText` annotations. `unavailable` is retained for
legacy documents but fails clean production. Each annotation
annotation names an output interval, exact visible text, visual scene ids, and
a review note. It does not modify or hide source pixels. Advanced planning and
arc remapping carry the annotation into the plan and render input. Remotion
uses normalized text matching during the annotated interval to suppress the
duplicate optional typography card and leave the complete speech caption layer
intact.

The annotation is optional because OCR is not assumed to be available. Missing
annotations do not claim that source text is absent; the decoded review bundle
must still record the collision review. Changed annotations alter plan/render
identity and invalidate downstream evidence.

## Consequences

Operators can explicitly record a baked opening title without giving the
renderer arbitrary OCR output or source-pixel editing authority. Existing
artifacts remain immutable. A new direction and approval are required to apply
the annotation to a campaign render.
