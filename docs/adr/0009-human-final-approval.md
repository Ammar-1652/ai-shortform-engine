# ADR 0009: Human final approval

- Status: Accepted
- Date: 2026-10-02

## Context

A short can be technically valid and still be the wrong cut, the wrong claim, or the wrong brand moment. Automatic publishing removes the last person who watched the file.

## Decision

V1 does not publish. The CLI has no publish command.

A final yes is a `ReviewDecision` with `subject_kind = final`, `decision = approved`, a human `reviewer_id`, and the `artifact_id` of the file that was reviewed. `automated` is typed as `False` only. A future publishing client, if an ADR adds one, must refuse to run without that record.

Candidate promotion and caption or framing notes use the same review model with different `subject_kind` values. They are not publication.

## Alternatives considered

- Auto-publish when QA is all `pass`. Rejected. QA does not watch the cut for taste or for claims the rules missed.
- A boolean `publish: true` on the render job. Rejected. It does not name a person or a file.

## Consequences

- Agents must not add a "successful" publish stub.
- Review rows in SQLite are the history. Deleting them to clear a block is a data bug, not a workflow.
- Building the review UI is a later round. The decision record exists now so that UI has a place to write.
