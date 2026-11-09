# ADR 0098: Tarteel editorial arc review binding

## Status

Accepted for new clean Tarteel Advanced Hero plans.

## Context

The typed arc document described hook, body, and punch beats, but a plan could
carry a reviewed-looking selection without an immutable continuity record. It
could therefore open on an unrelated moment, omit setup, or land on a payoff
that did not resolve the hook.

## Decision

Clean Tarteel planning requires one accepted `EditorialArcReview` sidecar per
candidate. The sidecar binds the source, transcript, visual analysis, and the
canonical persisted arc bytes. Each beat names transcript spans and a
representative frame hash, and the review records hook promise, body
development, punch payoff, continuity decisions, claim closure, and reviewer
identity.

The planner validates the sidecar after the arc is persisted, so the review
binds the actual canonical arc digest. The digest is carried into the Advanced
plan and render input. The render service copies and rechecks the sidecar;
cache lookup and technical QA reject a missing, stale, or unaccepted review.
Historical legacy artifacts remain readable.

## Consequences

- An unrelated hook or unresolved continuity decision cannot reach clean
  Tarteel rendering through an operator override.
- Changing a source range, arc order, transcript, visual analysis, or review
  frame invalidates the plan and downstream evidence.
- A real accepted sidecar and reviewer-readable shot strip are still required
  before a Tarteel source can complete the production path.
