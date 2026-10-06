# ADR 0062: Live Whop operator discovery

- Status: Accepted
- Date: 2026-10-06

## Context

Round 25 can import a local Whop snapshot. It cannot inspect a live catalogue, filter it, or bind a selection to that import. Whop's official MCP server signs the operator in through a browser. Clipforge must not collect the username, password, API key, OAuth token, bearer token, cookie, browser profile, or authorization header.

This round is read-only toward Whop. Joining a campaign, applying, submitting content, uploading media, creating products or ads, sending messages, changing settings, and spending money need a later explicit confirmation. External publishing stays deferred.

SQLite is schema 6. The new records are sidecars. A second table would not make the credential checks stronger.

## Decision

Whop discovery has four modes: `snapshot`, `browser_export`, `live_connector`, and `not_configured`. The default is `not_configured`. Four results stay distinct: `public_discovery`, `authenticated_discovery`, `not_configured`, and `provider_unavailable`.

Doctor and `discover` without `--live` do not open a socket. `discover --live` builds a provider only when `CLIPFORGE_WHOP_LIVE_SMOKE=1` and `CLIPFORGE_WHOP_CONNECTOR` is `public` or `authenticated`. Doctor reports `live_smoke: not_executed` in every case. It also reports `public_provider: available` or `authenticated_connector: available` when that connector is configured, and `whop_live: provider_unavailable` when live mode is requested in the environment but no connector is configured. Secrets are not command arguments.

## MCP and browser boundary

The public adapter speaks streamable HTTP MCP to `https://mcp.whop.com/mcp`. Loopback HTTP is for tests. The retired `/sse` endpoint is not used. The client posts `initialize`, records `protocolVersion`, posts `notifications/initialized`, and sends `MCP-Protocol-Version` on every later request. It then posts `tools/list` and one `tools/call`. `Mcp-Session-Id` stays on the client object. It is not written to a sidecar, a log line, or a manifest. Responses may be `application/json` or `text/event-stream`. An SSE body is matched by JSON-RPC id. HTTP 202 with an empty body accepts a notification. HTTP 401 is `auth_required`. HTTP 404 on an existing session is `stale_session` and initialization runs once. A discovery call is not repeated after an uncertain response. The public adapter does not send `Authorization`.

Tool names come from `docs/operations/assets/whop/tool-map.json`. That file has no official mapping until a real `tools/list` returns one. Names used by the loopback fixture are not official tools. The adapter rejects an unmapped name, a tool without read-only evidence, a destructive annotation, and any create, update, delete, join, apply, submit, upload, payment, or checkout operation. It does not choose a tool because the name contains `list` or `search`. If no mapped Content Rewards tool is present, the result is `unsupported_tool`. An empty campaign list is not written as success.

## Authenticated connector and operator handoff

Clipforge does not sign in to Whop and does not keep a process-local reader as proof of an account. The production adapter calls only `https://mcp.whop.com/mcp`. A local catalogue bridge on `127.0.0.1` is a test double. It returns provider id, version, mode `test_double`, tool name, sanitized business context, and campaigns. It does not return headers, cookies, session ids, tokens, passwords, or raw MCP envelopes, and it has no `--prove-session` switch. A fixture or a command-line flag cannot set `authenticated_discovery`. `live_claim` stays `not_claimed`. A second use of the nonce is `stale_session`. If the connector is down, the result is `provider_unavailable`. An operator snapshot import is `authenticated_operator_snapshot` with `credentials_stored: not_stored` and `live_transport: not_claimed`.

Design B is the required handoff when that connector is not authorized. The operator exports a sanitized snapshot and runs `whop import`. The snapshot is labeled `authenticated_operator_snapshot`, `credentials_stored: not_stored`, and `live_transport: not_claimed`. That import is not a live Clipforge MCP pass. The import row stays `whop_live: not_configured`.

A JSON field cannot set `live_status`, `provider_id`, or `evidence_origin`. Every stored discovery has `live_claim: not_claimed`.

A supplied provider is normalized into the existing `WhopCampaignSnapshot` and stored under `campaigns/whop-discoveries/<discovery_id>/` together with the snapshot import. The import row's `whop_live` field stays `not_configured`. The discovery record carries the adapter's live status. Unknown keys, forged provenance, secret-like text, absolute paths, `file:` URIs, traversal, backslashes, and HTML are rejected. Missing provider fields stay null. Clipforge does not invent a URL, an id, a duration, a license, or a content hash.

The filter is deterministic and fails closed. A request that names a fact rejects a missing fact. `selected: true` does not override that result. A declared provider hash is `declared_content_sha256`. It is not proof of local bytes. After the operator places a file, acquisition stores `acquired_file_sha256`, the file size, and an ffprobe fingerprint. Rendering stays blocked when those hashes differ or when no acquired hash exists. A page URL is not a media file.

Cache identity includes the project, operator, provider, provider version, tool name, provider mode, request fingerprint, policy fingerprint, catalogue fingerprint, response hash, source declarations, and acquisition policy. A hit does not rewrite the manifest. A changed catalogue, tool, version, operator, request, or policy is a new discovery. A stale response fails `verify`. An old discovery cannot select a newer import.

The snapshot import and the discovery files are staged, checked, and renamed together. A failure restores overwritten bytes and removes files this attempt created. It does not follow a symlink and does not leave a new import or discovery behind. `cancel` keeps the response. `resume` writes a new discovery id from that response and does not contact Whop. Selection evidence does not start acquisition or production.

The loopback board gains GET routes for capabilities, discoveries, and filter results. Operator text is assigned with `textContent`.

Contracts added at `schema_version` `1.0.0`: `WhopProviderCapability`, `WhopLiveDiscoveryRequest`, `WhopCampaignCatalogue`, `WhopFilterDecision`, `WhopDiscoveryAttempt`, and `WhopSelectionEvidence`. Existing Whop snapshot models gained optional metadata fields with defaults so an older snapshot still validates.

## Alternatives considered

- Automate the Whop sign-in page. Rejected. Clipforge would have to handle a password or a session cookie.
- Scrape campaign HTML. Rejected in Round 25, and this round does not bring it back.
- Store the MCP session id. Rejected. The reader, if a later smoke calls it, keeps that id in memory only.
- Treat a campaign row as license evidence. Rejected. Rights stay on the source record.
- Replace `WhopImportAttempt.whop_live`. Rejected. Snapshot imports would start claiming a live crawl they did not perform.

## Consequences

Operators can filter a normalized catalogue and select allowed sources without putting account secrets in the work root. `discover --live --connector authenticated` calls the loopback connector from a fresh process. `whop import` accepts a sanitized operator snapshot and does not claim live transport. Fixture results stay `test_double` and `live_claim: not_claimed`. A skipped live smoke is not a live pass. The checked-in tool map does not invent official Whop tool names. Publishing and account changes stay deferred.
