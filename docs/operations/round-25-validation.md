# Round 25 validation

Round 25 starts from merge `a642c202eed45a3aef26b791178f233778ff93a1` on branch `round-25-provider-boundaries-asset-handoff`. SQLite stays at schema 6. Contract `schema_version` stays `1.0.0`. No migration was added.

Whop intake reads an operator export. Envato registration reads a file the operator already placed under `incoming/`. External publishing stays deferred. Live Whop stays `not_configured`. This file does not store credentials, cookies, bearer tokens, or filesystem paths.

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

Local results on this branch: ruff, format, mypy, schema check, and doctor passed. Doctor reports SQLite schema version 6. Schema export wrote 180 files. Pytest: 523 passed, 1 skipped, 415 seconds. Renderer lint, typecheck, and 23 tests passed. The provider Chrome smoke is in that pytest run under the `browser` marker.

CI uses the Round 21 workflow: `verify-python`, then `verify-renderer-browser`, on `[self-hosted, linux, x64, clipforge]`. Feature-branch pushes do not start that workflow. Browser coverage stays on the `browser` marker. Live provider checks stay opt-in.

## Whop fixture

The synthetic snapshot names campaign `studio-demo`, operator `operator-1`, and sources `src-one` (allowed) and `src-two` (unknown rights). Importing the same bytes returns the same import id and does not write a second directory. A changed title creates a new id. A bearer token, cookie, API key, password, authorization header, absolute path, `file:` URI, HTML, or unknown key is rejected before `campaigns/whop/` exists. The import does not insert an `asset_license_records` row. Selecting `src-one` returns that id with no second confirmation. Selecting `src-two` fails with `rights_not_allowed`. A prohibited campaign policy fails with `policy_blocked`. Changing the snapshot file fails with `stale_snapshot`. A changed policy fingerprint fails with `stale_policy`.

`clipforge campaign operator whop doctor` prints `whop_live: not_configured`.

## Envato filter mapping

`FakeEnvatoMcpProvider` with the `search_stock_video` schema sends `orientation=vertical` and keeps `genre=ambient` in `deferred_filters`. `perPage` is at most 5. A row without a duration or a direct download URL stays null. A row without an item id stays null. The item-page URL `https://elements.envato.com/city-night-1` is stored as metadata and does not create a media file. Download status stays `manual_download_required`.

## Manual registration

The CI fixture is a one-second 160x90 H.264 and AAC file generated with lavfi. One measured registration:

| Field | Value |
| --- | --- |
| SHA-256 | `f1bb42156aa9e02caf355997141061752286e731ee45ce0a223f65d6d14e91cd` |
| Bytes | 3987 |
| Picture | h264 160x90 `30/1` |
| Audio | aac 48000 |
| Duration | 1000000 us |
| Container | mov |
| Relative path | `campaigns/envato-assets/env-f1bb42156aa9e02caf35/media/clip.mp4` |

The same bytes are a cache hit: the asset id is unchanged, the manifest bytes are unchanged, and no second job is inserted. Changed bytes create a new asset id and leave the first file in place. `--force` also keeps the previous directory. A hook failure at `final_rename` restores the previous media bytes. A hook failure at `staging_write` leaves no partial and no promoted file. `cancel` then `resume` reaches `verified`. `verify` does not change work-tree bytes or the database file size.

Rejected before promotion: traversal, backslash, absolute path, remote URL, `file:` URI, a symlinked file, a symlinked parent directory, corrupt bytes, an mpeg4 video, the wrong size, a 10-byte cap, empty license evidence, unknown rights, prohibited rights, and the Antoine outside-media policy.

## Advanced Hero

A verified registration is written into the source advanced-asset catalog with kind `envato`. `require_asset` and the B-roll planner accept it. Changing the file bytes raises before any render job is inserted. The jobs table contains only `envato_asset_registration`. A missing registration raises the same way. Campaigns that do not reference an Envato asset do not call this check.

## Board and privacy

The loopback board serves the Whop import, the Envato campaign view, the asset, and the campaign asset list. The Envato route still reports `discovery_only`. Payloads include the snapshot fingerprint, deferred filters, item-page URL, null direct download URL, hash, probe, license evidence, rights, and a relative path. They do not include `/home/`, `file:`, or bearer text. The static bundle has no `eval(`, `innerHTML`, or remote URL. The Chrome smoke renders `whop_status`, `snapshot_fingerprint`, and `asset_sha256` through `textContent`.

## Language

This round does not change narration or alignment claims. English WhisperX stays verified only when a real artifact exists. Arabic and Japanese stay `alignment_not_claimed`. KittenTTS stays English-only. en-GB narration stays `locale_not_smoked`. Fake provider rows are not reported as live evidence.

## Limits

Clipforge does not download Envato files, crawl Whop, or publish to TikTok, Instagram, YouTube, or Whop. Normal CI does not need Whop credentials, browser cookies, Envato tokens, or external network access.
