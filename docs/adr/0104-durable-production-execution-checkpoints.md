# ADR 0104: Durable production execution checkpoints

**Status:** accepted for the operator-driven local workflow

## Context

Campaign production previously wrote a final campaign report after its source
observations completed. If the controller stopped between sources, the next
operator had to infer progress from artifact directories and rerun work. That
made recovery ambiguous and could not prove which stage had been verified.

Advanced Hero already has a separate chunk-level render checkpoint. Campaign
execution needs a higher-level receipt that coordinates the existing services
without becoming another artifact, cache, database, or approval authority.

## Decision

Campaign execution writes an append-only journal and an atomically replaced
checkpoint under `campaigns/executions/<execution-id>/` in the ignored work
root. The checkpoint contains the request fingerprint, ordered source ids,
completed source records, stage receipts, status, and the eventual campaign
run id. Each receipt contains stage status, attempt, input/dependency hashes,
artifact id/hash, and reason code. No filesystem paths or secrets are stored.

The existing campaign manifest remains the production report and delivery
authority. The checkpoint may justify reuse only after the normal source,
rights, artifact, alignment, review, QA, and delivery checks pass again.

`campaign run` records progress after each bounded source step. A failure
leaves the checkpoint in `failed` state and preserves the prior package.
`campaign resume` finds the checkpoint bound to the final run and reuses only
source records that pass the normal current-evidence verifier. A changed source,
artifact, policy, approval, or dependency causes the source to run again.

Checkpoint `show`, `verify`, and `find` are read-only. They never mark a stage
complete, mutate a database row, or create approval. Force execution uses a new
checkpoint id and keeps the previous checkpoint available for audit.

## Consequences

- A crash has a durable last verified source and stage receipt.
- Resume is evidence-based and cannot turn a file's presence into success.
- Existing artifact, job, QA, final-review, and delivery authorities remain
  unchanged.
- The checkpoint is local and offline; Drive may archive it later but cannot
  override it.
- Old campaign manifests remain readable because the new record is additive.
