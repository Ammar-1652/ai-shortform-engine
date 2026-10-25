# Architecture

Clipforge turns authorized long-form video into short vertical edits. Round 7 records a human decision on the current rough preview. Round 8 renders a separate 1080×1920 Hero draft for the candidates that decision approved. A face is still not a speaker. Local delivery export copies an approved Advanced Hero into a directory. External platform publishing is not implemented.

## Planes

### Responsibility contract

Clipforge runs as an operator-led system. Codex is the `codex_operator` brain:
it reads policy and evidence, makes source-grounded editorial choices, and
invokes the typed CLI and services. The control/media/asset/review machinery
is the `system_enforcer` muscle: it executes declarative plans and enforces
rights, TimeMap synchronization, provenance, safe geometry, cache identity,
stale evidence, QA, and delivery. A `human_reviewer` watches the exact final
MP4 with audio and muted playback and is the only role that can approve final
delivery. The routing table and skill entry point are in [SKILLS.md](SKILLS.md);
the contract is fixed by [ADR 0101](docs/adr/0101-codex-operator-system-enforcer-human-final-role-boundary.md).

Skills, MCP adapters, repositories, and future tools are input producers at
their approved plane boundary. They return typed declarative records with
source evidence, rights, version, and hashes. They do not execute renderer
code, write reviews directly, replace the TimeMap, or bypass a gate.

### Control plane

Owns how work is requested, recorded, and stopped.

