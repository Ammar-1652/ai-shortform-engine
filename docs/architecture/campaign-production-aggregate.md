# Aggregate campaign production

`produce` turns a ready selection into one operator manifest by calling the existing campaign runner. See [ADR 0059](../adr/0059-aggregate-campaign-production.md).

SQLite schema version stays 6. Contract `schema_version` stays `1.0.0`.

## State machine

```text
production-plan -> produce -> succeeded
                           -> partial
                           -> failed
                           -> blocked
partial or failed -> production-resume -> succeeded or the same failure
incomplete aggregate -> cancel -> cancelled for incomplete sources
succeeded -> produce again -> same aggregate after revalidation
succeeded -> produce --force -> new aggregate, previous directory kept
```

`production-plan`, `production-show`, `production-list`, `production-verify`, and `production-report` do not write.

`produce` refuses a stale catalogue fingerprint, a stale policy fingerprint, or an `--expect` value that is not the selection file SHA-256. The refusal text is: `The campaign selection changed while this page was open; reload before saving.`

A selected source must still match its bound hash or have a verified acquisition of that hash. A changed hash is passed to the runner, which fails only that source. A missing unbound source is `acquisition_missing`.

## What the runner still owns

For each selected source the existing runner verifies acquisition or the bound file, media preparation, transcript, visual analysis, candidate mining, rough preview, candidate review, alignment, Hero plan and render, Advanced Hero, QA, narration when requested, and local delivery. `produce` does not call those tools itself. It records the runner's stage list, review ids, QA set id, delivery id, and hashes.

The aggregate also records a `reframe` stage for each source: requested strategy, applied strategy, plan id, trajectory hash, evidence digest, status, cache hit, and blocker. `contain` needs no face evidence. A stale `face_follow` plan blocks that source only. Resume reruns a source whose reframing evidence is missing or stale and leaves a current source in place.

A source is not marked succeeded by the aggregate when the runner status is missing, blocked, stale, cancelled, or failed. Candidate approval must be the current decision for the preview artifact. A newer rejection or `changes_requested` decision overrides an older approval. The same rule applies to the Hero review. No command in this round approves a review.

Narration that was not requested is `narration_not_requested` and does not block the run. Requested narration must be the verified English KittenTTS identity with a succeeded producer, matching script, model, revision, voice, and audio hash. A cache hit does not call VoiceStudio. `en-GB` narration stays `locale_not_smoked`. Arabic and Japanese narration stay `unsupported_language`. `zh-CN` is rejected before a pipeline job. English alignment is claimed only as `whisperx` when the runner recorded that from the verified alignment artifact.

## Manifest

```text
campaigns/production/<run_id>/manifest.json
```

The document stores the run id, pipeline run id, campaign id, selection id and SHA-256, catalogue and policy fingerprints, operator id, source ids in selection order, acquisition ids and hashes when present, source hashes and sizes, language, narration identity, review ids, Hero and Advanced Hero artifact ids, QA set ids, analytics snapshot ids when a row already exists, delivery ids, relative delivery paths, final media SHA-256 values taken from the package file list, per-source status, cache flags, failure codes, timestamps, and `manifest_sha256`. Publishing is `deferred`.

Paths in the manifest are relative. Absolute paths, `file:` URIs, and secret-like tokens are rejected.

Promotion order:

1. The runner finishes and verifies per-source outputs.
2. The aggregate is written to `manifest.json.partial`.
3. The `campaign_operator_production` job is committed.
4. The partial file replaces `manifest.json`.
5. The partial file is removed.
6. If the replacement fails and a previous manifest existed, those bytes are restored.

## Commands

```text
clipforge campaign operator produce SELECTION_ID
clipforge campaign operator production-plan SELECTION_ID
clipforge campaign operator production-show RUN_ID
clipforge campaign operator production-list CAMPAIGN_ID
clipforge campaign operator production-verify RUN_ID
clipforge campaign operator production-resume RUN_ID
clipforge campaign operator production-report RUN_ID
```

## Board

GET only, on `127.0.0.1`:

```text
GET /api/campaigns/<campaign_id>/productions
GET /api/campaign-productions/<run_id>
GET /api/campaign-productions/<run_id>/source/<source_id>
GET /api/campaign-productions/<run_id>/delivery
```

The page shows stage status, cache, review, QA, alignment, narration, delivery, and the media hash. It does not autoplay. Static files do not use `eval`, `innerHTML`, or a remote URL.

## Boundaries

Live Whop import remains `not_configured`. Local JSON and JSONL snapshots stay on the existing import command. Envato search still sends only supported filters and does not download media. External publishing is not implemented.
