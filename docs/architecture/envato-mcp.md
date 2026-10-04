# Envato MCP

The client talks to `https://mcp.envato.com/mcp`. It does not scrape HTML and it does not invent a download API.

```text
CLIPFORGE_ENVATO_MCP_ENABLED=0
CLIPFORGE_ENVATO_MCP_URL=https://mcp.envato.com/mcp
CLIPFORGE_ENVATO_MCP_LIVE_SMOKE=0
```

`clipforge assets doctor` reports the endpoint, the enabled flag, the connection state, advertised tools, and that authentication is delegated. It does not print secrets.

`clipforge assets envato search` accepts a query plus category, asset type, format, software, genre, style, duration, orientation, resolution, intended use, and campaign id. Missing provider fields stay null.

`clipforge assets envato request` writes `asset_download_requests.json` and `asset_download_requests.md`. Those files tell a person which item page to open. `download_status` is `manual_download_required` unless campaign policy rejects the row.

For Antoine Sallis the decision is `blocked` and the reason is `outside_media_prohibited_by_campaign_policy`. A future campaign can run `clipforge assets acquire REQUEST_FILE --source LOCAL_PATH --license TEXT` after the operator has the file. The command checks the hash, rejects symlinks and paths outside the work root, and refuses remote URLs.

Live search runs only when both Envato flags are `1`.
