# Round 24 validation

Round 24 starts from merge `b92270212a87cd59d05acec244f897b32a9d6b83` on branch `round-24-campaign-production-e2e`. SQLite stays at schema 6. Contract `schema_version` stays `1.0.0`. No migration was added.

`produce` calls the existing campaign runner and writes `campaigns/production/<run_id>/manifest.json`. External publishing stays deferred. Live Whop import stays `not_configured`. Envato stays discovery-only. This file does not store credentials, cookies, bearer tokens, or filesystem paths.

## Commands

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run clipforge schema check
uv run clipforge doctor
pnpm --dir apps/renderer lint
pnpm --dir apps/renderer typecheck
pnpm --dir apps/renderer test
```

Local results on this branch: ruff, format, mypy, schema check, and doctor passed. Doctor reports SQLite schema version 6. Pytest: 514 passed, 1 skipped, 395 seconds. Renderer lint, typecheck, and 23 tests passed. The production Chrome smoke is in that pytest run under the `browser` marker.

CI uses the Round 21 workflow: `verify-python`, then `verify-renderer-browser`, on `[self-hosted, linux, x64, clipforge]`. Feature-branch pushes do not start that workflow.

## Synthetic production

The automated fixture produces both selected catalogue sources with narration not requested. The aggregate status is `succeeded`. Alignment status is `whisperx`. Review decision is `approved`. Each source has a QA set id and a delivery path under `deliveries/`. A second `produce` returns the same run id, does not call the narration probe, and does not insert another `campaign_production` job. `--force` creates a new run id and leaves the first manifest in place. Deleting one QA file yields `partial` with the other source still `succeeded`. Restoring that file and `production-resume` returns the same run id and the same sibling delivery id. Changing one source's bytes yields a new aggregate whose other source stays `succeeded` and whose changed source is `source_changed`.

When narration is requested, `src-before-famous` records `verified_live` and `src-american-secret` records `narration_not_requested`. The narration probe is not called.

## Authorized local sources

The authorized campaign files are present on the operator machine and were measured. A fresh full render of those long sources was not repeated; that run stays opt-in. The existing verified local deliveries were measured instead.

| Source | Bytes | SHA-256 | Picture | Delivery id | Delivery MP4 SHA-256 |
| --- | --- | --- | --- | --- | --- |
| src-before-famous | 180882018 | `abe817eb72bdd67980de1b6a945858043ffead6567585d45b3ccdf1edfd08a89` | h264 1920x1080 30000/1001, aac 44100, 587.743492 s | `e5a07bd9c23e489c0c5228a21a568c79` | `c1a8a90f0cacc21025a372ae9198de3cd352999792b90f7172a7817ef7cf84b5` |
| src-american-secret | 163530208 | `495ae005f3ec2e7365a6baf57abc1e0c57529860dfa090cc3cb449da160b9ba8` | h264 1920x1080 24000/1001, aac 44100, 835.732608 s | `34a99657b1912b094a59260f959a39c0` | `61c174e0fdc61a89e571bce54caa0e31a55c4099929cd8a8cc3bd3f57836999a` |

Both delivery pictures are h264 1080x1920 at 30/1 with aac 48000. Durations are 18.475 s and 18.773 s. Candidate ids on those packages are `a6b6e6cd-b5e7-5dd7-8ec2-05967b5beddd` and `a947bea0-0089-5293-a926-a09dda2aac01`. Those packages were produced by the earlier verified campaign work, not by a new render in this round.
