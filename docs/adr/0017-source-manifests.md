# ADR 0017: Source manifests

- Status: Accepted
- Date: 2026-10-02

## Context

Schema version 3 already stores a source row: URI, project, license, and provenance. It has no column for the content hash, the selected streams, or the canonical clock. Putting those facts only in a log would make the hash impossible to query and would let two writers disagree.

Migrations 1, 2, and 3 are merged history and stay unchanged.

## Decision

Schema version 4 adds `source_manifests`. One row per source, in the same project as that source:

- `content_sha256` is queryable. `UNIQUE (project_id, content_sha256)` is the same-project deduplication key.
- `size_bytes` and `mtime_ns` support the cheap mutation check. They are not identity.
- Selected stream indexes, canonical duration, and `video_origin_us` are columns.
- `probe_json` is the `NormalizedMediaProbe` document. That document is the application authority for duration, stream choice, and classification.
- `storage_mode` is constrained to `referenced`.
- The foreign key `(source_asset_id, project_id)` references `source_assets`. A manifest cannot point at another project's source.

The raw ffprobe JSON is a file artifact of kind `ffprobe_json`. It is not read back to recompute duration.

`MediaProbe` is unchanged. New ingest code writes the normalized probe, not a second interpretation of the old summary model.

## Alternatives considered

- Store the hash only inside provenance JSON. Rejected. Deduplication and mutation checks would parse a blob to answer a question the table can answer directly.
- Edit migration 3 to add the columns. Rejected. That migration is already merged.
- A new rights table. Rejected. `asset_license_records` already exists and the source row already points at it.

## Consequences

`clipforge db init` upgrades a version 3 file in place and keeps its rows. A file that claims version 4 without `source_manifests`, or without the migration history through version 4, fails closed and is not repaired. Current history is `(1, initial)`, `(2, rights_and_lineage)`, `(3, project_lineage_integrity)`, `(4, source_manifests)`.
