# Round 27 validation

Round 27 starts from merge `06848987ccf1090e96e8120941fc9a3b1a61eab0` on branch `round-27-whop-live-operator`. SQLite stays at schema 6. Contract `schema_version` stays `1.0.0`. No migration was added.

Whop discovery is read-only. The default is `not_configured`. A fake provider is not a live Whop pass. External publishing stays deferred. This file does not store credentials, cookies, bearer tokens, or filesystem paths.

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

Local results on this branch: ruff, format, mypy, schema check, and doctor passed. Doctor reports SQLite schema version 6. Schema export wrote 193 files. The Whop tests were run twice: 23 passed and 1 skipped each time. The skip is the opt-in live smoke. Full pytest: 552 passed, 2 skipped, 445 seconds. Renderer lint, typecheck, and 27 tests passed. Normal CI does not set `CLIPFORGE_WHOP_LIVE_SMOKE`. The skipped smoke is not a live pass. No official Whop session was opened while these checks ran.

CI uses the Round 21 workflow: `verify-python`, then `verify-renderer-browser`, on `[self-hosted, linux, x64, clipforge]`. Feature-branch pushes do not start that workflow.

## Provider capability

| Command | Flag unset | `CLIPFORGE_WHOP_LIVE_SMOKE=1` |
| --- | --- | --- |
| `whop doctor` | `whop_live: not_configured` and `live_smoke: not_executed` | `provider_unavailable` when no connector is named; `public_provider: available` when `CONNECTOR=public`, still `live_smoke: not_executed` |
| `whop discover` | `not_configured`, no sidecar, exit zero | `--live` without the switch exits non-zero with `not_configured`; `--live` without a connector exits non-zero with `provider_unavailable` |
| `whop discover --live` with `CONNECTOR=public` | not used | calls the MCP adapter and writes a discovery with `live_claim: not_claimed` |

`public_headers()` sends `Content-Type`, `Accept`, and `User-Agent`. It does not send `Authorization`. Mutating operations stay `disabled`. Credentials stay `not_stored`. Publishing stays `deferred`.

Snapshot import of the older studio fixture still cache-hits, reports `whop_live: not_configured`, and selects `src-one` because that source is `allowed`. `source_may_proceed("allowed")` remains true.

`FakeWhopProvider` normalizes `camp-city` as `public_discovery` with `evidence_origin: test_double` and `live_claim: not_claimed`. It does not open a socket. `FakeBrowserExportProvider` records `authenticated_discovery` only as a test double. A cookie key is `secret_rejected` and writes nothing. `UnavailableWhopProvider` raises `provider_unavailable` before a sidecar. `MalformedWhopProvider` is rejected for bearer text, cookie text, API-key text, password text, an absolute path, a `file:` URI, traversal, a backslash, a remote media URL in a title, and an HTML payload. A payload field named `live_status` or `provider_version` is `forged_status`.

The public adapter is exercised against a loopback MCP server. That server records `initialize`, `notifications/initialized`, `tools/list`, and `tools/call` for `list_public_campaigns` only. `create_campaign` and `list_public_campaigns_and_checkout` are not called. JSON and SSE responses both normalize. Malformed JSON-RPC, an oversized body, a timeout, and a lost session fail before a sidecar. The session id `mcp-session` is absent from the stored files. The same response in `project-1` and `project-2` produces different discovery ids and import ids. A project-1 import cannot be selected as project-2. A changed catalogue is a new discovery. A changed policy is a new discovery, and the old row fails `verify` with `stale_policy`.

Selection rejects an inactive campaign, a prohibited category, a query miss, a language miss, a stale export, an unavailable source, a format miss, an oversized source, a duration outside the bounds, missing rights, and a missing content hash. `selected: true` does not override a failed filter. A source without `content_sha256` is not given a metadata digest. Promotion failure at each stage deletes the new files. A previous manifest and snapshot stay byte-for-byte. `resume` after `cancel` does not call the provider again.

## Filter examples

The public sample `camp-city` is `included` under the default request. The same fixture produces:

| Change | Reason |
| --- | --- |
| status `paused` and `require_status=active` | `status_not_active` |
| category `gambling` | `category_prohibited` |
| allow list `education` | `category_not_allowed` |
| policy `prohibited` | `policy_blocked` |
| language `ja` | `language_mismatch` |
| query `zzzz` | `search_mismatch` |
| export older than `max_age_hours` | `stale_campaign` |
| availability `missing` | `missing_source` |
| format `mov` | `format_mismatch` |
| size above 10 bytes | `source_too_large` |
| duration below 5 seconds | `duration_out_of_range` |
| rights `unknown` | `rights_not_allowed` |
| availability `offline` | `source_unavailable` |

Selecting `src-city` writes evidence and does not ask again. A mismatched catalogue fingerprint is `stale_selection`. A mismatched source hash is `source_changed`. A missing source id is `missing_source`. A changed policy fingerprint asks for a reload. All of those stale cases use the existing reload sentence.

## Cache and recovery

The same provider payload is a cache hit and leaves the manifest bytes unchanged. A different catalogue is a new discovery id. Overwriting `response.json` and importing again raises `stale_discovery`. Restoring those bytes is a hit again. `cancel` makes `verify` return `cancelled`, and the next import allocates a new id. A promotion hook that raises `promotion_failed` deletes partial files and leaves the earlier manifest unchanged. A snapshot import may already exist because that write happens before the discovery rename.

## Board and read-only commands

`doctor`, `discover`, and `show` leave the work tree size unchanged. `select` writes one evidence file and prints an id that starts with `sel-`.

The loopback board serves:

```text
GET /api/whop/capabilities
GET /api/whop/discoveries
GET /api/whop/discoveries/<id>
GET /api/campaigns/<campaign_id>/whop
GET /api/campaigns/<campaign_id>/filter-results
```

Capabilities report `live_status: not_configured`, `mutating_operations: disabled`, and `credentials: not_stored`. The stored discovery still reports `public_discovery`. The campaign route stays `whop_live: not_configured` because that row is the snapshot import. Filter results include the selection fingerprint. The JSON body has no home-directory prefix, bearer text, or cookie assignment. `app.js` has no `innerHTML`, `eval(`, `https://`, or `autoplay`. The browser smoke looks for `whop_provider` and `not_configured`.

## Language

English alignment stays `verified_live`. Arabic and Japanese stay `alignment_not_claimed`. KittenTTS stays English-only. This round does not run a new aligner or narrator.

## Security

Rejected before a discovery sidecar: bearer text, cookie text, API-key text, password text, absolute paths, `file:` URIs, traversal, backslashes, a remote media URL in a title, and HTML. A browser-export cookie key is dropped and the stored JSON does not contain `cookie`. Stored discovery files from the tests do not contain `cookie=`, `bearer `, `password=`, or `api_key`. No authorization header is added to the public MCP headers.

## Limits

No official Whop MCP session was opened. The loopback server is a test double of the public adapter. Doctor does not connect. `discover` without `--live` does not connect. The opt-in smoke was skipped. Clipforge does not automate Whop sign-in, does not download campaign media, and does not mutate the Whop account. Snapshot rows stay `not_configured`. Publishing stays deferred. Round 28 is not started.
