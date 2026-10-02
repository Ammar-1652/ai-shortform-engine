# ADR 0020: Transcription locking and media read consistency

- Status: Accepted
- Date: 2026-10-02

## Context

`media prepare` holds an exclusive `fcntl.flock` on `prepare.lock` and may replace `audio/asr.flac`. A transcript that hashed the file and then kept reading it could transcribe a mix of two encodes. Two transcripts of the same source could also publish the same JSON.

faster-whisper returns a generator. The model is still running while that generator is consumed. Releasing locks before the generator is exhausted would reopen the race.

## Decision

Transcription takes locks in this order, and only this order:

1. Shared lock on `WORK_ROOT/projects/<project>/sources/<source>/tmp/prepare.lock` (`LOCK_SH | LOCK_NB`).
2. Exclusive lock on `.../tmp/transcribe.lock` (`LOCK_EX | LOCK_NB`).

Media prepare keeps taking `prepare.lock` exclusively and does not take `transcribe.lock`. That avoids a lock-order deadlock.

The shared prepare lock is held for the whole read of the ASR FLAC, including model inference. The exclusive transcribe lock is held until the transcript, sidecar, artifact row, and final job status are written, or until failure cleanup finishes. The lock files may remain. The kernel lock is the authority. A crash releases both. Clipforge does not delete another process's lock file.

If either lock is busy, the command fails immediately. No job row is inserted or updated, no partial is deleted, and the backend is not called.

After both locks are held, a `running` `transcribe` job for that source is stale: no live transcription still holds the lock. It is marked `failed`. A live holder is never marked stale, because the second process cannot get the lock.

The running job is committed and the connection is closed before inference. The generator is consumed inside the locks. SQLite is not held across the model call.

Preflight (rights, mutation, ASR hash, producer job) runs before the model download and again after the locks, so a prepare that finished during the download cannot be transcribed from a stale FLAC.

## Alternatives considered

- Hash the FLAC and ignore later replacement. Rejected. The bytes under inference could still change.
- One exclusive lock shared with prepare for the whole transcription. Rejected. Readers could share the file safely; only replacement must wait. The shared lock does that.
- Take the transcribe lock before the prepare lock. Rejected. A future prepare that also waited on the transcribe lock could deadlock.

## Consequences

A prepare and a transcript of the same source cannot overlap. Two transcripts cannot overlap. A crashed `running` row is recoverable. Transcription can still run for a long time with the locks held and the database free for other projects.
