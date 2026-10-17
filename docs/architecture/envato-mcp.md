# Envato MCP

The client talks to `https://mcp.envato.com/mcp`. It does not scrape HTML and it does not invent a download API.

```text
CLIPFORGE_ENVATO_MCP_ENABLED=0
CLIPFORGE_ENVATO_MCP_URL=https://mcp.envato.com/mcp
CLIPFORGE_ENVATO_MCP_LIVE_SMOKE=0
```

`clipforge assets doctor` reports the endpoint, the enabled flag, the connection state, advertised tools, and that authentication is delegated. It does not print secrets.

`clipforge assets envato search` accepts a query plus campaign context and filter options. The adapter reads the live tool schema before calling Envato: asset type selects the typed search tool; supported values such as orientation, resolution, category, genre, and numeric duration bounds are translated to Envato's native names and enums. Unsupported constraints such as video format, compatible software, style, or ambiguous `--duration short` fail with `unsupported_filter` instead of being sent as invalid keys. `--min-duration` and `--max-duration` use seconds. Missing provider fields stay null.

`clipforge assets envato request` writes `asset_download_requests.json` and `asset_download_requests.md`, and persists one typed request sidecar per result. A request records the MCP item URL, requested media kind, supported/deferred filters, campaign policy fingerprint, and provider version. Search result rows that omit a type inherit the explicit requested kind, so `search_sound_effects` remains audio and `search_fonts` remains font instead of becoming an unusable `unknown` request.

For an authorized campaign, the existing MyToolsPlan bridge can complete the
download without exposing a signed URL:

```text
clipforge assets envato auth setup       # interactive; stores only in OS keyring
clipforge assets envato auth status
clipforge assets envato fetch --request REQUEST_ID --project PROJECT_ID \
  --license-name PROJECT_NAME --tag PURPOSE --work-dir var/work
clipforge assets envato verify ASSET_ID --work-dir var/work
```

`fetch` authenticates the saved keyring credential, resolves the MCP item page
to the bridge's item UUID/type, downloads the media archive and a project
license certificate, extracts only an allowlisted member, probes it, hashes
both files, and persists an `EnvatoAssetRegistration` plus an
`AssetLicenseRecord`. Audio accepts the bridge's `music` or `sound-effects`
type aliases. Fonts accept `fonts`/`font`, and are validated with `fc-scan`;
they must be a single `.ttf`, `.otf`, `.woff`, or `.woff2` member. A missing
credential, policy block, type mismatch, unsafe archive, stale request,
missing license, failed probe, or changed hash fails closed. Credentials,
session cookies, signed URLs, and absolute paths never enter artifacts or
logs.

For Antoine Sallis the decision is `blocked` and the reason is `outside_media_prohibited_by_campaign_policy`. A future campaign can run `clipforge assets acquire REQUEST_FILE --source LOCAL_PATH --license TEXT` after the operator has the file. The command checks the hash, rejects symlinks and paths outside the work root, and refuses remote URLs.

Live search runs only when both Envato flags are `1`.