- CLI: `clipforge` (Typer): doctor, projects, profiles, schema export, database init, source inspect/ingest/list/show, media prepare/verify, storage status, transcript doctor/run/show/verify, vision doctor/model/analyze/show/verify, candidate doctor/mine/list/show/verify, preview doctor/render/list/show/verify, review doctor/open/list/decide/verify, hero doctor/align/plan/render/list/show/verify, hero review, hero advanced, qa doctor/run/list/show/verify/gate, job doctor/list/show/verify/recover/resume/retry, batch doctor/run/list/show/verify/resume, and analytics doctor/record/import/list/show/verify/compare plus import profiles, label history, a loopback dashboard, benchmark readiness, and optional narration.
- Operator catalogue: `clipforge operator roles`, `tools`, `show`, `extensions`, and `verify` expose the approved responsibility and capability boundaries to Codex. The catalogue is read-only metadata; it does not dispatch commands or grant authority.
- Jobs: `JobRecord` and `RenderJob`. Status is an enum. A failed job must carry `error_message`. Media preparation commits `running`, closes the connection, then runs ffmpeg. It does not hold a write transaction across the encode. `clipforge job recover` fails a stale `running` row from `updated_at` and does not mark it succeeded. Resume and retry add a new attempt. See [docs/architecture/jobs-cache-restart-batch.md](docs/architecture/jobs-cache-restart-batch.md).
- Campaign execution checkpoints: `campaign run` writes a hash-bound, append-only stage journal and atomically updated progress checkpoint under the ignored work root. It records which source and stage receipts were verified and allows `campaign resume` to reuse only records that pass the normal evidence verifier. The checkpoint is recovery evidence; the campaign manifest, artifact rows, QA, final review, and delivery gates remain authoritative. See [ADR 0104](docs/adr/0104-durable-production-execution-checkpoints.md).
- Production release identity: `operator release capture` snapshots the current Git head and allowlisted runtime-file hashes. Campaign checkpoints bind the release fingerprint, so a dirty dependency change makes reuse stale. Capture is offline and stores no credentials or absolute paths. See [ADR 0105](docs/adr/0105-local-production-release-identity.md).
- State: SQLite file, migrations, repositories in `clipforge.storage`. Schema version 4 adds `source_manifests` on top of the version 3 project-bound lineage. Schema version 5 adds append-only `performance_outcomes`, `editorial_feature_snapshots`, and `analytics_imports`. Schema version 6 adds append-only `editorial_label_sets` and import profile columns. Schema version 7 persists `reviewer_role` so Codex editorial decisions and human final decisions cannot be confused. See [docs/architecture/analytics-operations.md](docs/architecture/analytics-operations.md). No global connection. A file that claims the current version but is missing a table, a required column, a critical foreign key, or a migration row is rejected and not rebuilt. See [docs/architecture/performance-analytics.md](docs/architecture/performance-analytics.md).
- Profiles: `CampaignProfile` with mode `organic` or `paid_campaign`. Files live in `configs/profiles/`. `profile-organic` and `profile-paid-campaign` use the same core. The files are not executed. See [docs/architecture/profiles-policy-qa.md](docs/architecture/profiles-policy-qa.md).
- Policies: `ComplianceRule` with severity fixed to `block`. `configs/policies/source-rights.json` and `configs/policies/asset-rights.json` are deterministic evaluators, not plugins.
- Review decisions: `ReviewDecision`. Codex records source-grounded candidate, Hero, caption, and framing decisions with `reviewer_role = codex_operator`; a human may also record those decisions. Final approval and playback require `reviewer_role = human_reviewer`. Candidate and Hero reviews name a `candidate_id`. Caption, framing, and final reviews name an `artifact_id`, including a rejected final review. `reviews.artifact_id` references `artifacts` when it is set. There is no candidate table yet, so `candidate_id` is not a foreign key.
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
- AV synchronization: every staged picture/speech pair uses the same ordered TimeMap, starts at output zero, and is rejected when either stream is missing, the streams differ from each other, or either stream drifts beyond the project duration tolerance. Approximate ASR timing is not final caption evidence. Hero browser renders consume the exact paired candidate-span stage; Advanced jump cuts reject boundaries inside a forced word and apply a deterministic speech envelope at discontinuities. Directed multi-moment plans default to a bounded Remotion dissolve at non-contiguous cuts unless an editorial arc explicitly selects `none`; the transition does not move the clock. See [ADR 0068](docs/adr/0068-synchronized-review-and-relevant-asset-gate.md), [ADR 0071](docs/adr/0071-cut-boundary-audio-envelope-and-asset-content-binding.md), and [ADR 0087](docs/adr/0087-smooth-directed-cut-default.md).
- Rough preview: `RoughPreviewSetDocument` for the current candidate set. The picture is the analysis proxy and the speech is the ASR FLAC. Captions are provisional. Browser staging preserves the current single-span candidate contract; Advanced Hero staging additionally consumes every range in an explicitly ordered `TimeMap` through `stage_time_map`, preserving jump cuts instead of repeating the first range. See [docs/architecture/rough-preview-rendering.md](docs/architecture/rough-preview-rendering.md) and [ADR 0067](docs/adr/0067-ordered-time-map-render-staging.md).
- Rendering and output validation: Remotion composites the rough review at 720×1280 and Hero/Advanced Hero drafts at 1080×1920. Advanced Hero burns grouped captions, typography, diagrams, native source-bound illustrations, B-roll, and approved SFX from typed render input; FFmpeg probes, normalizes, and re-measures the resulting audio against the profile loudness/true-peak policy. Reviewed manual reframing may be a fixed crop or a typed, ordered, hash-bound crop trajectory interpolated by output frame; it cannot silently fall back to contain. Hero drafts are `hero_draft_set_json` and do not replace `rough_preview_set_json`.
- Resumable Advanced rendering: browser renders use global 120-frame video chunks plus one complete PCM16 audio render. Each unit is atomically checkpointed with input/dependency hashes, byte size, and SHA-256 before assembly. `progress.json` is written after every candidate; `--resume RUN_ID` validates the exact source, plan, style, font, batch, and renderer bindings and reuses only verified units. No partial manifest or stale unit is promoted. See [ADR 0083](docs/adr/0083-resumable-render-units-auto-reframing-and-viewer-qa.md).
- Resumable Hero rendering: the legacy Hero composition now uses the same
  global 120-frame video units and one direct PCM conversion of its exact
  staged audio. Each unit is checked and atomically receipt-bound before the
  final mux; a browser crash leaves completed chunks under the candidate
  checkpoint for recovery. Audio is not rendered through a second browser
  session. See [ADR 0106](docs/adr/0106-resumable-hero-rendering.md).
- Worker logs distinguish import, bundle, browser selection and rendering with
  bounded stage heartbeats and measured memory counters. Missing counters stay
  unknown. Diagnostics never enter compositions or change their frame clock.
  Local validation runs browser tests in a fresh process after the mandatory
  non-browser partition, matching the consolidated CI boundary. Outer deadlines,
  browser serialization, private TMPDIR and process-group cleanup remain active.
