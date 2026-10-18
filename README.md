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
- `clipforge hero doctor` reports the WhisperX side interpreter, the alignment model cache, the speech-evidence gate, and that a normal run does not download. Production and tests discover an installed evidence pack at `~/.local/clipforge-speech-evidence`, or use an explicit `CLIPFORGE_SPEECH_EVIDENCE_ROOT`. An invalid explicit directory fails closed instead of falling back; discovery still requires matching WAV bytes and model evidence before live status is granted.
- `clipforge hero align SOURCE_ID CANDIDATE_ID` force-aligns one approved clip from the ASR FLAC. It does not align the rest of the source. `--allow-model-download` is required before a missing model can be fetched.
- `clipforge hero plan SOURCE_ID CANDIDATE_ID` writes a Hero edit plan from that forced alignment. Provisional timing is refused.
- `clipforge hero render SOURCE_ID` renders approved candidates in rank order into a separate Hero draft set. `--force` keeps the previous run.
- `clipforge hero list`, `clipforge hero show`, and `clipforge hero verify` read that set. Verify does not align, render, or repair.
- `clipforge hero review open SOURCE_ID` serves a loopback page for the current Hero drafts. `doctor`, `list`, `show`, and `verify` only read. `decide` appends a decision bound to that Hero artifact, plan, and alignment. Approval does not publish or encode a new file.
- `clipforge hero advanced plan` and `clipforge hero advanced render` write a separate advanced Hero set. Clean production requires a persisted source-grounded direction brief; it never invents hook/body/punch cards from word-position or character heuristics. Local B-roll, typography, diagrams, SFX, grouped captions, and semantic emphasis are supported. B-roll/SFX must be explicit direction placements with source evidence, purpose, relevance, and output timing; asset ids alone are a legacy compatibility path that QA and Remotion reject for clean production. Music and external Envato media are not included automatically. Final portrait delivery uses a deliberate full-frame treatment: `contain` keeps the source legible over a blurred background, `center_crop` uses the stored portrait crop, `face_follow` uses eligible stored face-track geometry through the candidate TimeMap, and `manual_window` uses reviewed source-bound 9:16 crop coordinates. Use `--focus-x/--focus-y` for a fixed subject position or `--manual-windows-file` for a typed, ordered crop trajectory that Remotion interpolates deterministically. A face box is not a speaker. An ineligible face-follow track fails closed; no strategy silently falls back to contain. The selected strategy is recorded in the render input, advanced manifest, QA evidence, final review evidence, and local delivery metadata. `hero advanced reframe doctor`, `show`, and `verify` only read. Rendering does not upload.
- `clipforge hero advanced plan` accepts `--editorial-arc-file` for a typed source-grounded hook/body/punch assembly. The arc names complete forced words and an ordered TimeMap; picture and speech are staged from that map and the parent Hero artifact remains immutable. The resulting Advanced draft is still unapproved until its exact MP4 receives QA and human final review.
- Presentation direction is audited through the project-local `.codex/skills/clipforge-motion-direction/SKILL.md`. It reads policy, transcript, alignment, profile, and current artifacts before returning exactly three source-grounded declarative hook/body/punch options. `clipforge hero advanced direction plan` binds the selected option to the current Hero plan and TimeMap and chooses among eight pinned styles (`editorial-clean-v1`, `quran-editorial-v1`, `quran-readable-v2`, `kinetic-caption-v1`, `documentary-broll-v1`, `data-explainer-v1`, `paper-explainer-v1`, `premium-minimal-v1`). A direction may also use one audited native illustration (`credit_card`, `travel_postcard`, `business_identity`, or quantitative `business_spotlight`) only when its interval, exact copied evidence text, purpose, and geometry pass validation; it is optional, stays above captions, and never carries downloaded media or executable code. A reviewed `SourceNativeText` annotation can identify a baked title or quote so duplicate baseline captions and optional typography are suppressed without editing source pixels. Numeric motion, local font identity/hashes, contrast, safe margins, and emphasis limits flow into the render identity; an explicit operator override is allowlisted. A diagram is omitted unless an operator provides explicit, unit-consistent source facts; unsupported kinds and unsafe geometry fail before rendering. Upstream iart guidance is provenance-locked in `docs/third_party/motion-skills.lock.json` and is not downloaded at runtime.
- `editorial-clean-v1` uses the locally installed DejaVu Sans Bold and Noto Sans CJK Bold fallback stack; their observed hashes and licenses (Bitstream Vera/DejaVu and SIL OFL) are recorded in the style profile and validated render-input fingerprint. The opt-in `quran-editorial-v1` style keeps the compact Quran treatment; `quran-readable-v2` is the public-readable variant with centered large lower captions, a larger centered upper context line, and word-id-bound active coloring. Both use the locally licensed Amiri Quran font through `CLIPFORGE_QURAN_FONT_DIR`. The renderer does not fetch fonts or use CDN assets.
- Burned-in captions normalize whitespace, group short words into readable phrases, keep punctuation with its phrase, and render in the final 1080×1920 safe area. Rough Preview keeps provisional ASR captions phrase-only by default; an explicit review-only `word_highlight_mode=reviewed` may show the stored word evidence, but it is not a forced-alignment claim. Advanced styles carry safe margins, contrast, and local font identity into the renderer; the clean defaults are 64px left/right, 120px top, and 300px bottom. Forced words can carry `unverified`, `correct`, or `incorrect` review status: active correct words turn green then settle white, incorrect words remain red, and unverified words never claim correctness. Rough review variants may use a bounded uniform `video_scale_permille` and `video_offset_x_px`; these preserve aspect ratio and are not a substitute for final portrait reframing. The pinned local caption fonts and license evidence are documented in [caption-fonts.md](docs/architecture/caption-fonts.md). The current deterministic caption layout evidence covers English, French, Japanese, and Arabic/RTL; unsupported locales fail closed. Production Advanced Hero inputs reject debug overlays and diagnostic event ids. The old magenta/cyan fixture panels are not a production component.
- Tarteel Quran captions use a pinned, hashed Quran.com Uthmani snapshot stored under the ignored work root. The engine corrects Quran and reviewed ordinary-dialogue ASR spelling from hashed campaign subtitle evidence while preserving forced-word timing (`canonical_match_verified`). Canonical-matched Quran words receive the agreed green active-word display treatment; this remains display-text evidence, not a pronunciation claim. The snapshot, source hash, transcript hash, subtitle-evidence hash, and mapping are stale gates; production never fetches Quran text at render time. Tarteel renders also require a meaningful reviewed upper context summary and decoded-frame visual review before reporting.
- When Hero and Advanced Hero need to be reviewed together, `direction plan`, `advanced plan`, `advanced render`, and `advanced verify --draft-only` use an isolated review-draft namespace. The resulting files carry `hero_review_status: pending`; they remain review-only and cannot pass delivery until the current Hero receives a human approval. Editorial arc beats also require explicit claim closure before rendering.
- Advanced audio targets `-16 LUFS` integrated, `-1.5 dBTP` true peak, and `11 LU` LRA. Narration ducks source audio by `-12 dB`, must cover the declared edit window within 100 ms, and is normalized after rendering. A near-silent output is rejected. Audio policy and narration evidence are part of render and delivery identity.
- Advanced jump-cut staging trims picture and speech from the same ordered integer-microsecond `TimeMap`. Picture frames are allocated on the canonical 30 fps output grid (including off-grid cuts), and speech gets only an 8 ms discontinuity fade; the staging recipe and profile fingerprint change when this policy changes. A cut through a forced word is rejected before rendering.
- `clipforge qa run SOURCE_ID` writes a `qa_set_json` artifact for the current advanced Hero draft. `list`, `show`, and `verify` only read. `qa gate` succeeds only when technical and campaign QA both pass and still match the current artifact.
- `clipforge job list`, `show`, and `verify` read recorded jobs. `recover` marks a stale running job failed. `resume` and `retry` start a new attempt and keep the previous row. A changed source hash or blocked rights record is refused.
- `clipforge batch run` prepares several sources in one SQLite database, in the order given. `list`, `show`, and `verify` only read. `resume` reruns children that are not a verified success. One source failure does not erase another source. The batch does not approve or publish.
- `clipforge analytics record` and `clipforge analytics import` append local outcome observations for an artifact that is already in the database. CSV, JSON, and JSONL exports can be normalized with `--profile`. `labels set` appends a manual label. `list`, `show`, `verify`, `compare`, `labels history`, and `dashboard verify` only read. `dashboard` serves a loopback page on `127.0.0.1`. Missing metrics stay missing. Comparisons are descriptive. They do not approve, optimize, or publish.
- `clipforge benchmark run` records the current local chain, including campaign and language stages, a labeled synthetic analytics fixture, and local delivery. Missing candidate approval, Hero approval, a passing QA result, or a verified local package blocks the record. It does not invent those decisions. External publishing stays deferred. `list`, `show`, `verify`, and `readiness` only read.
- `clipforge voice languages` lists narration capability. `clipforge voice doctor` passes when VoiceStudio is disabled. `voice generate` needs an explicit script, consent, and a commercial-use license. The default model is not treated as commercially permitted. Generated audio does not approve a Hero. Nothing downloads a model unless `--allow-model-download` is passed on a command that already had that flag.
- `clipforge publish doctor` reports the local exporter, the work-root path rule, and ffprobe. `publish plan` is a read-only preflight. `publish export SOURCE_ID CANDIDATE_ID` copies the verified Advanced Hero MP4 into `deliveries/<delivery_id>/` after preflight, including an effective approved final review. Hero approval alone does not authorize delivery. QA alone does not authorize delivery. It does not re-render. `list`, `show`, and `verify` only read. `recover` fails a stale running export. `resume` starts a new attempt only when the previous package is not a verified success. `--force` keeps the previous directory. `--destination` other than `local` fails because external platform publishing is not implemented.
- `clipforge platform doctor` and `clipforge platform capabilities` describe the optional adapter. `publish dry-run` checks a target against the verified local package and does not open a socket. `publish submit` does not upload unless `CLIPFORGE_PLATFORM_LIVE_SMOKE=1` and a real adapter are both configured. No production adapter is registered. `status` does not submit again. `cancel` is not success. Output keeps `local delivery` separate from `external platform`.
- `clipforge language doctor` and `clipforge language list` report which languages have a real aligner or narrator. `language align` writes a full-source alignment only when that provider is `verified_live`. `language check` still draws caption stills and does not claim Arabic or Japanese alignment. `language show` and `language verify` only read. A fake provider cannot be reported as `verified_live`. en-US, fr-FR, and ja are `verified_live` only when an external speech file under `CLIPFORGE_SPEECH_EVIDENCE_ROOT` matches the packaged speech record and the model measured on disk. Clipforge checks the file SHA-256, sample rate, channel count, and duration. The record must also match the measured locale, model id, revision, checkpoint, manifest, WhisperX version, and device. A missing directory, a missing file, a tone, a sine wave, noise, silence, a catalog constant, or a JSON row alone stays non-live. en-GB stays `available_not_smoked` unless that locale has its own speech record. Spanish and German stay `model_missing`. Arabic stays `alignment_not_claimed`. Full-source alignment stays `not_configured`. Selected-clip `hero align` is the production path.
- `clipforge campaign` records policy, inventory, and an explicit acquisition plan. `clipforge campaign operator` selects catalogue sources into an append-only sidecar and can serve a loopback board on `127.0.0.1`. `doctor`, `list`, `show`, `sources`, `verify`, and `status` only read. `select`, `import`, `run`, and `resume` validate first. `acquire plan`, `acquire list`, `acquire show`, and `acquire verify` only read. `acquire run` and `acquire resume` copy selected, policy-allowed sources into the work root after hash, size, and ffprobe checks. `produce` runs that selection through the existing campaign runner and writes an aggregate manifest. `production-plan`, `production-show`, `production-list`, `production-verify`, and `production-report` only read. `run` and `resume` call the existing campaign runner. An allowed source does not wait for a second confirmation. `campaign operator whop import` reads a sanitized snapshot and labels it `credentials_stored: not_stored` and `live_transport: not_claimed`. `whop auth doctor` reports Grok, the Whop plugin, and the connector without opening a browser or a socket. `whop auth login` installs `whopio/plugins#dist/grok/whop` when needed. If this Grok build cannot run `/mcps`, login tells the operator to authorize Whop in Grok and exits `auth_required`. `whop tools refresh` writes a verified read-only map outside the repository only after the official connector is ready. `whop discover` reports `not_configured` and does not connect. `whop discover --live` calls the public MCP adapter, the `official-grok` connector, or a loopback test double only when `CLIPFORGE_WHOP_LIVE_SMOKE=1` and the connector is set. An in-memory registry is not that connector. Credentials stay outside Clipforge. Doctor does not open a session. The packaged Whop tool map stays empty until a real tools list verifies names. Envato search sends only filters the selected tool supports. External publishing stays deferred.
- `clipforge assets doctor` reports the Envato MCP endpoint. Search writes a typed manual download request. `assets envato auth setup` can store an optional portal login in the OS keyring through an interactive TTY; it never stores a password in the repository, work root, SQLite, logs, or artifacts. `auth status` reports presence only, and `auth forget --yes` removes the local entry without claiming remote logout. `assets envato fetch --request REQUEST_ID --project PROJECT_ID` uses the saved login to resolve the MCP item page, create a license, download the portal archive and certificate, extract one supported media file, and pass it through the normal hash, probe, rights, policy, and provenance gates. Audio/SFX and fonts are typed separately (`search_sound_effects` and `search_fonts`), with `fc-scan` validation for `.ttf`, `.otf`, `.woff`, and `.woff2`. `--portal-item-uuid UUID` is an optional identity assertion, not a substitute for page resolution. `assets envato register` remains available for a manually placed file. Antoine stock rows are blocked, and signed download URLs are never stored or printed.

