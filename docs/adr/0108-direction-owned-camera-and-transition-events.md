# ADR 0108: direction-owned camera and transition events

## Status

Accepted for staged implementation on 2026-10-25.

## Context

The direction layer already binds captions, source-grounded graphics, and
rights-cleared asset placements. Camera movement and transitions were still
chosen inside the Advanced Hero builder: a directed plan received a default
dissolve at non-contiguous cuts, while the operator could not record why a
camera move or transition belonged to a beat. That made it difficult to reject
constant zooms, unrelated transitions, or motion that competed with captions
and faces.

## Decision

Add optional, versioned `camera_motion` and `transitions` arrays to each
`DirectionOption`. They remain empty for historical documents. A new event must
bind to source evidence, an output interval, a bounded intensity/geometry, and
an allowlisted path or transition style.

Camera events are converted to Advanced Hero render events and are evaluated in
output space. The renderer applies only deterministic frame-derived transforms
and uses a hold fallback when the move is absent or cannot be used safely.
Transition events start at interior TimeMap cuts and carry a narrative purpose;
they are converted to existing `TransitionEvent` records and do not create a
second clock. Existing direction documents without explicit transitions retain
their recorded default behavior so old artifacts remain verifiable.

The selected choices, evidence, component/profile hashes, render input, QA,
review, and delivery records remain bound through the existing direction and
Advanced Hero fingerprints. The renderer receives typed events only; it never
receives arbitrary animation code.

## Consequences

- Codex can explain why a camera move or transition exists and reject it when
  the source does not support it.
- Caption, face, source-native-text, and platform-safe geometry can be checked
  before encoding.
- Ready-made transition components can be used through the local registry when
  their licenses and deterministic behavior are verified.
- Historical plans remain readable and immutable because the new fields are
  additive and optional.
- A full recipe catalog, reference-analysis loop, and human visual acceptance
  remain separate gates; typed events do not prove that an edit is good.
