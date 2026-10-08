# Architecture

Clipforge turns authorized long-form video into short vertical edits. Round 7 records a human decision on the current rough preview. Round 8 renders a separate 1080×1920 Hero draft for the candidates that decision approved. A face is still not a speaker. Local delivery export copies an approved Advanced Hero into a directory. External platform publishing is not implemented.

## Planes

### Control plane

Owns how work is requested, recorded, and stopped.

- CLI: `clipforge` (Typer): doctor, projects, profiles, schema export, database init, source inspect/ingest/list/show, media prepare/verify, storage status, transcript doctor/run/show/verify, vision doctor/model/analyze/show/verify, candidate doctor/mine/list/show/verify, preview doctor/render/list/show/verify, review doctor/open/list/decide/verify, hero doctor/align/plan/render/list/show/verify, hero review, hero advanced, qa doctor/run/list/show/verify/gate, job doctor/list/show/verify/recover/resume/retry, batch doctor/run/list/show/verify/resume, and analytics doctor/record/import/list/show/verify/compare plus import profiles, label history, a loopback dashboard, benchmark readiness, and optional narration.
- Jobs: `JobRecord` and `RenderJob`. Status is an enum. A failed job must carry `error_message`. Media preparation commits `running`, closes the connection, then runs ffmpeg. It does not hold a write transaction across the encode. `clipforge job recover` fails a stale `running` row from `updated_at` and does not mark it succeeded. Resume and retry add a new attempt. See [docs/architecture/jobs-cache-restart-batch.md](docs/architecture/jobs-cache-restart-batch.md).
- State: SQLite file, migrations, repositories in `clipforge.storage`. Schema version 4 adds `source_manifests` on top of the version 3 project-bound lineage. Schema version 5 adds append-only `performance_outcomes`, `editorial_feature_snapshots`, and `analytics_imports`. Schema version 6 adds append-only `editorial_label_sets` and import profile columns. See [docs/architecture/analytics-operations.md](docs/architecture/analytics-operations.md). No global connection. A file that claims the current version but is missing a table, a required column, a critical foreign key, or a migration row is rejected and not rebuilt. See [docs/architecture/performance-analytics.md](docs/architecture/performance-analytics.md).
- Profiles: `CampaignProfile` with mode `organic` or `paid_campaign`. Files live in `configs/profiles/`. `profile-organic` and `profile-paid-campaign` use the same core. The files are not executed. See [docs/architecture/profiles-policy-qa.md](docs/architecture/profiles-policy-qa.md).
- Policies: `ComplianceRule` with severity fixed to `block`. `configs/policies/source-rights.json` and `configs/policies/asset-rights.json` are deterministic evaluators, not plugins.
- Review decisions: `ReviewDecision`. Candidate and Hero reviews name a `candidate_id`. Caption, framing, and final reviews name an `artifact_id`, including a rejected final review. `reviews.artifact_id` references `artifacts` when it is set. There is no candidate table yet, so `candidate_id` is not a foreign key.
- Language capability: `clipforge language` reports which aligners and narrators are live. Full-source alignment is optional and is not a live claim unless the verified WhisperX checkpoint actually ran. en-US, fr-FR, and ja are `verified_live` only when an external speech file matches the packaged record and the measured model. The file hash is checked. A JSON row, a tone, a sine wave, or a copied manifest is not evidence. A missing external file stays non-live. en-GB is not verified unless it has its own speech record. Spanish and German stay `model_missing`. Arabic stays `alignment_not_claimed`. Full-source alignment is `not_configured`. Selected-clip `hero align` is the production path. See [docs/architecture/multilingual-alignment.md](docs/architecture/multilingual-alignment.md), [ADR 0061](docs/adr/0061-multilingual-alignment-and-narration.md), and [ADR 0066](docs/adr/0066-multilingual-alignment-production.md).
- Campaign operator: `clipforge campaign operator` appends a `CampaignSelectionDocument` under the work root and can serve a read-only board on `127.0.0.1`. `acquire` copies a selected allowed source into the work root only after hash, size, confinement, and ffprobe checks. `produce` calls the existing campaign runner and writes `campaigns/production/<run_id>/manifest.json`. `whop` imports an operator-exported snapshot and can filter a normalized discovery through a public MCP adapter or a loopback connector. The default live status is `not_configured`. The packaged tool map stays empty until a real tools list verifies names into an uncommitted operator map. Doctor does not open an account session. `auth login` installs the Whop Grok plugin and, on this Grok build, stops at `auth_required` until the operator runs `/mcps` and `/whop-connect`. SQLite stays at schema 6. See [docs/architecture/campaign-operator-control-plane.md](docs/architecture/campaign-operator-control-plane.md), [docs/architecture/source-acquisition.md](docs/architecture/source-acquisition.md), [docs/architecture/campaign-production-aggregate.md](docs/architecture/campaign-production-aggregate.md), [docs/architecture/provider-boundaries.md](docs/architecture/provider-boundaries.md), [docs/architecture/whop-live-discovery.md](docs/architecture/whop-live-discovery.md), [ADR 0057](docs/adr/0057-campaign-operator-selection-and-control-plane.md), [ADR 0058](docs/adr/0058-source-acquisition-and-policy-intake.md), [ADR 0059](docs/adr/0059-aggregate-campaign-production.md), [ADR 0060](docs/adr/0060-whop-and-envato-provider-boundaries.md), [ADR 0062](docs/adr/0062-whop-live-operator-discovery.md), and [ADR 0063](docs/adr/0063-whop-grok-connector-onboarding.md).

