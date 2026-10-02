# Architecture

Clipforge turns authorized long-form video into short vertical edits. Round 3 adds a faster-whisper transcript of the canonical ASR audio. It does not align Hero captions or cut.

## Planes

### Control plane

Owns how work is requested, recorded, and stopped.

- CLI: `clipforge` (Typer): doctor, projects, schema export, database init, source inspect/ingest/list/show, media prepare/verify, storage status, transcript doctor/run/show/verify.
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
- Visual analysis: `Scene` and `FaceObservation`. A complete scene needs visual evidence and transcript evidence. A face observation cannot set a speaker. PySceneDetect, MediaPipe, and OpenCV are deferred.
- Time mapping: implemented. See [docs/architecture/time-mapping.md](docs/architecture/time-mapping.md).
- Rendering and output validation: `RenderJob`, `RenderArtifact`, `QAResult`. Remotion is the selected renderer. The app under `apps/renderer` typechecks and does not compose a reel.

### AI decision plane

Owns judgment that is not a deterministic media tool. Agents orchestrate. They do not replace ffmpeg, the time map, or the compliance gate.

- Campaign interpretation: `CampaignProfile` and policy ids. No interpreter yet.
- Candidate discovery: `CandidateClip` plus `CandidateEvidence`. The time map must have a positive output duration. Ready for review requires transcript evidence and visual evidence.
- Scoring: optional `creative_score` in `[0, 1]`. It is not combined with compliance.
- Edit planning: `EditPlan` for stage `rough` or `hero`, bound to a time-map digest. The map must have a positive output duration. `Scene` and `FaceObservation` provenance must include their own `source_asset_id`. A face is still not a speaker.
- QA assistance: `QAResult` aggregates checks. The status cannot be stronger than the worst check.

### Asset plane

Owns files that are not the long-form source, and the rights on every file including the source.

- Source media: `SourceAsset.license_record_id` references `asset_license_records`, and that record's `asset_id` must be the source id. A version-1 file is migrated by inserting `unknown` placeholders. Those placeholders stay blocked.
- Campaign assets, local assets, Envato assets, graphics, audio, fonts: `AssetKind` on `AssetReference`.
- Rights: `AssetLicenseRecord`. `require_rights_cleared` blocks `unknown`, `prohibited`, and missing evidence.
- Motion library: `MotionEvent.component_id` names a future Remotion component. No components are implemented.

### Review plane

Owns human decisions. Nothing in Round 1 plays video.

- Candidate review: `subject_kind = candidate`.
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
| PySceneDetect | Scene boundaries | Deferred |
| MediaPipe and OpenCV | Faces, pose, framing signals | Deferred |
| Remotion, React, TypeScript | Programmatic 9:16 render | Scaffold only |
| pnpm | JavaScript installs | Used by the scaffold |
| pytest, Ruff, mypy | Python checks | Used |
| Vitest, ESLint, `tsc` | TypeScript checks | Used by the scaffold |
| GitHub Actions | CI without GPU or model downloads | Configured |
| Envato MCP | External stock search | Deferred |
| Grok CLI | Development agent | Not a runtime dependency |

## Deferred on purpose

The following are not stubbed as successful commands:

- WhisperX integration
- PySceneDetect integration
- MediaPipe or OpenCV analysis
- Remotion reel compositions and actual rendering
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
