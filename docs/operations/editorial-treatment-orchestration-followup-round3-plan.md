# Editorial treatment orchestration follow-up round 3

**Review date:** 2026-10-26
**Reviewed head:** `6bd76212b85b56bcb4225a312b52ad8690e62d82`
**Branch:** `round-36-editorial-knowledge-engine`
**PR:** [#38](https://github.com/Ammar-1652/ai-shortform-engine/pull/38)
**Purpose:** close the evidence and integration gaps found when reviewing the
round-2 implementation against its own acceptance criteria.

## Review findings

### R3-1 — Persist and consume the bound treatment revision

The asset command now verifies provider, selection, acquisition, license, and
registered-byte records and writes a typed binding sidecar. The sidecar is not
automatically incorporated into a new immutable `DirectionDocument` revision,
so a caller can still produce a verified handoff that is not the direction
consumed by Advanced planning. This leaves a manual merge step at the most
important rights boundary.

Fix workflow:

1. Add a typed direction-revision operation that loads the current immutable
   direction, replaces exactly one request and placement with the verified
   binding, increments the direction identity, and preserves the previous
   document unchanged.
2. Require the revision to match project, source, candidate, source hash,
   TimeMap hash, alignment hash, and visual-analysis hash.
3. Re-run source-evidence validation, treatment lint, policy evaluation, and
   the complete placement/request hash comparison before publishing the new
   direction artifact.
4. Make Advanced planning reject a binding sidecar that is not present in the
   selected direction revision.
5. Add immutable revision, rollback, stale-source, and failed-promotion tests.

Acceptance: the only placement that can reach render input is the placement
inside the persisted direction revision that passed the provider and rights
checks.

### R3-2 — Replace tag-only B-roll relevance with decoded observations

`TreatmentRegion` now covers some output-space geometry, but source-native text
uses a fixed rectangle and there are no measured logo, CTA, active-subject, or
B-roll regions. Relevance still comes from transcript-token/tag intersection.
No decoded B-roll observation sidecar is produced or consumed.

Fix workflow:

1. Add a typed `TreatmentAssetObservation` sidecar containing asset hash,
   media kind, sampled-frame files, sample timestamps, visual labels,
   output placement, relevance score, threshold, analyzer version, and
   provenance.
2. Decode bounded representative frames for every selected visual asset using
   the existing argv-only media runner; publish them atomically under the work
   root and reject missing, corrupt, or changed bytes.
3. Add output-space rectangles for source text, logo, CTA, active subject,
   captions, platform rails, and the selected B-roll layer after the actual
   crop/reframe transform. Include confidence and evidence-source fields.
4. Evaluate relevance from the decoded observation plus reviewed source
   evidence. Tags may assist search, but cannot independently produce
   `related`.
5. Calculate the full camera envelope against every protected rectangle and
   emit a stable omission reason before render input creation.
6. Add tests for unrelated frames with matching tags, changed observation
   bytes, source-native text, logo/CTA overlap, B-roll overlap, and maximum
   camera travel.

Acceptance: a selected visual asset has a verified decoded observation and
numeric relevance evidence, and all protected regions are measured in final
output coordinates.

### R3-3 — Make audio overlap and intelligibility factual

`TreatmentAudioMixResult.speech_overlap_windows` is currently populated with
the entire SFX interval, regardless of whether speech exists. The renderer
ducks source audio over that interval, but the plan does not contain measured
speech activity, narration windows, silence proof, or an intelligibility
result. `intelligibility_status` remains `unverified` for production plans.

Fix workflow:

1. Derive speech windows from the canonical aligned-word intervals and any
   validated narration window; keep source and narration clocks separate.
2. Intersect each SFX cue with those windows and store only the actual
   overlap, with source and output timestamps.
3. Apply source-dialogue ducking only over measured overlap windows. Preserve
   source audio through non-speech intervals and when no SFX is selected.
4. Measure post-encode speech/SFX overlap, silence windows, integrated LUFS,
   true peak, RMS, and clipping from the decoded output.
5. Require `intelligibility_status=pass` for a clean production QA result;
   `unverified` must block final review and delivery for a treatment that has
   audio cues.
6. Bind the measured result into the audio mix identity and add source-only,
   overlap, silence, narration, loud-SFX, and changed-policy regressions.

Acceptance: the mix receipt describes measured speech overlap and a decoded,
validated intelligibility result; it is not a restatement of cue duration.

### R3-4 — Create a canonical treatment evidence bundle

The current `treatment_evidence_sha256` hashes the treatment fingerprint and
audio mix. It does not persist a typed bundle containing the request/selection/
acquisition/license chain, policy states, regions, observations, event
receipts, omission reasons, and measured audio facts. Downstream stages compare
the digest but cannot independently load and validate the complete evidence.

Fix workflow:

1. Add a versioned `TreatmentEvidenceBundle` schema with all beat decisions,
   requests, placements, provider/license receipts, visual observations and
   regions, event receipts, policy findings, omission reasons, and measured
   audio facts.
2. Persist it atomically beside the Advanced plan with a relative path and
   SHA-256 digest.
3. Put the bundle path and digest in render input, viewer evidence, QA,
   final-review evidence, cache facts, and delivery facts.
4. Make each downstream verifier load the bundle and validate its parent
   direction, render input, encoded bytes, and QA artifact instead of only
   comparing strings.
5. Add stale-bundle, changed-region, changed-provider-receipt,
   changed-mix, rollback, and failed-promotion tests.

Acceptance: a digest without a readable, hash-matching bundle cannot pass QA,
approval, or delivery.

### R3-5 — Route the shared policy evaluator through every gate

`evaluate_treatment_policy()` is currently called by direction lint and the
editorial treatment CLI. QA and delivery rely on downstream fingerprints and
technical checks but do not independently execute the same policy evaluator.
The render-event set check also compares sets, so duplicate references across
two `use` decisions are not rejected as “exactly one”.

Fix workflow:

1. Call the shared evaluator from Advanced preflight, QA, final review, and
   delivery using the exact selected direction and preset.
2. Reject any error finding at each gate; retain warning findings in the
   review packet.
3. Replace set-only event checks with multiplicity-aware ownership checks:
   every rendered event must have exactly one `use` decision and every `use`
   event must render exactly once.
4. Add tests that inject duplicate camera, transition, B-roll, SFX, and
   graphic references and verify that every gate blocks them.

Acceptance: all gates use the same policy result and no event can be omitted,
duplicated, or silently rendered outside its decision.

### R3-6 — Complete authorized production proof and CI bookkeeping

No authorized non-campaign generic source with persisted rights evidence is
available in the current work area, so the provider-backed production proof
cannot be fabricated. PR #38's self-hosted `verify-python` job is still
queued, with no runner assigned.

Fix workflow:

1. Add an authorized generic source and rights records under the ignored work
   root, or record the exact external input required from the operator.
2. Acquire one relevant visual asset and one SFX through the existing provider
   boundaries and preserve their evidence hashes.
3. Run direction, treatment binding, observation, Advanced rendering, decoded
   viewer evidence, QA, final review, and local delivery.
4. Record MP4, contact-sheet, audio, provider, license, and cache facts in a
   review packet without committing media.
5. Diagnose the self-hosted queue; record the exact CI conclusion for this
   head. Do not bypass or weaken the workflow.

Acceptance: the generic clip proves the provider-backed path and CI is green
on the exact reviewed commit. Until then these are environment gates, not
claims of production proof.

## Exit criteria

R3-1 through R3-5 require code, failure tests, generated schemas where
applicable, and a full validation run. R3-6 requires authorized media and a
runner result. The round must remain draft and unmerged until independent code
and visual review are complete.
