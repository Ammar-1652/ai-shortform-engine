# Round 14 validation

Date: 2026-10-04. Branch `round-14-analytics-operations`. Started from Round 13 merge `31946408c5e205311b027e71d2fd292336df84b9`. The pull request is a draft and is not merged.

## Scope

Append-only manual labels, local CSV/JSON/JSONL normalization, and a loopback analytics page. SQLite schema moves from 5 to 6 in one forward migration. There is no second database and no platform client.

Commands:

```text
clipforge analytics doctor
clipforge analytics import-profile list
clipforge analytics import-profile show PROFILE_ID
clipforge analytics import FILE --profile PROFILE_ID
clipforge analytics import validate FILE --profile PROFILE_ID
clipforge analytics import list PROJECT_ID
clipforge analytics import show IMPORT_ID
clipforge analytics import verify IMPORT_ID
clipforge analytics labels list PROJECT_ID
clipforge analytics labels show ARTIFACT_ID
clipforge analytics labels set PROJECT_ID ARTIFACT_ID --reviewer-id ID
clipforge analytics labels history ARTIFACT_ID
clipforge analytics labels verify PROJECT_ID
clipforge analytics dashboard PROJECT_ID
clipforge analytics dashboard verify PROJECT_ID
clipforge analytics compare PROJECT_ID
```

## Checks

`uv run pytest` passed, 366 tests. `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy` passed (179 source files). `uv run clipforge schema check` passed. `uv run clipforge doctor` passed with 10 checks and schema version 6. Renderer lint, typecheck, and 23 Vitest tests passed.

`tests/test_round14.py` covers schema export, a version 5 upgrade, future-schema rejection through the Round 13 probe, CSV/JSON/JSONL normalization, atomic import failure, replay, corrections, duplicate rows, mixed projects, invalid dates, currencies, and metric relationships, append-only labels, effective-label ordering, stale writes, cross-project and cross-source rejection, artifact hash changes, missing media, review binding, comparison filters, missing metrics, source provenance, cache hit and miss, sidecar failure, read-only commands, loopback refusal, traversal, unknown JSON keys, and unsafe text.

`tests/test_round14_browser.py` opens the analytics page, saves a label, reloads `Café`, `説明`, and `$12.50`, and checks that a stale save is rejected. CI runs that file in the `analytics` job.

A version 5 database keeps its project row and its import row, gains the label table, and fills the new import columns with defaults.

## Limitations

- The page listens on `127.0.0.1` only. It does not call a platform.
- Import profiles parse local files. They do not fetch a post.
- Effective labels change comparison in memory. They do not edit the outcome or the edit plan.
- A label cache miss is reported. Read-only verification does not rebuild the sidecar.
- No publishing, viewer tracking, automatic approval, or autonomous optimization.
