# ADR 0057: Campaign operator selection and control plane

- Status: Accepted
- Date: 2026-10-06

## Context

Round 20 records one campaign production run over the existing ingest, review, alignment, Hero, QA, narration, and local delivery gates. Round 21 keeps that coverage on two self-hosted CI jobs. An operator still needs one local place to choose sources, see why a source is blocked, and start or resume the run that already exists.

The selection has to stay invalid when the catalogue, the policy, the source hash, or the project changes. It must not approve a review, publish a video, crawl a Whop account, or turn an Envato item page into media.

SQLite is at schema 6. The production run is already a sidecar plus one artifact row. A selection table would not make those gates stronger.

## Decision

Operator selection is a versioned JSON sidecar, `CampaignSelectionDocument`, schema version `1.0.0`. Files live at `campaigns/selections/<selection_id>/selection.json` under the work root. Writes are append-only. An identical evidence fingerprint returns the current file and does not write another one. A different selection requires the SHA-256 of the latest selection file. If that hash is missing or wrong, the command fails with: `The campaign selection changed while this page was open; reload before saving.`

The document stores ids, hashes, the catalogue fingerprint, the policy fingerprint, the language, the narration policy, the operator id, and provenance. It does not store absolute paths. Unknown JSON keys are rejected. There is no SQLite migration.

`clipforge campaign operator run` and `resume` call `run_campaign` and `resume_campaign`. They do not bind sources, choose candidates, approve reviews, align, narrate, check QA, or verify packages on a second path. A selection whose status is not `ready` is refused before that call. `verify` re-checks the stored fingerprints and the current source hash and does not write.

The board listens on `127.0.0.1` only. Any other host is refused before a socket is created. The page is static, read-only, and has no upload route. Operator-controlled strings are assigned with `textContent`.

`clipforge campaign operator import --file` accepts a local `CampaignImportSnapshot` as JSON or JSONL. A future Whop adapter must use that contract. This round does not read `CLIPFORGE_WHOP_LIVE`, cookies, or a browser profile. Doctor reports `whop_live: not_configured` and local commands still succeed.

Envato search records already on disk are shown as discovery metadata. An item-page URL is not a downloaded file. A hit stays outside rendering unless a local acquired file, item id, license evidence, and a policy that is not blocked are all present. Campaigns that do not need outside assets still run when that file is absent.

## Alternatives considered

- Add a `campaign_selections` table. Rejected. The sidecar is the record, and schema 6 already holds the jobs the runner reuses.
- Approve the newest candidate when the operator selects a source. Rejected. Selection is not a review.
- Crawl Whop when `CLIPFORGE_WHOP_LIVE=1`. Rejected. This round has no authorized session and must not invent campaign rows.
- Fetch Envato items that have an item-page URL. Rejected. Discovery metadata is not a license or a media file.

## Consequences

Operators inspect one campaign from the CLI or from `http://127.0.0.1:<port>/`. Allowed catalogue sources proceed. Blocked sources keep a reason code. Successful delivery still means the existing package verifier returned PASS. Arabic and Japanese alignment stay unclaimed. External publishing stays deferred.
