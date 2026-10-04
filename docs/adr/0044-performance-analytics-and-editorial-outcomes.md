# ADR 0044: Performance analytics and editorial outcomes

- Status: Accepted
- Date: 2026-10-04

## Context

Round 12 is merged on main as `d28b183977c1ae4a976cebdd2d1cbaf912639c3d`. Clipforge can recover jobs and compare cache hits, but it cannot record what happened after a human published a clip somewhere else. A later editorial choice needs those observations without a platform client, a second database, or an automatic change to the edit.

## Decision

Analytics is an append-only layer in the same SQLite file. Schema version 5 adds `performance_outcomes`, `editorial_feature_snapshots`, and `analytics_imports`. Migrations 1 through 4 are unchanged. A database newer than version 5 is rejected. A version 4 file upgrades in place and keeps its rows.

An outcome may name a historical artifact. The artifact row must exist, belong to the same project and source, match the declared kind, and come from a succeeded job. The file hash is checked when the file is still inside the work root. A symlink or a path outside that root is rejected. If the file is later gone, the outcome stays and verification reports that the media evidence is unavailable. It is not rebound to another artifact.

Metrics are optional. A missing view count is not stored as zero. Completion count cannot exceed views. Completion rate stays between 0 and 1. Revenue is a non-negative decimal USD amount. Observed time cannot precede published time.

The feature snapshot copies facts already on the artifact JSON: duration from the canonical time map, scores, captions, B-roll, SFX, typography, diagrams, emphasis, profile, and policy ids. Fields that are absent stay null. Hook, topic, CTA, format, and audience labels are manual. Their default is `unknown`. Nothing in this round infers them.

Imports are local JSON or JSONL. The whole file is validated before any insert. A failure inserts nothing. Replaying the exact same records returns the original rows and does not write again. A correction is a new outcome id and a new idempotency key. No update or delete command is exposed.

`analytics compare` groups observations and prints coverage, totals, means, and medians only for metrics that were present. An empty filter is `insufficient_evidence`. Cohorts smaller than five are marked small. The text says the evidence is descriptive. It does not call a cohort best, optimal, or viral, and it does not write back into profiles, plans, reviews, or jobs.

`list`, `show`, `verify`, `compare`, and `doctor` do not open a write transaction.

## Consequences

- Operators can record what they measured and compare patterns without a network call.
- QA and review rows stay the authority. Analytics stores a snapshot of a decision. It does not approve.
- Publishing, platform APIs, viewer profiles, and automatic optimization remain out of scope.
- Schema version is now 5. `clipforge db init` applies the new migration to an older file.
