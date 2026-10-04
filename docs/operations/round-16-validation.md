# Round 16 validation

Branch `round-16-local-delivery-export` starts from `67ae3c3126aa8046da9cb0f6b8becb4603801395`. SQLite stays at schema version 6. Local delivery export is implemented. External platform publishing is not.

## Local checks

- `uv run ruff check .` passed.
- `uv run ruff format --check .` passed.
- `uv run mypy` passed, 197 source files.
- `uv run clipforge schema check` passed.
- `uv run clipforge doctor` passed, 10 checks, schema version 6.
- `pnpm --dir apps/renderer lint`, `typecheck`, and `test` passed, 23 Vitest tests.
- `uv run pytest` collected 395 tests. One full run passed 393, skipped 1, and failed `tests/test_hero_smoke.py::test_real_hero_render_is_portrait_and_captioned` because Chrome reported `Page crashed` inside Remotion. That test passed when run again by itself. The preview smoke that crashed in an earlier loaded run also passed on the next full run.

## Synthetic benchmark

Fixture `deterministic_synthetic`. Total elapsed 33 ms. Technical readiness passed. Local delivery blocked (`unsafe_path` on the lightweight chain, which has no verified package). Platform publishing `not_implemented`. Real-source verification `unavailable` because no authorized source was supplied. VoiceStudio `unavailable`. Overall blocked.

| Stage | Status | Cache hit | Elapsed ms | Error |
| --- | --- | --- | --- | --- |
| ingest | passed | yes | 0 | none |
| media_prepare | passed | yes | 0 | none |
| transcript | passed | yes | 2 | none |
| visual_analysis | passed | yes | 2 | none |
| candidate_mining | passed | yes | 2 | none |
| rough_preview | passed | yes | 2 | none |
| candidate_review | passed | yes | 0 | none |
| alignment | passed | yes | 2 | none |
| hero_plan | passed | yes | 2 | none |
| hero_render | passed | yes | 2 | none |
| advanced_plan | passed | yes | 2 | none |
| advanced_render | passed | yes | 2 | none |
| qa | passed | yes | 2 | none |
| hero_review | passed | yes | 0 | none |
| analytics | passed | yes | 2 | synthetic_fixture |
| publish_export | blocked | no | 2 | unsafe_path |

The analytics row is a labeled synthetic fixture. It is not a viewer metric and does not approve or publish.

## Local package from the Round 16 fixture

This package is a synthetic 1080×1920 H.264/AAC file, not an authorized source.

- Delivery id: `ca2ed522dda44ae9fffc8b55a0098de2`
- Package: `deliveries/ca2ed522dda44ae9fffc8b55a0098de2`
- Manifest SHA-256: `7ee30ef6c16841e13c1bef3e5e531515888e72da8245af8a4c5e9b0e7b227cfd`
- MP4 SHA-256: `445410c3ab6125995e0b4a29b4c77de5bdf1bd52b02e119fc187cbfd76d9a940`
- MP4 size: 107910 bytes
- ffprobe: H.264, AAC, 30/1, 1080×1920
- Second export: `cache_hit` on the same delivery id

## VoiceStudio

`CLIPFORGE_VOICESTUDIO_URL` was unset and `CLIPFORGE_VOICESTUDIO_LIVE_SMOKE` was unset. `127.0.0.1:3900` refused the connection. Live smoke was not run. Status: unavailable.

## What this round does not claim

- External platform publishing is not implemented.
- Real-source verification is unavailable. No authorized source was supplied.
- The synthetic fixture is not production validation.
