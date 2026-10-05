# ADR 0060: Whop and Envato provider boundaries

- Status: Accepted
- Date: 2026-10-06

## Context

Campaign intake and stock acquisition still stop at the operator's machine. Whop has no approved live connector. Envato search can see an item page, and it cannot download the file. Publishing to TikTok, Instagram, YouTube, or Whop is still out of scope.

SQLite is schema 6. The new records are sidecars. A second table would not make the credential or confinement checks stronger.

## Decision

Whop intake is an operator-exported `WhopCampaignSnapshot`. `WhopImportAttempt` is append-only under `campaigns/whop/<import_id>/`. Identical canonical bytes reuse the import id. A changed snapshot gets a new id. Invalid JSON, secrets, absolute paths, `file:` URIs, and unknown keys are rejected before a sidecar is written. The built-in connector returns no bytes, so `whop_live` stays `not_configured`. Snapshot metadata is not an `AssetLicenseRecord`. A source marked allowed can be selected without a second confirmation. Unknown or prohibited policy blocks that source. A stale snapshot or a stale policy fingerprint fails closed.

Envato search keeps the official MCP adapter. The call sends only filters the selected tool schema lists, caps `perPage` at 5, and stores the rest as `deferred_filters`. Missing provider fields stay null. An item-page URL is not a local file. A direct download URL is stored only when the provider returned one, and Clipforge does not fetch it. The download status stays `manual_download_required`.

The operator places the file under `incoming/`. `register` rejects symlinks, traversal, backslashes, absolute paths, remote URLs, and files outside the work root. It enforces the byte cap, hashes the file, runs ffprobe and a decode, checks codec, dimensions, duration, and frame rate, and requires license evidence with rights `allowed`. Promotion is atomic. A failed replacement restores the previous file. A verified asset can enter Advanced Hero planning only while the registration, hash, confinement, rights, license, producer job, campaign, project, and policy fingerprint still match. Any other state blocks the plan before a render job is inserted. Campaigns that do not request an Envato asset never take that branch.

The loopback board gains read-only routes for the Whop import and the Envato asset. Responses use relative paths. `doctor`, `list`, `show`, and `verify` do not write.

Live checks stay behind `CLIPFORGE_WHOP_LIVE_SMOKE=1` and `CLIPFORGE_ENVATO_MCP_LIVE_SMOKE=1`. Normal CI does not need credentials or a network.

## Alternatives considered

- Scrape an authenticated Whop session on the server. Rejected. Cookies and account secrets would have to be stored.
- Download Envato bytes from an item-page URL. Rejected. That URL is a catalogue page, not a licensed file.
- Make every campaign require an Envato asset. Rejected. Antoine policy blocks outside media, and campaigns that do not ask for stock must keep planning.

## Consequences

Operators can import a Whop export and register a manually downloaded Envato file without putting credentials in the repository. Advanced Hero will not render a stale or uncleared Envato asset. External publishing is still deferred.
