# Round 12 validation

Date: 2026-10-04. Branch `round-12-jobs-cache-restart-batch`. Started from Round 11 merge `338ac295691a44816c3497a946a2f7c453bcdc1b`. The pull request is a draft and is not merged.

## Scope

Durable local jobs, cache checks, restart, and one-database batch runs. SQLite schema stays 4. No second database. No publisher.

Commands:

```text
clipforge job doctor
clipforge job list [PROJECT_ID]
clipforge job show JOB_ID
clipforge job verify JOB_ID
clipforge job recover [PROJECT_ID]
clipforge job resume JOB_ID
clipforge job retry JOB_ID
clipforge batch doctor
clipforge batch run SOURCE_ID [SOURCE_ID ...]
clipforge batch list BATCH_ID
clipforge batch show BATCH_ID
clipforge batch verify BATCH_ID
clipforge batch resume BATCH_ID
```

`list`, `show`, and `verify` do not write. `recover` marks a stale `running` job `failed` from `updated_at`. It does not mark one `succeeded`. `resume` and `retry` create a new job id and keep the previous row. Unknown kinds fail closed.

## Checks

`uv run pytest` passed, 345 tests. That includes the Round 12 job, cache, promotion, batch, and path tests, plus the existing Round 1–11 suite. `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy` passed (168 source files). `uv run clipforge schema check` passed after exporting `BatchChild` and `BatchManifest`.

`tests/test_round12.py` covers stale recovery, resume and retry history, hash and rights refusal, cross-project refusal, lock contention before insert, a media cache hit that does not start ffmpeg, a failed producer that misses, a transcript cache hit that does not call the backend, force and model-revision misses, corrupt and symlinked cache files, promotion boundaries, batch order, child isolation, resume, read-only verify, symlink batch directories, and confined promotion paths.

`tests/test_transcription.py` still proves a transcript cache hit does not call the fake backend and `--force` does. `tests/test_media_integration.py` still proves a second prepare is served from cache.

`pnpm --dir apps/renderer lint`, `typecheck`, and `test` passed (23 Vitest tests). `uv run clipforge doctor` passed with 10 checks and schema version 4.

Push CI: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37182225440

Pull-request CI: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37182227762

Both runs succeeded. Each had nine jobs: python, media, transcription, vision, candidate, preview, review, hero, and renderer.

## Limitations

- Production resume covers `media_prepare`, `transcribe`, and `rough_preview_render`. Vision, candidate, Hero, advanced Hero, and QA jobs fail closed instead of being guessed.
- `batch run` executes `media_prepare` only. Concurrency other than 1 is rejected.
- A full media cache hit does not execute ffmpeg to compare the installed binary with the stored tool version. Remove the recipe sidecar to rebuild after an ffmpeg upgrade.
- A changed source file during transcription is refused. The old transcript is not a hit, and the backend is not started.
- Batch `--force` is recorded. Media prepare treats a changed source hash as a miss and has no second force switch.
- No publishing, analytics, Envato, full-source WhisperX, speaker attribution, face recognition, or automatic approval.
