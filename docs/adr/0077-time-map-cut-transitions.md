# ADR 0077: TimeMap-bound cut transitions

## Status

Accepted

## Context

Advanced Hero can now assemble several source ranges into a reviewed editorial
arc. A hard cut at each range boundary is valid, but a production short needs a
small visual bridge that does not alter the program clock or hide a bad edit.
The renderer previously had no typed representation of those boundaries, so a
composition could not prove where a transition was allowed.

## Decision

Advanced plans derive a `clean_cut_v1` `TransitionEvent` from every interior
`TimeMap` boundary. The event owns a short output-clock interval beginning at
the next segment and is serialized into the plan and Remotion render input.
Remotion renders only this allowlisted, deterministic overlay. It is not an
operator-supplied JSX/CSS payload, does not add time, and is absent from a
single-segment map. The TimeMap remains the sole source-to-output clock.

The transition is presentation only: it cannot replace a source-grounded
caption, graphic, B-roll placement, or human review. Its stable event id and
the plan/render-input fingerprints make a transition change invalidate cached
renders and downstream evidence.

## Consequences

- Jump-cut drafts visibly communicate reviewed segment changes without
  repeating footage or changing speech timing.
- Existing one-range plans remain readable with an empty transition list.
- QA and final delivery validate the same plan and render-input hashes; no
  separate transition gate is introduced.
