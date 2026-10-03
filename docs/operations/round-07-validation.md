# Round 7 validation

Date: 2026-10-03. Branch `round-07-candidate-review`. These are commands that were run.

## Baseline

Round 7 starts from the merged Round 6 commit `1236c3fca71726e3bb9dedc2c0fc8509de0a668b`. The closure note in `round-06-validation.md` records that Round 6 technical checks passed and that acceptance criterion 75 failed because pull request 6 was merged.

## Commands

`uv run ruff check .` passed. `uv run ruff format --check .` passed. `uv run mypy` reported no issues in 124 source files.

`CLIPFORGE_DISK_RESERVE_GB=0 uv run pytest` passed 257 tests:

| Marker | Tests |
| --- | --- |
| general | 95 |
| media | 18 |
| transcription | 29 |
| vision | 34 |
| candidate | 35 |
| preview | 35 |
| review | 11 |
| total | 257 |

`uv run clipforge schema check` printed `Schemas match` for `schemas/generated` (76 JSON files). The database schema is still 4. `ReviewDecision` was not given a new field.

`pnpm --dir apps/renderer lint`, `typecheck`, and `test` passed (17 Vitest tests).

`clipforge doctor` exited 0. `clipforge preview doctor` exited 0. `clipforge review doctor` exited 0 and reported schema version 4, the `ReviewDecision` fields, loopback `127.0.0.1`, and the three static files.

`clipforge review verify source-1` on a synthetic one-candidate preview set printed:

```text
PASS preview: preview set 85b66e9f-0403-4fc6-a105-2197c3ca7811 candidates 1
PASS reviews: 0 stored review rows
```

## Browser smoke

`tests/test_review_browser.py` opened `http://127.0.0.1/` in the installed Google Chrome (`--headless=new`, a temporary user-data directory, background networking disabled). The dumped page contained a `video` element without autoplay, the word `heuristic`, and `provisional`. It did not contain `http://` or `https://`. A saved decision was visible after reload, including the note `Café stays text`. The media route returned an MP4. No browser binary was downloaded.

## What this round does not do

Decisions are human review evidence. There is no Hero edit, no WhisperX, no publishing, and no AI call.
