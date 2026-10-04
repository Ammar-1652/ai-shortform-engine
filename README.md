# Clipforge

Clipforge is a local-first engine for turning authorized long-form video into reviewed short-form edits. Organic posts and paid campaigns share one processing core. Profiles and policies carry the differences.

The local path is ingest, prepare, transcript, visual analysis, candidate mining, a rough preview, and a human review. Round 8 renders a separate Hero draft for candidates approved on the current rough preview. The draft is reviewable. It does not publish.

## What works

- `clipforge doctor` checks the local toolchain and prints `PASS`, `WARN`, or `FAIL`.
- `clipforge db init` and `clipforge db status` create and inspect a SQLite file.
- `clipforge project create` and `clipforge project list` store project rows. `--profile-id` validates a profile before insert. `clipforge project set-profile` assigns one later.
- `clipforge profile doctor`, `list`, `show`, and `verify` read `configs/profiles` and `configs/policies`. They do not execute those files.
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
- `clipforge candidate doctor` reports the candidate recipe, duration limits, and disk. It does not load a model.
- `clipforge candidate mine SOURCE_ID` builds a candidate set from the current transcript and visual analysis. Scores are editorial heuristics. Edit opportunity is separate. There is no virality probability and the command does not publish.
- `clipforge candidate list`, `clipforge candidate show`, and `clipforge candidate verify` read that set. `show` keeps word timing marked provisional. Verify does not repair or rescore.
- `clipforge preview doctor` reports the rough-preview recipe, Node, pnpm, ffmpeg, ffprobe, and a local browser. It does not launch the browser or download one.
- `clipforge preview render SOURCE_ID` builds one review MP4 per selected candidate. `--force` renders again and keeps the previous run.
- `clipforge preview list`, `clipforge preview show`, and `clipforge preview verify` read the current set. Verify does not render or repair. Captions stay provisional. Verify also checks each MP4 with ffprobe.
- `clipforge review doctor` reports the review contract and that the server binds to loopback.
- `clipforge review open SOURCE_ID` serves a local page for the current rough previews. The host must be `127.0.0.1`.
- `clipforge review list`, `clipforge review decide`, and `clipforge review verify` read or append human decisions. A decision does not change the preview files.
- `clipforge hero doctor` reports WhisperX, the alignment model cache, and that a normal run does not download.
- `clipforge hero align SOURCE_ID CANDIDATE_ID` force-aligns one approved clip from the ASR FLAC. It does not align the rest of the source. `--allow-model-download` is required before a missing model can be fetched.
- `clipforge hero plan SOURCE_ID CANDIDATE_ID` writes a Hero edit plan from that forced alignment. Provisional timing is refused.
- `clipforge hero render SOURCE_ID` renders approved candidates in rank order into a separate Hero draft set. `--force` keeps the previous run.
- `clipforge hero list`, `clipforge hero show`, and `clipforge hero verify` read that set. Verify does not align, render, or repair.
- `clipforge hero review open SOURCE_ID` serves a loopback page for the current Hero drafts. `doctor`, `list`, `show`, and `verify` only read. `decide` appends a decision bound to that Hero artifact, plan, and alignment. Approval does not publish or encode a new file.
- `clipforge hero advanced plan` and `clipforge hero advanced render` write a separate advanced Hero set. Local B-roll, typography, diagrams, SFX, and semantic emphasis are supported. Music, Envato, and publishing are not included. The picture uses contain framing.
- `clipforge qa run SOURCE_ID` writes a `qa_set_json` artifact for the current advanced Hero draft. `list`, `show`, and `verify` only read. `qa gate` succeeds only when technical and campaign QA both pass and still match the current artifact.
- `clipforge job list`, `show`, and `verify` read recorded jobs. `recover` marks a stale running job failed. `resume` and `retry` start a new attempt and keep the previous row. A changed source hash or blocked rights record is refused.
- `clipforge batch run` prepares several sources in one SQLite database, in the order given. `list`, `show`, and `verify` only read. `resume` reruns children that are not a verified success. One source failure does not erase another source. The batch does not approve or publish.

## What does not work yet

- Full-source WhisperX transcription
- Active-speaker detection, face recognition, and dynamic reframing
- Music. Local B-roll and SFX are supported. Music is prohibited.
- Publishing and analytics
- A review UI on any address other than loopback
- Envato search or download
- Publishing
- Analytics and learning

`clipforge --help` only lists commands that run. There is no publish command.

## Hero alignment runtime

WhisperX is an optional local runtime. `uv sync` and CI do not install it, and it is not part of the locked default environment. That keeps the pinned `ctranslate2` used by faster-whisper unchanged.

```text
uv venv ~/.local/clipforge-hero-align --python 3.11
UV_TORCH_BACKEND=cpu uv pip install --python ~/.local/clipforge-hero-align -e . 'whisperx==3.4.5'
NLTK_DATA=~/.cache/nltk ~/.local/clipforge-hero-align/bin/python -c "import nltk; nltk.download('punkt_tab'); nltk.download('punkt')"
~/.local/clipforge-hero-align/bin/python -c "import whisperx; whisperx.load_align_model(language_code='en', device='cpu')"
```

The last command is the explicit model download. After that, normal commands set `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_DATASETS_OFFLINE=1`, and `NLTK_DATA`. `--allow-model-download` remains the only switch that may fetch weights.

The local CPU validation used WhisperX 3.4.5, torch 2.14.1+cpu, torchaudio 2.11.0+cpu, and NLTK 3.10.3. English alignment loads torchaudio `WAV2VEC2_ASR_BASE_960H` from `wav2vec2_fairseq_base_ls960_asr_ls960.pth`. WhisperX 3.4.5 does not implement `model_cache_only`; Clipforge blocks `torch.hub` downloads instead of pretending that flag exists. Alignment v1 is one TimeMap segment and English text.

## Architecture

Five planes share one core:

| Plane | Round 1 role |
| --- | --- |
| Control | Typer CLI, SQLite jobs, profiles, policies, review records |
| Media | Local ingest, canonical source clock, analysis proxy, ASR audio, faster-whisper transcript, scene and face-detection evidence, candidate mining from those artifacts. |
| AI decision | Contracts for evidence and scores. No model calls. |
| Assets | License and provenance records. No downloads. |
| Review | Human decisions are data. Nothing is published. |

The normative timing rules are in [docs/architecture/time-mapping.md](docs/architecture/time-mapping.md). Candidate mining is in [docs/architecture/candidate-mining.md](docs/architecture/candidate-mining.md). Rough previews are in [docs/architecture/rough-preview-rendering.md](docs/architecture/rough-preview-rendering.md). Decisions are in [docs/adr](docs/adr). The map of later rounds is [ROADMAP.md](ROADMAP.md).

## Requirements

- Python 3.11, installed for this repo by `uv` (`.python-version`). System Python may be newer.
- [uv](https://docs.astral.sh/uv/) 0.11 or newer
- Git
- Node.js 22 LTS or newer and pnpm, for the Remotion preview renderer
- A local Chrome or Chromium binary for `preview render`. Clipforge does not download a browser. Set `CLIPFORGE_BROWSER_EXECUTABLE` when it is not on `PATH`.
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
