# Architecture

Clipforge turns authorized long-form video into short vertical edits. Round 5 reads the current transcript and the current visual analysis and writes a candidate set. Round 6 renders that set as rough 720×1280 review files. A face is still not a speaker. Hero editing is not started.

## Planes

### Control plane

Owns how work is requested, recorded, and stopped.

- CLI: `clipforge` (Typer): doctor, projects, schema export, database init, source inspect/ingest/list/show, media prepare/verify, storage status, transcript doctor/run/show/verify, vision doctor/model/analyze/show/verify, candidate doctor/mine/list/show/verify, preview doctor/render/list/show/verify, review doctor/open/list/decide/verify.
- Jobs: `JobRecord` and `RenderJob`. Status is an enum. A failed job must carry `error_message`. Media preparation commits `running`, closes the connection, then runs ffmpeg. It does not hold a write transaction across the encode.
- State: SQLite file, migrations, repositories in `clipforge.storage`. Schema version 4 adds `source_manifests` on top of the version 3 project-bound lineage. No global connection. A file that claims the current version but is missing a table, a required column, a critical foreign key, or a migration row is rejected and not rebuilt.
- Profiles: `CampaignProfile` with mode `organic` or `paid_campaign`. Example file: `configs/profiles/organic.json`. The file is not executed.
- Policies: `ComplianceRule` with severity fixed to `block`. Example: `configs/policies/source-rights.json`.
- Review decisions: `ReviewDecision`. Candidate and Hero reviews name a `candidate_id`. Caption, framing, and final reviews name an `artifact_id`, including a rejected final review. `reviews.artifact_id` references `artifacts` when it is set. There is no candidate table yet, so `candidate_id` is not a foreign key.

### Media plane

Owns bytes, clocks, and pictures.

- ffprobe / ffmpeg: local ingest, the analysis proxy, ASR audio, and output validation. Commands are argv lists. `shell=True` is not used. See [docs/architecture/media-ingest.md](docs/architecture/media-ingest.md).
- Source ingest: a referenced local file plus an `AssetLicenseRecord` and a `source_manifests` row. The normalized probe is the clock authority. `MediaProbe` stays the older summary contract.
- Proxies and ASR audio: `analysis-proxy` v1 and `asr-audio` v1, cached by recipe, source hash, and artifact hash. Paths belong under the work root.
- Transcription: `Transcript` with `alignment` of `approximate` for the faster-whisper pass. The input is `audio/asr.flac`. Word times are provisional. WhisperX is reserved for `forced` alignment of selected Hero clips and is not installed. See [docs/architecture/transcription.md](docs/architecture/transcription.md).
- Visual analysis: `VisualAnalysisDocument` over the analysis proxy. `Scene.analysis_complete` stays false until transcript evidence exists. `FaceObservation.speaker_attribution` stays `unknown`. See [docs/architecture/visual-analysis.md](docs/architecture/visual-analysis.md).
- Time mapping: implemented. See [docs/architecture/time-mapping.md](docs/architecture/time-mapping.md).
- Rough preview: `RoughPreviewSetDocument` for the current candidate set. The picture is the analysis proxy and the speech is the ASR FLAC. Captions are provisional. See [docs/architecture/rough-preview-rendering.md](docs/architecture/rough-preview-rendering.md).
- Rendering and output validation: Remotion composites the rough review at 720×1280. `RenderJob` and `RenderArtifact` remain the later Hero records. FFmpeg probes the preview. It does not draw the captions.

### AI decision plane

Owns judgment that is not a deterministic media tool. Agents orchestrate. They do not replace ffmpeg, the time map, or the compliance gate.

