# Whop live operator discovery

Whop discovery is optional and read-only. The default result is `not_configured`. Credentials stay outside Clipforge. See [ADR 0062](../adr/0062-whop-live-operator-discovery.md) and [provider boundaries](provider-boundaries.md).

SQLite schema version stays 6. Contract `schema_version` stays `1.0.0`. No migration was added.

## Provider modes

| Mode | What it accepts | Live status on a discovery | CLI default |
| --- | --- | --- | --- |
| `snapshot` | Local JSON or JSONL | The import row stays `not_configured` | `import --file` |
| `browser_export` | Normalized metadata from an operator export | `authenticated_discovery` | No browser is launched |
| `live_connector` | A documented HTTPS provider, only when a caller supplies one | `public_discovery` or `provider_unavailable` | Doctor does not connect |
| `not_configured` | No approved provider | `not_configured` | `doctor`, `capabilities`, `discover` |

`CLIPFORGE_WHOP_LIVE_SMOKE=1` is required before a live attempt. With that flag and no open session, doctor prints `whop_live: provider_unavailable` and `session: not opened`. `CLIPFORGE_WHOP_CONNECTOR` names a connector. `CLIPFORGE_WHOP_URL` overrides the public MCP URL for the unused reader. None of these variables is a secret, and none is written into a manifest.

The official hosts are `mcp.whop.com` and `docs.whop.com`. The operator signs in on Whop's own page. Clipforge does not automate that page, does not read a password, and does not export cookies or a browser profile.

## Capability matrix

| Check | Default | Smoke flag, no session |
| --- | --- | --- |
| `whop_live` | `not_configured` | `provider_unavailable` |
| Mode | `not_configured` | `live_connector` only when `CLIPFORGE_WHOP_CONNECTOR` is set, otherwise `not_configured` |
| Mutating Whop operations | `disabled` | `disabled` |
| Credentials | `not_stored` | `not_stored` |
| Publishing | `deferred` | `deferred` |
| Socket | closed | closed |

Public catalogue fields are `title`, `campaign_url`, `status`, `category`, and `payout_text`. Account membership is named as an account field and is not queried. A fake provider in tests may report `public_discovery` or `authenticated_discovery`. That is a test double, not a live pass.

## Browser and export boundary

`browser_export` accepts a dictionary of campaign and source metadata. Keys named like authorization, cookie, password, token, or API key are dropped before validation. Secret-like strings become null and then fail closed. The export path does not launch a browser, does not read a profile directory, and does not keep a session id.

`WhopMcpReader` can speak JSON-RPC over HTTPS with `Content-Type`, `Accept`, and `User-Agent` only. It has no `Authorization` header. It is not called by doctor, discover, or CI. A non-HTTPS URL is `provider_unavailable`. Tool names that contain create, update, delete, join, apply, submit, upload, message, charge, pay, purchase, or checkout are ignored. Responses are redacted before use.

## Contracts and files

Discovery sidecars:

```text
campaigns/whop-discoveries/<discovery_id>/manifest.json
campaigns/whop-discoveries/<discovery_id>/response.json
campaigns/whop-selections/<evidence_id>/evidence.json
```

Snapshot imports stay at `campaigns/whop/<import_id>/`. Every stored campaign keeps its id, title, URL when present, status, category, payout text when present, policy, source ids, source URLs as metadata, rights, hashes when present, catalogue fingerprint, provider identity, provider version, import time, and evidence fingerprint.

New models: `WhopProviderCapability`, `WhopLiveDiscoveryRequest`, `WhopCampaignCatalogue`, `WhopFilterDecision`, `WhopDiscoveryAttempt`, `WhopSelectionEvidence`.

## Filter and policy

The filter walks the snapshot in order and returns one decision per campaign. A campaign is included when at least one source passes. Reason codes:

| Code | Condition |
| --- | --- |
| `included` | At least one source passed |
| `status_not_active` | `require_status` is set and the campaign status differs |
| `category_prohibited` | Category is on the prohibited list |
| `category_not_allowed` | An allow list is set and the category is absent |
| `policy_blocked` | Policy is not the required value, or it is `unknown` or `prohibited` |
| `language_mismatch` | A language is required and the campaign language is some other value |
| `search_mismatch` | The query is absent from the title, category, payout text, and source names |
| `stale_campaign` | `exported_at` is older than `max_age_hours` |
| `missing_source` | No sources, or a source is marked `missing` and none pass |
| `format_mismatch` | The media format differs from the request |
| `source_too_large` | `size_bytes` is above the cap |
| `duration_out_of_range` | Duration is outside the requested bounds |
| `rights_not_allowed` | Rights are not the required state |
| `source_unavailable` | Availability is neither `available` nor `unknown` |

