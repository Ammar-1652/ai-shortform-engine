# Provider boundaries

Whop intake and Envato handoff stay on the operator machine. Clipforge does not publish. See [ADR 0060](../adr/0060-whop-and-envato-provider-boundaries.md).

SQLite schema version stays 6. Contract `schema_version` stays `1.0.0`. No migration was added.

## Whop

Credentials, cookies, and API keys are not fields. A snapshot is local JSON or JSONL. Doctor does not open a socket. With no live switch it reports `whop_live: not_configured` and `live_smoke: not_executed`. A public connector, or an authenticated loopback connector with a one-time handle, is reported as available and still not executed. A live switch without a connector is `provider_unavailable`. `discover --live` is the command that may connect. The public adapter uses only `https://mcp.whop.com/mcp`. A `127.0.0.1` connector is a sanitized test handoff, not an authenticated Whop session. Import verification recomputes selectable sources, status, and reason from the snapshot. `whop auth` keeps the browser profile outside the repository and does not read cookies. `auth login` installs the official Whop Grok plugin when it is missing, then asks the operator to run `/mcps` and `/whop-connect` in Grok when this CLI cannot start those commands. `auth doctor` does not open a socket. An in-memory registry is not account access. A sanitized operator snapshot imports as `authenticated_operator_snapshot` with `credentials_stored: not_stored` and `live_transport: not_claimed`. The packaged tool map stays empty. A verified map may be stored under the user config directory after `tools/list`, and it is not committed. `official-grok` is the production connector. `authenticated` remains a loopback test double and cannot set `live_claim: claimed`. Declared content hashes are not acquired file hashes. See [whop-live-discovery.md](whop-live-discovery.md), [ADR 0062](../adr/0062-whop-live-operator-discovery.md), and [ADR 0063](../adr/0063-whop-grok-connector-onboarding.md).

Accepted records:

- `WhopCampaignSnapshot`
- `WhopCampaignRecord`
- `WhopCampaignSourceRecord`
- `WhopImportAttempt`

Imports are append-only under `campaigns/whop/<import_id>/`. The same canonical snapshot is a cache hit. A changed snapshot is a new id. `--force` also creates a new id and leaves the previous directory. Validation runs before any sidecar write.

A selected source is selectable only when the campaign policy, the source policy, and the source rights are `allowed`. That source does not need a second confirmation. Any other state is blocked. The snapshot is not license evidence. `verify` fails when the snapshot file hash, the policy fingerprint, or the latest import id does not match.

## Envato

Search still uses the official MCP tool schema. Unsupported generic filters stay in `deferred_filters` and are not sent. `perPage` is at most 5. Null provider fields stay null. Item-page URLs are metadata. A missing direct download URL stays `manual_download_required`. Clipforge does not invent an item id, a duration, a license, or a download URL.

The operator copies the downloaded file into `incoming/` and registers it. The registration stores the asset id, campaign, project, item page, item id, relative path, byte size, SHA-256, ffprobe facts, license evidence, rights, provider version, acquisition status, producer job id, and timestamp.

Registration rejects:

- symlink files and symlink parent directories
- traversal, backslashes, absolute paths, `file:` URIs, and remote URLs
- files outside the work root or over the campaign byte cap
- corrupt media, an unexpected codec, dimensions, duration, or frame rate
- missing license evidence
- rights other than `allowed`
- a stale request or a stale policy fingerprint

Antoine's outside-media rule blocks registration for that campaign. Other campaigns can register when their policy fingerprint is current.

A cache hit returns the same asset id and does not copy again. Changed bytes are a new asset. `--force` keeps the previous directory. A failed promotion restores the previous media and manifest. `cancel` leaves an unverified registration. `resume` continues it. `verify` reads and does not write.

### Optional portal credential setup

`clipforge assets envato auth setup` stores a portal login only in the user
account's OS Secret Service. It prompts on a TTY, never accepts a password as a
CLI option, and never writes credentials, cookies, or browser profiles to the
repository, work root, SQLite, logs, or artifacts. `auth doctor` checks local
prerequisites without unlocking the keyring; `auth status` reports presence
only; `auth forget --yes` removes the local entry without claiming remote
logout. This does not claim portal login or implement downloads. The future
bridge must remain a separate, reviewed adapter and still pass every existing
hash, probe, license, policy, provenance, and path-confinement gate.

## Advanced Hero

`require_asset` checks an Envato catalog entry against the registration before planning continues. The asset must still match its hash, stay inside the work root, keep allowed rights and license evidence, have a succeeded producer job, and match the campaign, project, and current policy fingerprint. A failure raises before a render job is inserted. Graphic and audio assets that are not Envato are unchanged.

## Board

The board stays on `127.0.0.1` and accepts GET only.

```text
GET /api/whop/capabilities
GET /api/whop/discoveries
GET /api/whop/discoveries/<id>
GET /api/campaigns/<campaign_id>/whop
GET /api/campaigns/<campaign_id>/filter-results
GET /api/whop-imports/<import_id>
GET /api/campaigns/<campaign_id>/envato
GET /api/envato-assets/<asset_id>
GET /api/campaigns/<campaign_id>/assets
```

Pages show provenance, import status, the snapshot fingerprint, policy, deferred filters, item-page URLs, a direct download URL only when the provider returned one, manual download status, hash, size, probe facts, license evidence, rights, whether the asset can be used, the failure reason, and relative paths. Strings use `textContent`.

## Commands

```text
clipforge campaign operator whop doctor
clipforge campaign operator whop capabilities
clipforge campaign operator whop discover
clipforge campaign operator whop discover --live --connector authenticated --project PROJECT_ID --operator OPERATOR_ID --request REQUEST.json --work-dir WORK_ROOT
clipforge campaign operator whop import --file SANITIZED_SNAPSHOT.json --project PROJECT_ID --work-dir WORK_ROOT
clipforge campaign operator whop list
clipforge campaign operator whop show CAMPAIGN_ID
clipforge campaign operator whop verify IMPORT_ID
clipforge campaign operator whop select CAMPAIGN_ID --import IMPORT_ID --project PROJECT_ID --source SOURCE_ID
clipforge assets envato request
clipforge assets envato auth doctor
clipforge assets envato auth setup
clipforge assets envato auth status
clipforge assets envato auth forget --yes
clipforge assets envato requests
clipforge assets envato register
clipforge assets envato show ASSET_ID
clipforge assets envato verify ASSET_ID
clipforge assets envato list
```

`doctor`, `capabilities`, `discover`, `list`, `show`, `requests`, and `verify` do not write. `register --cancel` and `envato resume` cover an interrupted registration. Whop `select` writes selection evidence for an already allowed source and does not contact Whop.

## Limits

- No TikTok, Instagram, YouTube, or Whop publishing.
- No server-side Whop scrape, no stored browser cookies, and no live Whop session from doctor or `discover` without `--live`. A loopback fixture is not a live Whop pass.
- No automatic Envato download or portal login; OS-keyring setup is only a
  credential boundary for a future reviewed bridge.
- English WhisperX alignment is verified only when a real alignment artifact exists.
- Arabic and Japanese alignment stay `alignment_not_claimed`.
- KittenTTS stays English-only. en-GB narration stays `locale_not_smoked`.
- A fake provider result is not live evidence. Whop discovery stays `not_configured` until a real session exists.
- Live provider checks are opt-in: `CLIPFORGE_WHOP_LIVE_SMOKE=1` and `CLIPFORGE_ENVATO_MCP_LIVE_SMOKE=1`.
