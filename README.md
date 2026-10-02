# Clipforge

Clipforge is a local-first engine for turning authorized long-form video into reviewed short-form edits. Organic posts and paid campaigns share one processing core. Profiles and policies carry the differences.

Round 4 ingests a local video file, builds a review proxy and canonical ASR audio, transcribes that audio with faster-whisper, and records scene, frame, and face-detection evidence from the analysis proxy. It does not score candidates or render a reel.

## What works

- `clipforge doctor` checks the local toolchain and prints `PASS`, `WARN`, or `FAIL`.
- `clipforge db init` and `clipforge db status` create and inspect a SQLite file.
- `clipforge project create` and `clipforge project list` store project rows.
- `clipforge schema export` and `clipforge schema check` write and verify JSON Schema.
- The timeline mapper converts source time, output time, and frames for jump cuts.
- Pydantic contracts reject illegal timing, missing provenance, weighted compliance, and automated final approval.
- `clipforge source inspect` probes a local file without writing a database row.
- `clipforge source ingest` stores a referenced source after an explicit rights assertion.
- `clipforge media prepare` writes an H.264 analysis proxy and, when the source has audio, 16 kHz mono FLAC aligned to the video clock.
- `clipforge media verify` reports source, rights, proxy, and audio state without repairing them.
- `clipforge storage status` prints free space and the disk reserve.
- `clipforge transcript doctor` reports the local ASR runtime and does not download a model.
- `clipforge transcript run` transcribes the prepared ASR FLAC for one source. Word timestamps are provisional. A missing model downloads only with `--allow-model-download`.
- `clipforge transcript verify` and `clipforge transcript show` read the stored transcript and do not load a model.
- `clipforge vision doctor` reports PySceneDetect, PyAV, OpenCV, and MediaPipe. It does not download or load the face model.
- `clipforge vision model status` and `clipforge vision model fetch face-detector --allow-model-download` manage the official BlazeFace file. Nothing downloads without the flag.
- `clipforge vision analyze` reads the analysis proxy for one source. Faces are detections only. Speaker attribution is not performed. Candidate mining is not performed.
- `clipforge vision verify` and `clipforge vision show` read the stored analysis. Verify does not repair files or load the face model.

## What does not work yet

- WhisperX alignment
- Active-speaker detection and face recognition
- Candidate mining and scoring
- Rough or Hero rendering
- Envato search or download
- A review UI
- Publishing
- Analytics and learning

`clipforge --help` only lists commands that run. There is no publish command.

## Architecture

Five planes share one core:

| Plane | Round 1 role |
| --- | --- |
| Control | Typer CLI, SQLite jobs, profiles, policies, review records |
| Media | Local ingest, canonical source clock, analysis proxy, ASR audio, faster-whisper transcript, scene and face-detection evidence. |
| AI decision | Contracts for evidence and scores. No model calls. |
| Assets | License and provenance records. No downloads. |
| Review | Human decisions are data. Nothing is published. |

The normative timing rules are in [docs/architecture/time-mapping.md](docs/architecture/time-mapping.md). Decisions are in [docs/adr](docs/adr). The map of later rounds is [ROADMAP.md](ROADMAP.md).

## Requirements

- Python 3.11, installed for this repo by `uv` (`.python-version`). System Python may be newer.
- [uv](https://docs.astral.sh/uv/) 0.11 or newer
- Git
- Node.js 22 LTS or newer and pnpm, for the renderer scaffold
- FFmpeg and ffprobe from your OS packages. `clipforge doctor` warns when they are missing. `source` and `media` commands fail until they are installed.

No Docker, Redis, Postgres, n8n, or paid inference API is required.

## Install

```bash
uv sync --all-groups
uv run clipforge doctor
```

Renderer scaffold:

```bash
cd apps/renderer
pnpm install
pnpm typecheck
pnpm test
```

Optional environment variables are listed in `.env.example`. The program does not read that file. Export `DATABASE_PATH`, `CLIPFORGE_WORK_ROOT`, or `WORK_ROOT` when you want a non-default location. `CLIPFORGE_WORK_ROOT` wins over `WORK_ROOT`. Defaults are `var/clipforge.sqlite3` and `var/work`. `CLIPFORGE_DISK_RESERVE_GB` defaults to 10. Both directories are gitignored.

## Everyday commands

```bash
uv run clipforge doctor
uv run clipforge db init
uv run clipforge db status
uv run clipforge project create "Launch film"
uv run clipforge project list
uv run clipforge schema check
uv run clipforge storage status
uv run clipforge source inspect /path/to/video.mp4
```

Ingest and prepare, after `db init` and `project create`:

```bash
uv run clipforge source ingest PROJECT_ID /path/to/video.mp4 \
  --rights-status campaign_provided \
  --rights-evidence /path/to/brief.pdf \
  --rights-name "Campaign provided footage" \
  --confirm-rights
uv run clipforge media prepare SOURCE_ID
uv run clipforge media verify SOURCE_ID
uv run clipforge transcript doctor
uv run clipforge transcript run SOURCE_ID --allow-model-download
uv run clipforge transcript verify SOURCE_ID
uv run clipforge transcript show SOURCE_ID
```

`--confirm-rights` records your assertion. It does not verify the license. The original file stays where it is. A second `media prepare` reuses a valid proxy and FLAC instead of transcoding again. A second `transcript run` reuses a valid transcript instead of calling the model again. `--allow-model-download` is required only when the model is not already under `CLIPFORGE_MODEL_ROOT` (default `var/models`). Inference is local. The model download is the only optional network step.

`clipforge doctor` exits `0` when every check is `PASS` or `WARN`. It exits `1` when a check is `FAIL` (Python older than 3.11, an unwritable work directory, or a broken SQLite library).

## Checks

```bash
make test
make lint
make typecheck
make validate
```

`./scripts/validate.sh` runs Ruff, mypy, pytest, schema check, and the renderer lint, typecheck, and tests. `make doctor` runs the CLI doctor.

## Repository layout

```text
src/clipforge/          Python package: CLI, contracts, time map, SQLite
apps/renderer/          TypeScript scaffold. No reel composition.
schemas/generated/      JSON Schema exported from the Pydantic models
configs/profiles/       Example profile. Not an execution engine.
configs/policies/       Example hard-block policy.
docs/adr/               Architecture decisions
tests/                  pytest, including tests/fixtures
```

Python is one installable distribution, `clipforge`, in `src/`. That choice is [ADR 0010](docs/adr/0010-single-python-distribution.md). The renderer stays in `apps/renderer` so TypeScript dependencies do not mix into the Python package.

## Development rules

Read [AGENTS.md](AGENTS.md) before changing architecture. A material change needs a new ADR. Timing changes have to preserve the tests in `tests/test_timeline.py`. Schema changes require `uv run clipforge schema export` and a committed diff that `clipforge schema check` accepts.

SQLite files, source media, model weights, renders, and `.env` must stay untracked. See [SECURITY.md](SECURITY.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

Final approval is a human `ReviewDecision`. This repository cannot publish. Compliance failures are hard blocks, not points added to a creative score. Do not commit credentials or footage.

## License

No license is selected yet. All rights reserved by the repository owner until one is added.
