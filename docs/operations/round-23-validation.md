# Round 23 validation

Round 23 starts from merge `1dcd8926b9c4c0dc23f173bdc56bfee1bb6e10b9` on branch `round-23-source-acquisition-policy-intake`. SQLite stays at schema 6. Contract `schema_version` stays `1.0.0`. No migration was added.

Acquisition is an append-only work-root sidecar. `clipforge campaign operator run` still calls the campaign production runner. External publishing stays deferred. Live Whop import stays `not_configured`. Envato live search stays opt-in. This file does not store credentials, cookies, bearer tokens, or filesystem paths.

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

Local results on this branch: ruff, format, mypy, schema check, and doctor passed. Doctor reports SQLite schema version 6. Pytest: 507 passed, 1 skipped, 383 seconds. Renderer lint, typecheck, and 23 tests passed. The acquisition Chrome smoke is in that pytest run under the `browser` marker.

CI uses the Round 21 workflow: `verify-python`, then `verify-renderer-browser`, on `[self-hosted, linux, x64, clipforge]`. Feature-branch pushes do not start that workflow.

## Acquisition fixture

The unit fixture is a one-second 160x90 H.264 and AAC file at 30 fps and 48 kHz. A succeeded result records that probe, the SHA-256 of the file, the byte size, and a relative path under `campaigns/acquisitions/<id>/media/`. A second run of the same selection returns the same acquisition id and does not insert another `campaign_acquisition` job. `--force` creates a new id and leaves the first manifest in place. A changed input records `source_changed` on a new attempt and leaves the previous succeeded manifest. Resume retries the incomplete source and keeps the sibling file hash.

## Envato

`search_stock_video` receives `orientation` and `resolution` when those keys are in its schema. `format` stays in `deferred_filters` and is not sent. `perPage` is 5 and `page` is 1. A hit without a download URL keeps `direct_download_url` null.

## Whop

`whop_live_import` returns `not_configured`. A snapshot whose policy text contains a bearer token is rejected and is not written under the work root.
