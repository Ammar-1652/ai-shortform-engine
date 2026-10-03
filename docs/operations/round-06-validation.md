# Round 6 validation

Date: 2026-10-03. Branch `round-06-rough-renderer`. Starting commit `f9d3e6153b976a5509dac940b7780f7856322794`. These are the commands that were run, not a plan.

## Closure correction

Checked against GitHub on 2026-10-03, after pull request 6 left the draft state.

Round 6 technical validation passed. The command results below are unchanged.

Round 6 administrative acceptance criterion 75 failed. That criterion required the pull request to stay a draft and remain unmerged. Pull request 6 was merged.

- Merge commit on `main`: `1236c3fca71726e3bb9dedc2c0fc8509de0a668b`
- Pull request head that was merged: `242c00ea371ac0349c443a74b97fe5e5aabe76f1`
- An earlier report named `1317cdeddc484835de4e78fcc059aa8aed6a6c03`. That commit exists. It is an ancestor of the pull request head, not the merged head. Later commits on the branch confined preview paths before the squash merge.
- Verified `main` at the start of Round 7 is the merge commit above.
- Round 6 is not a full PASS while criterion 75 is false.
- Round 7 starts from this merged baseline.

## Environment

- OS: EndeavourOS, Linux x86_64
- CPU: 12th Gen Intel Core i7-12700H, 14 cores / 20 threads
- RAM: 15 GiB, no swap
- GPU: NVIDIA GeForce RTX 3060 Laptop GPU is visible to `nvidia-smi`. Rough preview rendering used Remotion with `gl: "swangle"`. It did not use the GPU.
- Python: 3.11.15
- Node: v26.8.1
- pnpm: 10.34.6
- FFmpeg and ffprobe: n9.0.1
- Browser resolved by `preview doctor`: `/usr/bin/google-chrome-stable` (Google Chrome 152.0.7977.64)
- Remotion, `@remotion/renderer`, `@remotion/bundler`: 4.0.532
- React: 19.3.0
- TypeScript: 5.9.3
- SQLite schema: 4. No migration was added.

## Commands

`uv run ruff check .` passed. `uv run ruff format --check .` passed. `uv run mypy` reported no issues in 118 source files.

`CLIPFORGE_DISK_RESERVE_GB=0 uv run pytest` passed 243 tests:

| Marker | Tests |
| --- | --- |
| general | 95 |
| media | 18 |
| transcription | 29 |
| vision | 34 |
| candidate | 35 |
| preview | 32 |
| total | 243 |

`uv run clipforge schema check` printed `Schemas match /home/pakka/hero_edit/schemas/generated.` The export wrote 76 JSON files, including the seven new preview contracts.

`pnpm --dir apps/renderer lint`, `typecheck`, and `test` passed. Vitest ran 17 tests: 3 scaffold tests and 14 rough-preview tests.

`clipforge doctor` was 10 pass, 0 warn, 0 fail, schema version 4. `clipforge preview doctor` passed the recipe, 720×1280, 30/1, `provisional-caption-v1`, Node, pnpm, ffmpeg, ffprobe, and the Chrome path. `clipforge candidate doctor` passed. `clipforge transcript doctor` still warns that CUDA libraries and `small.en` are absent. `clipforge vision doctor` still warns that the face model is not cached. Those warnings were not changed.

## Real render

`tests/test_preview_smoke.py` built a 2 second 1280×720 synthetic picture and a FLAC tone, mined one candidate, and rendered it with Remotion. The test passed. The output was 720×1280 H.264 with AAC audio. A decoded frame had a dark top bar, a red contained picture in the middle, and bright caption pixels in the lower safe area. The render input contained `Café`.

A separate 12 second synthetic render is recorded in `round-06-benchmark.md`. ffprobe on that file reported H.264, 720×1280, `yuvj420p`, average frame rate 30/1, AAC audio, and duration 12.011 seconds. The canonical duration was 12.000 seconds. The error is 11 ms, inside the 100 ms preview tolerance. `yuvj420p` is the full-range tag for the same 4:2:0 layout the profile requests as `yuv420p`.

## What was not claimed

Captions are provisional. The smoke used a color field and a tone, not a podcast. No Whisper model and no MediaPipe model were downloaded.
