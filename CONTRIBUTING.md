# Contributing

## Setup

```bash
uv sync --all-groups
cd apps/renderer && pnpm install
uv run clipforge doctor
```

Use `uv run` so the interpreter is the pinned Python 3.11, not a newer system Python. Export `DATABASE_PATH` or `WORK_ROOT` when you do not want the defaults under `var/`. The process does not read `.env` for you.

## Before an architecture change

1. Read `ARCHITECTURE.md`.
2. Read the ADRs that cover the area.
3. If the change alters a plane boundary, a clock, a gate, storage, or a chosen tool, add `docs/adr/NNNN-title.md` with status, context, decision, alternatives, and consequences.
4. Update `ARCHITECTURE.md` in the same change.

Do not bypass a Pydantic model with an untyped dict in a pipeline "just for now".

## Tests

`./scripts/validate.sh` is the full check: Ruff, mypy, pytest (unit and ffmpeg integration), schema check, renderer lint, typecheck, and tests. The integration tests need ffmpeg and ffprobe on `PATH`. CI runs them in a separate job that installs Ubuntu's ffmpeg package. `pytest -m "not media"` is the unit subset.

Run it before a commit that claims the branch is green. Do not skip a failing test or downgrade an error to a warning to satisfy CI.

SQLite tests create a temporary file. Do not point tests at a personal `var/clipforge.sqlite3`.

Timing changes extend `tests/test_timeline.py`. Include a failure case, not only the happy path.

## Schema changes

1. Change the Pydantic model.
2. Bump `schema_version` if stored JSON already shipped with the old shape. Round 1 is still `1.0.0` until a release stores data you must keep reading.
3. Run `uv run clipforge schema export`.
4. Review the diff under `schemas/generated/`.
5. `uv run clipforge schema check` must pass.

## Migrations

Add the next `Migration` in `src/clipforge/storage/migrations.py`. Do not rewrite migrations 1, 2, or 3. `clipforge db init` applies pending versions. A file newer than the code is an error.

Opening the database must not invent missing tables outside `initialize`.

## Failures

If a step cannot finish, raise `ClipforgeError` (or a subclass) or store `JobStatus.FAILED` with `error_message`. Do not catch an exception and continue. Do not return `None` from a time-map lookup.

## Branches

Do the work for a round on `round-XX-*`. Open a draft pull request into `main` and wait for review. Do not merge it yourself. Push follow-up fixes to that same branch. Do not force-push.

## Commits

Use a conventional prefix and a specific subject, for example `fix: harden foundation integrity before media ingest`.

Do not commit `.env`, databases, footage, weights, renders, `.venv`, or `node_modules`.
