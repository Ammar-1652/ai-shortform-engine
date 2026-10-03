# Candidate review surface

Round 7 lets a person watch the current rough-preview set and record a decision for each candidate. The preview files stay immutable. Nothing is published, and no Hero edit is created.

## What opens

`clipforge review open SOURCE_ID` loads the current `rough_preview_set_json` artifact and runs the same integrity checks as `preview verify`, including ffprobe of every MP4. A missing, stale, cross-project, or technically invalid set does not open.

The page lists every selected candidate in rank order. Zero candidates shows:

```text
No candidates were selected in the current candidate set.
```

Scores are labeled heuristic. They do not hide a candidate or block a decision.

## Decisions

A decision is an append-only `ReviewDecision`:

- `subject_kind` is `candidate`
- `candidate_id` is the candidate that was watched
- `artifact_id` is the current rough-preview artifact
- `decision` is `approved`, `rejected`, or `changes_requested`
- `automated` is false
- `reviewer_id` is a human id
- `notes` are optional text, at most 4000 characters

`approved` means the person may want Hero work later. It does not create an edit plan, change the candidate, or publish.

The effective decision is the newest row for that candidate and the current artifact, ordered by creation time and then review id. Decisions for an older preview artifact stay in the history and do not apply to a new preview set. Each successful preview render inserts a new artifact id so that binding stays distinct.

A save sends the source, project, artifact, preview set, manifest SHA, and candidate the page loaded. If any of those changed, the write is rejected and the page must be reloaded. The previous decision row is not edited.

## Server

The server binds to `127.0.0.1` only. Static files are the HTML, CSS, and script in the package. Preview bytes are served only as `GET /media/candidate/<candidate_id>` for an id in the current manifest. The response is `preview.mp4`. Symlinks and paths outside the work root are refused.

There is no upload, no source-media route, no CDN, and no call to an AI service.
