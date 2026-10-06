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

The public adapter speaks MCP to an HTTPS URL, or to loopback HTTP in tests. It sends `initialize`, then `notifications/initialized`, then `tools/list`, then `tools/call` for one exact name from the discovery allowlist: `list_public_campaigns`, `search_public_campaigns`, `get_public_campaign`, `discover_public_campaigns`, or `read_public_campaigns`. A name is not chosen because it contains `list` or `read`. Tools whose name contains a mutating token (`create`, `update`, `delete`, `join`, `apply`, `submit`, `upload`, `message`, `charge`, `pay`, `purchase`, `checkout`) are rejected. Responses may be `application/json` or `text/event-stream`. The `Mcp-Session-Id` header stays on the client object. It is not written to a sidecar, a log line, or a manifest.

The authenticated adapter accepts an `AuthenticatedConnectorSession`. The operator signs in through Whop's own browser flow. Clipforge receives an opaque `CLIPFORGE_WHOP_SESSION_HANDLE` and a process-local reader. The reader returns normalized campaign metadata. The session object has no password, cookie, or bearer field. A fixture reader is stored as `evidence_origin: test_double`. Only `AuthenticatedConnectorSession` may be stored as `authenticated_connector`. A JSON field cannot set `live_status`, `provider_id`, or `evidence_origin`. Every stored discovery has `live_claim: not_claimed`.

A supplied provider is normalized into the existing `WhopCampaignSnapshot` and stored under `campaigns/whop-discoveries/<discovery_id>/` together with the snapshot import. The import row's `whop_live` field stays `not_configured`. The discovery record carries the adapter's live status. Unknown keys, forged provenance, secret-like text, absolute paths, `file:` URIs, traversal, backslashes, and HTML are rejected. Missing provider fields stay null. Clipforge does not invent a URL, an id, a duration, a license, or a content hash.

The filter is deterministic. Selection reloads the stored request and applies it again. A source needs `content_sha256` before it can be selected. A metadata digest is not a media hash. A source excluded by status, category, query, language, policy, rights, availability, size, duration, format, or age cannot be selected because `selected` is true. Cache identity includes the project, provider, provider version, filter fingerprint, policy fingerprint, catalogue fingerprint, and response hash. A hit does not rewrite the manifest. A changed catalogue or policy is a new discovery. Verification of the old row fails when the policy fingerprint no longer matches.

The snapshot import and the discovery files are staged, checked, and renamed together. A failure deletes every file this attempt created and leaves the previous import and discovery byte-for-byte. `cancel` keeps the response. `resume` writes a new discovery id from that response and does not contact Whop. Selection evidence does not start acquisition or production.

The loopback board gains GET routes for capabilities, discoveries, and filter results. Operator text is assigned with `textContent`.

Contracts added at `schema_version` `1.0.0`: `WhopProviderCapability`, `WhopLiveDiscoveryRequest`, `WhopCampaignCatalogue`, `WhopFilterDecision`, `WhopDiscoveryAttempt`, and `WhopSelectionEvidence`. Existing Whop snapshot models gained optional metadata fields with defaults so an older snapshot still validates.

## Alternatives considered

- Automate the Whop sign-in page. Rejected. Clipforge would have to handle a password or a session cookie.
- Scrape campaign HTML. Rejected in Round 25, and this round does not bring it back.
- Store the MCP session id. Rejected. The reader, if a later smoke calls it, keeps that id in memory only.
- Treat a campaign row as license evidence. Rejected. Rights stay on the source record.
- Replace `WhopImportAttempt.whop_live`. Rejected. Snapshot imports would start claiming a live crawl they did not perform.

## Consequences

Operators can filter a normalized catalogue and select allowed sources without putting account secrets in the work root. `discover --live` can call the public MCP adapter or an already authenticated connector. Fixture results stay `test_double` and `live_claim: not_claimed`. A skipped live smoke is not a live pass. Publishing and account changes stay deferred.
