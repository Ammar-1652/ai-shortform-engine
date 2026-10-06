# ADR 0063: Official Grok connector onboarding

- Status: Accepted
- Date: 2026-10-06

## Context

ADR 0062 keeps Whop discovery read-only and leaves official tool names empty until a real `tools/list`. The first auth helper prepared a dedicated browser profile and stopped at `grok mcp doctor whop`. On this machine that command reports that the Whop server is not configured, so login returned `connector_unavailable` before installing the plugin or starting Whop's browser authorization.

The official setup is the Whop Grok plugin and the Grok commands `/mcps` and `/whop-connect`. `grok mcp doctor whop` is a diagnostic. It is not the authorization flow. This Grok build exposes `plugin` and `mcp` command groups. It does not expose `/mcps` or `/whop-connect` as subcommands. Those commands belong to the Grok interface.

Clipforge still must not read browser cookies, store a password or token, send `Authorization` to `https://mcp.whop.com/mcp`, or treat a loopback fixture as a live account.

## Decision

`clipforge campaign operator whop auth doctor` and `auth status` are read-only. They may run `grok plugin list` and `grok mcp list`. They do not open Chrome, do not open a socket, and do not run `grok mcp doctor whop`.

`auth login` is the command that may install the plugin and start an interactive flow:

1. Require a Grok executable.
2. Install `whopio/plugins#dist/grok/whop` with `grok plugin install --trust` when `grok plugin list` does not show `whop`.
3. If this Grok build lists `mcps` or `whop-connect` as a command, run those commands and wait.
4. Run `grok mcp doctor whop` only after that attempt.
5. When the doctor reports a usable connector, post `initialize` to `https://mcp.whop.com/mcp` with no `Authorization` header.
6. Return success only when that check passes.

If the installed Grok cannot start `/mcps`, login prints this and exits non-zero:

```text
Whop authorization is required in Grok.
Open Grok, run /mcps, select Whop, authorize it, then run /whop-connect.
After that, rerun:
clipforge campaign operator whop auth status
```

That result is `auth_required`. It is not success and it is not `connector_unavailable`.

`auth refresh` reuses the same profile, runs the doctor, and repeats login when the connector is expired. `auth logout` requires confirmation and removes only the dedicated profile, the local auth metadata, and the operator tool map.

After doctor reports the connector ready, `whop tools refresh` posts `initialize`, `notifications/initialized`, and `tools/list`. It stores a verified map at `~/.config/clipforge/whop/tool-map.json` (override `CLIPFORGE_WHOP_STATE_DIR`). The file is owner-only and is rejected when it is a symlink. The map records the official endpoint, server name, provider version, protocol version, exact tool name, schema hash, verification time, and a read-only pass. It does not store credentials or an MCP session id.

A tool is kept only when its annotation says read-only, its declared output is a campaign catalogue, and every input is one of `query`, `language`, `status`, `category`, `platform`, or `media_format`. A name that merely contains `list`, `search`, or `campaign` is not enough. Mutating, secret, upload, and checkout inputs are dropped. If none remain, the result is `unsupported_tool` and no discovery sidecar is written.

`CLIPFORGE_WHOP_CONNECTOR=official-grok` uses that map and the official endpoint. `authenticated` stays the loopback test double. `live_claim` becomes `claimed` only after `OfficialGrokProvider` completes `initialize`, `tools/list`, and one read-only `tools/call` against `https://mcp.whop.com/mcp` with the default opener. A loopback opener, a fixture, or a local JSON file cannot set that claim. The packaged map at `src/clipforge/campaign/data/whop-tool-map.json` stays empty.

## Alternatives considered

- Call `grok mcp add` with the Whop URL. Rejected. That registers an HTTP server without the official OAuth plugin flow.
- Open Chrome to an invented Whop URL. Rejected. Clipforge does not know an authorization URL and must not collect the password.
- Replay Chrome cookies to the MCP endpoint. Rejected in ADR 0062.
- Trust a tool because its name contains `campaign`. Rejected. Selection uses the read-only annotation and the output schema.

## Consequences

The operator still completes `/mcps` and `/whop-connect` once in Grok. After that, refresh and tools refresh reuse the connector. Until doctor reports ready and a real read-only `tools/call` succeeds, discovery stays `unsupported_tool` or `auth_required`, `live_claim` stays `not_claimed`, and this round does not report a live Whop pass. Publishing and mutating Whop operations stay off.
