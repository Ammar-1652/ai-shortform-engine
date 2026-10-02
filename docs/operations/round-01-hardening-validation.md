# Round 1.1 validation

Date: 2026-10-02.

## Baseline SHA

`a096a0a54795948cf1b15141e97c7b6edf14c8c4` on `main`.

Work is on `round-01-foundation-hardening`. It is not merged.

## Findings fixed

1. `AssetLicenseRecord` is stored in `asset_license_records`.
2. A source cannot cite a missing license, or a license that belongs to another asset.
3. Artifact `source_asset_id` references `source_assets`. Provenance must list that id. `job_id` and `provenance.job_id` must match, and a producing job must be named in provenance.
4. Review `artifact_id`, when set, references `artifacts`. `candidate_id` is still not a foreign key.
5. `CandidateClip` and `EditPlan` reject a time map with output duration 0.
6. `Scene` and `FaceObservation` require their own source id in provenance. Speaker attribution stays `unknown`.
7. Review subject kinds require the primary id. A final review always names an artifact, including a rejection.
8. A current-version database missing a required table fails closed and is not rebuilt.
9. `@types/node` is 22.20.5.
10. `AGENTS.md` uses the `round-XX-*` branch and draft-PR rule.
11. CI actions are the current official majors that run on Node 24: `actions/checkout@v7`, `actions/setup-node@v7`, `pnpm/action-setup@v6`, `astral-sh/setup-uv@v10`.

## Migration version

Schema version 2, name `rights_and_lineage`. Migration 1 SQL was not edited.

Version-1 sources each receive one `unknown` rights row recorded by `clipforge-migration-2`. A license id shared by two sources aborts the migration and leaves the version-1 file unchanged. Orphan artifact and review pointers do the same. Nothing is deleted to make a foreign key fit.

## Migration test results

`tests/test_foundation_hardening.py` builds a real version-1 file with migration 1 SQL, then calls `Database.initialize()`.

- One legacy source becomes an `unknown` record and `require_rights_cleared` rejects it.
- A shared license id rolls back. `user_version` stays 1. The license table is absent. Both source rows remain.
- A current database with `asset_license_records` dropped fails `status` and `initialize`. The table is still absent afterward.

## Rights storage result

Table `asset_license_records`. Repository: `insert_asset_license_record`, `get_asset_license_record`, `list_asset_license_records`. Rows are validated as `AssetLicenseRecord`. `recorded_at` and `recorded_by` are required. `schema_version` stays `1.0.0` because the shared `Versioned` literal cannot be overridden per model, and no rights row existed before this change. The exported schema shows the new fields.

## Artifact lineage result

Composite foreign key from `(license_record_id, source_asset_id)` to `(license_record_id, asset_id)`. Artifact `source_asset_id` references `source_assets`. Repository rejects a provenance list that does not contain the column value, and rejects a job id mismatch. A missing source fails the insert with `StorageError`.

## Review semantics result

`candidate` and `hero` require `candidate_id`. `caption`, `framing`, and `final` require `artifact_id` for every decision, including `rejected`. A review whose `artifact_id` is not in `artifacts` fails with `StorageError`.

## Zero-duration contract result

Every `CandidateStatus` rejects an empty time map. `EditPlan` rejects an empty time map when the digest matches. `TimeMap([])` still has duration 0 for the low-level mapper.

## Provenance result

Mismatched scene and face provenance fail validation. Tests cover `asset-a` versus `asset-b`.

## Database health result

`health_check` runs `PRAGMA quick_check` and `PRAGMA foreign_key_check`. A planted review pointing at a missing artifact is reported and not deleted. A non-database file raises `StorageError`. Ordinary `connect` checks that the current version's tables exist. It does not run `quick_check`.

Local doctor: schema version 2, 10 pass, 0 warn, 0 fail. SQLite library 3.50.4.

## Node types result

`@types/node` 22.20.5. TypeScript stays 5.9.3. Renderer lint, `tsc --noEmit`, and 3 vitest tests passed.

## GitHub Action versions

| Action | Before | After | Runtime in upstream `action.yml` |
| --- | --- | --- | --- |
| `actions/checkout` | v4 | v7 | node24 |
| `actions/setup-node` | v4 | v7 | node24 |
| `pnpm/action-setup` | v4 | v6 | node24 |
| `astral-sh/setup-uv` | v5 | v10.2.0 | node24. There is no moving `v10` tag. |

The first Actions run for this branch is the push that contains this file. This document does not claim that run is green.

## Pytest count

68 passed, including the previous timeline, compliance, rollback, schema, and renderer-adjacent contract tests.

## Lint

Ruff check passed. Ruff format check passed.

## Typecheck

mypy: no issues in 24 source files.

## Schema check

`clipforge schema check` matched `schemas/generated`. The only schema diff is `AssetLicenseRecord.schema.json`.

## Renderer checks

ESLint, `tsc --noEmit`, and vitest (3 tests) passed.

## Known warnings

- Disk was 95% full at the Round 1 inspection. Unchanged by this round.
- CUDA inference is still not executed.
- CI's Python job will still warn when ffmpeg, pnpm, or `nvidia-smi` are absent. Those warnings exit 0. They are not this round's action-runtime warnings.
- `candidate_id` has no foreign key until a candidate table exists.

## Round 2 readiness

Not started. The draft pull request has to be reviewed before media ingest.

## Independent review follow-up

The review of `c920ac7` asked for two remaining integrity fixes. They are on the same branch and the same draft pull request.

Cross-project lineage is schema version 3, migration `project_lineage_integrity`. Migrations 1 and 2 were not edited. An artifact source, an artifact job, and a review artifact must belong to the child row's project. SQLite enforces that with composite foreign keys. Null `job_id`, `source_asset_id`, and `artifact_id` stay optional. The repository returns `StorageError` with both project ids when it can see the mismatch. A version-2 file with a cross-project artifact fails migration 3, stays at `user_version` 2, and keeps its rows. A valid version-2 file built from the real migration SQL upgrades to version 3, keeps its rights row, and keeps its indexes. `initialize` twice stays at version 3.

Migration-2 placeholders still use the source row's `created_at` as `recorded_at`. That is not a separate verification time. `status` remains `unknown`, and `require_rights_cleared` still blocks those rows. Migration 2 was not rewritten to change the timestamp.

Current-schema validation now checks required columns, the critical foreign-key groups, and the migration history `1 initial`, `2 rights_and_lineage`, `3 project_lineage_integrity`. A missing column, a missing foreign key, a gap such as versions 1 and 3 without 2, or a wrong migration name fails closed and does not rewrite the file. `health_check` still runs `PRAGMA quick_check` and `PRAGMA foreign_key_check`.

No candidate table was added. No ingest, transcription, or rendering code was added.

Local validation after the follow-up: pytest 74 passed, Ruff passed, mypy reported no issues in 25 source files, schema check matched, renderer lint, typecheck, and 3 tests passed, and doctor reported schema version 3 with 10 pass, 0 warn, 0 fail. The GitHub Actions run for this follow-up commit is whatever the push of this documentation update triggers. This section does not claim that run is green until it is observed.
