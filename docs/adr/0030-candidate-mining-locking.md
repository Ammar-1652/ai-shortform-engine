# ADR 0030: Candidate mining locking

- Status: Accepted
- Date: 2026-10-02

## Context

Candidate mining reads a transcript and a visual analysis that other commands replace under exclusive locks. Those artifacts also depend on the ASR audio and the analysis proxy, which `media prepare` replaces under `prepare.lock`. Two miners must not publish the same sidecar.

## Decision

The lock order is fixed:

1. Shared `prepare.lock`.
2. Shared `transcribe.lock`.
3. Shared `vision.lock`.
4. Exclusive `candidate.lock` at `tmp/candidate.lock`.

All four are non-blocking. A busy lock fails before a candidate job is inserted and before a mining run directory is created. The shared locks are held for the whole revalidation and mining run, so a transcription or visual analysis cannot take its exclusive lock in the middle. Prepare cannot replace the derived media either.

After all four locks are held, a `running` `candidate_mine` job for that source is stale and is marked failed. The new job is inserted only after a second validation of rights, source bytes, and both upstream artifacts. SQLite is not held across window generation, scoring, or dedupe.

`candidates/` and `candidates/runs/` are real directories inside the work root. A symlink is refused. Cleanup of a failed run deletes `*.partial.*` inside that run only.

## Alternatives considered

- Skip the prepare lock because mining does not decode video. Rejected. The transcript and visual artifacts are only meaningful while the derived media they were built from is stable.
- Take the candidate lock first. Rejected. That inverts the order the writers already use and can deadlock.
- Wait for a busy lock. Rejected. The rest of the pipeline fails fast.

## Consequences

An active prepare, transcription, visual analysis, or candidate mine blocks a new mine immediately. A live mine blocks a new transcription and a new visual analysis. That stall is intentional.
