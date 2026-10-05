# Campaign production orchestration

A campaign run is a versioned sidecar plus one `campaign_production` job. It does not add a SQLite migration. The document lives at `campaigns/runs/<campaign_run_id>/manifest.json` under the work root. The database stores the job and an artifact of kind `campaign_production_run_json`. The JSON itself stores ids and hashes, not filesystem paths.

## Lifecycle

`clipforge campaign plan` is read-only. It does not open a provider and it does not insert a job. The plan lists the selected sources in sorted order, the language profile, the narration policy, and a `not_run` row for every stage.

`clipforge campaign run` executes only the sources named by the campaign. For `antoine-sallis` those are the two selected catalogue files. Duplicate ids, an unknown campaign, an unselected file, and sources that belong to different projects are rejected before a sidecar is written.

Each source then walks the same stage order: source verification, ingest, media preparation, transcription, vision, candidate mining, preview, review, alignment, Hero planning, Hero rendering, Advanced Hero, QA, narration, and local delivery. A stage that already has a matching artifact is `cache_hit`. The runner does not insert a new stage job for that hit, does not copy the delivery package again, and does not call VoiceStudio.

A second `run` with the same evidence fingerprint returns the previous succeeded document. `--force` writes a new run id and leaves the previous file in place. `resume` re-reads only sources that are not succeeded, or whose source hash no longer matches. A succeeded sibling stays as it was. One failed source does not erase the other.

`verify` re-checks the source, every file named by the delivery package, `checksums.sha256`, the producer job, the candidate review, the hero approval, QA, alignment, and narration. A cache hit does that again before it returns the stored run. A changed MP4, QA file, review, narration, or producer status invalidates that source. Resume rebuilds only the invalidated source and leaves a sibling that still verifies. A symlink in any path component is rejected, including a parent directory. The manifest is staged under the work root and promoted only after the database commit. A failed promotion deletes the new manifest and does not leave a succeeded job behind. Missing artifact rows fail closed. A stage is `cache_hit` only after those checks. A missing stage stays blocked. This round reuses verified artifacts. It does not launch a new render or a new narration request when the evidence is already intact, and it does not mark a missing stage succeeded.

## Source policy

`CampaignSource.rights_state` is the gate. `allowed` proceeds without a second operator confirmation. The runner does not rewrite an allowed source to `needs_operator_confirmation`.

These still fail closed: a missing file, a changed SHA-256, prohibited or unknown rights, a symlink, a `..` or backslash path, a remote URL, and a delivery or narration file outside the work root. Referenced source files may live outside the work root when the ingest URI is a normal `file:` URI and the hash matches the manifest. That is the existing referenced-storage rule.

## Language and narration

Planning, alignment, captions, and the campaign report read one capability registry. English alignment is the verified WhisperX checkpoint. Arabic and Japanese stay `alignment_not_claimed`. `zh-CN` is rejected. KittenTTS narration is a verified live claim for `en-US` only, and only for the engine, model, revision, voice, and script that were actually smoked. A production run never selects `FakeForcedAlignment`.

Narration is optional. It is requested for `src-before-famous` and recorded as `narration_not_requested` for `src-american-secret`. A disabled plan does not open a socket. An unsupported language records `unsupported_language` or `locale_not_smoked` and does not borrow the English artifact. A cold-start timeout is `provider_timeout`, which resume can retry. It is not stored as a successful audio file.

## Cache identity

The evidence fingerprint covers the campaign id, language, narration engine identity, each source SHA-256, each stage artifact id and hash, the candidate id, the QA hash, the narration hash, and the delivery id and manifest hash. A changed source or upstream artifact misses that fingerprint. Timestamps and the run id are not part of it, so a cache hit returns the same manifest bytes.

## Recovery

Browser and Remotion work stay at concurrency 1. The render policy remains the candidate-local span from ADR 0054: the staged clip starts at frame 0 and the full analysis proxy is not seeked. A failed render still leaves the previous current artifact in place. Resume retries the incomplete stage. There is no blind retry loop that would insert a second narration request or a second delivery copy.

Reviews stay append-only. The runner records the existing human decision. It does not approve a Hero or an Advanced Hero by itself.

## Local delivery and publishing

A succeeded source points at the current local delivery package: the MP4, the package manifest, source and artifact hashes, QA evidence, language, alignment state, and narration identity when narration was requested. External platform publishing is `deferred`. It is not a stage in this round, and its absence does not fail a local campaign.

## Envato

Stock search stays schema-aware. Video uses `search_stock_video` when that tool is advertised. Unsupported filters are rejected before a call. Missing item ids, durations, formats, and direct download URLs stay null. A hit whose campaign policy is not `allowed`, or that has no local rights evidence, cannot enter a render. An Envato failure does not block a campaign that does not require outside assets.
