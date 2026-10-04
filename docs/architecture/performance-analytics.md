# Performance analytics

Round 13 records what a person observed about an artifact that Clipforge already produced. It does not publish, approve, rank a clip as viral, or change the edit.

## What is stored

SQLite schema version 5 adds three tables to the existing database:

- `performance_outcomes` — one immutable measurement
- `editorial_feature_snapshots` — facts copied from that artifact at that observed time
- `analytics_imports` — the SHA-256 and outcome ids for one accepted local file

The import row does not store the file path. Outcome and snapshot JSON do not store absolute paths, home directories, shell commands, tokens, or viewer identifiers.

An outcome id and an idempotency key are unique. The same key with the same body is a replay and writes nothing. The same key with a different body is rejected. A correction uses a new id, a new key, and a later `observed_at`.

## Binding

Before an insert, Clipforge checks:

- the artifact row exists
- project, source, and kind match
- the producing job succeeded
- a supplied candidate id is in the artifact JSON
- a supplied candidate media hash matches that candidate
- duration matches the canonical time map when the artifact has one
- a review id, when supplied, is the original review row and is not modified
- QA evidence matches the selected policy

`not_required` is refused for an advanced Hero artifact. `current` requires the current QA set, a readable QA document, and a binding to this artifact. `historical` can keep a QA row whose file is gone and reports `unavailable`. A failed QA status is stored as fail. It is not upgraded.

If the artifact file is missing, the outcome can still be recorded with the supplied hash and `media_available: false`. Verification later reports `media_evidence: unavailable`. A file that exists with a different hash is rejected.

## Metrics

Every metric is optional: views, unique viewers, watch time, completion count and rate, likes, comments, shares, saves, follows, clicks, paid views, and USD revenue. Relationships are checked when both sides are present. Comparison totals and rates use only the observations that reported the metric, and they show that count as the denominator. Missing values are not filled with zero.

Manual labels are `unknown` until a person sets them. Topic tags are normalized, unique, and sorted.

## Comparison

`clipforge analytics compare PROJECT_ID --by DIMENSION` is read-only. Dimensions include platform, campaign, geography, profile, source, measurement window, duration bucket, hook, topic, CTA, caption presence, B-roll, SFX, typography, diagrams, reframing, motion-library version, and rank band. Cohort keys are sorted. A filter that matches nothing returns `insufficient_evidence`. A cohort with fewer than five observations is marked small. The note says the evidence is descriptive only.

## Commands

```text
clipforge analytics doctor
clipforge analytics record --input FILE
clipforge analytics import FILE
clipforge analytics list PROJECT_ID
clipforge analytics show OUTCOME_ID
clipforge analytics verify OUTCOME_ID
clipforge analytics compare PROJECT_ID
```

`record` and `import` read a local file inside the work root. Symlinks, `..`, backslashes, and paths outside that root are rejected. URLs are not fetched. `list`, `show`, `verify`, `compare`, and `doctor` do not write.

Filters on list and compare include `--platform`, `--campaign-id`, `--geography`, `--profile-id`, `--from`, and `--to`. Compare also accepts `--by` and `--format text|json`.

## Non-goals

No platform API, analytics SDK, upload, viewer profile, IP address, revenue collection service, or second database. No automatic republish, approval, clip selection, or campaign optimization. Human review remains the approval record. `qa gate` remains the prerequisite for any later publishing work.
