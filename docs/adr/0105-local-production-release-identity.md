# ADR 0105: Local production release identity

**Status:** accepted for the operator-driven local workflow

## Context

The editorial direction, render, and recovery work can be correct while the
checkout changes underneath a resumable run. A branch or commit alone does not
describe relevant uncommitted skills, schemas, renderer files, policy files, or
lockfiles. Reusing a checkpoint after those bytes change can produce a result
that no longer matches the evidence.

## Decision

`clipforge operator release capture` computes a release fingerprint from the
current Git `HEAD` and an allowlisted inventory of runtime files, including
relevant tracked and untracked files. It stores the snapshot under the ignored
work root with relative paths, byte hashes, and sizes. It does not fetch,
checkout, activate, or publish code and it never captures credentials.

Campaign execution checkpoints bind the release id and fingerprint. A changed
release makes an old checkpoint stale; the controller captures a new release
and does not reuse old source receipts. `operator release verify` is read-only.

The release snapshot supplements Git and does not replace branch, PR, or human
review. Old render and review artifacts remain immutable under their recorded
recipe and can still be verified with the release that produced them.

## Consequences

- Resume decisions include dirty working-tree dependencies that affect output.
- Release capture is offline and bounded to repository files.
- A release mismatch blocks reuse and requires a new checkpoint/evidence path.
- The snapshot contains facts and hashes, never absolute paths or secrets.
