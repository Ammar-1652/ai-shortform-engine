# Source acquisition

Acquisition copies a selected, policy-allowed campaign source into the work root and records why it was accepted or refused. The campaign production runner still builds the edit. See [ADR 0058](../adr/0058-source-acquisition-and-policy-intake.md).

SQLite schema version stays 6. Contract `schema_version` stays `1.0.0`.

## State machine

```text
plan -> run -> succeeded
             -> partial
             -> failed
             -> blocked
             -> cancelled
partial or failed -> resume -> succeeded or the same failure
any incomplete attempt -> cancel -> cancelled for incomplete sources
succeeded -> run again -> same attempt (cache hit)
succeeded -> run --force -> new attempt, previous directory kept
```

`plan` only prints rights, cache, and the byte cap. `verify` re-hashes the promoted file and probes it again. Neither command creates a file or a job.

`run` reads the selection. It refuses a stale catalogue fingerprint, a stale policy fingerprint, or an `--expect` value that is not the selection file SHA-256, with: `The campaign selection changed while this page was open; reload before saving.`

For each selected source:

1. Rights other than `allowed` stop that source. `rights_unverified` is `missing_evidence`. Unknown and prohibited rights are `rights_not_allowed`.
2. The input is the bound file when it is inside the work root, otherwise `incoming/<source_id>.mp4`. Remote URLs, backslash paths, `..`, symlinks, and paths outside the work root fail before a copy.
3. SHA-256 must match the selection. Size must match the manifest when that size is known, and must be within the byte cap.
4. Bytes are copied to `staging/<source_id>.partial`. ffprobe and a decode must succeed. Codec, dimensions, duration, frame rate, and sample rate must satisfy `MediaConstraints`.
5. `os.replace` promotes the file to `media/<source_id>.mp4`. Checksums and `manifest.json` are written after that. A `campaign_acquisition` job is marked succeeded.
6. A failed check deletes the partial. A failed promotion deletes the partial and does not leave a new final file. A sibling that already succeeded is left in place.

`resume` keeps a succeeded source whose file still matches and retries the others. `--force` skips the cache and writes a new attempt id.

A repeated run of an unchanged selection returns the existing attempt. It does not insert another job and does not copy the media again. If the input bytes change, that source is a miss: a new attempt records `source_changed` and the previous promoted file stays.

## Commands

```text
clipforge campaign operator acquire plan SELECTION_ID
clipforge campaign operator acquire run SELECTION_ID
clipforge campaign operator acquire list CAMPAIGN_ID
clipforge campaign operator acquire show ACQUISITION_ID
clipforge campaign operator acquire verify ACQUISITION_ID
clipforge campaign operator acquire resume ACQUISITION_ID
```

`run` and `resume` accept `--expect` and `--operator`. `run` accepts `--force`.

Read-only: `plan`, `list`, `show`, `verify`.

## Campaign run

`clipforge campaign operator run` requires each selected source to still match its bound hash, or to have a verified acquisition of that hash. It then calls `run_campaign`. The link is `campaigns/runs/<campaign_run_id>/operator.json`: selection id and hash, policy and catalogue fingerprints, acquisition ids, language, narration flag, delivery ids, and per-source status. Publishing stays `deferred`.

## Board

These routes are GET-only on `127.0.0.1`:

```text
GET /api/campaigns/<campaign_id>/acquisitions
GET /api/acquisitions/<acquisition_id>
GET /api/campaigns/<campaign_id>/envato
GET /api/campaigns/<campaign_id>/policy
```

The page shows acquisition status, byte size, SHA-256, probe facts, the relative path, and the failure code. Strings are assigned with `textContent`.

## Envato

`SUPPORTED_ENVATO_FIELDS` names the generic filters each tool may receive. A filter is sent only when that tool's schema also lists the mapped field. Anything else is `deferred_filters` and applied to the returned rows. A hit with a missing field stays in the list. `perPage` is at most 5. `FakeEnvatoMcpProvider` is the test double. Live search still requires both Envato environment flags. Item-page URLs are metadata. A direct download URL is stored only when the provider returned one. This round does not download or render Envato media.

## Whop

`whop_live_import` uses `WhopSnapshotConnector`. The connector in this build returns no payload, so the status is `not_configured`. Local snapshots continue through `clipforge campaign operator import`. Credentials and secret-like text are rejected before a selection file is written.

## Privacy

Manifests, job payloads, board JSON, and checksums store ids, hashes, sizes, codecs, and relative paths. They do not store absolute paths, bearer tokens, cookies, or account identifiers.
