# ADR 0028: Deterministic candidate deduplication

- Status: Accepted
- Date: 2026-10-02

## Context

Overlapping transcript windows describe the same moment many times. The default profile may keep at most 25 candidates. The soft target of 15 is not a quota. Adjacent different ideas must survive, and the survivor of a duplicate pair must be the better editorial interval, not the busier one.

## Decision

Temporal overlap uses integer microseconds on half-open ranges. Adjacent ranges have an empty intersection. A pair is a near-duplicate when containment is at least 0.80, or when temporal IoU and token-set Jaccard are both at least 0.70. Empty token sets score Jaccard 0, so punctuation-only text is not a match. Containment can still collapse nested ranges.

Before that comparison, scored hypotheses with enough quality coverage are cut to a pre-dedupe pool of 200, ordered by the same rank used for the winner. The pool size is part of the profile fingerprint. The walk keeps the first item in each cluster. Edit opportunity is not a winner key.

Every pool member gets a `CandidateDeduplicationDecision`. Other removals get a `CandidateFilterDecision`. After dedupe, the kept list is capped at `max_candidates`. The rest are `output_cap`, not duplicates. If the raw walk hits 5000 windows it stops and sets `raw_hypothesis_cap_reached`. That is not a job failure, and it is not a claim of exhaustive search.

## Alternatives considered

- Embeddings or topic clusters. Rejected. They are not deterministic from the local artifacts and would add a model.
- Keep the first window in time. Rejected. That biases the opening of the source.
- Drop duplicates with no audit row. Rejected. The document has to explain the count.

## Consequences

A source with 7 distinct eligible intervals publishes 7. A source with more than 25 publishes 25. A source with none publishes an empty candidate list and still succeeds.