- Advanced browser authorization and caption evidence: the service issues one candidate receipt binding its canonical batch, local worker dependency map, output location and staged media hashes before Remotion runs. Final encoding is followed by decoded cue/word edge capture bound to the MP4 and staged audio, plus a viewer-evidence bundle containing representative frames, 4:5/1:1 platform crops, contact sheets, and ebur128 facts. QA and cache lookup recheck every report/file hash and the exact artifact binding; this evidence does not prove all audible speech was transcribed or that a human accepted the edit, so clean campaign QA remains insufficient until the reviewed speech inventory and audio/muted watch exist. See [ADR 0096](docs/adr/0096-advanced-render-authorization-and-caption-evidence.md).
- Motion direction: a promoted candidate may carry an immutable `DirectionDocument` with exactly three source-grounded hook/body/punch alternatives. The selected option uses one of the pinned declarative presets and the project-defined portrait safe region (not a universal platform guarantee). The opt-in `concat-editorial-v1` preset uses locally staged, independently licensed fonts and native Remotion motion adaptations; it does not copy or execute Concat's AGPL Rust/WGSL compositor. An optional native motion graphic chooses an audited template, copied evidence text, canonical interval, purpose, and geometry above the caption lane; template eligibility must match the claim's visual meaning, so a generic “company” mention cannot select a rising business chart. A reviewed `SourceNativeText` annotation can identify text already burned into a scene so duplicate optional typography is suppressed while the speech caption remains. It has no remote asset or operator code payload. Directed accent tracks are plan-positioned on a caption-adjacent rail, away from the portrait face area. Reviewed B-roll/SFX placements carry exact output intervals, asset in-points, source evidence, purpose, and relevance; evenly spaced or unrelated assets are rejected by clean production. Its source, Hero-plan, TimeMap, style, font, placement, native-graphic recipe, and audio-policy hashes flow into the Advanced Hero plan, render input, cache, QA, review, and delivery checks. The direction skill can propose options, but only the typed CLI validator can bind them; it cannot supply executable renderer code. Picture and speech are staged from the same ordered TimeMap before Remotion, with duration and zero-start checks. See [ADR 0069](docs/adr/0069-source-grounded-motion-direction-presets.md), [ADR 0070](docs/adr/0070-source-grounded-asset-timing-and-production-audio-gates.md), [ADR 0073](docs/adr/0073-source-bound-native-motion-graphics.md), [ADR 0079](docs/adr/0079-claim-specific-native-graphics.md), [ADR 0080](docs/adr/0080-source-native-text-collision-annotations.md), and [ADR 0086](docs/adr/0086-concat-fonts-and-remotion-motion-adaptation.md).
- New directed production uses `direction-v3`: one reviewed, source-grounded upper context sentence is mandatory, every spoken caption is grouped into one readable line before Remotion, and every hook/body/punch beat records B-roll, SFX, camera, transition, and graphics treatment states. The pinned modern style profiles reserve an inner platform-safe band (96/160px horizontal and 270/360px top/bottom margins) for captions, context, logos, and graphics; animated bounds are checked against platform search/header, side-rail, and description/action regions. Historical `direction-v1`/`direction-v2` and legacy Hero artifacts remain readable and immutable, but they are not silently upgraded. See [ADR 0107](docs/adr/0107-platform-safe-caption-and-context-policy.md) and [ADR 0111](docs/adr/0111-editorial-treatment-orchestration.md).
- New direction options may also carry bounded `camera_motion` and narrative `transitions`. These are source-evidence-bound output events, validated at interior TimeMap cuts and rendered from the canonical frame clock. Camera transforms use a hold fallback and stay inside the platform-safe/caption/face envelope. Historical direction documents without these arrays retain their recorded behavior. See [ADR 0108](docs/adr/0108-direction-owned-camera-and-transition-events.md).
- Editorial recipes and reference analyses are independently hash-bound. The
  motion catalog verifies each recipe and every local renderer reference before
  planning; the Remotion registry rejects unknown recipe ids and requires the
  catalog fingerprint. Reference analyses recheck the authorized source and
  evidence bytes, and proposed style cards retain the analysis digest. Camera
  and transition events are remapped onto an editorial arc and their receipts
  are checked in viewer evidence and QA. See [ADR 0109](docs/adr/0109-editorial-recipe-and-reference-integrity.md).
