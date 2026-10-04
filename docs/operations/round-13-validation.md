# Round 13 validation

Date: 2026-10-04. Branch `round-13-performance-analytics`. Started from Round 12 merge `d28b183977c1ae4a976cebdd2d1cbaf912639c3d`. Merged on main as `31946408c5e205311b027e71d2fd292336df84b9`. Round 14 starts from that commit.

## Scope

Append-only local outcomes and descriptive cohort comparisons. SQLite schema moves from 4 to 5 in one forward migration. There is no second database and no platform client.

Commands:

```text
clipforge analytics doctor
clipforge analytics record --input FILE
clipforge analytics import FILE
clipforge analytics list PROJECT_ID
clipforge analytics show OUTCOME_ID
clipforge analytics verify OUTCOME_ID
clipforge analytics compare PROJECT_ID
```

## Checks

`uv run pytest` passed, 355 tests. `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy` passed (174 source files). `uv run clipforge schema check` passed. `uv run clipforge doctor` passed with 10 checks and schema version 5. Renderer lint, typecheck, and 23 Vitest tests passed.

`tests/test_round13.py` covers schema rejection, migration from a version 4 file, future-version rejection, atomic import, replay, corrections, artifact binding, stale hashes, missing media, cross-project and cross-source rejection, deterministic feature snapshots, cohort coverage, missing metrics, read-only commands, symlink and path rejection, and the absence of network clients.

A version 4 database keeps its project row and gains empty analytics tables at version 5.

## Limitations

- Imports are local JSON or JSONL. There is no platform pull.
- Resume of analytics is not a job kind. Recording does not create a media job.
- Manual labels are not inferred.
- Cohort text does not recommend a settings change.
- No publishing, approval, viewer tracking, or automatic optimization.
