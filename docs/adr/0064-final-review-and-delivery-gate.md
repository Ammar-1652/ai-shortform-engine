# ADR 0064: Final review and delivery gate

- Status: Accepted
- Date: 2026-10-06

## Context

Clipforge can review a candidate, approve a Hero draft, render an Advanced Hero, pass QA, and copy a local delivery package. Those checks are not the same decision. A Hero approval or a passing QA set was enough for `publish export` to copy the MP4. The operator had no append-only decision bound to the exact Advanced Hero artifact, QA set, source hash, and policy fingerprints.

SQLite schema 6 already allows `subject_kind = final` when the row names an artifact. Whop MCP and external platform publishing stay out of this round.

## Decision

Local delivery requires an effective final `ReviewDecision`:

- `subject_kind` is `final`
- `automated` is false
- `candidate_id` and `artifact_id` name the current candidate and Advanced Hero artifact
- the newest row for that pair wins, ordered by `created_at` then `review_id`
- `rejected` and `changes_requested` supersede an older approval
- a row for an older artifact stays in history and is not effective

The evidence digest is stored with the row and in `final-reviews/<review_id>.json` under the work root. The sidecar has no filesystem path. A changed source, QA set, Advanced Hero manifest, plan, alignment, profile, rights, or recorded delivery hash makes the approval ineffective. The first export may follow an approval that has no delivery hash yet. A later checksum failure blocks that package.

`publish plan` and `publish export` fail with `final_approval_required` when that decision is missing. Campaign production records a `final_review` stage on the aggregate and blocks only the source that lacks approval.

The review page binds to `127.0.0.1`, serves the verified MP4, and rejects a stale post with a reload message.

## Alternatives considered

- Treat Hero approval as final. Rejected. The Hero decision is about the draft, not the Advanced Hero package.
- Treat QA pass as final. Rejected. QA is a check, not a human decision.
- Add SQLite columns for every hash. Rejected. Schema 6 already stores the decision. The digest rides with the row and the work-root sidecar.

## Consequences

Delivery without a current final approval fails closed. Whop MCP stays deferred. External publishing stays deferred. SQLite schema stays 6.