- Clean Advanced plans also publish a pilot preflight receipt before browser
  encoding. It binds the plan, direction, camera, transition, graphic,
  caption, and audio dependency identities; a missing or stale receipt blocks
  rendering. Narrative presets route only to approved motion recipes.
- Treatment orchestration is the decision boundary between Codex direction and
  Advanced Hero events. `editorial treatment plan/show/lint` exposes per-beat
  use, omission, policy-block, and review states plus bounded B-roll/SFX
  provider requests. The renderer never performs provider discovery or adds a
  decorative effect that the selected treatment omitted. See [ADR 0111](docs/adr/0111-editorial-treatment-orchestration.md).

### AI decision plane

Owns judgment that is not a deterministic media tool. Agents orchestrate. They do not replace ffmpeg, the time map, or the compliance gate.

The editorial knowledge layer stores pinned source guidance, authorized
reference observations, narrative patterns, style cards, evaluation cases,
conflicts, releases, direction contexts, and append-only feedback. Its local
context command supplies Codex with selected guidance, rejected alternatives,
source facts, unknowns, and the motion-catalog fingerprint. The direction
validator can bind that context to a direction document. Guidance is advisory:
it cannot execute code, change a TimeMap, override policy, or create approval.
See [ADR 0102](docs/adr/0102-editorial-knowledge-and-direction-engine.md).

- Campaign interpretation: `CampaignProfile` selects policy ids. The policy engine evaluates those ids with a fixed Python registry.
- Candidate discovery: `clipforge candidate mine` writes one `CandidateMiningDocument` per source. Each selected `CandidateClip` has one source range, transcript evidence, and visual evidence. See [docs/architecture/candidate-mining.md](docs/architecture/candidate-mining.md).
- Scoring: `creative_score` is the quality heuristic in `[0, 1]`. `edit_opportunity_score` is stored beside it and is not added in. Neither score is compliance or a virality probability.
- Edit planning: `EditPlan` for stage `rough` or `hero`, bound to a time-map digest. The map must have a positive output duration. `Scene` and `FaceObservation` provenance must include their own `source_asset_id`. A face is still not a speaker.
- QA assistance: `QASetDocument` binds a technical `QAResult` and a campaign `QAResult` to the current advanced Hero artifact. Technical QA includes a named viewer-quality contract for caption coverage, forced-word uniqueness, source-range repetition, graphic evidence, native-text/crop collisions, and the hash-bound viewer-evidence bundle; missing or stale objective evidence is `INSUFFICIENT_EVIDENCE`, not a pass. A `HumanPlaybackReview` must separately document audio and muted playback by a `human_reviewer`. The aggregate status cannot be stronger than the worst check. `clipforge qa gate` is the deterministic prerequisite for any later publishing work.

### Asset plane

Owns files that are not the long-form source, and the rights on every file including the source.

Openverse is an optional bounded metadata provider. Search never downloads
media, scraping is prohibited, and provider license metadata is discovery
evidence only. Selection remains pending or blocked until independent license
evidence matches the response hash. Any later acquisition must use the normal
asset license, confinement, probe, decode, and campaign-policy gates. See
[ADR 0103](docs/adr/0103-motion-catalog-and-openverse-boundary.md).

