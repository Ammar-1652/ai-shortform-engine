# ADR 0046: End-to-end V1 benchmark and optional voice sidecar

- Status: Accepted
- Date: 2026-10-04

## Context

Round 14 is merged on main as `39d09e83b74239632d59c67fc456131419ed31ce`. The local chain can ingest, prepare, transcribe, analyze, mine, preview, review, align, render Hero and Advanced Hero drafts, run QA, and record analytics. Nothing yet writes down whether those stages are present together, or where a person still has to act. Narration from another local program is also absent. VoiceStudio can synthesize speech on loopback, and its application license is separate from its model licenses.

## Decision

`clipforge benchmark run` reads the current project and writes one `v1_benchmark_run_json` artifact. The manifest lists every stage from ingest through optional analytics. A missing rights clearance, candidate approval, Hero approval, QA pass, or evidence file blocks or fails that stage and stops the required chain. The command does not insert a review, change an edit plan, or publish. A deterministic synthetic fixture is labeled `deterministic_synthetic`. A real authorized run must be requested explicitly and is not inferred.

The same SQLite file stores the benchmark job and artifact. The manifest lives at `benchmarks/runs/<id>/manifest.json`, and `benchmarks/<source>/current.json` is the current sidecar. The publish commits the database row only after the manifest validates. A failed publish restores the previous sidecar and leaves no current file on the first failure. The manifest stores hashes and ids, not filesystem paths.

VoiceStudio is a separate process. Clipforge does not vendor it or import it as a Python dependency. The provider is disabled unless `CLIPFORGE_VOICESTUDIO_ENABLED=1`. The default URL is `http://127.0.0.1:3900`. Discovery uses `GET /.well-known/voicestudio-speech` and expects `voicestudio.speech.v1`. Speech uses `POST /v1/audio/speech` with `response_format=wav`. Remote plain HTTP is refused. HTTPS to another host requires `CLIPFORGE_VOICESTUDIO_ALLOW_REMOTE=1`. Tests use `FakeVoiceProvider`. A live smoke runs only when `CLIPFORGE_VOICESTUDIO_LIVE_SMOKE=1`.

Narration is a `narration_audio` artifact bound to the project, source, script hash, consent record, and model license. Commercial output rejects unknown, prohibited, and CC-BY-NC model rights. The default `k2-fsa/` model id is not treated as commercially permitted. Advanced Hero rendering accepts narration only when that artifact verifies. Without narration, the render input stays as it was.

## Consequences

- A readiness report can say the technical chain passed while delivery stays blocked, because publishing is not implemented.
- Unavailable tools and a disabled voice provider stay `unavailable`. They are not recorded as passed.
- Operators can add optional narration without making VoiceStudio part of normal CI.

## Non-goals

No publishing, platform API client, upload route, viewer tracking, automatic approval, automatic voice cloning, music, cloud inference, or model download from Clipforge.