### Media plane

Owns bytes, clocks, and pictures.

- ffprobe / ffmpeg: local ingest, the analysis proxy, ASR audio, and output validation. Commands are argv lists. `shell=True` is not used. See [docs/architecture/media-ingest.md](docs/architecture/media-ingest.md).
- Source ingest: a referenced local file plus an `AssetLicenseRecord` and a `source_manifests` row. The normalized probe is the clock authority. `MediaProbe` stays the older summary contract.
- Proxies and ASR audio: `analysis-proxy` v1 and `asr-audio` v1, cached by recipe, source hash, and artifact hash. Paths belong under the work root.
- Transcription: `Transcript` with `alignment` of `approximate` for the faster-whisper pass. The input is `audio/asr.flac`. Word times are provisional. WhisperX force-aligns an approved Hero clip only. See [docs/architecture/transcription.md](docs/architecture/transcription.md) and [docs/architecture/hero-alignment-and-motion.md](docs/architecture/hero-alignment-and-motion.md).
- Visual analysis: `VisualAnalysisDocument` over the analysis proxy. `Scene.analysis_complete` stays false until transcript evidence exists. `FaceObservation.speaker_attribution` stays `unknown`. See [docs/architecture/visual-analysis.md](docs/architecture/visual-analysis.md).
- Time mapping: implemented. See [docs/architecture/time-mapping.md](docs/architecture/time-mapping.md).
- AV synchronization: every staged picture/speech pair uses the same ordered TimeMap, starts at output zero, and is rejected when either stream is missing or drifts beyond the project duration tolerance. Approximate ASR timing is not final caption evidence. See [ADR 0068](docs/adr/0068-synchronized-review-and-relevant-asset-gate.md).
- Rough preview: `RoughPreviewSetDocument` for the current candidate set. The picture is the analysis proxy and the speech is the ASR FLAC. Captions are provisional. Browser staging preserves the current single-span candidate contract; Advanced Hero staging additionally consumes every range in an explicitly ordered `TimeMap` through `stage_time_map`, preserving jump cuts instead of repeating the first range. See [docs/architecture/rough-preview-rendering.md](docs/architecture/rough-preview-rendering.md) and [ADR 0067](docs/adr/0067-ordered-time-map-render-staging.md).
- Rendering and output validation: Remotion composites the rough review at 720×1280 and Hero/Advanced Hero drafts at 1080×1920. Advanced Hero burns grouped captions, typography, diagrams, B-roll, and approved SFX from typed render input; FFmpeg probes, normalizes, and re-measures the resulting audio against the profile loudness/true-peak policy. Hero drafts are `hero_draft_set_json` and do not replace `rough_preview_set_json`.
- Motion direction: a promoted candidate may carry an immutable `DirectionDocument` with exactly three source-grounded hook/body/punch alternatives. The selected option uses one of six pinned declarative presets and the project-defined `portrait-safe-v1` region (not a universal platform guarantee). Reviewed B-roll/SFX placements carry exact output intervals, asset in-points, source evidence, purpose, and relevance; evenly spaced or unrelated assets are rejected by clean production. Its source, Hero-plan, TimeMap, style, font, placement, and audio-policy hashes flow into the Advanced Hero plan, render input, cache, QA, review, and delivery checks. The direction skill can propose options, but only the typed CLI validator can bind them; it cannot supply executable renderer code. Picture and speech are staged from the same ordered TimeMap before Remotion, with duration and zero-start checks. See [ADR 0069](docs/adr/0069-source-grounded-motion-direction-presets.md) and [ADR 0070](docs/adr/0070-source-grounded-asset-timing-and-production-audio-gates.md).

### AI decision plane

Owns judgment that is not a deterministic media tool. Agents orchestrate. They do not replace ffmpeg, the time map, or the compliance gate.

