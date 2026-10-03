# ADR 0035: Rough-preview locking and recovery

- Status: Accepted
- Date: 2026-10-03

## Context

A preview reads the proxy, the ASR audio, the transcript, the visual analysis, and the candidate set. Those artifacts are replaced by exclusive locks in earlier rounds. Two previews must not publish the same sidecar. A failed preview must not erase the last good set.

## Decision

The lock order is fixed and non-blocking:

1. Shared `prepare.lock`.
2. Shared `transcribe.lock`.
3. Shared `vision.lock`.
4. Shared `candidate.lock` (`candidate_read_lock`).
5. Exclusive `preview.lock` at `tmp/preview.lock`.

Candidate mining still takes `candidate.lock` exclusive and does not take `preview.lock`. A busy lock or an unsafe symlink fails before a preview job is inserted and before a new run directory is created. `preview verify` does not create directories, lock files, or jobs.

After all five locks are held, a `running` `rough_preview_render` job for that source is stale and is marked failed. A live render still holds the lock, so it is not marked stale.

Publication writes each MP4 to a partial path, probes it, hashes it, and renames it. The manifest is published the same way. One transaction then points the artifact at the manifest and marks the job succeeded. The sidecar is replaced after that commit.

If sidecar publication fails and a previous preview artifact existed, that row is restored and the new job is marked failed. If there was no previous row, the new artifact row is deleted. The incomplete run does not become current. `KeyboardInterrupt` marks the job cancelled. Partial files in the failed run are removed. Historical completed runs are not deleted.

## Alternatives considered

- Take the preview lock first. Rejected. That can deadlock with the writers that already take `prepare.lock` before their own exclusive lock.
- Leave a first-run artifact in place when the sidecar fails. Rejected. Round 5 had to fix that false current pointer.

## Consequences

An active prepare, transcription, visual analysis, candidate mine, or preview blocks a new preview immediately. A live preview blocks those exclusive writers. Other sources stay independent.
