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
15. analytics, using a labeled synthetic fixture when the run is synthetic
16. local delivery export (`publish_export`)
17. optional platform dry-run
18. optional platform submit, which stays `not_run` unless live smoke is enabled

`--execute` may run a missing prepare stage and may export the local package when preflight passes. Existing artifacts are `recorded_evidence`. The benchmark does not insert a human approval and does not download a model. Platform dry-run uses the local dry-run publisher only after a verified package exists, and platform submit does not contact a remote platform. A synthetic run is marked `synthetic_only`. Without an executed real-source delivery, readiness stays `real_source_verified: unavailable` and `no authorized source supplied`.

Each stage stores status, timestamps, elapsed milliseconds from a monotonic clock, cache hit, artifact id, artifact hash, error category, delivery id, delivery manifest hash, readiness classification, and whether a person must act. A required stage that is `failed`, `blocked`, or `unavailable` stops the later required stages. A synthetic run writes `benchmarks/fixtures/synthetic-analytics.json` and marks analytics `synthetic_fixture`. That file is not a viewer metric. A real run with no local outcomes leaves analytics `not_run`.

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

`clipforge benchmark readiness` separates technical, editorial, rights, QA, local delivery, platform publishing, VoiceStudio, and real-source verification. `local_delivery` is `passed` only after a package verifies, and the report then says `local_delivery_pass`. A passing technical rollup says `technical_pass`. `platform_publishing` stays `not_implemented`. `external_publishing` stays `external_publishing_deferred`. `real_source_verified` stays `unavailable` with reason `no authorized source supplied` when no authorized source was supplied. `evidence_class` is `synthetic_only` for the deterministic fixture. `--fixture real_source` records `evidence_class: real_source` and still leaves `real_source_verified` unavailable until that fixture has an executed, verified local delivery. A synthetic fixture is never reported as real-source verification. `voice_result` stays `voice_disabled` unless VoiceStudio is enabled, and an enabled provider that was not shown to answer is `voice_provider_unavailable`, not `voice_live_pass`. `alignment_claim` stays `alignment_not_claimed` or `not_run` until a real aligner result is recorded. Overall stays `blocked` while local delivery is not `passed`. The report lists the remaining manual steps. External publishing is not passed because a local package exists.

## Commands

```text
clipforge benchmark doctor
clipforge benchmark run SOURCE_ID --fixture-kind deterministic_synthetic
clipforge benchmark run SOURCE_ID --fixture real_source
clipforge benchmark list PROJECT_ID
clipforge benchmark show BENCHMARK_ID
clipforge benchmark verify BENCHMARK_ID
clipforge benchmark readiness BENCHMARK_ID
```

The loopback page binds to `127.0.0.1` and shows stage status plus any narration label. It does not serve arbitrary files.
