# Final review and delivery gate

Local delivery needs a human final decision for the current Advanced Hero evidence. See [ADR 0064](../adr/0064-final-review-and-delivery-gate.md).

SQLite schema version stays 6. Contract `schema_version` stays `1.0.0`. No migration was added. `subject_kind = final` was already allowed when the row names an artifact.

## What authorizes delivery

An effective final review is the newest `final` row for the current candidate and Advanced Hero artifact. `approved` is effective only when the stored evidence digest still matches the source hash, QA set, Advanced Hero manifest, plan, alignment, profile fingerprint, rights fingerprint, reframing strategy, and trajectory hash. `rejected` and `changes_requested` block delivery. An older artifact's approval stays in history. A contain plan stores an empty trajectory hash. A face-follow approval does not authorize a different trajectory.

Hero approval does not authorize delivery. A passing QA set does not authorize delivery. Candidate approval is still required, and it does not replace the final decision.

## Commands

`clipforge final review doctor` only reads. `list`, `show`, and `verify` only read. `decide` appends one row. `open` serves `http://127.0.0.1:<port>/final-review`. `publish plan` and `publish export` fail with `final_approval_required` until the effective decision is `approved`.

The page uses a native `video` element with `controls` and without `autoplay`. Notes and labels are assigned with `textContent`. The card shows the requested strategy, the applied strategy, the face-track id, the trajectory hash, and the reframing blocker. A face track is not a speaker and not an identity.

## Campaign production

The aggregate adds a `final_review` stage for each source. A missing or rejected final decision blocks that source. Another source can still succeed. Resume retries the blocked source. An unchanged approved package is a cache hit and is not rendered again.

## Deferred

Whop MCP stays deferred. External platform publishing stays deferred. This gate does not upload a package and does not store Whop credentials.