- Source media: `SourceAsset.license_record_id` references `asset_license_records`, and that record's `asset_id` must be the source id. A version-1 file is migrated by inserting `unknown` placeholders. Those placeholders stay blocked.
- Campaign assets, local assets, Envato assets, graphics, audio, fonts: `AssetKind` on `AssetReference`.
- Envato handoff: a verified registration is hash-bound, probe-checked, rights-bound, and confined. Advanced Hero planning rejects a stale or unverified Envato asset before a render job is inserted; clean B-roll additionally requires operator-confirmed content tags copied into a source-grounded placement. Campaigns that do not request Envato assets are unchanged. See [docs/architecture/provider-boundaries.md](docs/architecture/provider-boundaries.md) and [ADR 0071](docs/adr/0071-cut-boundary-audio-envelope-and-asset-content-binding.md).
- Campaign-provided local material: `clipforge assets register-local` registers a CTA, watermark, graphic, or audio file in the existing source-bound Advanced Hero catalog. It hashes and decodes bytes, records `campaign_provided` rights with evidence, binds semantic tags into the asset identity, and rechecks the evidence before planning/rendering. It never searches, downloads, or grants editorial approval. See [docs/architecture/provider-boundaries.md](docs/architecture/provider-boundaries.md).
- Campaign overlays are rendered as typed, source-bound layers. Tarteel's official CTA is staged as an audio-free VP9/WebM alpha video and placed inside the original contained foreground picture using `foreground_attention_v1`; it is never reduced to a still or composited onto the blurred background. See [ADR 0088](docs/adr/0088-tarteel-animated-cta-safe-rail.md) and [ADR 0089](docs/adr/0089-tarteel-foreground-composition-and-editorial-window.md).
- Clean Tarteel overlays also require a hash-bound `OverlayExclusionEvidence`
  sidecar. It records transformed exclusion regions for faces, children/body,
  tablet, captions, context, source logo, watermark, and platform rails across
  CTA entrance, hold, exit, and maximum extent. Missing or unknown clearance
  evidence blocks the clean worker, cache, and technical QA. See [ADR 0097](docs/adr/0097-tarteel-transformed-overlay-clearance.md).
- Clean Tarteel plans also require an accepted source-bound
  `EditorialArcReview` sidecar. Its persisted arc, transcript, visual-analysis,
  representative-frame, and continuity hashes flow into the plan, render
  input, cache, and QA; an unrelated or unresolved hook/body/punch arc cannot
  reach a clean render. See [ADR 0098](docs/adr/0098-tarteel-editorial-arc-review.md).
- Tarteel hard rules include a maximum CTA size, face/caption clearance evidence, canonical Quran caption verification, measured word timing, exact post-caption copy, and child-dignity checks. Quran display correction uses a hashed offline Quran.com snapshot and never turns text matching into pronunciation proof. See [docs/architecture/tarteel-campaign-hard-rules.md](docs/architecture/tarteel-campaign-hard-rules.md) and [ADR 0090](docs/adr/0090-canonical-quran-display-evidence.md).
- Tarteel's `quran-readable-v2` preset is the versioned public-readable caption treatment: centered large lower captions, a larger centered upper context line, and forced-word-id active coloring. It keeps the compact preset and old artifacts immutable. See [ADR 0092](docs/adr/0092-tarteel-readable-caption-preset.md).
- Relevant-asset gate: an enhanced edit gets a source-grounded Remotion graphics brief and an official Envato MCP request file before asset acquisition. The operator must confirm the downloaded files and license certificates before work continues; unrelated stock is never substituted. See [ADR 0068](docs/adr/0068-synchronized-review-and-relevant-asset-gate.md).
- Rights: `AssetLicenseRecord`. `require_rights_cleared` blocks `unknown`, `prohibited`, and missing evidence.
- Motion library: `motion-library-v1` writes `MotionEvent` values for a caption reveal, caption emphasis, and short opening and closing fades. Events do not change the TimeMap. See [ADR 0039](docs/adr/0039-deterministic-motion-library.md).

### Review plane

Owns append-only decisions and human final playback. Codex may record
source-grounded candidate, Hero, caption, framing, direction, speech, and arc
decisions with `reviewer_role = codex_operator`; a human may record them too.
Final playback approval is always `reviewer_role = human_reviewer`. Round 7
serves the review surfaces on `127.0.0.1` for the current rough-preview set.
See [docs/architecture/candidate-review-surface.md](docs/architecture/candidate-review-surface.md).
Hero drafts have their own loopback page. See
[docs/architecture/hero-review-and-approval.md](docs/architecture/hero-review-and-approval.md)
and [ADR 0040](docs/adr/0040-hero-review-binding.md).

- Candidate review: `subject_kind = candidate`, bound to the current rough-preview artifact. Decisions are append-only. Approval does not publish.
- Hero review: `subject_kind = hero`, bound to the current Hero artifact, plan, and alignment. Approval does not render or publish.
- Caption and framing correction: `subject_kind` values `caption` and `framing`.
- Final playback approval: `subject_kind = final` and `decision = approved` require an `artifact_id`.
- Clean Advanced final approval additionally binds a typed `HumanPlaybackReview`
  to the exact MP4, source, plan and manifest. Audio and muted observations live
  in the existing append-only final-review sidecar, not in immutable render
  evidence. Technical QA can finish before playback; delivery still requires
  the effective human final decision. See [ADR 0100](docs/adr/0100-final-playback-without-render-mutation.md).
