# ADR 0025: Visual analysis locking

- Status: Accepted
- Date: 2026-10-02

## Context

`media prepare` holds `prepare.lock` exclusively and can replace `proxy/analysis.mp4`. Two visual analyses of one source would race on the current sidecar and the artifact row. Transcription already holds the same prepare lock shared, then its own exclusive lock. ADR 0020 is unchanged.

## Decision

Visual analysis takes locks in this order:

1. Shared `prepare.lock`.
2. Exclusive `vision.lock` at `tmp/vision.lock`.

Both are non-blocking. If either is busy, the command fails before a job row is inserted and before scene detection. The lock files may remain. The kernel lock is the authority. Symlinked lock files are not followed where `O_NOFOLLOW` exists.

The shared prepare lock is held while the proxy is read, including scene detection, decode, and face detection. Transcription may hold the same shared lock and its own `transcribe.lock` at the same time. That pairing cannot deadlock: prepare never takes `vision.lock` or `transcribe.lock`, and neither reader takes the other's exclusive lock.

After both locks are held, a `running` `visual_analyze` job for that source is stale and is marked failed. A live holder cannot be marked stale because the second process cannot get `vision.lock`.

The running job is committed and the connection is closed before detection. SQLite is not held across PySceneDetect or MediaPipe.

`vision/` and `vision/runs/` are real directories created inside the work root. A symlink at the vision root, the runs directory, or a run directory is refused. Cleanup of a failed run deletes `*.partial.*` inside that run only.

## Alternatives considered

- Reuse `transcribe.lock` for vision. Rejected. Transcription and visual analysis are allowed to overlap.
- Take `vision.lock` before `prepare.lock`. Rejected. The same order bug ADR 0020 avoids.
- Skip the prepare lock because the proxy is immutable. Rejected. Prepare replaces it.

## Consequences

An active prepare blocks vision immediately. An active vision blocks a second vision immediately. Transcription and vision of the same source can run together. Both block prepare until they release the shared lock.
