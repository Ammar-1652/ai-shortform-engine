# ADR 0052: Envato MCP discovery

- Status: Accepted
- Date: 2026-10-05

## Context

Stock search has to use the official Envato MCP endpoint, `https://mcp.envato.com/mcp`. The server returns structured search, filters, metadata, and item-page links. It does not download the asset. HTML scraping and invented REST paths would both be false clients.

## Decision

`EnvatoMcpDiscoveryProvider` speaks JSON-RPC `initialize`, `tools/list`, and `tools/call`. It is off unless `CLIPFORGE_ENVATO_MCP_ENABLED=1`. A live call also requires `CLIPFORGE_ENVATO_MCP_LIVE_SMOKE=1`. Authentication stays with the MCP host. Clipforge does not store tokens.

Search rows copy only fields the provider sent. Missing item ids, URLs, durations, formats, and licenses stay null. `direct_download_url` stays null unless the server sent an https URL, and `download_status` stays `manual_download_required` or `rejected`. The request files are `asset_download_requests.json` and `asset_download_requests.md`.

For the Antoine campaign every external stock row is `blocked` with `outside_media_prohibited_by_campaign_policy`. Those rows cannot be acquired into a render. A later campaign can bind a local file with `assets acquire`, a license statement, and a hash check.

## Consequences

- Fake and dry-run providers do not open sockets and do not invent catalog URLs.
- A failed or disabled connection is `provider_unavailable` or `not_configured`, not a live pass.

## Non-goals

No Envato HTML scraper, no automatic download, and no use of stock inside the Antoine render.
