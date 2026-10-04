# Round 15 validation

Date: 2026-10-04. Branch `round-15-e2e-benchmark-voice-sidecar`. Started from Round 14 merge `39d09e83b74239632d59c67fc456131419ed31ce`. The pull request is a draft and is not merged.

## Scope

A local readiness record for the existing production chain, plus an optional VoiceStudio narration sidecar. SQLite schema stays at version 6. Benchmark runs and narration audio are artifact kinds. There is no second database and no platform client.

Commands:

```text
clipforge benchmark doctor
clipforge benchmark run SOURCE_ID
clipforge benchmark list PROJECT_ID
clipforge benchmark show BENCHMARK_ID
clipforge benchmark verify BENCHMARK_ID
clipforge benchmark readiness BENCHMARK_ID
clipforge voice doctor
clipforge voice capabilities
clipforge voice generate --request REQUEST.json
clipforge voice verify ARTIFACT_ID
clipforge voice list PROJECT_ID
```

## Fixture

The CI and local automated path uses `deterministic_synthetic`. A real authorized source was not present in this workspace.

VoiceStudio live smoke: unavailable. `CLIPFORGE_VOICESTUDIO_LIVE_SMOKE` was not set, and nothing was listening on `127.0.0.1:3900`.

One synthetic chain recorded these stages. Elapsed times are from that local run and are not a production timing budget.

| Stage | Status | Cache hit | Elapsed ms |
| --- | --- | --- | --- |
| ingest | passed | yes | 0 |
| media_prepare | passed | yes | 0 |
| transcript | passed | yes | 2 |
| visual_analysis | passed | yes | 2 |
| candidate_mining | passed | yes | 2 |
| rough_preview | passed | yes | 2 |
| candidate_review | passed | yes | 0 |
| alignment | passed | yes | 2 |
| hero_plan | passed | yes | 2 |
| hero_render | passed | yes | 1 |
| advanced_plan | passed | yes | 2 |
| advanced_render | passed | yes | 1 |
| qa | passed | yes | 2 |
| hero_review | passed | yes | 0 |
| analytics | not_run | no | 1 |

Selected candidates: 1. QA result: passed. Total elapsed: 25 ms. Technical readiness: passed. Delivery: blocked. VoiceStudio readiness: unavailable. Overall: blocked, because publishing is not implemented.

## Checks

`uv run pytest` passed with 378 collected tests and 1 skipped live VoiceStudio smoke. `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy` passed (191 source files). `uv run clipforge schema check` passed. `uv run clipforge doctor` passed with 10 checks and schema version 6. Renderer lint, typecheck, and 23 Vitest tests passed.

`tests/test_round15.py` covers schema export, stage order, synthetic and blocked runs, failed QA, sidecar rollback, read-only verify, symlink refusal, fake narration, cache reuse, license rejection, a disabled provider, remote URL refusal, timeout, malformed audio, ffprobe, and the optional live smoke. `tests/test_round15_browser.py` opens the readiness page and checks Unicode narration text. `tests/test_advanced_hero.py` checks that a plain advanced render does not mention narration and that an explicit narration asset is bound before a new advanced job.

## Limitations

- The benchmark observes evidence that is already stored. It does not launch Whisper, vision, or a browser by itself.
- A real authorized fixture was not run.
- VoiceStudio was not installed for the live smoke.
- Delivery stays blocked. Publishing, platform clients, automatic approval, and automatic voice cloning are not implemented.
- Narration is an optional input. It does not replace the canonical transcript or the source audio.