- `clipforge final review doctor` reports that final approval is human, Whop MCP is deferred, and external publishing is deferred. `open`, `list`, `show`, and `verify` only read. `decide` appends one final `ReviewDecision` for the current Advanced Hero evidence. The loopback page is `127.0.0.1` only.

## What does not work yet

- Full-source WhisperX transcription
- Active-speaker detection and face recognition. `face_follow` uses detection geometry only and does not claim either of those.
- Music. Local B-roll and SFX are supported. Music is prohibited.
- External platform publishing. The adapter interface and dry-run path exist. Upload is `not_configured` until an operator sets `CLIPFORGE_PLATFORM_LIVE_SMOKE=1` and a real adapter. There is no TikTok, Instagram, or YouTube client. Credentials are not stored in SQLite or artifacts.
- A review UI on any address other than loopback
- Envato remains fail-closed for unsupported or unlicensed portal flows. The reviewed `assets envato fetch` path handles explicitly selected audio/SFX, fonts, video, image, and graphic items; manual registration remains available, and Antoine campaign stock stays blocked.
- An unattended Whop login, and a claimed live Whop pass. The operator still installs the Whop plugin, opens Grok, runs `/mcps`, authorizes Whop, and runs `/whop-connect`. Clipforge does not store the password, cookies, tokens, or browser profile, and it does not join campaigns or publish. `discover` without `--live` stays `not_configured`. A skipped live smoke stays `live_smoke: not_executed`. `live_claim` stays `not_claimed` until `https://mcp.whop.com/mcp` accepts a verified read-only call.
- Platform API clients, viewer tracking, and automatic optimization
- A required VoiceStudio install. The live narration engine is optional, local-only by default, and may be unavailable. Clipforge does not download its models automatically.
- Real-source verification without an authorized source. A synthetic benchmark is not that verification.
- Treating analytics evidence as approval, optimization, or a publish decision.

