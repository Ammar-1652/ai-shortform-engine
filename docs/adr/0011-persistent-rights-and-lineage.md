# ADR 0011: Persistent rights records and relational lineage

- Status: Accepted
- Date: 2026-10-02

## Context

Round 1 defined `AssetLicenseRecord` and required `SourceAsset.license_record_id`, but the database had nowhere to put the rights row. A source could name a license that did not exist. Artifact `source_asset_id` and review `artifact_id` were also unchecked text. A damaged file could report the current migration number after a required table had been dropped.

## Decision

Schema version 2, migration `rights_and_lineage`, adds `asset_license_records` and rebuilds `source_assets`, `artifacts`, and `reviews` so foreign keys can be declared. Migration 1 is unchanged.

`source_assets (license_record_id, source_asset_id)` references `asset_license_records (license_record_id, asset_id)`. The rights row therefore belongs to that source.

Version-1 sources are given one placeholder rights row each:

- `status = unknown`
- `recorded_by = clipforge-migration-2`
- `recorded_at` copied from that source row's `created_at`. It is not an independent time when someone verified the rights.
- notes that say the rights were not verified

`require_rights_cleared` still rejects `unknown`. If one license id is shared by two sources, migration 2 stops, rolls back, and deletes nothing. Orphan artifact or review pointers do the same. No placeholder is marked owned, licensed, or campaign-provided.

`recorded_at` and `recorded_by` are required on `AssetLicenseRecord`. No rights row had been stored, so the shared document `schema_version` stays `1.0.0` instead of a one-model literal that the `Versioned` base cannot override. The exported JSON Schema is the record of the new fields.

An artifact whose `source_asset_id` is set must list that id in provenance. If `artifacts.job_id` is set, `provenance.job_id` is required and must match. The repository rejects contradictions before insert. The foreign key rejects a missing source or a missing artifact on a review. `candidate_id` is not a foreign key because candidates are not a table yet.

A database already at the current version that is missing a required table fails `connect`, `status`, `initialize`, and `health_check`. The missing table is not recreated. `health_check` also runs `PRAGMA quick_check` and `PRAGMA foreign_key_check`. Ordinary reads do not.

`CandidateClip` and `EditPlan` reject a time map whose output duration is 0. The low-level `TimeMap` may still be empty.

## Alternatives considered

- Leave rights as JSON on the source row. Rejected. The contract already had a separate record, and a dangling id was the bug.
- Fail migration 2 whenever any version-1 source exists, forcing a manual repair. Rejected for the common case of one license id per source. The placeholder is explicitly not clearance. The shared-id case still fails closed.
- Add a candidate table so reviews can foreign-key `candidate_id`. Rejected. Candidate persistence is not this round.

## Consequences

- New source rows must insert the rights record first.
- Legacy `unknown` rows cannot be used in an edit until a person replaces them with a real, evidenced status.
- Later ingest must keep writing the license row and the source row in one transaction.
- `clipforge db init` on a current but damaged file does not "heal" it.
