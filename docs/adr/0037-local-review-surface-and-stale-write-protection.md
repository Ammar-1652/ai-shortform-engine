# ADR 0037: Local review surface and stale-write protection

- Status: Accepted
- Date: 2026-10-03

## Context

The review page has to play the current preview and save a decision. The preview set can be replaced while the page is open. The server must not be reachable off the machine, and it must not expose the work root.

## Decision

`clipforge review open` binds only to `127.0.0.1`. Other hosts are refused before the socket is created. The page, script, and stylesheet are package files. They do not load a CDN, a font host, or remote script.

`GET /api/review` returns sanitized JSON: ids, microseconds, codecs, heuristic scores, the relative preview URL, the effective decision, and history. It does not return filesystem paths.

`GET /media/candidate/<candidate_id>` resolves that id through the current manifest, rejects traversal and symlinks, and serves only `preview.mp4` inside the work root.

`POST /api/review/decisions` and `clipforge review decide` call the same writer. The body must name the source, project, artifact, preview set, manifest SHA, and candidate that the client observed. Unknown keys are rejected. `automated: true` is rejected. If the current preview set no longer matches that context, the write fails with:

```text
the preview set changed while this review page was open; reload before saving
```

`review doctor`, `review list`, `review verify`, and the GET routes do not create directories, locks, jobs, artifacts, or review rows.

## Alternatives considered

- Bind to all interfaces so a phone on the LAN can review. Rejected. The previews and transcript text stay on this machine.
- Trust the page and skip the context check. Rejected. A replaced manifest would receive a decision for a file the person did not watch.

## Consequences

A review server is a local process. Stopping it does not change the preview artifact. No network service is required to record a decision.
