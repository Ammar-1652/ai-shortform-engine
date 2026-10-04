# Analytics operations

Round 14 adds manual labels, local export normalization, and a loopback review page on top of the Round 13 outcome store. The records stay descriptive. They do not publish, approve, rank, or change an edit plan.

## Label history

`editorial_label_sets` is append-only. Saving inserts a row. The previous rows remain available in history. The effective set is the newest valid row for that artifact, ordered by `created_at` and then `label_set_id`.

A label names the same project, source, and artifact. When it also names an outcome or snapshot, those ids must match that lineage. Unknown values stay the explicit label `unknown`. Notes are limited to 500 characters. Markup, URLs, filesystem paths, secrets, control characters, and viewer identifiers are rejected.

The page sends `expected_label_set_id` and `expected_artifact_sha256`. If the history or the artifact bytes changed while the page was open, the save fails and tells the operator to reload. The outcome row and the feature snapshot are not modified.

## Local import profiles

Profiles are JSON files in `configs/analytics-imports/`.

| Profile | Kind | Files | Unknown columns |
| --- | --- | --- | --- |
| `clipforge-observation-v1` | native | JSON, JSONL | rejected by the observation contract |
| `generic-metrics-v1` | tabular | JSON, JSONL, CSV | rejected |
| `generic-metrics-ignore-v1` | tabular | JSON, JSONL, CSV | ignored |

A tabular row can carry platform, post id, observed time, publication time, measurement window, geography, campaign, views, unique viewers, watch time, average watch time, completion count and rate, likes, comments, shares, saves, follows, clicks, paid views, and revenue with currency. Empty metric cells stay missing. They are not stored as zero. Watch time is seconds and must convert to whole microseconds. Dates must include a timezone. Currency must be USD when revenue is present. Spreadsheet formulas are rejected.

When the file does not supply an outcome id and an idempotency key, both are derived from the profile, the binding, the times, and the metrics. The same file therefore replays. A changed metric is a new outcome.

The import row stores the content hash, the profile id, the normalized row count, the outcome ids, and a validation summary. It does not store the original path.

## Comparison

Filters and dimensions include platform, campaign, geography, profile, source, date range, measurement window, duration bucket, hook, topic, CTA, format, audience, captions, B-roll, SFX, typography, diagrams, reframing, motion library, and rank band. Effective manual labels are applied in memory before the filter. The stored outcome is not rewritten.

Output is ordered and descriptive. Coverage and denominators count only metrics that were present. A filter with no rows is `insufficient_evidence`. Provenance lists every source asset represented by the selected rows. The text does not claim a cause or an optimization.

## Page

`clipforge analytics dashboard PROJECT_ID` binds to `127.0.0.1`. `0.0.0.0` and every other host are refused before the listener opens. Routes are the page, `app.js`, `styles.css`, and the analytics JSON routes for overview, outcomes, comparison, and labels. The only write is `POST /api/analytics/labels`.

The page shows the outcome id, platform, observation window, artifact and source ids, artifact availability, duration, metrics, metric coverage, QA status, review history, effective labels, label history, comparison filters, cohort sample counts, denominators, missing counts, provenance, and the import profile. An absent metric is `not reported`. Warnings say when media is unavailable or the label cache is stale.

Static files come from the package. Traversal and symlinks are rejected. Unknown JSON keys and automated approval fields are rejected. The bundle has no `eval`, `innerHTML`, CDN, font host, or remote request.

## Cache

`current.json` is the latest label document. `cache.json` records the project, source, outcome, artifact hash, snapshot, label-set id, history hash, and import profile. A missing, corrupt, stale, or symlinked file is a miss. Rebuilds publish through a partial file and a database transaction that commits only after the sidecar is in place. A failure restores the previous current file, or leaves none on the first run. Verification does not create jobs or write rows.

## Commands

```text
clipforge analytics doctor
clipforge analytics import-profile list
clipforge analytics import-profile show PROFILE_ID
clipforge analytics import FILE --profile PROFILE_ID
clipforge analytics import validate FILE --profile PROFILE_ID
clipforge analytics import list PROJECT_ID
clipforge analytics import show IMPORT_ID
clipforge analytics import verify IMPORT_ID
clipforge analytics labels list PROJECT_ID
clipforge analytics labels show ARTIFACT_ID
clipforge analytics labels set PROJECT_ID ARTIFACT_ID --reviewer-id ID
clipforge analytics labels history ARTIFACT_ID
clipforge analytics labels verify PROJECT_ID
clipforge analytics dashboard PROJECT_ID
clipforge analytics dashboard verify PROJECT_ID
clipforge analytics compare PROJECT_ID --by hook_type --hook-type question
```

`list`, `show`, `history`, `verify`, `compare`, `doctor`, and dashboard verification only read. `labels set` and `import` append. A second label save must pass `--expected-label-set-id` from `labels show`. Failures exit non-zero.

## Non-goals

No platform API client, OAuth, SDK, upload route, viewer tracking, automatic approval, automatic ranking, or autonomous optimization. The page does not modify an EditPlan.
