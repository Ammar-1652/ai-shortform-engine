# Whop live operator discovery

Whop discovery is optional and read-only. The default result is `not_configured`. Credentials stay outside Clipforge. See [ADR 0062](../adr/0062-whop-live-operator-discovery.md), [ADR 0063](../adr/0063-whop-grok-connector-onboarding.md), and [provider boundaries](provider-boundaries.md).

SQLite schema version stays 6. Contract `schema_version` stays `1.0.0`. No migration was added.

## Provider modes

| Mode | What it accepts | Live status on a discovery | CLI default |
| --- | --- | --- | --- |
| `snapshot` | Local JSON or JSONL | The import row stays `not_configured` | `import --file` |
| `browser_export` | Normalized metadata from an operator export | `authenticated_discovery` | No browser is launched |
| `live_connector` | A documented HTTPS provider, only when a caller supplies one | `public_discovery` or `provider_unavailable` | Doctor does not connect |
| `not_configured` | No approved provider | `not_configured` | `doctor`, `capabilities`, `discover` |

## Operator setup

Doctor never opens a socket. It always prints `live_smoke: not_executed`.

| Environment | Doctor |
| --- | --- |
| Live switch unset | `whop_live: not_configured`, `public_provider: not_configured`, `authenticated_connector: not_configured`, `session: not opened` |
| `CLIPFORGE_WHOP_LIVE_SMOKE=1` and `CLIPFORGE_WHOP_CONNECTOR=public` with an https URL | `whop_live: not_configured`, `public_provider: available` |
| `CLIPFORGE_WHOP_LIVE_SMOKE=1`, `CLIPFORGE_WHOP_CONNECTOR=authenticated`, a loopback `CLIPFORGE_WHOP_CONNECTOR_URL`, and `CLIPFORGE_WHOP_SESSION_HANDLE` | `authenticated_connector: available`, `session: handle_only`, `live_smoke: not_executed` |
| Live switch set and no usable connector | `whop_live: provider_unavailable` |

`not_configured` means the live command was not enabled. `provider_unavailable` means it was enabled and no connector can run. `public_provider: available` means the public adapter would be used by `discover --live`. It does not mean a live call already succeeded.

Enable a public read:

```text
CLIPFORGE_WHOP_LIVE_SMOKE=1
CLIPFORGE_WHOP_CONNECTOR=public
clipforge campaign operator whop discover --live --project PROJECT_ID --operator OPERATOR_ID --work-dir WORK_ROOT
```

`clipforge campaign operator whop auth doctor` and `auth status` read the local Grok install. They may run `grok plugin list` and `grok mcp list`. They do not open Chrome, do not open a socket, and do not run `grok mcp doctor whop`. `auth login` installs `whopio/plugins#dist/grok/whop` when it is missing, then runs `mcps` and `whop-connect` only if this Grok build lists those commands. If it does not, login exits `auth_required` and tells the operator to open Grok, run `/mcps`, authorize Whop, and run `/whop-connect`. It does not return `connector_unavailable` before that attempt, and it does not invent a browser URL. `auth refresh` reuses the same profile and repeats login when `grok mcp doctor whop` reports an expired connector. `auth logout` removes only the dedicated profile and the operator tool map after confirmation. The production URL is exactly `https://mcp.whop.com/mcp`. `CLIPFORGE_WHOP_URL` may repeat that URL. Any other host, including another HTTPS host, is `provider_unavailable`. Loopback HTTP is accepted only when a test constructs the adapter with `allow_loopback`. A URL with a username, a password, a query string, or a fragment is rejected. None of these variables is written into a manifest. The adapter does not follow a redirect to another host.

Private campaigns use a connector that already completed Whop's browser sign-in. Clipforge does not automate that page and does not keep the session.

```text
CLIPFORGE_WHOP_LIVE_SMOKE=1
CLIPFORGE_WHOP_CONNECTOR=authenticated
CLIPFORGE_WHOP_CONNECTOR_URL=http://127.0.0.1:PORT/handoff
CLIPFORGE_WHOP_SESSION_HANDLE=one-time-nonce
clipforge campaign operator whop discover --live --connector authenticated --project PROJECT_ID --operator OPERATOR_ID --request REQUEST.json --work-dir WORK_ROOT
```

The handle is a one-time nonce for that process. It is not a cookie or a bearer token, and Clipforge does not write it. A fresh process can call the connector. An in-memory Python registry is not that boundary. A second use of the nonce is `stale_session`. If the connector is down, the command exits non-zero with `provider_unavailable` and writes nothing.

The one-time operator sequence is:

```text
grok plugin install whopio/plugins#dist/grok/whop
```

In Grok, run `/mcps`, select Whop, authorize it, then run `/whop-connect`. Then:

