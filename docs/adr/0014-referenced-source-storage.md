# ADR 0014: Referenced source storage

- Status: Accepted
- Date: 2026-10-02

## Context

The machine this round was built on has a nearly full root filesystem. Copying every source into the work directory would spend the free space twice: once for the original and once for the copy, before any proxy exists.

The source still needs a stable identity. Filename, size, and mtime are not identity. A later reader must be able to ask for the SHA-256 without parsing a log.

## Decision

Round 2 stores sources as `storage_mode = referenced`. The database records the local `file:` URI. The bytes stay where the user put them. Derived files live under the work root, in directories named by project id and source id, never by the raw filename.

Identity is the streaming SHA-256 of those bytes. The hash is a column on `source_manifests`, unique per project together with `project_id`. The same hash in the same project returns the existing source. A different project may ingest the same bytes as its own source. There is no global deduplication.

Before derived work, size and mtime are compared with the stored values. A match is treated as unchanged. A mismatch recomputes the hash. If the hash differs, preparation stops. The stored digest is not updated and the new bytes are not processed under the old id. If the hash still matches, only size and mtime are refreshed.

Moving or deleting the original breaks later preparation. That is the cost of not copying it. A managed-copy mode is out of scope.

## Alternatives considered

- Copy the source into the work root. Rejected. Disk headroom is the constraint this policy exists to respect.
- Deduplicate across projects. Rejected. Project boundaries are intentional, including rights records.
- Use mtime as identity. Rejected. A touch, a copy, or a rewrite can change or preserve mtime independently of the bytes.

## Consequences

Operators must keep the original path stable. `clipforge media verify` reports a missing file and a changed hash. It does not repair either one.
