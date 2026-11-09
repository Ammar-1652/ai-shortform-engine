# ADR 0110: Codex operator revalidation of stale editorial evidence

**Status:** Accepted for the round-36 draft implementation

## Decision

Codex may revalidate and append a new operator review when a Tarteel Hero plan
identity changes but the reviewed source ranges, forced words, campaign overlay
geometry, timing, and inspected decoded frames remain unchanged. The system
rebases the evidence into a new sidecar and preserves the old sidecar as
immutable history.

The selected direction is remapped onto the current editorial arc output clock;
unselected alternatives remain historical proposals and are not validated
against the recut clock. Final human playback and publication approval remain
separate gates.

## Reason

Codex is the editorial operator for the local pipeline. Requiring a human to
repeat an unchanged arc or overlay clearance solely because a deterministic
Hero plan fingerprint changed stopped production before the actual Remotion
render. Revalidation still fails closed when source spans, words, geometry,
timing, frame evidence, or rights differ.

## Consequences

- Old approvals and proof remain immutable and auditable.
- A changed story, crop, CTA geometry, source, or inspected frame still blocks
  until fresh evidence is produced.
- Codex-owned rebases are included in plan, pilot, render, QA, cache, and
  final-review identities.
- Human review remains required for the exact encoded MP4 before delivery.
