# ADR 0114: Resumable failure receipts and reviewed output regions

- Status: Accepted
- Date: 2026-11-08

## Context

Treatment observations previously carried selected media frames and a numeric
relevance score, while the direction placement carried its own optional output
rectangle. The two records could therefore drift. Browser render checkpoints
also recorded completed units, but did not explain which unit was active, how
many times it had been attempted, whether cleanup completed, or whether a
failed run was safe to resume.

## Decision

Reviewed visual observations may carry an immutable `broll` output-space
region and a crop/reframe/camera geometry dependency hash. A graphic placement
that references such an observation must carry the same rectangle and hash.
Treatment revision binds the observation region into the shared visual evidence
bundle, so camera collision checks and downstream QA consume the measured
placement instead of a tag-only claim.

Each checkpointed Hero or Advanced Hero render unit records its cumulative
attempt count, active unit and attempt, bounded failure category, process
cleanup status, and resume eligibility. The checkpoint is written before a
worker starts and after every successful or failed unit. Partial media remains
ineligible for assembly and delivery. A completed checkpoint is marked
`complete` only after the final encoded file is atomically promoted.

The renderer worker keeps a per-run retry bound and resumes missing units only
when the existing input and dependency hashes still match. The persisted
attempt history is evidence; it does not authorize stale bytes or bypass the
existing render authorization, QA, review, or delivery gates.

## Compatibility

- Existing observations without regions remain readable.
- Existing placements without observed regions remain readable.
- Existing checkpoints parse with defaults and retain their recorded unit
  receipts; new renders write the additional state.
- No SQLite migration is required; these records remain ignored-work-root
  sidecars.
- Approved MP4s and old manifests are immutable and are never reinterpreted.

## Consequences

The treatment path can prove where a selected visual asset is placed and can
reject a placement/observation geometry mismatch before rendering. A browser
crash now leaves an operator-readable, hash-bound recovery record and a
deterministic test proves that resume renders only missing units.