`clipforge --help` only lists commands that run. `publish` exports a local package. It does not upload.

## Hero alignment runtime

WhisperX is an optional local runtime. `uv sync` and CI do not install it, and it is not part of the locked default environment. That keeps the pinned `ctranslate2` used by faster-whisper unchanged.

```text
uv venv ~/.local/clipforge-hero-align --python 3.11
UV_TORCH_BACKEND=cpu uv pip install --python ~/.local/clipforge-hero-align -e . 'whisperx==3.4.5'
NLTK_DATA=~/.cache/nltk ~/.local/clipforge-hero-align/bin/python -c "import nltk; nltk.download('punkt_tab'); nltk.download('punkt')"
~/.local/clipforge-hero-align/bin/python -c "import whisperx; whisperx.load_align_model(language_code='en', device='cpu')"
```

The last command is the explicit model download. After that, normal commands set `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_DATASETS_OFFLINE=1`, and `NLTK_DATA`. `--allow-model-download` remains the only switch that may fetch weights.

The local CPU validation used WhisperX 3.4.5, torch 2.14.1+cpu, torchaudio 2.11.0+cpu, and NLTK 3.10.3. English alignment loads torchaudio `WAV2VEC2_ASR_BASE_960H` from `wav2vec2_fairseq_base_ls960_asr_ls960.pth`. WhisperX 3.4.5 does not implement `model_cache_only`; Clipforge blocks `torch.hub` downloads instead of pretending that flag exists. A jump cut aligns each TimeMap segment on its own source interval. en-US, fr-FR, and ja are `verified_live` only when their external speech files and measured models both match. en-GB is not verified from the English checkpoint alone. `hero align --language` must match the transcript language. `--allow-model-download` is the only download switch, and it does not by itself mark a language live.

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

