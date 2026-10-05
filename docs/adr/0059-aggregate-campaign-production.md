# ADR 0059: Aggregate campaign production

- Status: Accepted
- Date: 2026-10-06

## Context

Rounds 22 and 23 select sources and acquire them. The campaign runner from Round 20 already executes the verified local pipeline and writes `campaigns/runs/<id>/manifest.json`. An operator still needs one aggregate that names the selection, the acquisitions, the pipeline run, the reviews, QA, and the local deliveries, and that can be resumed without rerunning a source that is still verified.

SQLite is schema 6. The pipeline record is already a sidecar plus a job. A second table would not make those checks stronger.

## Decision

`CampaignProductionRun` stays the pipeline record. The new operator aggregate is `CampaignProductionManifest` under `campaigns/production/<run_id>/manifest.json`, schema version `1.0.0`. It points at `pipeline_run_id`. Per-source evidence is `CampaignProductionSource`. Cache identity is `CampaignProductionCacheRecord`.

`clipforge campaign operator produce` checks the selection fingerprints, requires a bound unchanged source or a verified acquisition, then calls `run_campaign`. It does not reimplement preparation, transcription, vision, mining, preview, alignment, Hero, Advanced Hero, QA, narration, or delivery. A cache hit revalidates that pipeline run and returns the stored aggregate without calling the runner. `--force` creates a new aggregate and a new pipeline run and leaves the previous files in place.

`production-resume` calls `resume_campaign` for the stored pipeline id and rewrites only that aggregate. A source the runner still considers current is not rebuilt. `production-verify`, `production-plan`, `production-show`, `production-list`, and `production-report` do not write.

The aggregate is staged, the `campaign_operator_production` job is committed, then the sidecar is renamed into place. If that rename fails, the previous manifest bytes are restored when a previous manifest existed, and the partial file is removed.

An allowed source still does not need a second rights confirmation. Candidate review, Hero review, QA, and delivery verification stay mandatory. No review is auto-approved. Narration stays optional: a source that did not request it records `narration_not_requested`. English alignment is `whisperx` only when the pipeline recorded that claim from a verified alignment artifact. Analytics snapshots are copied when one already exists for the artifact; a missing snapshot is `not_recorded` and is not invented.

Whop live import stays `not_configured`. Envato stays discovery-only. Publishing stays `deferred`.

## Alternatives considered

- Replace `CampaignProductionRun` with the aggregate. Rejected. Existing runs and tests already bind that document to the pipeline.
- Require a fresh analytics observation before success. Rejected. Recording a metric the operator did not supply would invent evidence.
- Re-render authorized long sources in ordinary CI. Rejected. That run stays opt-in. The synthetic fixture exercises the aggregate.

## Consequences

Operators can produce, resume, verify, and inspect one campaign from the loopback board. Success still means the existing package verifier and the existing review and QA bindings passed. A failed source does not delete a sibling's delivery.
