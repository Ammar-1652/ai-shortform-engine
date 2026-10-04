# ADR 0043: Jobs, cache, restart, and batch

- Status: Accepted
- Date: 2026-10-04

## Context

Round 11 is merged on main as `338ac295691a44816c3497a946a2f7c453bcdc1b`. Producers already insert `JobRecord` rows and keep their own cache sidecars. A crashed `running` row could be mistaken for success, a retry could overwrite the current artifact, and nothing could run several sources through one database without a second store.

SQLite schema version stays 4. There is no migration and no second database.

## Decision

`clipforge job` inspects the existing jobs table. `list`, `show`, and `verify` only read. `show` prints the public payload: identifiers and hashes. Absolute paths, home directories, file URIs, remote URLs, and secret-like fields are omitted. `verify` re-checks the source hash, rights, and, when a succeeded job records them, the proxy or transcript sidecar, the file hash, and the producer job. It does not rewrite rows or files.

`recover` selects `running` jobs whose `updated_at` is older than an explicit threshold. The default is 15 minutes. A lock file is not evidence that a process is alive. A stale row is marked `failed` with an error that says it was not marked succeeded. Fresh `running` rows are left alone.

`resume` and `retry` are the same operation. They require `failed`, `blocked`, or `cancelled`, and they require the live source hash and cleared rights to still match the recorded payload. A changed source or a prohibited rights row is refused before a new job is inserted. Supported kinds are `media_prepare`, `transcribe`, and `rough_preview_render`. Any other kind fails closed. The new attempt has a new job id. The previous row is not updated. If the producer returns an existing succeeded job, because of a cache hit, Clipforge inserts a new succeeded attempt that points at that job and does not rewrite it. A failed attempt does not replace the current artifact or sidecar.

Media-prepare cache identity is the source SHA-256, the recipe name and version, the stored ffmpeg version, the selected streams, and the artifact hash and size. A hit also requires a succeeded producer in the same project and source. A symlink, a missing file, a hash mismatch, a failed job, or a recipe mismatch is a miss. A full hit does not execute ffmpeg or ffprobe and does not insert a job. The stored tool version is the identity. Discovering a newer ffmpeg binary would itself execute ffmpeg, so an upgrade does not invalidate a byte-identical proxy until the sidecar is removed or the recipe version changes. Stored argv lists keep option tokens and drop absolute paths. Transcript cache identity is unchanged: source hash, ASR FLAC hash, request, language, model name and revision, device, compute type, and recipe versions. A hit does not call the backend. `--force` on `transcript run` still writes a new artifact and keeps the previous job.

Promotion of a replacement follows one order: output bytes, manifest validation, database commit, sidecar publish. A failure before the sidecar leaves the previous current file in place. A sidecar failure rolls the database change back. The batch manifest uses that order. The new JSON is written to a partial file and replaces `manifest.json` only in the sidecar step. The first failure leaves no manifest. A later failure restores the previous bytes.

`clipforge batch` runs sources in the order given, through the same SQLite file. Concurrency is 1. Duplicate ids and mixed projects are rejected. The default operation is `media_prepare`. One source failure does not delete another source's job. The batch record is `batches/<batch_id>/manifest.json` under the work root. It stores the batch id, project, profile and policy ids when the project has a profile, ordered sources and operations, child job ids, statuses, cache-hit flags, artifact hashes, and the aggregate status. The aggregate cannot be stronger than the children. `resume` reruns children that are not a verified succeeded job. `list`, `show`, and `verify` only read. A symlink anywhere under the batch directory is rejected before a write. The manifest stores no absolute paths.

Lock contention is still detected by the producer before it inserts a job. `job resume` calls that producer only after the source hash and rights checks.

## Consequences

- Operators can see a failed job, recover a stale `running` row, and start a new attempt without losing the old row.
- A cache hit stays a hit only while the bytes, the sidecar, the lineage, and the succeeded producer still agree.
- A batch is a file next to the existing work root, not a new database.
- Vision, candidate, Hero, advanced Hero, and QA jobs are not resumed by guessing. Batch execution does not auto-approve or publish.
- Publishing, analytics, Envato, full-source WhisperX, speaker attribution, and face recognition stay out of this round.