The default discovery request prohibits `gambling` and requires policy and rights `allowed`. It does not require a status, so a snapshot that omits status stays `unknown` and can still pass the other checks. An explicit request replaces the prohibited list. A null language passes a language filter. A null duration or size is not invented and is not compared.

Example outcomes for the public sample campaign `camp-city`:

- The default request includes it with reason `included`.
- Status `paused` with `require_status=active` is `status_not_active`.
- Category `gambling` is `category_prohibited`.
- An allow list of `education` is `category_not_allowed`.
- Policy `prohibited` is `policy_blocked`.
- Language `ja` against `en-US` is `language_mismatch`.
- Query `zzzz` is `search_mismatch`.
- An export older than `max_age_hours` is `stale_campaign`.
- Availability `missing` is `missing_source`.
- Format `mov` against `mp4` is `format_mismatch`.
- A size cap of 10 bytes is `source_too_large`.
- A minimum duration of 5 seconds is `duration_out_of_range`.
- Rights `unknown` is `rights_not_allowed`.
- Availability `offline` is `source_unavailable`.

The discovery record stores the included and excluded decisions, the policy fingerprint, and the catalogue fingerprint. Selecting a source with rights `unknown` fails with `rights_not_allowed`. Selecting a missing source id fails with `missing_source`. An allowed source writes selection evidence and does not prompt again.

## Selection

`select` binds one imported campaign to the existing operator workflow. The evidence records the campaign id, Whop import id, catalogue fingerprint, policy fingerprint, selected source ids, source hashes, language, narration request, operator id, and evidence fingerprint. It does not copy media, start acquisition, start production, or change `CampaignSelectionDocument`.

`content_sha256` is the source hash when the provider supplied one. Otherwise the hash is the canonical metadata of that source record. A caller-supplied hash that differs is `source_changed` and asks the operator to reload. A changed snapshot is `stale_snapshot`. A changed policy fingerprint is `stale_policy`. A caller-supplied catalogue fingerprint that differs is `stale_selection`. All four use the same reload sentence.

## Cache and recovery

Identity is the SHA-256 of the provider id, provider version, normalized request, policy fingerprint, catalogue fingerprint, and response hash. The request id and the request timestamp are not part of that hash. The same provider payload is a cache hit and does not rewrite the manifest. `verify` reads the response file and compares its hash.

A response file whose bytes no longer match that hash is `stale_discovery`. Restoring the original bytes makes the next import a hit again. A changed catalogue is a new discovery id, and the previous manifest stays. `force` also allocates a new id. `cancel` marks the manifest `cancelled`, deletes `*.partial`, and the next import of the same payload allocates a new id.

Promotion writes `response.json.partial` and `manifest.json.partial`, then renames them. A hook failure or an interrupted rename deletes the partials and restores the previous final files when they existed. The snapshot import runs before that rename. A failed discovery promotion can therefore leave a valid snapshot import. The discovery manifest from the previous success stays unchanged.

## Board

The board stays on `127.0.0.1` and accepts GET only.

```text
GET /api/whop/capabilities
GET /api/whop/discoveries
GET /api/whop/discoveries/<id>
GET /api/campaigns/<campaign_id>/whop
GET /api/campaigns/<campaign_id>/filter-results
```

The page shows provider status and version, campaign status, category, policy, source count, rights, availability, filter result, exclusion reason, import fingerprint, selection fingerprint, and live status. Paths in the page script are relative. User-controlled text uses `textContent`. The script has no `innerHTML`, `eval`, autoplay, CDN, analytics, or remote URL.

## Commands

```text
clipforge campaign operator whop doctor
clipforge campaign operator whop capabilities
clipforge campaign operator whop discover
clipforge campaign operator whop import --file SNAPSHOT.json --project PROJECT_ID
clipforge campaign operator whop list
clipforge campaign operator whop show CAMPAIGN_ID
clipforge campaign operator whop verify IMPORT_ID
clipforge campaign operator whop select CAMPAIGN_ID --import IMPORT_ID --project PROJECT_ID --source SOURCE_ID
```

`doctor`, `capabilities`, `discover`, `list`, `show`, and `verify` do not write. `import` reads a local file. `select` writes selection evidence for sources that are already allowed. `discover` does not call a provider and does not download media.

## Language

English WhisperX alignment stays `verified_live` for the known checkpoint. Arabic and Japanese stay `alignment_not_claimed`. KittenTTS stays English-only. Unsupported narration still fails before a job. This round does not change those claims.

## Limits

- No live Whop session is opened by doctor, discover, or CI.
- A fake `public_discovery` or `authenticated_discovery` is not a live pass.
- Snapshot import rows stay `whop_live: not_configured`.
- Campaign metadata is not an `AssetLicenseRecord`.
- Media URLs are not downloaded.
- Account mutation and external publishing stay deferred.
- A future mutating Whop call needs an explicit operator confirmation that this round does not provide.
