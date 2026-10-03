# Round 9 validation

Date: 2026-10-03. Branch `round-09-hero-review`. These are commands that were run on this machine. The pull request is a draft and is not merged.

## Baseline

Round 8 merged to `main` as `7c1b22cf9266319119350b3db9e80fe18d9d155b` (`feat: add hero alignment and motion drafts`). `origin/main` and the starting `round-09-hero-review` tip were that commit. Round 8 history was not rewritten.

## What this round adds

`clipforge hero review` opens a loopback page for the current Hero draft set. The page shows manifest order, alignment words, plan and motion metadata, the effective decision, and append-only history. A decision is a new `ReviewDecision` with `subject_kind = hero`, bound to the Hero artifact, plan, and alignment the page loaded. Approval does not publish and does not encode a new Hero file.

No schema change. SQLite schema stays 4. `ReviewDecision` is unchanged.

Routes:

```text
GET  /api/hero-review
GET  /api/hero-review/hero/<candidate_id>
GET  /media/hero/<candidate_id>
POST /api/review/decisions
```

The manifest does not store an alignment checkpoint SHA, an alignment language, or an audio sample rate. The page shows `unavailable` for those.

## Commands

`uv run ruff check .` passed. `uv run ruff format --check .` passed. `uv run mypy` reported no issues in 143 source files.

`uv run pytest` passed 292 tests. `pytest --collect-only -m hero` collected 35. `pytest --collect-only -m review` collected 12.

`uv run clipforge schema check` printed `Schemas match` for `schemas/generated`. No schema file changed.

`pnpm --dir apps/renderer lint`, `typecheck`, and `test` passed (21 Vitest tests). The repository documents pnpm for the renderer. That is the command CI runs.

The Hero review browser smoke is `tests/test_hero_review_browser.py`. It uses the installed Chrome, FakeForcedAlignment, and the fake Hero encoder. It opened the loopback page, saw the portrait player without autoplay, read `Café`, `説明`, and `$12.50`, rejected a stale save after a new Hero set, saved `approved`, and showed that decision in history after reload. HTML-like notes stayed text. The run passed on this machine.

## CI

Commit `25866cf8e7fec82cadf9d5c2ee15cfc79f8fa96f`. Every listed job passed: python, media, transcription, vision, candidate, preview, review, hero, and renderer.

- Push: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37153634398
- Pull request: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37153638133

Draft pull request: https://github.com/Ammar-1652/ai-shortform-engine/pull/9

## Limitations

- Publishing is not implemented.
- Dynamic reframing, face or speaker inference, B-roll, music, and sound effects are not implemented.
- Alignment v1 stays one TimeMap segment and English. This round does not align.
- Approving a Hero draft does not render another file.
- CI does not install WhisperX. The review tests use `FakeForcedAlignment`.
- The browser smoke skips when no local Chrome or Chromium binary is installed.
