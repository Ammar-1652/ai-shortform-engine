# Hero review and approval

Round 9 reviews the current Hero draft. The decision is evidence. It does not publish, replace the source, or render another Hero file.

Candidate review stays on `clipforge review`. A broken Hero set does not stop that page from opening. The Hero page is separate.

## Routes

`clipforge hero review open SOURCE_ID` binds to `127.0.0.1` only. `0.0.0.0` and every other host are refused before a socket exists.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/` | Hero review page |
| GET | `/hero.js` and `/styles.css` | Package files. No remote URL. |
| GET | `/api/hero-review` | Current board, or an empty board when no Hero draft is stored |
| GET | `/api/hero-review/hero/<candidate_id>` | One draft. The id is the candidate id in the current manifest. |
| GET | `/media/hero/<candidate_id>` | The current `hero.mp4` only |
| POST | `/api/review/decisions` | Append one decision. Same route as candidate review. |

There is no upload route, remote media URL, CDN, analytics endpoint, or publishing endpoint.

The player is a native `video` element with controls and no autoplay. CSS keeps the 1080×1920 frame at 9:16. Drafts are shown in manifest rank order. Scores do not reorder or hide them.

## Integrity

Opening the page and `hero review doctor` or `verify` run the current-set checks. A failure names a category and does not bind the server:

- `artifact_kind`
- `artifact_binding`
- `hero_set_binding`
- `manifest_hash`
- `missing_manifest`
- `corrupt_manifest`
- `candidate_set_binding`
- `render_input`
- `missing_mp4`
- `corrupt_mp4`
- `ffprobe`
- `alignment_binding`
- `plan_binding`
- `path_confinement`
- `symlink`
- `preview`

The checks cover artifact kind, source and project, the database-selected Hero set, manifest hash, candidate set, render input, MP4 hash and size, ffprobe, profile dimensions, frame rate, codecs, pixel format, duration, alignment and plan binding, TimeMap, work-root containment, and symlinks. A previous run is not current. A partial render is not promoted.

## Decision

The body repeats `source_asset_id`, `source_sha256`, `project_id`, `candidate_id`, `artifact_id`, `hero_set_id`, `preview_set_id` (the same Hero set id), `manifest_sha256`, `plan_id`, `plan_sha256`, `alignment_id`, and `alignment_sha256`. Unknown keys are rejected. `automated: true` is rejected. Reviewer id must be non-blank. Notes are text up to 4000 characters. Identifiers and SHA-256 values must match the stored shapes.

Each save inserts a row. Nothing updates or deletes an older row. The effective decision is the newest row for the current Hero artifact and candidate, ordered by `created_at` and then `review_id`. Older artifacts remain in the history list and are marked as older.

The page copies aligned words exactly, including Unicode, currency, punctuation, and quotes. Notes and words are assigned with `textContent`. The manifest has no alignment checkpoint SHA, alignment language, or audio sample rate. Those lines say `unavailable`.

## Commands

```text
clipforge hero review doctor SOURCE_ID
clipforge hero review open SOURCE_ID
clipforge hero review list SOURCE_ID
clipforge hero review show SOURCE_ID CANDIDATE_ID
clipforge hero review decide SOURCE_ID CANDIDATE_ID
clipforge hero review verify SOURCE_ID
```

`doctor`, `list`, `show`, and `verify` only read. `decide` appends one row and does not encode a new file.

## Not in this round

Publishing, dynamic reframing, face or speaker inference, B-roll, music, sound effects, multilingual alignment, multi-TimeMap alignment, and rendering again because a reviewer approved.