- Campaign interpretation: `CampaignProfile` selects policy ids. The policy engine evaluates those ids with a fixed Python registry.
- Candidate discovery: `clipforge candidate mine` writes one `CandidateMiningDocument` per source. Each selected `CandidateClip` has one source range, transcript evidence, and visual evidence. See [docs/architecture/candidate-mining.md](docs/architecture/candidate-mining.md).
- Scoring: `creative_score` is the quality heuristic in `[0, 1]`. `edit_opportunity_score` is stored beside it and is not added in. Neither score is compliance or a virality probability.
- Edit planning: `EditPlan` for stage `rough` or `hero`, bound to a time-map digest. The map must have a positive output duration. `Scene` and `FaceObservation` provenance must include their own `source_asset_id`. A face is still not a speaker.
- QA assistance: `QASetDocument` binds a technical `QAResult` and a campaign `QAResult` to the current advanced Hero artifact. The aggregate status cannot be stronger than the worst check. `clipforge qa gate` is the deterministic prerequisite for any later publishing work.

### Asset plane

Owns files that are not the long-form source, and the rights on every file including the source.

- Source media: `SourceAsset.license_record_id` references `asset_license_records`, and that record's `asset_id` must be the source id. A version-1 file is migrated by inserting `unknown` placeholders. Those placeholders stay blocked.
- Campaign assets, local assets, Envato assets, graphics, audio, fonts: `AssetKind` on `AssetReference`.
- Envato handoff: a verified registration is hash-bound, probe-checked, rights-bound, and confined. Advanced Hero planning rejects a stale or unverified Envato asset before a render job is inserted. Campaigns that do not request Envato assets are unchanged. See [docs/architecture/provider-boundaries.md](docs/architecture/provider-boundaries.md).
- Relevant-asset gate: an enhanced edit gets a source-grounded Remotion graphics brief and an official Envato MCP request file before asset acquisition. The operator must confirm the downloaded files and license certificates before work continues; unrelated stock is never substituted. See [ADR 0068](docs/adr/0068-synchronized-review-and-relevant-asset-gate.md).
- Rights: `AssetLicenseRecord`. `require_rights_cleared` blocks `unknown`, `prohibited`, and missing evidence.
- Motion library: `motion-library-v1` writes `MotionEvent` values for a caption reveal, caption emphasis, and short opening and closing fades. Events do not change the TimeMap. See [ADR 0039](docs/adr/0039-deterministic-motion-library.md).

### Review plane

Owns human decisions. Round 7 serves them on `127.0.0.1` for the current rough-preview set. See [docs/architecture/candidate-review-surface.md](docs/architecture/candidate-review-surface.md). Hero drafts have their own loopback page. See [docs/architecture/hero-review-and-approval.md](docs/architecture/hero-review-and-approval.md) and [ADR 0040](docs/adr/0040-hero-review-binding.md).

- Candidate review: `subject_kind = candidate`, bound to the current rough-preview artifact. Decisions are append-only. Approval does not publish.
- Hero review: `subject_kind = hero`, bound to the current Hero artifact, plan, and alignment. Approval does not render or publish.
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
| WhisperX | Forced alignment of one approved Hero clip | Used when installed. CI uses a test double |
| PySceneDetect | Scene boundaries on the analysis proxy | Used |
| MediaPipe and OpenCV | Face boxes and frame measurements. No identity and no speaker label | Used |
| Remotion, React, TypeScript | Rough 720×1280 review and Hero 1080×1920 draft | Used for local drafts |
| pnpm | JavaScript installs | Used by the scaffold |
| pytest, Ruff, mypy | Python checks | Used |
| Vitest, ESLint, `tsc` | TypeScript checks | Used by the scaffold |
| GitHub Actions | CI without GPU or model downloads | Configured |
| Envato MCP | External stock search | Deferred |
| Grok CLI | Development agent | Not a runtime dependency |

## Deferred on purpose

The following are not stubbed as successful commands:

- Full-source WhisperX and music. `face_follow` is an opt-in crop from stored face geometry. B-roll and local SFX already exist. Face recognition and speaker attribution do not.
- Envato direct download and a claimed live Whop account session. Snapshot import, normalized discovery, the Grok onboarding helper, and manual registration exist. The default Whop status is `not_configured`. A loopback connector is not a live Whop pass. `live_claim` stays `not_claimed` until an official read-only call succeeds. Clipforge does not fetch provider media or store account credentials.
- Remotion Player and publishing UI
- Publishing APIs. Local delivery export does not upload.
- Cloud workers
- Performance learning
- External analytics integrations

## Invariants later rounds must keep

- One core, two edit stages, hard compliance gates, human final approval.
- One time map. Captions, graphics, B-roll, SFX, QA, and reviews consume it.
- Failures raise or record `FAILED` with a message. They do not continue.
- Schema version `1.0.0` is the current contract generation. Bump it when stored JSON changes shape.
