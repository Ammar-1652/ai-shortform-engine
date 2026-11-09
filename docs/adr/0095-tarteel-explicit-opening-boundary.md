# ADR 0095: Explicit Tarteel editorial opening boundary

## Status

Accepted for new Tarteel Advanced Hero arcs.

## Context

The Tarteel review trio exposed an opening-selection failure: a source clip
could carry an attention-grabbing but irrelevant greeting before the actual
question. The existing `EditorialArcDocument` stored the first segment and its
forced words, but did not identify that first word as a separately reviewed
opening decision. An idea or copied batch could therefore inherit a filler
opener without a machine-readable reason.

## Decision

`EditorialArcDocument` gains an optional `opening_word_id` and
`opening_boundary_note`. Old non-Tarteel arcs remain readable. New Tarteel
arcs must use `selection_mode=reviewed`, set `opening_word_id` to the first
hook word, and record a non-empty review note. The validator rejects a
boundary that does not equal the first hook word. The service rejects a new
Tarteel plan when either field is absent.

The field identifies the reviewed source boundary; it does not hard-code one
word or timestamp for the campaign. Each candidate must choose its own
source-grounded opening. The effective TimeMap and forced alignment remain the
only clocks.

## Consequences

- A filler opener cannot enter a new Tarteel plan without an explicit reviewed
  decision.
- Changing the opening word changes the arc bytes, alignment, render input,
  cache identity, QA, and downstream approval bindings.
- Existing artifacts and generic campaign arcs are immutable and remain
  readable under their recorded schema.
