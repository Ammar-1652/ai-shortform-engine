# Roadmap

Each round ends in a commit that a reviewer can read before the next round starts. A round is complete only when its own acceptance criteria pass. Later rows are plans, not claims that the code exists.

## Round 1 — Foundation

Status: complete. `docs/operations/round-01-validation.md` records the local validation run. GitHub Actions is configured and runs on push. It was not green in this working tree before the first push.

Repository layout, agent rules, ADRs, Pydantic contracts, JSON Schema export, canonical time map, SQLite, CLI, doctor, Python and TypeScript checks, CI. No media processing.

## Round 1.1 — Foundation hardening

Status: locally validated. See `docs/operations/round-01-hardening-validation.md`. The draft pull request is the review gate. Round 2 has not started.

Rights records are stored. Source, artifact, and review foreign keys are enforced. Empty clips and contradictory provenance fail validation.

## Round 2 — Media ingest

Status: not started.

ffprobe ingest, duration and rational frame rate into `MediaProbe`, proxies, audio extraction. Fail the job when ffmpeg is missing or exits non-zero. Keep paths and hashes on the source asset.

## Round 3 — faster-whisper transcription

Full-source transcript with `alignment = approximate`. No WhisperX on the full file. Persist segments and words on the source clock. A failed chunk fails the job.

## Round 4 — Scene, visual, and face analysis

PySceneDetect, plus MediaPipe or OpenCV signals. Scenes are not complete without visual evidence. Face tracks stay `speaker_attribution = unknown` until a separate speaker model exists.

## Round 5 — Candidate mining

About 15–25 candidates is a target band, not a constant. Score, dedupe, and attach transcript and visual evidence. Compliance remains a gate. No fixed top 5.

## Round 6 — Rough Remotion renderer

Cheap vertical previews and captions driven by the canonical time map. No second timing implementation inside React.

## Round 7 — Candidate review

A local review surface, later the Remotion Player. Writes `ReviewDecision` rows. Does not publish.

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
