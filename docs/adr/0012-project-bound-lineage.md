# ADR 0012: Project-bound lineage

- Status: Accepted
- Date: 2026-10-02

## Context

Migration 2 proved that a referenced id exists. It did not prove that the referenced row belongs to the same project. An artifact in project A could name a source or job from project B, and a review in project A could name an artifact from project B. Those links are lineage corruption. Version 2 is already on the review branch, so the repair has to be a new migration.

A database that only matches table names can also claim the current version while missing a column, a foreign key, or a migration row.

## Decision

Schema version 3, migration `project_lineage_integrity`, rebuilds `source_assets`, `jobs`, `artifacts`, and `reviews`. Migrations 1 and 2 are unchanged.

Composite foreign keys bind each child to a parent in the same project:

- `artifacts (source_asset_id, project_id)` references `source_assets (source_asset_id, project_id)`
- `artifacts (job_id, project_id)` references `jobs (job_id, project_id)`
- `reviews (artifact_id, project_id)` references `artifacts (artifact_id, project_id)`

SQLite does not enforce a composite foreign key when any column in it is null. A null `job_id`, `source_asset_id`, or `artifact_id` stays optional. `project_id` itself stays required and still references `projects`.

`source_assets (license_record_id, source_asset_id)` still references the rights row for that same source.

Reviews also require the primary subject id in SQL: `candidate` and `hero` need `candidate_id`. `caption`, `framing`, and `final` need `artifact_id`. There is still no candidate table, so `candidate_id` is not a foreign key.

Before the rebuild, migration 3 lists every cross-project link and stops. It does not change a `project_id`, re-parent a row, or delete one. The transaction rolls back.

A file that already claims the current version is checked for required tables, required columns, those foreign-key groups, and the full migration history `(1, initial)`, `(2, rights_and_lineage)`, `(3, project_lineage_integrity)`. A gap or a wrong name fails. Missing columns and keys are not added back. `health_check` still runs `PRAGMA quick_check` and `PRAGMA foreign_key_check` after that structural check. Ordinary connections run the structural check and not the full integrity pragmas.

The repository raises `StorageError` when it can see that an existing parent belongs to another project, before SQLite reports a generic foreign-key failure.

## Alternatives considered

- Python checks only. Rejected. A raw insert or a later bug would still write the bad link.
- Edit migration 2. Rejected. That migration has already been pushed and exercised.
- A candidate table so reviews can foreign-key `candidate_id`. Rejected. Candidate persistence is still deferred.
- Hash `sqlite_master` SQL. Rejected. Formatting differences would fail healthy files.

## Consequences

- A version-2 file with only same-project links upgrades. A version-2 file with a cross-project link stays at version 2 until someone repairs it.
- Later ingest must write the source, the job, the artifact, and the review inside one project.
- `candidate_id` can still name a candidate that was never stored. That remains a known limit.
