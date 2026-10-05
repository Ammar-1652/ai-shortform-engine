# Campaign operator control plane

The operator control plane selects catalogue sources and shows the state of a campaign run. The campaign production runner still does the work. See [ADR 0057](../adr/0057-campaign-operator-selection-and-control-plane.md) and [ADR 0056](../adr/0056-campaign-production-run-and-language-capabilities.md).

SQLite schema version stays 6. Contract `schema_version` stays `1.0.0`.

## Selection sidecar

`clipforge campaign operator select` writes `campaigns/selections/<selection_id>/selection.json`. The file is a `CampaignSelectionDocument`:

- selection id, campaign id, project id, operator id
- selected source ids and source SHA-256 values
- language tag, narration enabled flag, narration policy (`disabled` or `optional_english`)
- catalogue fingerprint and policy fingerprint
- evidence fingerprint, status, reason code
- provenance (`clipforge-operator`, the operator id, and the evidence hash)
- `publishing` fixed to `deferred` and `whop_live` fixed to `not_configured`

Ids and hashes only. Absolute paths, `file:` URIs, and secret-like tokens are rejected. Unknown keys are rejected. A repeated selection with the same evidence fingerprint returns the existing id. Any other selection is appended only when `--expect` is the SHA-256 of the latest selection file for that campaign. The previous file stays.

`verify` reads that file and checks the current catalogue fingerprint, policy fingerprint, language, narration capability, rights, project, and source hash. It does not open a write transaction and it does not replace the file. A removed source, a changed hash, a rights state other than `allowed`, a symlink, a missing file, a remote URI, a traversal or backslash path, a different project, a changed policy, or an unsupported language fails closed.

An allowed `CampaignSource` is not rewritten to `needs_operator_confirmation`. `unknown`, `prohibited`, and every other non-allowed state are `rights_not_allowed`.

## Commands

```text
clipforge campaign operator doctor
clipforge campaign operator list
clipforge campaign operator show CAMPAIGN_ID
clipforge campaign operator sources CAMPAIGN_ID
clipforge campaign operator select CAMPAIGN_ID --source SOURCE_ID --project PROJECT_ID --operator OPERATOR_ID
clipforge campaign operator verify SELECTION_ID
clipforge campaign operator run SELECTION_ID
clipforge campaign operator resume RUN_ID
clipforge campaign operator status RUN_ID
clipforge campaign operator import --file CAMPAIGN_SNAPSHOT.json --project PROJECT_ID
clipforge campaign operator acquire plan SELECTION_ID
clipforge campaign operator acquire run SELECTION_ID
clipforge campaign operator acquire list CAMPAIGN_ID
clipforge campaign operator acquire show ACQUISITION_ID
clipforge campaign operator acquire verify ACQUISITION_ID
clipforge campaign operator acquire resume ACQUISITION_ID
clipforge campaign operator produce SELECTION_ID
clipforge campaign operator production-plan SELECTION_ID
clipforge campaign operator production-show RUN_ID
clipforge campaign operator production-list CAMPAIGN_ID
clipforge campaign operator production-verify RUN_ID
clipforge campaign operator production-resume RUN_ID
clipforge campaign operator production-report RUN_ID
clipforge campaign operator serve --host 127.0.0.1 --port 8772
```

Read-only commands are `doctor`, `list`, `show`, `sources`, `verify`, `status`, `acquire plan`, `acquire list`, `acquire show`, and `acquire verify`. They do not modify the database or a sidecar. `serve` has no POST, PUT, or DELETE handler.

`select` and `import` validate before they write. `run` refuses a selection that is not `ready`, then calls `run_campaign` with that selection's source ids, language, and narration flag. `resume` calls `resume_campaign`. A cache hit returns the existing verified run, does not call narration, and does not copy the delivery again. Resume retries sources that are not still verified and leaves a succeeded sibling in place. A failed replacement does not delete the previous manifest until the runner promotes a new one.

Status values used by this surface include `succeeded`, `partial`, `blocked`, `failed`, `cancelled`, `cache_hit` on a stage, `not_configured`, `unsupported_language`, `policy_blocked`, `review_missing`, `qa_missing`, `delivery_missing`, and `source_changed`. A succeeded campaign still means the local delivery package verifies.

## Board

`serve` binds `127.0.0.1` only. `0.0.0.0`, a public address, `localhost`, and any other host are refused before the socket is created.

```text
GET /
GET /app.js
GET /styles.css
GET /api/campaigns
GET /api/campaigns/<campaign_id>
GET /api/campaigns/<campaign_id>/sources
GET /api/campaigns/<campaign_id>/runs
GET /api/campaign-runs/<run_id>
GET /api/campaign-runs/<run_id>/source/<source_id>
GET /api/campaigns/<campaign_id>/acquisitions
GET /api/acquisitions/<acquisition_id>
GET /api/campaigns/<campaign_id>/envato
GET /api/campaigns/<campaign_id>/policy
```

The page shows campaign identity, policy rules, sources in source-id order, rights, verification, SHA-256, duration and size when the database is present, language and narration capability, stage and cache status, candidate review, Hero review id, QA, delivery as `deliveries/<id>/manifest.json`, the failure reason, and review paths `review/candidates/<id>` and `hero-review/candidates/<id>`. Publishing is `deferred`. The page does not autoplay media. Static files do not use `eval`, `innerHTML`, remote scripts, remote fonts, analytics, or a CDN. Strings from the campaign are inserted with `textContent`.

## Whop

Live account crawling is not implemented. If a session is absent, doctor reports `whop_live: not_configured`. Ordinary local selection and runs do not fail for that reason. `import` reads a local JSON object, a JSON array, or JSONL. Each row is a `CampaignImportSnapshot` with a campaign id, source ids, policy state, and selection state. `withheld` does not select. Credentials, absolute paths, and `file:` URIs are rejected. An `https` `remote_media_ref` is metadata and is not fetched or copied into the selection.

## Envato

Search stays discovery-only. When `assets/<campaign_id>/asset_download_requests.json` exists, the board shows provider, provider version (`not_recorded` when the file has none), search tool, query, filters, item-page URL, item id, duration, direct download URL, rights, license evidence, and download status. A missing item id, missing license evidence, missing direct download URL, or a blocked policy keeps `renderable` false. A campaign that does not need those assets still runs when the file is missing or Envato is disabled.

## Language and VoiceStudio

`en-US` alignment is the verified WhisperX checkpoint. `en-US` narration is KittenTTS `expr-voice-2-f` when the selection enables it. `en-GB` narration is `locale_not_smoked`. Arabic and Japanese alignment stay `alignment_not_claimed`. `zh-CN` is `unsupported_language`. Narration for a locale that is not verified live is refused before a selection file is written.

## Publishing

External platform publishing is not implemented. The selection, the board, and the production run keep `publishing` at `deferred`.