- Campaign interpretation: `CampaignProfile` and policy ids. No interpreter yet.
- Candidate discovery: `clipforge candidate mine` writes one `CandidateMiningDocument` per source. Each selected `CandidateClip` has one source range, transcript evidence, and visual evidence. See [docs/architecture/candidate-mining.md](docs/architecture/candidate-mining.md).
- Scoring: `creative_score` is the quality heuristic in `[0, 1]`. `edit_opportunity_score` is stored beside it and is not added in. Neither score is compliance or a virality probability.
- Edit planning: `EditPlan` for stage `rough` or `hero`, bound to a time-map digest. The map must have a positive output duration. `Scene` and `FaceObservation` provenance must include their own `source_asset_id`. A face is still not a speaker.
- QA assistance: `QAResult` aggregates checks. The status cannot be stronger than the worst check.

### Asset plane

Owns files that are not the long-form source, and the rights on every file including the source.

- Source media: `SourceAsset.license_record_id` references `asset_license_records`, and that record's `asset_id` must be the source id. A version-1 file is migrated by inserting `unknown` placeholders. Those placeholders stay blocked.
- Campaign assets, local assets, Envato assets, graphics, audio, fonts: `AssetKind` on `AssetReference`.
- Rights: `AssetLicenseRecord`. `require_rights_cleared` blocks `unknown`, `prohibited`, and missing evidence.
- Motion library: `MotionEvent.component_id` names a future Hero component. Round 6 has one review composition and no motion package.

### Review plane

Owns human decisions. Round 7 serves them on `127.0.0.1` for the current rough-preview set. See [docs/architecture/candidate-review-surface.md](docs/architecture/candidate-review-surface.md).

- Candidate review: `subject_kind = candidate`, bound to the current rough-preview artifact. Decisions are append-only. Approval does not publish.
- Hero promotion: a later review over a candidate. Promotion count is not fixed in the schema.
- Caption and framing correction: `subject_kind` values `caption` and `framing`.
- Final playback approval: `subject_kind = final` and `decision = approved` require an `artifact_id`.

### Data and analytics plane

Owns history that later rounds can learn from. Round 1 stores the rows and does not read platform metrics.

- Job provenance: `ArtifactProvenance` on derived documents, plus the jobs table.
- Edit plans: stored as contract JSON when a later round writes them. The SQLite `artifacts` table can point at the file.
- Render metadata: `RenderArtifact`.
- Performance data and learning: deferred. No network analytics client.

## V1 technology and what it is responsible for

| Technology | Responsibility | Round 1 |
| --- | --- | --- |
| Python 3.11 | Control plane and contracts | Used |
| Typer | CLI | Used |
| Pydantic v2 | Typed contracts and JSON Schema | Used |
| SQLite | Projects, sources, jobs, artifacts, reviews | Used |
| FFmpeg and ffprobe | Ingest, proxy, ASR audio, validation | Used for local files |
| faster-whisper | Full-source approximate transcript of the ASR FLAC | Used |
| WhisperX | Forced alignment of selected Hero clips | Deferred |
| PySceneDetect | Scene boundaries on the analysis proxy | Used |
| MediaPipe and OpenCV | Face boxes and frame measurements. No identity and no speaker label | Used |
| Remotion, React, TypeScript | Rough 720×1280 review composition | Used for review previews |
| pnpm | JavaScript installs | Used by the scaffold |
| pytest, Ruff, mypy | Python checks | Used |
| Vitest, ESLint, `tsc` | TypeScript checks | Used by the scaffold |
| GitHub Actions | CI without GPU or model downloads | Configured |
| Envato MCP | External stock search | Deferred |
| Grok CLI | Development agent | Not a runtime dependency |

## Deferred on purpose

The following are not stubbed as successful commands:

- WhisperX integration
- Hero edit plans and motion graphics
- Candidate review UI
- Envato MCP
- Review web UI and Remotion Player
- Publishing APIs
- Cloud workers
- Performance learning
- External analytics integrations

## Invariants later rounds must keep

- One core, two edit stages, hard compliance gates, human final approval.
- One time map. Captions, graphics, B-roll, SFX, QA, and reviews consume it.
- Failures raise or record `FAILED` with a message. They do not continue.
- Schema version `1.0.0` is the current contract generation. Bump it when stored JSON changes shape.
