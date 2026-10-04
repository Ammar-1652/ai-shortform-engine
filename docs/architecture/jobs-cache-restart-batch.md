# Jobs, cache, restart, and batch

Round 12 makes a failed or interrupted local run recoverable. It does not add a worker queue, a second database, or a publisher.

## Job states

`JobRecord.status` is `pending`, `running`, `succeeded`, `failed`, `cancelled`, or `blocked`. A `failed` row must store `error_message`. `clipforge job recover` changes a stale `running` row to `failed`. It never changes one to `succeeded`. The age check uses `updated_at` and `--older-than-minutes` (default 15). The presence of `prepare.lock` or any other lock file is not liveness.

`clipforge job list` prints id, kind, project, source, status, `updated_at`, cache flag, and a one-line error. `show` prints the same facts plus the public payload. `verify` reads the job, the source bytes, the rights row, and the current sidecar when the payload names an output hash. None of those commands write.

## Retry and resume

`resume` and `retry` share one function. Both refuse a kind outside `media_prepare`, `transcribe`, and `rough_preview_render`. Both refuse a job that is not `failed`, `blocked`, or `cancelled`. Both re-read the source file when the URI is `file:` and compare it with `payload.source_sha256`. Both call `require_rights_cleared`. A mismatch raises before the producer runs.

The producer then runs with its own lock. If that lock is already held, the producer raises and no new job row is inserted. A new producer job is stamped with `parent_job_id`, `attempt`, and `operation`. If the producer returns a job id that already existed, which is what a transcript or preview cache hit does, Clipforge inserts a new succeeded attempt and leaves both the old job and the current artifact untouched. A producer error leaves the previous current artifact and sidecar where they were.

Payloads store ids, hashes, recipe versions, model name and revision, and request options. They do not store absolute paths, model cache paths, home directories, or shell strings.

## Cache identity

Analysis proxy and ASR audio reuse a `DerivativeCacheRecord` when all of these match:

- source content SHA-256
- recipe name and version (`analysis-proxy` v1 or `asr-audio` v1)
- stored ffmpeg version
- selected video and audio stream indexes
- artifact SHA-256 and size
- a succeeded `media_prepare` job for that artifact, project, and source

The sidecar and the media file must be regular files. A symlink is a miss. A full hit returns the existing job id and does not start ffmpeg or ffprobe. A miss inserts a `running` job only after the prepare lock is held, then encodes outside any SQLite write transaction. Failed and blocked attempts are not hits.

Transcript reuse keeps the Round 3 identity: source SHA-256, ASR FLAC SHA-256, language and decoding fingerprint, model name, revision, and source kind, device, compute type, faster-whisper version, CTranslate2 version, and recipe version. The transcript JSON must parse, the transcript id must match the sidecar, and the producing job must be `succeeded`. A hit does not call the backend and does not download a model. `transcript run --force` bypasses the cache, writes a new job, and leaves the previous transcript job in history. A changed model revision or a corrupt sidecar is a miss. A changed source file is refused before the backend starts, because the ASR FLAC still belongs to the previous bytes.

The stored ffmpeg version is part of the proxy record. A hit does not execute `ffmpeg -version` to compare it with the binary on `PATH`. Replacing the ffmpeg package does not by itself rebuild a byte-identical proxy. Delete the recipe sidecar, or change the recipe version, to force a new encode.

## Restart

The promotion helper runs four steps in order: write output bytes, validate the manifest, commit the database, publish the sidecar. Output or manifest failure does not publish. A database failure rolls back. A sidecar failure rolls the database back and restores the previous current file. The first run has no previous file, so a sidecar failure removes the new manifest. Partial files stay beside the current name until that cleanup. Orphan run directories may remain for inspection. They are not current. Another source's files are not deleted.

Symlinks, `..`, backslashes, remote URLs, and file URIs outside the work root are rejected before a batch manifest or other promotion target is replaced. Referenced source files may still live outside the work root. That exception is only for the ingested source, not for outputs.

## Batch manifest

`clipforge batch run` takes source ids in order and uses the database from `--db`. Default concurrency is 1. Any other value is an error. Duplicate ids are an error. Sources from more than one project are an error. The production operation is `media_prepare`. Each source gets that producer's job and artifact lineage. `--force` is stored on the manifest. Media prepare has no separate force switch: a changed source hash is already a miss. Transcript force remains `clipforge transcript run --force`.

The manifest is `batches/<batch_id>/manifest.json`. Fields:

- `batch_id`, `project_id`, `created_at`, `updated_at`
- `profile_id`, `profile_sha256`, and `policy_ids` when the project has a profile
- `source_asset_ids` and `operations`, in run order
- `children`: source, operation, status, job id, cache hit, artifact id, artifact SHA-256, cache identity, error
- `status`: `succeeded` only when every child succeeded; any failed child makes the batch `failed` or `partial`; any cancelled child makes it `cancelled` or `partial`; `pending` or `running` stays `running`
- `concurrency` is 1
- provenance naming `clipforge-batch`

`batch resume` keeps a child only when its job row is still `succeeded` in the same project. Other children run again. `list`, `show`, and `verify` do not write. A symlinked `batches` directory is rejected and nothing is written through the link.

The batch does not approve reviews, run QA as a pass, or publish.

## Commands

```text
clipforge job doctor
clipforge job list [PROJECT_ID]
clipforge job show JOB_ID
clipforge job verify JOB_ID
clipforge job recover [PROJECT_ID]
clipforge job resume JOB_ID
clipforge job retry JOB_ID
clipforge batch doctor
clipforge batch run SOURCE_ID [SOURCE_ID ...]
clipforge batch list BATCH_ID
clipforge batch show BATCH_ID
clipforge batch verify BATCH_ID
clipforge batch resume BATCH_ID
```

Shared options are `--db`, `--work-dir`, `--created-by`, and on the batch run, `--concurrency` and `--force`.

## Non-goals

No cloud workers. No publishing, analytics, or Envato. No full-source WhisperX, speaker attribution, or face recognition. No automatic approval. QA remains a prerequisite for any later publishing work, and QA still does not render or approve. The canonical time map remains the only timing authority. Schema version stays 4.
