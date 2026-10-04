# End-to-end V1 benchmark

`clipforge benchmark` records whether the local production chain is present. It does not approve a clip or publish one.

## Flow

The recorded order is:

1. ingest and rights
2. media preparation
3. transcript
4. visual analysis
5. candidate mining
6. rough preview
7. human candidate review
8. selected-clip alignment
9. Hero plan
10. Hero render
11. Advanced Hero plan
12. Advanced Hero render
13. technical and campaign QA evidence
14. human Hero review
15. optional analytics

Each stage stores status, timestamps, elapsed milliseconds from a monotonic clock, cache hit, artifact id, artifact hash, error category, and whether a person must act. A required stage that is `failed`, `blocked`, or `unavailable` stops the later required stages. Analytics may stay `not_run`.

Rights must be owned, licensed, or campaign-provided. Unknown and prohibited rights block ingest. Candidate review blocks until an approved human decision exists for the selected candidate. Hero review blocks until an approved Hero decision exists. QA fails when the QA document status is not `pass`. The benchmark does not create those decisions.

## Fixture policy

`--fixture-kind deterministic_synthetic` is the default. CI uses that label for a chain of local JSON evidence. `--fixture-kind real_authorized` is an operator assertion that the source is authorized. Clipforge does not discover a real fixture in the repository. If no authorized media is supplied, the real run is unavailable and is not reported as passed.

## What is measured

The manifest can include source duration, output duration, candidate and selected counts, preview, Hero, and Advanced Hero counts, QA result, total elapsed time, per-stage elapsed time, cache hits, and the byte size of the work tree at the end of the run. Tool versions record Python, Clipforge, and whether ffmpeg and ffprobe are present. A missing tool is `unavailable`, not a pass.

Output width, height, codec, and frame rate stay empty unless a later measurement supplies them. They are not invented.

## Cache and recovery

A second run with the same source hash, fixture kind, approvals, and artifact hashes returns the existing manifest and does not insert another row. `--force` writes another record. The run id is the first 32 hex characters of that identity.

Promotion writes a partial manifest, validates it, inserts the job and artifact, then publishes `manifest.json` and `current.json`. A sidecar failure rolls the database back and deletes a first-run current file.

`list`, `show`, `verify`, and `readiness` only read. `verify` checks lineage and hashes. It does not create a job.

## Readiness

`clipforge benchmark readiness` separates technical, editorial, rights, QA, delivery, and VoiceStudio. Delivery stays `blocked` because publishing is not implemented. VoiceStudio stays `unavailable` unless a later record says the endpoint answered. Overall stays `blocked` while delivery is blocked, even when the technical chain passed. The report lists the remaining manual steps.

## Commands

```text
clipforge benchmark doctor
clipforge benchmark run SOURCE_ID --fixture-kind deterministic_synthetic
clipforge benchmark list PROJECT_ID
clipforge benchmark show BENCHMARK_ID
clipforge benchmark verify BENCHMARK_ID
clipforge benchmark readiness BENCHMARK_ID
```

The loopback page binds to `127.0.0.1` and shows stage status plus any narration label. It does not serve arbitrary files.