- Clean Tarteel captions derive from separately reviewed speech, ordinary
  Arabic corrections and, when retained, canonical Quran evidence. The raw
  alignment/live-evidence status stays immutable. Derived caption hashes bind
  plan, render, cache and QA. See [ADR 0099](docs/adr/0099-reviewed-speech-caption-derivation.md).

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
| Envato MCP | External stock search | Search adapter and reviewed local portal bridge |
| Grok CLI | Development agent | Not a runtime dependency |

## Deferred on purpose

The following are not stubbed as successful commands:

- Full-source WhisperX and music. `face_follow` is an opt-in crop from stored face geometry. B-roll and local SFX already exist. Face recognition and speaker attribution do not.
- Envato direct download and a claimed live Whop account session. Snapshot import, normalized discovery, the Grok onboarding helper, manual registration, and optional OS-keyring credential setup exist. The reviewed Envato portal bridge can fetch and certificate-register explicitly allowed items through a short-lived in-memory session; it never stores signed URLs or browser cookies. The default Whop status is `not_configured`. A loopback connector is not a live Whop pass. `live_claim` stays `not_claimed` until an official read-only call succeeds. External publishing remains deferred and Antoine outside-media policy remains a hard block. See [ADR 0085](docs/adr/0085-envato-portal-download-bridge.md).
- Remotion Player and publishing UI
- Publishing APIs. Local delivery export does not upload.
- Cloud workers
- Performance learning
- External analytics integrations

## Invariants later rounds must keep

Speech evidence discovery is shared by production and tests: an explicit
`CLIPFORGE_SPEECH_EVIDENCE_ROOT` takes precedence over the installed
`~/.local/clipforge-speech-evidence` directory. Invalid overrides do not fall
back. Discovery does not grant live status; every existing byte, locale, model,
and artifact binding check still applies. See [ADR 0074](docs/adr/0074-shared-speech-evidence-discovery.md).

Advanced Hero plans persist the exact TimeMap used for staging. New renders
stage that map; old plans without the field fall back to their immutable Hero
map. A map digest mismatch fails closed. See [ADR 0075](docs/adr/0075-advanced-time-map-propagation.md).

An Advanced Hero may also bind a source-grounded `EditorialArcDocument` with
ordered hook/body/punch ranges and forced-word ids. Planning remaps the forced
alignment to that map; it does not mutate the parent Hero artifact or approval.
See [ADR 0076](docs/adr/0076-source-grounded-editorial-arcs.md).

Advanced browser renders persist candidate/chunk receipts and one continuous
audio receipt under the run directory. A failed run is resumable only when its
source, plan, style/font dependencies, batch input, and renderer dependency
hashes still match. `--reframing auto` selects a reviewed face-follow
trajectory when complete frame-level evidence exists and otherwise chooses an
explicit contain view when a crop is unsafe. Viewer-quality contract failures
block QA even when media probes pass. See [ADR 0083](docs/adr/0083-resumable-render-units-auto-reframing-and-viewer-qa.md).

- One core, two edit stages, hard compliance gates, human final approval.
- One time map. Captions, graphics, B-roll, SFX, QA, and reviews consume it.
- One portrait transform. Hero and Advanced Hero use the shared deterministic
  `containRect` output-space geometry; explicit contain review backgrounds and
  reviewed crop trajectories are separate layers and cannot stretch source
  media. The renderer recipe version is part of profile/cache identity.
- Advanced Hero also has an explicit `--draft-only` review-bundle path. It
  records `hero_review_status: pending` through an isolated review-draft
  namespace, plan, render input, manifest, cache identity, and artifact kind;
  delivery rejects it. The default Advanced path still requires current human
  Hero approval; draft-only does not manufacture one. Editorial arcs also
  require an explicit complete-claim decision before rendering. See
  [ADR 0082](docs/adr/0082-isolated-advanced-review-drafts-and-claim-closure.md).
- Failures raise or record `FAILED` with a message and never promote partial
  output. Advanced browser runs may continue only through an explicit,
  hash-validated `--resume RUN_ID` that reuses verified render receipts.
- Schema version `1.0.0` is the current contract generation. Bump it when stored JSON changes shape.
