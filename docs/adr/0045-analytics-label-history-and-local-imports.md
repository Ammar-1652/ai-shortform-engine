# ADR 0045: Analytics label history and local imports

- Status: Accepted
- Date: 2026-10-04

## Context

Round 13 is merged on main as `31946408c5e205311b027e71d2fd292336df84b9`. Outcomes and feature snapshots are append-only. Comparison can filter on the labels that were copied when the outcome was recorded. A person still cannot correct those labels later, normalize a platform CSV, or review the evidence on a local page.

## Decision

Schema version 6 adds `editorial_label_sets` and three columns on `analytics_imports`: `profile_id`, `validation_summary`, and `outcome_ids_json`. Migrations 1 through 5 are unchanged. A version 5 database upgrades in place and keeps its rows. A database newer than version 6 is rejected.

A label save inserts a new row. Older rows stay. The effective set is the last row for that artifact ordered by `created_at`, then `label_set_id`. The client sends the label id and artifact hash it loaded. If either has changed, the write fails with: `The labels changed while this page was open; reload before saving.` Outcomes and snapshots are not updated. Comparison reads the effective labels in memory.

The label sidecar is `analytics/labels/<artifact_id>/current.json` plus `cache.json`. The cache identity includes the project, source, outcome, artifact hash, snapshot, label history hash, and import profile. A missing, corrupt, stale, or symlinked sidecar is a cache miss. The database row is the authority. A failed publish rolls the new row back and restores the previous sidecar. The first failure leaves no current file. Read-only commands do not rebuild it.

Import profiles live in `configs/analytics-imports/`. `clipforge-observation-v1` accepts the Round 13 JSON and JSONL documents. `generic-metrics-v1` parses CSV, JSON, and JSONL into the same outcome contract. Unknown columns are rejected unless the profile sets `unknown_columns` to `ignore`. The stored import keeps the file hash, the profile id, the row count, and a short validation summary. It does not keep the path.

Every row is validated before the transaction. Duplicate ids, mixed projects, bad dates, unsupported currencies, negative metrics, and impossible count relationships insert nothing. An exact replay writes nothing. A changed measurement is a new outcome. Cancelling before commit leaves no partial rows.

`clipforge analytics dashboard` listens on `127.0.0.1` only. Any other host is refused before a listener opens. The page shows one project. It does not serve arbitrary files. User text is assigned with `textContent`. Absent metrics render as `not reported`.

## Consequences

- A person can label an artifact after the outcome exists, and comparison uses that label.
- A spreadsheet export can be normalized locally. Clipforge still does not call a platform.
- The page can save a label and nothing else. It does not approve, rank, or change an edit plan.
- Schema version is now 6.

## Non-goals

No platform API client, OAuth, upload route, viewer tracking, automatic approval, or autonomous optimization.
