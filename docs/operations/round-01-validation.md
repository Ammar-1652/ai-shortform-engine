# Round 1 validation

Date: 2026-10-02. Working directory: `/home/pakka/hero_edit`.

Round 1 status from this run: the local suite passed. The GitHub Actions run starts on the first push and is not claimed green here until that run is observed.

## Environment summary

EndeavourOS, Linux 7.2.3-arch1-3, x86_64. Intel i7-12700H. About 15.3 GiB RAM, no swap, about 5.1 GiB available at inspection. NVIDIA RTX 3060 Laptop, 6144 MiB, driver 610.57.04, CUDA 13.3. Disk 26 GiB free (95% used).

Project interpreter: CPython 3.11.15 via uv. System Python: 3.14.7. Node v26.8.1. pnpm 10.34.6. FFmpeg and ffprobe n9.0.1. Git 2.55.0. GitHub CLI authenticated as Ammar-1652. Full table: `docs/environment-report.md`.

## Commands run

```bash
uv sync --all-groups
./scripts/validate.sh
```

`scripts/validate.sh` runs, in order:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy`
- `uv run pytest`
- `uv run clipforge schema check`
- `pnpm lint`, `pnpm typecheck`, `pnpm test` in `apps/renderer`
- `uv run clipforge doctor`

Renderer dependencies were installed before that with:

```bash
cd apps/renderer
pnpm add remotion react react-dom
pnpm add -D typescript eslint typescript-eslint vitest @types/node
pnpm add -D typescript@5.9
```

## Test results

pytest: 53 passed.

Renderer vitest: 3 passed (`src/index.test.ts`).

Timeline mapping cases are inside the pytest run (`tests/test_timeline.py`): single range, jump cuts, exact boundaries, reversed touching ranges, overlaps, gaps, retiming, non-integer microsecond values, and 24, 25, 29.97, 30, and 60 fps including frame round-trips.

Database cases are `tests/test_storage.py`: idempotent init, missing file, rejected `:memory:`, isolation, rollback, foreign keys, corrupt JSON, and the job status check constraint.

## Lint result

Ruff check: all checks passed. Ruff format: 50 files already formatted on the validation run.

Renderer ESLint: passed (`eslint .`).

## Typecheck result

mypy: `Success: no issues found in 24 source files`. Settings: strict, Pydantic plugin, Python 3.11.

Renderer `tsc --noEmit`: passed. `tsconfig` has `strict` and `noUncheckedIndexedAccess`. TypeScript is 5.9.3. A first install pulled TypeScript 7.0.2, and `typescript-eslint` 8.71 refused to run. The scaffold was pinned back to 5.9.3. That is a tooling cap, not a skipped error.

## Schema result

`clipforge schema export` wrote 32 files to `schemas/generated` (31 model schemas plus `index.json`). `clipforge schema check` printed `Schemas match /home/pakka/hero_edit/schemas/generated.` The `TimeMap` schema is the persisted time-map document.

## CLI result

`clipforge doctor` (from `validate.sh`):

```text
[PASS] python: 3.11.15 at /home/pakka/hero_edit/.venv/bin/python3
[PASS] ffmpeg: ffmpeg version n9.0.1
[PASS] ffprobe: ffprobe version n9.0.1
[PASS] node: v26.8.1
[PASS] npm: 11.12.1
[PASS] pnpm: 10.34.6
[PASS] git: git version 2.55.0
[PASS] work_directory: writable var/work
[PASS] sqlite: library 3.50.4; clipforge schema version 1
[PASS] gpu: NVIDIA GeForce RTX 3060 Laptop GPU, 6144 MiB, 610.57.04 nvcc=/opt/cuda/bin/nvcc. CUDA inference libraries were not executed.
summary: 10 pass, 0 warn, 0 fail
acceleration: NVIDIA GPU visible to nvidia-smi. CUDA transcription is not verified in Round 1.
```

Exit code 0. pytest covers `--help`, `--version`, `db init`, `db status`, `project create`, `project list`, `schema export`, and `schema check` against a temporary database.

## Database result

SQLite library 3.50.4. Schema version 1 (`initial`). Tables: `schema_migrations`, `projects`, `source_assets`, `jobs`, `artifacts`, `reviews`. Tests use temporary files. `var/clipforge.sqlite3` was not created. `var/work` was created by doctor and is gitignored.

## Timeline mapping test result

Passed inside pytest. The cut at output 5_000_000 us on the 10-15s / 20-25s example maps to source 20_000_000 us. Frame 150 at 30 fps starts on that cut and maps to the same source instant. `29.97` is `30000/1001`. Frame 1 starts at 33366 us. A 1.001s timeline contains 30 frames and rejects frame 30.

## CI status / configuration status

File: `.github/workflows/ci.yml`.

- Python job: uv, CPython 3.11, frozen lock, Ruff, mypy, pytest, schema check, doctor.
- Renderer job: pnpm 10, Node 22, frozen lock, lint, typecheck, test.

The workflow does not download models, does not need a GPU, and does not need secrets.

Expected difference from the local doctor: the Python job's runner does not have ffmpeg, Node, pnpm, or an NVIDIA GPU. Those checks are `WARN` by ADR 0005 and `doctor.py`. They exit 0. A non-zero ffmpeg, a Python older than 3.11, or a broken SQLite check is still `FAIL`. This file records that distinction so a yellow doctor line in CI is not a hidden failure and is not a claim that CI was watched.

The first GitHub run is whatever the push of this commit triggers. It is not marked green in this document.

## Warnings

- Root filesystem is 95% full, 26 GiB free.
- No swap. Available RAM was about 5.1 GiB during inspection.
- `pip` on `PATH` is the Python 2.7 installer. `pip3` and `uv` are the Python 3 tools.
- System CPython is 3.14.7. The repo does not use it.
- CUDA toolkit and the GPU are visible. No CUDA inference library was executed.
- pnpm was absent at inspection and was installed afterward.
- Local Node is v26.8.1 (Current). CI uses Node 22. The package floor is `>=22`.
- TypeScript 7 was rejected by the ESLint tooling and pinned to 5.9.3.
- `var/work` exists locally from doctor and must stay untracked.

## Known limitations

- No ingest, transcription, analysis, candidate mining, rendering, Envato, review UI, or publishing.
- The renderer imports the `Codec` type and reads `remotion/package.json`. It does not register a composition or render a frame.
- Profiles and policies in `configs/` are examples validated by pytest. Nothing loads them into a policy engine.
- `.env.example` is not read by the process.
- V1 time maps do not retime.

## Missing optional dependencies

- faster-whisper, WhisperX, PySceneDetect, MediaPipe, OpenCV, PyTorch, and CTranslate2 are not installed. That is intentional.
- Envato credentials are not configured.

## Blockers for Round 2

- Free disk space before storing sources, proxies, and extracts. 26 GiB is tight.
- Keep using OS ffmpeg. This machine already has n9.0.1 with NVDEC and NVENC.
- Do not switch the project interpreter to system 3.14 for the media stack without a wheel check.
- Round 2 still must fail a job when ffmpeg is missing or exits non-zero. Doctor's `WARN` is only for the foundation CLI.
