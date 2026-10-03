# Round 8 validation

Date: 2026-10-03. Branch `round-08-hero-alignment-motion`. These are commands that were run on this machine. The pull request is a draft and is not merged.

## Baseline

`main` was `3b99d03080ee6c04cf6cf951937ff62b197e1b0e` (`docs: remove stale review UI limitation`). That commit contains the Round 7 merge `06783647073d8ef117ff0f0b04996e5a4a6e3bc9`. `ROADMAP.md` and `docs/operations/round-07-validation.md` record that merge. The Round 8 branch was created from that `main` tip. Round 7 history was not rewritten.

## What this round adds

Hero drafts are a separate `hero_draft_set_json` artifact. They do not replace rough previews. A candidate is rendered only when its effective decision on the current rough-preview artifact is `approved`. The production alignment adapter calls WhisperX on that clip's ASR span. Tests use `FakeForcedAlignment`. Publishing is not implemented. Dynamic reframing, B-roll, music, and sound effects are not implemented.

Profile `hero-draft-v1` is 1080×1920, 30/1, H.264, AAC, `yuv420p`, contain fit, background `neutral-dark-v1`. Fingerprint from the local smoke render: `cbb8cef5a383f022aa73044089d5554d0c10231d789132813f29e4920a944c3a`. Motion library `motion-library-v1`. Caption algorithm `hero-caption-v1`. SQLite schema stays 4. No migration.

## Commands

`uv run ruff check .` passed. `uv run ruff format --check .` passed. `uv run mypy` reported no issues in 141 source files.

`uv run pytest` passed 278 tests:

| Marker | Tests |
| --- | --- |
| general | 95 |
| media | 18 |
| transcription | 29 |
| vision | 34 |
| candidate | 35 |
| preview | 35 |
| review | 11 |
| hero | 21 |
| total | 278 |

`uv run clipforge schema check` printed `Schemas match` for `schemas/generated`. Eight Hero contracts were added. `ReviewDecision` was not given a new field. Hero reviews use the existing `subject_kind = hero`.

`pnpm --dir apps/renderer lint`, `typecheck`, and `test` passed (21 Vitest tests).

## Smoke render

`tests/test_hero_smoke.py` ran with the local Chrome binary and the fake alignment double. WhisperX is not installed here, so the live alignment path was not executed. The test printed:

`hero_smoke_seconds 16.150 fingerprint cbb8cef5a383f022aa73044089d5554d0c10231d789132813f29e4920a944c3a motion motion-library-v1`

ffprobe accepted a 1080×1920 H.264/AAC frame. A frame at 0.5 seconds showed the contained red source, dark bars from the static contain fit, and a bright caption plate. The opening frame was darker than that later frame. The render input contained `説明` and `$12.50`. No OCR program was installed, so the decoded pixels were not read back as characters.

## CI

Draft pull request: https://github.com/Ammar-1652/ai-shortform-engine/pull/8

The first push, commit `15c865fac353880cc192a9825aebe8ab8352c6bc`, failed the hero job. GitHub's runner already had Chrome, the smoke test started Remotion, and `@remotion/bundler` was not installed in that job. Push run: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37139869791. Pull request run: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37139873074.

Commit `a2f105a` skips that smoke unless the renderer packages are installed. These runs were green. Every listed job passed: python, media, transcription, vision, candidate, preview, review, hero, and renderer.

- Push: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37140026025
- Pull request: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37140028751

## Limitations

- WhisperX and its alignment model are not installed. `hero align` fails closed instead of using provisional times. CI does not install WhisperX.
- The Hero profile does not reframe to a face. Fit is static `contain`.
- Alignment v1 expects one TimeMap segment and English text for the WhisperX aligner.
- B-roll, music, sound effects, and publishing are not implemented.
- Approving a Hero draft only appends a review row.
