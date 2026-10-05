# ADR 0058: Source acquisition and policy-bound intake

- Status: Accepted
- Date: 2026-10-06

## Context

Round 22 lets an operator select catalogue sources and run the existing campaign production runner. The file that reaches that runner still needs a checked copy inside the work root: hash, size, media facts, rights, and confinement. A second confirmation for a source the campaign already marks `allowed` would only add a stall.

Envato search was sending generic filter keys to `search_stock_video`. The server rejects keys its schema does not list. Whop still has no approved live connector.

SQLite remains schema 6. The production run sidecar already records pipeline evidence. Acquisition does not need a new table.

## Decision

Acquisition is a versioned sidecar, `CampaignAcquisitionAttempt`, schema version `1.0.0`, under `campaigns/acquisitions/<acquisition_id>/`. Each selected source has a `CampaignAcquisitionRequest` and a `CampaignAcquisitionResult`. The promoted file, checksum, and manifest use paths relative to the work root. Absolute paths, `file:` URIs, and secret-like tokens are rejected.

`plan`, `list`, `show`, and `verify` do not write. `run` acquires only sources in the current ready selection. An unchanged verified attempt is returned without another copy or job. `--force` writes a new attempt and leaves the previous directory in place. A source whose bytes no longer match the selection is a miss and is not promoted. Staging files are removed on the next run or resume. `resume` retries sources that are not still a verified success. One failure does not delete a sibling's promoted file.

An `allowed` `CampaignSource` is acquired without another confirmation. Unknown, prohibited, and `rights_unverified` rights fail closed. Symlinks, traversal, backslash paths, remote URLs, and files outside the work root fail closed. ffprobe and a decode pass must succeed before `os.replace` promotes the staged file. The result records a `campaign_acquisition` job.

`clipforge campaign operator run` calls `run_campaign` after the source is either still bound to that hash or has a verified acquisition. It writes `campaigns/runs/<run_id>/operator.json` with the selection, policy fingerprint, acquisition ids, and per-source status. It does not reimplement ingest, review, Hero, QA, narration, or delivery.

Envato search uses an explicit field map plus the tool schema. Unsupported generic filters are kept for local post-filtering and are not sent. `perPage` is capped. Missing provider fields stay null. Direct download URLs are not invented. `FakeEnvatoMcpProvider` covers tests. Live MCP remains behind `CLIPFORGE_ENVATO_MCP_ENABLED` and `CLIPFORGE_ENVATO_MCP_LIVE_SMOKE`.

Whop live import calls `WhopSnapshotConnector`. The built-in connector returns no bytes and the command reports `not_configured`. Local JSON and JSONL snapshots stay on the Round 22 import contract.

## Alternatives considered

- Require a second operator confirmation after `allowed`. Rejected. The campaign rights state is the authorization.
- Add an acquisitions table. Rejected. The sidecar, checksum, and job row already bind the hash.
- Send every generic filter and let the Envato server reject the call. Rejected. The tool schema is the capability boundary.
- Read a source file that lives outside the work root during acquisition. Rejected. Referenced ingest can point outside; the acquired copy must be contained.

## Consequences

Operators can inspect, acquire, verify, and resume selected sources from the CLI and the loopback board. A succeeded acquisition is hash-bound and probe-bound. The production runner remains the only path that builds a campaign delivery. Publishing stays deferred.