```text
grok mcp doctor whop
clipforge campaign operator whop auth status
clipforge campaign operator whop tools refresh
CLIPFORGE_WHOP_LIVE_SMOKE=1 CLIPFORGE_WHOP_CONNECTOR=official-grok \
  clipforge campaign operator whop discover --live --project PROJECT_ID --operator OPERATOR_ID
```

`official-grok` calls `https://mcp.whop.com/mcp` after doctor reports the connector ready and `tools refresh` has stored a verified map outside the repository at `~/.config/clipforge/whop/tool-map.json`. `authenticated` remains the loopback test double. `live_claim` stays `not_claimed` until that official call succeeds. A fixture, a local JSON file, or a loopback handoff cannot set `claimed`.

When no authorized connector is running, the operator exports a sanitized snapshot and imports it. That path is `authenticated_operator_snapshot`, `credentials_stored: not_stored`, and `live_transport: not_claimed`. It is not a live Clipforge MCP pass.

```text
clipforge campaign operator whop import --file SANITIZED_SNAPSHOT.json --project PROJECT_ID --work-dir WORK_ROOT
```

`discover` without `--live` prints `not_configured`, writes nothing, and exits zero.

## Operator flow

1. The operator authorizes the Whop MCP connection through the official Whop browser flow. Clipforge does not collect the password.
2. The operator verifies the connected account or business and the tools that connection exposes.
3. The operator runs read-only discovery. Clipforge does not create, join, apply, submit, upload, purchase, or modify a campaign.
4. Only campaign metadata and policy or source facts are exported. Cookies, tokens, and raw MCP envelopes stay outside the snapshot.
5. Clipforge imports and fingerprints the sanitized snapshot.
6. Clipforge applies the campaign and source filters. Missing required facts fail closed.
7. The operator selects an allowed source. `selected: true` does not override a failed filter.
8. Acquisition obtains only an authorized source file. A page URL is not that file. An unavailable direct download stays manual.
9. Acquisition hashes the local file, compares it with `declared_content_sha256` when present, and records ffprobe evidence as `acquired_file_sha256`.
10. Rendering starts only after source bytes, rights, review, QA, and acquisition checks pass. Publishing stays deferred.

## Capability matrix

| Check | Default | Smoke flag, no session |
| --- | --- | --- |
| `whop_live` | `not_configured` | `provider_unavailable` when no connector is named; `not_configured` when a connector is only configured |
| `public_provider` | `not_configured` | `available` for `CONNECTOR=public`, otherwise `unavailable` |
| `authenticated_connector` | `not_configured` | `available` for a loopback handle, or for `CONNECTOR=official-grok` on the official URL. That means the connector is selected, not that a call succeeded |
| `live_smoke` | `not_executed` | `not_executed` |
| Mutating Whop operations | `disabled` | `disabled` |
| Credentials | `not_stored` | `not_stored` |
| Publishing | `deferred` | `deferred` |
| Socket from doctor | closed | closed |

Public catalogue fields are `title`, `campaign_url`, `status`, `category`, and `payout_text`. Account membership is named as an account field and is not queried by this adapter. A fixture may carry `public_discovery` or `authenticated_discovery` only with `evidence_origin: test_double` and `live_claim: not_claimed`.

## MCP and browser boundary

The public adapter posts `initialize`, records the negotiated protocol version, posts `notifications/initialized`, and sends `MCP-Protocol-Version` on later requests. It then posts `tools/list` and one `tools/call` for an exact name. The packaged map at `src/clipforge/campaign/data/whop-tool-map.json` has no official mapping. `whop tools refresh` may write a verified map outside git after a live `tools/list`. Fixture names such as `list_public_campaigns` are test doubles. A prefix, a substring, or a mutating token does not qualify. A tool without read-only evidence is rejected. If `tools/list` has no mapped Content Rewards tool, the result is `unsupported_tool` and nothing is stored. Headers are `Content-Type`, `Accept`, and `User-Agent`. `Authorization` is not set. `Mcp-Session-Id` stays on the client for that process and is not stored. JSON and `text/event-stream` bodies are accepted, and the SSE event must match the JSON-RPC id. HTTP 202 with an empty body accepts a notification. HTTP 401 is `auth_required`. HTTP 404 on a live session is `stale_session` and initialization runs once. Oversized bodies, timeouts, and malformed JSON-RPC are errors and are not retried. Secret keys and secret-like text reject the document. A payload field named `live_status` or `provider_version` is `forged_status`.

The authenticated boundary is the loopback connector, not a registry inside the Clipforge process. The connector returns sanitized campaign JSON. Clipforge does not launch a browser, does not read a profile, and does not keep a password. Normal CI does not set the live switch. The opt-in smoke skips with `whop_live: not_configured` and `live_smoke: not_executed` unless an authorized connector is actually running. A skip is not a live pass. A loopback fixture is not a live pass.

## Contracts and files

Discovery sidecars:

