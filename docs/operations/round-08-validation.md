# Round 8 validation

Date: 2026-10-03. Branch `round-08-hero-alignment-motion`. These are commands that were run on this machine. The pull request is a draft and is not merged.

## Baseline

`main` was `3b99d03080ee6c04cf6cf951937ff62b197e1b0e` (`docs: remove stale review UI limitation`). That commit contains the Round 7 merge `06783647073d8ef117ff0f0b04996e5a4a6e3bc9`. `ROADMAP.md` and `docs/operations/round-07-validation.md` record that merge. The Round 8 branch was created from that `main` tip. Round 7 history was not rewritten.

## What this round adds

Hero drafts are a separate `hero_draft_set_json` artifact. They do not replace rough previews. A candidate is rendered only when its effective decision on the current rough-preview artifact is `approved`. The production alignment adapter calls WhisperX on that clip's ASR span. Tests use `FakeForcedAlignment`. Publishing is not implemented. Dynamic reframing, B-roll, music, and sound effects are not implemented.

Profile `hero-draft-v1` is 1080×1920, 30/1, H.264, AAC, `yuv420p`, contain fit, background `neutral-dark-v1`. Fingerprint from the local smoke render: `cbb8cef5a383f022aa73044089d5554d0c10231d789132813f29e4920a944c3a`. Motion library `motion-library-v1`. Caption algorithm `hero-caption-v1`. SQLite schema stays 4. No migration.

## Commands

`uv run ruff check .` passed. `uv run ruff format --check .` passed. `uv run mypy` reported no issues in 141 source files.

`uv run pytest` passed 279 tests:

| Marker | Tests |
| --- | --- |
| general | 95 |
| media | 18 |
| transcription | 29 |
| vision | 34 |
| candidate | 35 |
| preview | 35 |
| review | 11 |
| hero | 22 |
| total | 279 |

`uv run clipforge schema check` printed `Schemas match` for `schemas/generated`. Eight Hero contracts were added. `ReviewDecision` was not given a new field. Hero reviews use the existing `subject_kind = hero`.

`pnpm --dir apps/renderer lint`, `typecheck`, and `test` passed (21 Vitest tests).

## Live WhisperX alignment

WhisperX is installed only in `~/.local/clipforge-hero-align`, not in the project lock. Provisioning used `UV_TORCH_BACKEND=cpu` and `whisperx==3.4.5`.

| Piece | Value |
| --- | --- |
| Python | 3.11.15 |
| WhisperX | 3.4.5 |
| torch | 2.14.1+cpu |
| torchaudio | 2.11.0+cpu |
| NLTK | 3.10.3 |
| punkt | `/home/pakka/.cache/nltk/tokenizers/punkt_tab/english` |
| Device | cpu |
| Model | torchaudio `WAV2VEC2_ASR_BASE_960H` |
| Checkpoint | `~/.cache/torch/hub/checkpoints/wav2vec2_fairseq_base_ls960_asr_ls960.pth` |
| Checkpoint SHA-256 | `488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d` |

Speech was generated locally with eSpeak NG 1.52.0, not committed. The transcript text was `Café costs $12.50 today please.` Offline environment: `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_DATASETS_OFFLINE=1`, `NLTK_DATA=/home/pakka/.cache/nltk`.

Commands, against database `/tmp/clipforge-hero-live/clipforge.sqlite3` and work root `/tmp/clipforge-hero-live/work`, candidate `2f2752f3-7ae2-5911-8b3b-70fb58d2f34a`:

```text
clipforge hero doctor
clipforge hero align source-1 2f2752f3-7ae2-5911-8b3b-70fb58d2f34a
clipforge hero plan source-1 2f2752f3-7ae2-5911-8b3b-70fb58d2f34a
clipforge hero render source-1
clipforge hero verify source-1
```

No `FakeForcedAlignment` was passed. Align took 23.969 seconds and recorded WhisperX 3.4.5. Render took 29.594 seconds (`runtime_seconds: 29.061`) and wrote hero set `c2e68f26-dd27-47c0-9ed9-d670774ab8ae`. A second render was `cache: hit` in 0.244 seconds. The rough preview manifest hash stayed `8dc56c5228a304f214b487cabf27e9992398014508c084108e61f17ddd6fa1d8`. The rough artifact id was `409e43a7-6232-48a6-a50f-ae8c5376ce2d`.

Aligned words, all `forced`, source and output microseconds, half-open frames:

| text | source us | output us | frames |
| --- | --- | --- | --- |
| Café | 60000–382000 | 60000–382000 | 2–12 |
| ` costs` | 423000–664000 | 423000–664000 | 13–20 |
| ` $12.50` | 684000–805000 | 684000–805000 | 21–25 |
| ` today` | 825000–926000 | 825000–926000 | 25–28 |
| ` please.` | 946000–1127000 | 946000–1127000 | 29–34 |

Intervals are positive, monotonic, and non-overlapping. Touching frame 25 is half-open. The full source was not aligned; the adapter trimmed the candidate ASR span.

ffprobe of the Hero MP4: H.264, 1080×1920, `yuvj420p`, 30/1, AAC, duration 3.200000 seconds. Remotion 4.0.532.

## OCR

Tesseract 5.5.3 from a user-local conda-forge install, language `eng`, data in `/home/pakka/.local/clipforge-ocr/share/tessdata/`. It is not a Clipforge dependency.

A frame at 1.0 seconds was decoded from the Hero MP4, cropped to the lower caption area, and passed to `tesseract --psm 6 -l eng`. The OCR text was:

```text
Café costs $12.50 today please.
```

Whitespace was not changed. The accent and `$12.50` were present.

## Earlier fake-backend smoke

`tests/test_hero_smoke.py` still uses `FakeForcedAlignment` when Remotion is installed and WhisperX is not. That run printed `hero_smoke_seconds 16.150` and is not the live-alignment evidence.

## CI

Draft pull request: https://github.com/Ammar-1652/ai-shortform-engine/pull/8

The first push, commit `15c865fac353880cc192a9825aebe8ab8352c6bc`, failed the hero job. GitHub's runner already had Chrome, the smoke test started Remotion, and `@remotion/bundler` was not installed in that job. Push run: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37139869791. Pull request run: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37139873074.

Commit `a2f105a` skips that smoke unless the renderer packages are installed. These runs were green. Every listed job passed: python, media, transcription, vision, candidate, preview, review, hero, and renderer.

- Push: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37140026025
- Pull request: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37140028751

The follow-up offline-alignment hardening in commit `1b88f406e2eb19d4e4c88aaaccfe9bc114bec957` and the mypy correction in `3a8ed0f9381b902c1749440c1e5e8e61821e61d5` also passed every listed job:

- Push: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37145159495
- Pull request: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37145161890

Those runs predate the live WhisperX alignment. That follow-up keeps WhisperX out of the default lock, reports the torchaudio checkpoint, and passes `model_cache_only` only when the installed loader declares it.

## Limitations

- CI does not install WhisperX, torch, or the alignment checkpoint. The live run used the separate CPU environment above.
- Alignment v1 is one TimeMap segment and English. This run covered English text with `Café` and `$12.50`. It does not claim Japanese or other languages.
- The Hero profile does not reframe to a face. Fit is static `contain`.
- B-roll, music, sound effects, and publishing are not implemented.
- Approving a Hero draft only appends a review row.
