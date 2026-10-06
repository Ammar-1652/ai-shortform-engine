# ADR 0062: Live Whop operator discovery

- Status: Accepted
- Date: 2026-10-06

## Context

Round 25 can import a local Whop snapshot. It cannot inspect a live catalogue, filter it, or bind a selection to that import. Whop's official MCP server signs the operator in through a browser. Clipforge must not collect the username, password, API key, OAuth token, bearer token, cookie, browser profile, or authorization header.

This round is read-only toward Whop. Joining a campaign, applying, submitting content, uploading media, creating products or ads, sending messages, changing settings, and spending money need a later explicit confirmation. External publishing stays deferred.

SQLite is schema 6. The new records are sidecars. A second table would not make the credential checks stronger.

## Decision

Whop discovery has four modes: `snapshot`, `browser_export`, `live_connector`, and `not_configured`. The default is `not_configured`. Four results stay distinct: `public_discovery`, `authenticated_discovery`, `not_configured`, and `provider_unavailable`.

`clipforge campaign operator whop doctor`, `capabilities`, and `discover` do not open a socket and do not write a sidecar. `CLIPFORGE_WHOP_LIVE_SMOKE=1` changes the doctor line to `provider_unavailable` and prints `session: not opened`. A connector name in `CLIPFORGE_WHOP_CONNECTOR` still does not open a session from doctor or discover. `CLIPFORGE_WHOP_URL` is read only by the unused HTTPS reader. Secrets are not command arguments.

A supplied provider is normalized into the existing `WhopCampaignSnapshot` and stored as an append-only discovery under `campaigns/whop-discoveries/<discovery_id>/`. The snapshot import under `campaigns/whop/<import_id>/` stays compatible, and its `whop_live` field stays `not_configured`. The discovery attempt carries the live status. Unknown keys, secret-like text, absolute paths, `file:` URIs, traversal, backslashes, and HTML are rejected. Missing provider fields stay null and are listed. Clipforge does not invent a URL, an id, a duration, a license, or a source hash.

The filter is deterministic. It can require an active status, an allowed category, a prohibited category, policy, language, source availability, rights, size, duration, format, freshness, and search text. The default request prohibits the category `gambling` and requires policy and rights `allowed`. An explicit request replaces that list. Campaign membership is not rights evidence. Unknown, prohibited, missing, or stale rights cannot be selected. A source marked `allowed` is selected by writing `WhopSelectionEvidence` and does not ask for a second confirmation. A stale import, catalogue, policy, source hash, or rights state uses the existing reload sentence: "The campaign selection changed while this page was open; reload before saving."

Cache identity is the provider, provider version, normalized filter, policy fingerprint, catalogue fingerprint, and response hash. A hit re-reads the stored response and does not rewrite it. A changed response is a new id. A tampered response file with the same identity is `stale_discovery`. A cancelled discovery is not a hit. A failed promotion deletes partials and restores the previous discovery files. Selection evidence lives under `campaigns/whop-selections/<evidence_id>/` and does not start acquisition or production.

The loopback board gains GET routes for capabilities, discoveries, and filter results. Operator text is assigned with `textContent`.

Contracts added at `schema_version` `1.0.0`: `WhopProviderCapability`, `WhopLiveDiscoveryRequest`, `WhopCampaignCatalogue`, `WhopFilterDecision`, `WhopDiscoveryAttempt`, and `WhopSelectionEvidence`. Existing Whop snapshot models gained optional metadata fields with defaults so an older snapshot still validates.

## Alternatives considered

- Automate the Whop sign-in page. Rejected. Clipforge would have to handle a password or a session cookie.
- Scrape campaign HTML. Rejected in Round 25, and this round does not bring it back.
- Store the MCP session id. Rejected. The reader, if a later smoke calls it, keeps that id in memory only.
- Treat a campaign row as license evidence. Rejected. Rights stay on the source record.
- Replace `WhopImportAttempt.whop_live`. Rejected. Snapshot imports would start claiming a live crawl they did not perform.

## Consequences

Operators can filter a normalized catalogue and select allowed sources without putting account secrets in the work root. A fake provider can exercise `public_discovery` and `authenticated_discovery` in tests. Those results are not a live Whop pass. Doctor and the discover command still do not open a session. Publishing and account changes stay deferred.
