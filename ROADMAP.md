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

Status: complete on branch `round-06-rough-renderer`. The draft PR is not merged. See `docs/operations/round-06-validation.md`.

The current candidate set is rendered from the analysis proxy and the ASR FLAC into 720×1280 review MP4s. Captions are provisional. The TimeMap stays the clock. Round 7 is not started.

## Round 7 — Candidate review

Not started. A local review surface, later the Remotion Player. Writes `ReviewDecision` rows. Does not publish.

## Round 8 — Hero alignment and motion library

WhisperX forced alignment on selected Hero clips only. Hero edit plans and the first purposeful motion components.

## Round 9 — Envato

Official Envato MCP for search, plus an asset request that cannot land in an edit without provenance and a license record.

## Round 10 — Advanced Hero editing

B-roll, typography, diagrams, SFX, semantic emphasis, reframing strategies that are not "the face is the speaker".

## Round 11 — Profiles, policy engine, QA

Campaign profiles select rules. Technical QA and campaign QA are hard gates. A pass requires check evidence.

## Round 12 — Jobs, cache, restart, batch

Resume a failed job from recorded state. Cache probes and transcripts. Batch several sources without a second database.

## Round 13 — Performance analytics

Store outcomes so a later round can see which editorial patterns performed. No automatic republish.

## Round 14 — End-to-end benchmark and V1

A fixed authorized fixture, a full run from ingest through human approval, and a written list of what is still manual. V1 still does not publish by itself.
