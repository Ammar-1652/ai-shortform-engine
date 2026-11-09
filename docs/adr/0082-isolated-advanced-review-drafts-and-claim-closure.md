# ADR 0082: Isolated Advanced review drafts and claim closure

Status: accepted

## Context

Advanced Hero review drafts may be rendered before a current Hero approval so
that a human can compare Hero and Advanced presentation. The earlier draft-only
implementation wrote the ordinary Advanced plan, sidecar, and artifact
namespace. That allowed an unapproved experiment to replace the current
approved package. Word-boundary validation also allowed a beat to end on a
syntactically valid but editorially unfinished claim.

## Decision

Store pending Advanced directions, plans, remapped alignments, arcs, runs,
sidecars, cache records, and artifact rows under an explicit review-draft
namespace and artifact kind. Default Advanced commands read only the approved
namespace. The `--draft-only` commands opt into the review namespace and
delivery remains approval-gated.

Editorial arc segments carry an explicit `claim_closure` decision. Rendering
requires `complete`; segments without terminal source punctuation must be
marked as continuations. The operator must extend or replace an open claim
with source-backed words; the renderer never invents a completion.

Native motion graphics distinguish a source-grounded business identity card
from a quantitative business trend chart. The latter requires numeric evidence.

## Consequences

Approved artifacts and approvals remain verifiable after review experiments.
Review drafts need an explicit review command or direct artifact path because
they are not the current delivery package. Cache and stale checks include the
namespace/status. Historical approved artifacts remain immutable. Existing
arc documents without `claim_closure: complete` fail closed when reused and
must be deliberately reviewed again.
