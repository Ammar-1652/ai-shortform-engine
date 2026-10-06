# Roadmap

Each round ends in a commit that a reviewer can read before the next round starts. A round is complete only when its own acceptance criteria pass. Later rows are plans, not claims that the code exists.

## Round 1 — Foundation

Status: complete. `docs/operations/round-01-validation.md` records the local validation run. GitHub Actions is configured and runs on push. It was not green in this working tree before the first push.

Repository layout, agent rules, ADRs, Pydantic contracts, JSON Schema export, canonical time map, SQLite, CLI, doctor, Python and TypeScript checks, CI. No media processing.

## Round 1.1 — Foundation hardening

Status: merged on main as `ff38583ed55e0b2ccffa05485074bfedfea8db9f`. See `docs/operations/round-01-hardening-validation.md`.

Rights records are stored. Source, artifact, and review foreign keys are enforced. Empty clips and contradictory provenance fail validation.

## Round 2 — Media ingest

Status: merged on main as `d9f227c90e933f319376a183dd407267d606602b`. See `docs/operations/round-02-validation.md`.

Local ffprobe ingest, streaming SHA-256, referenced storage, explicit rights, canonical video time, an H.264 analysis proxy, and 16 kHz mono FLAC aligned to that clock. A missing ffmpeg, a bad exit, a changed source hash, unknown rights, or a disk reserve violation fails the job before or instead of publishing a file.

## Round 3 — faster-whisper transcription

Status: merged on main as `826dfc3af2e181a1c8b73f1b683e1f08376ae459`. See `docs/operations/round-03-validation.md`.

Full-source transcript of the Round 2 ASR FLAC with `alignment = approximate`. Word timestamps are provisional. No WhisperX on the full file.

## Round 4 — Scene, visual, and face analysis

Status: merged on main as `00402a23ceac3f7814d1a4aa0019f815cf54554c`. See `docs/operations/round-04-validation.md`.

PySceneDetect shot intervals, representative frames, luma and sharpness measurements, and MediaPipe face boxes. `speaker_attribution` stays `unknown`. No recognition and no candidate ranking.

## Round 5 — Candidate mining

Status: merged on main as `f9d3e6153b976a5509dac940b7780f7856322794`. See `docs/operations/round-05-validation.md`.

The current transcript and the current visual analysis are mined into one candidate-set artifact. Quality and edit opportunity stay separate. About 15–25 candidates is a target band, not a quota, and there is no fixed top 5. Compliance remains a gate.

## Round 6 — Rough Remotion renderer

Status: merged on main as `1236c3fca71726e3bb9dedc2c0fc8509de0a668b`. Technical validation passed. Administrative acceptance criterion 75 failed because pull request 6 was merged. See the closure note in `docs/operations/round-06-validation.md`.

The current candidate set is rendered from the analysis proxy and the ASR FLAC into 720×1280 review MP4s. Captions are provisional. The TimeMap stays the clock. Round 7 starts from that merge.

## Round 7 — Candidate review

Status: merged on main as `06783647073d8ef117ff0f0b04996e5a4a6e3bc9`. See `docs/operations/round-07-validation.md`.

A loopback page plays the current rough previews and appends a human decision for each candidate. The decision is bound to that preview artifact. A stale page cannot save.

## Round 8 — Hero alignment and motion library

Status: merged on main as `7c1b22cf9266319119350b3db9e80fe18d9d155b`. See `docs/operations/round-08-validation.md`.

Approved candidates on the current rough preview are force-aligned as clips and rendered as a separate Hero draft. The motion library is `motion-library-v1`. The draft can be reviewed. It is not published. Dynamic reframing stays deferred. Local B-roll and SFX are implemented in Round 10. Music remains prohibited.

The Hero review workflow that follows this merge is recorded in `docs/operations/round-09-validation.md`. The product round below is still Envato.

## Round 9 — Envato

Official Envato MCP for search, plus an asset request that cannot land in an edit without provenance and a license record.

## Round 10 — Advanced Hero editing

Status: merged on main as `81d49fff27f6ee8a2765746fc9054ac3e27a55ba`. See `docs/operations/round-10-validation.md`.

Advanced Hero B-roll, typography, diagrams, SFX, semantic emphasis, and contain rendering are implemented. Music stays prohibited. A face is not a speaker. Remaining limits are Envato, publishing, analytics, full-source WhisperX, speaker attribution, face recognition, and optional OCR.

## Round 11 — Profiles, policy engine, QA

Status: merged on main as `338ac295691a44816c3497a946a2f7c453bcdc1b`. See `docs/operations/round-11-validation.md`.

Campaign profiles select rules. Technical QA and campaign QA are hard gates. A pass requires check evidence. The gate does not publish.

## Round 12 — Jobs, cache, restart, batch

Status: merged on main as `d28b183977c1ae4a976cebdd2d1cbaf912639c3d`. See `docs/operations/round-12-validation.md`.

Inspect and recover recorded jobs. Resume creates a new attempt and keeps the previous row. Cache hits for probes and transcripts must match the source, the sidecar, and a succeeded producer. Batch runs use one SQLite database. See `docs/architecture/jobs-cache-restart-batch.md`.

## Round 13 — Performance analytics

Status: merged on main as `31946408c5e205311b027e71d2fd292336df84b9`. See `docs/operations/round-13-validation.md`.

