# ADR 0036: Candidate review and artifact binding

- Status: Accepted
- Date: 2026-10-03

## Context

Round 6 publishes one current rough-preview manifest per source. A person must be able to approve, reject, or ask for changes on a candidate without changing that manifest. A later preview render must not inherit decisions that were made while watching an older file.

## Decision

Candidate reviews use the existing `ReviewDecision` row. SQLite stays at schema version 4. The service requires both `candidate_id` and `artifact_id` even though the schema allows a candidate review to omit the artifact.

`automated` stays false. The three decisions are `approved`, `rejected`, and `changes_requested`. Notes are text, capped at 4000 characters by the service.

Rows are insert-only. The service does not update or delete a review. The effective decision for a candidate is the latest row whose `artifact_id` is the current rough-preview artifact, ordered by `created_at` and then `review_id`.

Each successful preview render inserts a new artifact id instead of reusing the previous row. `find_artifact` already returns the newest row for that kind. A sidecar failure deletes the new row and leaves the previous artifact current. Reviews that name the old artifact remain history.

## Alternatives considered

- Add a `preview_set_id` column. Rejected for this round. A new artifact id already distinguishes the set that was watched, and schema version 4 can stay.
- Overwrite the latest decision. Rejected. The history is the evidence.

## Consequences

Approval is not an edit plan and not a publish action. Round 8 can read these rows. It is not started here.