```text
campaigns/whop-discoveries/<discovery_id>/manifest.json
campaigns/whop-discoveries/<discovery_id>/response.json
campaigns/whop-discoveries/<discovery_id>/request.json
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

The default discovery request prohibits `gambling` and requires policy and rights `allowed`. It does not require a status, so a snapshot that omits status stays `unknown` and can still pass the other checks. An explicit request replaces the prohibited list. When the request requires a fact, a missing value fails closed: `missing_status`, `missing_category`, `missing_language`, `source_unavailable`, `missing_format`, `missing_size`, `missing_duration`, `rights_not_allowed`, `policy_blocked`, `missing_content_hash`, or `manual_download_required`. Unknown is not treated as allowed. A null duration or size is not invented.

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

A declared content hash is required before a source can be selected. A missing hash is `missing_content_hash`. Clipforge does not substitute a metadata digest and does not record the declared hash as the hash of a local file. Acquisition writes `acquired_file_sha256` only after hashing the local file, comparing it with the declaration when one exists, rejecting symlinks, and running ffprobe and a decode check. A mismatch is `hash_mismatch` and blocks rendering. A caller-supplied hash that differs is `source_changed` and asks the operator to reload. A changed snapshot is `stale_snapshot`. A changed policy fingerprint is `stale_policy`. A caller-supplied catalogue fingerprint that differs is `stale_selection`. A discovery from another project is `project_mismatch`. An old discovery cannot select a newer import. The stale cases use the same reload sentence. A Whop page URL is metadata. It is not a downloadable file. A source with no direct download needs a manual acquisition reference.

## Cache and recovery

Identity is the SHA-256 of the project id, operator id, provider id, provider version, tool name, provider mode, request fingerprint, policy fingerprint, catalogue fingerprint, response hash, source declarations, and acquisition policy. The request id and the request timestamp are not part of that hash. The same payload in another project, for another operator, or from another tool or provider version is a different discovery. A cache hit requires that same identity and does not rewrite the manifest. `verify` reads the response file, the request file, and the current policy fingerprint.

A response file whose bytes no longer match that hash is `stale_discovery`. Restoring the original bytes makes the next import a hit again. A changed catalogue is a new discovery id, and the previous manifest stays. `force` also allocates a new id. `cancel` marks the manifest `cancelled`, deletes `*.partial`, and the next import of the same payload allocates a new id.

Promotion stages the new snapshot import and the discovery response, request, and manifest. Hashes are checked before the rename. A hook failure, a cancellation, or an interrupted rename restores any overwritten file and removes files this attempt created. It does not follow a symlink. The previous import and discovery stay byte-for-byte. No successful job row is inserted. `resume` copies that response into a new discovery id and does not call the provider.

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
clipforge campaign operator whop discover --live --connector authenticated --project PROJECT_ID --operator OPERATOR_ID --request REQUEST.json --work-dir WORK_ROOT
clipforge campaign operator whop import --file SANITIZED_SNAPSHOT.json --project PROJECT_ID --work-dir WORK_ROOT
clipforge campaign operator whop list
clipforge campaign operator whop show CAMPAIGN_ID
clipforge campaign operator whop verify IMPORT_ID
clipforge campaign operator whop select CAMPAIGN_ID --import IMPORT_ID --project PROJECT_ID --source SOURCE_ID
```

`doctor`, `capabilities`, `list`, `show`, and `verify` do not write. `discover` without `--live` does not write and does not connect. `discover --live` writes a discovery only after the connector returns a catalogue. An empty catalogue, a provider error, a blocked filter, or a missing connector exits non-zero. `import` reads a local file. `select` writes selection evidence for sources that pass the stored request and have a content hash. It does not download media.

## Language

English WhisperX alignment stays `verified_live` for the known checkpoint. Arabic and Japanese stay `alignment_not_claimed`. KittenTTS stays English-only. Unsupported narration still fails before a job. This round does not change those claims.

## Limits

- Doctor, `discover` without `--live`, and normal CI do not open a socket.
- `discover --live` can open the public MCP socket or call a loopback connector from a clean process. A fixture result stays `live_claim: not_claimed`.
- The opt-in smoke skips with `whop_live: not_configured` and `live_smoke: not_executed` when no authorized connector is running. That skip is not a live pass.
- Official Whop tool names stay unverified until `tools/list` on `https://mcp.whop.com/mcp` returns them. The checked-in tool map is empty. A verified map outside the repository is not a live claim by itself. `live_claim: claimed` requires one successful read-only `tools/call` on that endpoint.
- A Whop page URL is not a media file. Direct downloads that are unavailable need manual acquisition. Acquired file hashes stay separate from declared hashes.
- Snapshot import rows stay `whop_live: not_configured`.
- Campaign metadata is not an `AssetLicenseRecord`.
- Media URLs are not downloaded.
- Account mutation and external publishing stay deferred.
- A future mutating Whop call needs an explicit operator confirmation that this round does not provide.