Record observed outcomes for known artifacts and compare editorial patterns. The records are append-only and descriptive. They do not publish, approve, or change an edit. See `docs/architecture/performance-analytics.md`.

## Round 14 — Analytics operations

Status: merged on main as `39d09e83b74239632d59c67fc456131419ed31ce`. See `docs/operations/round-14-validation.md`.

Append manual labels, normalize local CSV, JSON, and JSONL exports, and review the evidence on a loopback page. Effective labels feed comparison. The page does not publish or approve. See `docs/architecture/analytics-operations.md`.

## Round 15 — End-to-end benchmark and optional narration

Status: merged on main as `67ae3c3126aa8046da9cb0f6b8becb4603801395`. See `docs/operations/round-15-validation.md`.

Record a local readiness pass across the existing production chain and keep human decisions explicit. VoiceStudio narration is an optional local sidecar and stays off unless the operator enables it. See `docs/architecture/end-to-end-v1-benchmark.md`.

## Round 16 — Local delivery export

Status: merged on main as `dcbd18ac10826cfc684c893b8b9a14e9baed1200`. See `docs/operations/round-16-validation.md`.

Copy an approved Advanced Hero into a verified local package. External platform publishing is not implemented. Real-source verification still requires an authorized source. See `docs/architecture/local-delivery-export.md`.

## Round 17 — Real-source validation and platform boundary

Status: merged on main as `646c805fc4490042597c173f468c1e6ed3a1d32d`.

Keep local delivery, isolate Remotion browser renders, and add a fail-closed platform boundary. Fake and dry-run publishers do not upload. A real source is never inferred from a synthetic fixture. See `docs/architecture/platform-publishing.md`.

## Round 18 — Campaign ingestion, multilingual voice, and Envato discovery

Status: merged on main as `9209df919d5f6a7503a5e1ae77da9773fc038209`. See `docs/operations/round-18-validation.md`.

Ingest the two selected Antoine Sallis sources, keep native Clipforge editing allowed, and block black-box editors. Voice narration stays optional. Envato search uses the official MCP server and does not download files. External publishing stays deferred. See `docs/architecture/campaign-ingestion.md`.

## Round 19 — Real-source validation and VoiceStudio

Status: merged on main as `75f1553da04d6703fea1f7861dcd2dd999f4dafc`. See `docs/operations/round-19-validation.md`.

Run the authorized local sources through alignment, Hero, QA, and local delivery. English KittenTTS narration is verified live. Arabic and Japanese alignment stay unclaimed.

## Round 20 — Campaign production and integrity

Status: merged on main as `9f554f49b948908b5ea2ba9d48f8d1910e1fc023`. See `docs/operations/round-20-validation.md`.

One campaign runner reuses the verified stages for the selected sources. Cache, resume, review binding, and delivery checks fail closed. See `docs/adr/0056-campaign-production-run-and-language-capabilities.md`.

## Round 21 — CI consolidation

Status: merged on main as `332b879f7d491ab148261c257743ef2d556cf55f`. See `docs/operations/ci-performance.md`.

Pull-request CI is two self-hosted jobs, `verify-python` and `verify-renderer-browser`. Feature-branch pushes do not start a second workflow.

## Round 22 — Campaign operator control plane

Status: merged on main as `1dcd8926b9c4c0dc23f173bdc56bfee1bb6e10b9`. See `docs/operations/round-22-validation.md`.

Operators select catalogue sources in an append-only sidecar and inspect them on a loopback board. Execution stays in the campaign runner. See `docs/adr/0057-campaign-operator-selection-and-control-plane.md`.

## Round 23 — Source acquisition and policy intake

Status: merged on main as `b92270212a87cd59d05acec244f897b32a9d6b83`. See `docs/operations/round-23-validation.md`.

Selected allowed sources are copied into the work root only after hash, size, confinement, and ffprobe checks. Envato search sends only filters the tool schema supports. See `docs/adr/0058-source-acquisition-and-policy-intake.md`.

## Round 24 — Aggregate campaign production

Status: merged on main as `a642c202eed45a3aef26b791178f233778ff93a1`. See `docs/operations/round-24-validation.md`.

`produce` calls the existing runner and writes one aggregate manifest for selection, review, QA, and local delivery. See `docs/adr/0059-aggregate-campaign-production.md`.

## Round 25 — Provider boundaries and asset handoff

Status: merged on main as `5ce59f0fecaf5851edf71c0cca67275b680c76cb`. See `docs/operations/round-25-validation.md`.

Import a validated Whop snapshot without credentials. Register a manually downloaded Envato file only after hash, probe, license, and confinement checks. Publishing stays deferred. See `docs/adr/0060-whop-and-envato-provider-boundaries.md`.

## Round 26 — Multilingual alignment and narration

Status: in progress on `round-26-multilingual-alignment-narration`, started from `5ce59f0fecaf5851edf71c0cca67275b680c76cb`.

Record which languages have a real aligner or narrator. Full-source alignment runs only when that provider is available. Arabic and Japanese captions keep their characters and direction. A fake provider is not a live claim. Live Whop crawling stays a later provider round. See `docs/adr/0061-multilingual-alignment-and-narration.md`.

## Later

External platform publishing is planned and not implemented. Live Whop crawling is a separate provider round and is not implemented. Arabic and Japanese alignment stay unclaimed until a real provider runs.
