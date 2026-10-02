# ADR 0024: Visual analysis artifact and cache

- Status: Accepted
- Date: 2026-10-02

## Context

Round 3 showed that a new transcript file can be published before the database points at it, and a later crash then looks valid if the check only asks "is there a succeeded job?". Visual analysis has more files: `analysis.json`, representative JPEGs, and contact sheets.

## Decision

Each run is a new directory `vision/runs/<analysis_id>/`. The current sidecar is `metadata/visual-analysis.recipe.json`. The artifact kind is `visual_analysis_json`. The job kind is `visual_analyze`. SQLite stays at schema version 4. There is no migration 5. Frame and face rows are not tables.

Publication order:

1. Finish the run directory, including evidence files and `analysis.json`.
2. Write the transcription-style log while the previous sidecar is still current.
3. In one transaction, point the artifact row at that analysis and mark the job succeeded. The payload stores `analysis_id`.
4. Atomically replace the sidecar.

If the sidecar write fails, the previous artifact row is restored when there was one, and the new job is marked failed. The new run directory may remain. It is not current.

Cache hits return the existing succeeded job and do not decode or detect. `--force` builds a new run and leaves the old directory in place. `created_at` is not identity.

A valid analysis requires all of:

- `document.analysis_id` equals the sidecar and `payload["analysis_id"]`
- `document.provenance.job_id` equals the sidecar, the artifact row, and the succeeded `visual_analyze` job
- document proxy SHA, provenance input digest, and artifact input digest equal the current proxy SHA
- document scene, sampling, face, and tracking settings rebuild the sidecar fingerprints
- every evidence path hashes to the manifest, and the manifest digest matches

`vision verify` is read-only. `vision show` checks project and source and does not hash the whole tree, load a model, or decode video.

The log is written before the database commit. A log error restores nothing that was already current, marks the new job failed, and leaves the previous analysis usable. Cleanup errors are collected. They do not skip the job status update and they do not replace the original exception.

## Alternatives considered

- Overwrite `analysis.json` in place. Rejected. A crash mid-tree is harder to roll back than an unreferenced run directory.
- Publish the sidecar before the database commit. Rejected. That is the Round 3 crash shape. Binding checks would still catch it, and this order plus the checks is stronger.
- A `visual_frames` table. Rejected. The JSON document is what Round 5 can read without OpenCV.

## Consequences

Disk holds old runs until an operator deletes them. Verify fails closed on a mismatched job even if the JSON parses. Contact sheets are required evidence. A sheet failure fails the job.
