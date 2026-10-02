# Clipforge

Clipforge is a local-first engine for turning authorized long-form video into reviewed short-form edits. Organic posts and paid campaigns share one processing core. Profiles and policies carry the differences.

Round 1 is the foundation: typed contracts, a canonical time map, SQLite state, a CLI, and a TypeScript scaffold. It does not transcribe, cut, score, or render video.

## What works

- `clipforge doctor` checks the local toolchain and prints `PASS`, `WARN`, or `FAIL`.
- `clipforge db init` and `clipforge db status` create and inspect a SQLite file.
- `clipforge project create` and `clipforge project list` store project rows.
- `clipforge schema export` and `clipforge schema check` write and verify JSON Schema.
- The timeline mapper converts source time, output time, and frames for jump cuts.
- Pydantic contracts reject illegal timing, missing provenance, weighted compliance, and automated final approval.

## What does not work yet

- Source ingest, proxies, and audio extraction
- faster-whisper transcription and WhisperX alignment
- Scene, face, or motion analysis
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
| Media | Time mapping only. FFmpeg is detected, not called. |
| AI decision | Contracts for evidence and scores. No model calls. |
| Assets | License and provenance records. No downloads. |
| Review | Human decisions are data. Nothing is published. |

The normative timing rules are in [docs/architecture/time-mapping.md](docs/architecture/time-mapping.md). Decisions are in [docs/adr](docs/adr). The map of later rounds is [ROADMAP.md](ROADMAP.md).

## Requirements

- Python 3.11, installed for this repo by `uv` (`.python-version`). System Python may be newer.
- [uv](https://docs.astral.sh/uv/) 0.11 or newer
- Git
- Node.js 22 LTS or newer and pnpm, for the renderer scaffold
- FFmpeg and ffprobe from your OS packages before Round 2. Round 1 only warns when they are missing.

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

Optional environment variables are listed in `.env.example`. The program does not read that file. Export `DATABASE_PATH` or `WORK_ROOT` in the shell when you want a non-default location. Defaults are `var/clipforge.sqlite3` and `var/work`. Both are gitignored.

## Everyday commands

```bash
uv run clipforge doctor
uv run clipforge db init
uv run clipforge db status
uv run clipforge project create "Launch film"
uv run clipforge project list
uv run clipforge schema check
```

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