Optional environment variables are listed in `.env.example`. The program does not read that file. Export `DATABASE_PATH`, `CLIPFORGE_WORK_ROOT`, or `WORK_ROOT` when you want a non-default location. `CLIPFORGE_SPEECH_EVIDENCE_ROOT` overrides the installed `~/.local/clipforge-speech-evidence` directory of provider smoke WAVs used for `verified_live`; it is separate from selected-clip source audio. Those files stay outside the repository. Directory discovery never replaces hash/model validation. `CLIPFORGE_WORK_ROOT` wins over `WORK_ROOT`. Defaults are `var/clipforge.sqlite3` and `var/work`. `CLIPFORGE_DISK_RESERVE_GB` defaults to 10. Both directories are gitignored.

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

Register campaign-provided CTA, watermark, graphic, or audio material before
an Advanced Hero plan references it. Use paths relative to the work root and
repeat `--source-asset-id` for every source catalog that may use the asset:

```bash
uv run clipforge assets register-local \
  --project PROJECT_ID \
  --source-asset-id SOURCE_ID \
  --file campaigns/Campaign/cta/cta.mp4 \
  --license-file campaigns/Campaign/intake/campaign-provided-rights-assertion.md \
  --kind graphic --confirm-rights --tag cta --tag campaign-provided
uv run clipforge assets verify-local SOURCE_ID
```

This records a campaign-provided rights row and a hash-bound Advanced Hero
catalog entry. It never downloads media or substitutes for human review.

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

For Advanced Hero, let the current visual analysis choose portrait framing and
resume a failed browser render from its verified run receipts:

```bash
uv run clipforge hero advanced plan SOURCE_ID CANDIDATE_ID \
  --reframing auto --db PATH --work-dir PATH
uv run clipforge hero advanced render SOURCE_ID --db PATH --work-dir PATH
# If the command reports a resumable advanced_set_id after a crash:
uv run clipforge hero advanced render SOURCE_ID --resume RUN_ID \
  --db PATH --work-dir PATH
```

`auto` uses a complete frame-level face trajectory only when it is valid for
the current TimeMap and does not crop reviewed source-native text; otherwise
it records an explicit contain strategy. Advanced browser rendering saves a
validated 120-frame video receipt and one full-length PCM audio receipt after
each unit, then assembles and normalizes the final MP4. `clipforge qa run`
also evaluates the viewer-quality contract (caption coverage, duplicate
forced words, repeated source ranges, graphic evidence, and crop collisions),
but decoded-frame inspection and human final review remain required.

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
