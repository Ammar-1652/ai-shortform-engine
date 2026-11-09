# ADR 0087: Smooth directed recut boundaries

## Status

Accepted

## Context

The canonical TimeMap kept picture, speech, and captions on one clock, but a
directed multi-moment recut could still receive a hard visual boundary when no
transition preference was supplied. The result was technically synchronized
but unnecessarily abrupt.

## Decision

When a new directed clean-production plan has real non-contiguous TimeMap
segments and no explicit editorial arc transition choice, Clipforge derives
the allowlisted `concat_blur_dissolve_v1` bridge. A persisted editorial arc
that explicitly selects `none` remains a hard cut. Legacy/no-direction plans
are not reinterpreted. The bridge is rendered from output frames only and does
not change TimeMap duration or audio/caption timing.

## Consequences

- New directed recuts have a restrained visual bridge by default.
- Operators retain an auditable hard-cut override when meaning requires it.
- Transition style remains in the plan and render fingerprint, so old QA and
  approvals cannot authorize a newly styled artifact.
- The audio boundary remains a separate deterministic envelope; the visual
  bridge does not hide a cut through a spoken word.
