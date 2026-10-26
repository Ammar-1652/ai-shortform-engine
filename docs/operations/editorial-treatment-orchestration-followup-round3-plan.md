# Editorial treatment orchestration follow-up round 3

**Review date:** 2026-10-26
**Reviewed head:** `331f13eb3f26fe9bfca3422c68cc9cfe3043ae92`
**Branch:** `round-36-editorial-knowledge-engine`
**PR:** [#38](https://github.com/Ammar-1652/ai-shortform-engine/pull/38)
**Purpose:** close the evidence and integration gaps found when reviewing the
round-2 implementation against its own acceptance criteria.

**Current status:** `REVIEW OPEN — NOT COMPLETE`.

This status is intentional. Passing local tests, completing a code slice, or
having a draft PR does not authorize changing this plan to `COMPLETE`.

**Implementation checkpoint:** R3-1 through R3-5 now have code paths and
targeted regression coverage in the working tree. Full exact-head validation,
generic provider-backed media proof, and CI confirmation remain open gates.

### Execution ledger (implementation checkpoint)

The following is the evidence state before the final full validation run. The
ledger deliberately distinguishes code from real production evidence; a local
fixture cannot close the provider or visual-review requirements.

| item | status | commit_sha | implementation and test evidence | artifact/provider state | downstream/external state |
|---|---|---|---|---|---|
| R3-1 | TECHNICALLY_VERIFIED | `2af93a8` | Immutable `direction-v4` revision and `revise-direction` CLI in `direction_service.py`/`editorial_cmd.py`; `uv run pytest -q tests/test_treatment_revisions.py tests/test_treatment_assets.py` (targeted success, stale, binding-mismatch, idempotence, and confinement cases) | No authorized generic provider acquisition is available in the work root for an evidence-complete receipt | Advanced planning revalidates the selected revision; generic provider-backed proof remains open; reviewer `AWAITING_REVIEW` |
| R3-2 | TECHNICALLY_VERIFIED | `2af93a8` | `TreatmentAssetObservation` and `observe-asset` decode/hash sidecars with stale-frame rejection; observation and source-asset binding are checked during revision | No authorized generic visual asset observation is available for a real production packet | Collision/relevance facts are consumed by the shared treatment policy; real decoded generic proof remains open; reviewer `AWAITING_REVIEW` |
| R3-3 | TECHNICALLY_VERIFIED | `2af93a8` | Canonical aligned-word overlap is stored per SFX cue; encoded-window RMS, duck-policy, peak, and silence evidence produce `TreatmentAudioMeasurement` beside viewer evidence. The measurement path/hash now propagates through the Advanced manifest, QA set/cache, preflight, final-review evidence, and delivery facts. `uv run pytest -q tests/test_viewer_evidence.py tests/test_treatment.py` covers pass/fail and sidecar binding | Measurement sidecar is produced only when a real Advanced render reaches decoded viewer evidence; no generic production packet has been authorized in this workspace | QA and delivery reject missing/stale measurement or non-passing intelligibility; the signal test is technical evidence, not semantic human listening; reviewer `AWAITING_REVIEW` |
| R3-4 | TECHNICALLY_VERIFIED | `2af93a8` | `TreatmentEvidenceBundle` is persisted atomically, hash-bound into render input/viewer evidence/QA/final review/cache/delivery; schema export/check passes | No real generic bundle with provider receipts is available to hash into the required production packet | Stale bundle and changed receipt tests are present; provider-backed artifact ledger remains open; reviewer `AWAITING_REVIEW` |
| R3-5 | TECHNICALLY_VERIFIED | `2af93a8` | Shared evaluator is called by direction lint, Advanced planning/preflight, QA, and delivery; multiplicity-aware ownership rejects duplicate/omitted events | No production artifact is being promoted by this checkpoint | Exact-gate checks are implemented; external CI and independent code/visual review remain open; reviewer `AWAITING_REVIEW` |
| R3-6 | IN_PROGRESS | `2af93a8` | No fixture may be substituted for the required authorized generic provider path | The work area has campaign and Envato files, but no persisted authorized **generic non-campaign** source plus complete provider selection/acquisition/license chain for this proof | PR #38 self-hosted `verify-python` is queued for the current head; exact-head CI and authorized production proof are still open |

The code commits are `e0e007c` (`feat: require decoded treatment audio
evidence`), `ba57bcf` (`fix: preserve legacy audio evidence compatibility`),
and `2af93a8` (`feat: bind audio measurements through QA and delivery`).
The final validation run must record its exact resulting HEAD below before any
status can advance.

**Final validation result:** `PENDING — rerun after the QA/delivery audio
measurement binding change`.
**Final CI result:** `PENDING — a queued or different-head job is not a pass`.
**Independent review:** `AWAITING_REVIEW`.

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

## Mandatory completion protocol

The operator must use these statuses for every R3 item:

1. `NOT_STARTED`: no implementation evidence exists.
2. `IN_PROGRESS`: implementation or tests are being changed.
3. `CODE_COMPLETE`: the code path exists, but the complete acceptance
   evidence has not been produced.
4. `TECHNICALLY_VERIFIED`: targeted and full automated checks pass for the
   exact commit, including meaningful failure tests.
5. `EVIDENCE_COMPLETE`: the required real artifacts, decoded frames/audio,
   provider records, rights records, and review receipts exist, are hashed,
   and are bound to the exact plan.
6. `COMPLETE`: only after every item is `EVIDENCE_COMPLETE`, all required
   external gates are green, and independent code and visual review are still
   available. `COMPLETE` must never be inferred from CI alone.

The plan may not report `COMPLETE` when any of these conditions applies:

- a required provider, acquisition, license, source, or generic test asset is
  missing or unauthorized;
- a fixture substitutes for the required real provider-backed production path;
- a digest exists without a readable, hash-matching evidence bundle;
- audio overlap or intelligibility is `unverified` for a treatment with audio
  cues;
- a policy evaluator is not executed at every required gate;
- any rendered event can be duplicated, omitted, or owned by more than one
  treatment decision;
- a browser, Remotion, ffmpeg, or media step is still running or failed;
- CI is queued, cancelled, failed, or reports a different commit SHA;
- the exact output MP4, decoded frame/audio evidence, and manifests have not
  been inspected;
- independent code and visual review has not happened.

## Required evidence ledger

Before changing any item to `EVIDENCE_COMPLETE`, append a row to the round
report containing all of the following. A prose assertion is not evidence.

| Field | Required value |
|---|---|
| item | `R3-1` through `R3-6` |
| status | one of the statuses above |
| commit_sha | exact Git SHA under test |
| implementation_paths | source files and schema files changed |
| test_commands | exact commands and counts, including failure cases |
| artifact_paths | relative paths under the ignored work root |
| artifact_sha256 | hashes of every bundle, MP4, frame sheet, audio report, and rights record |
| provider_rights | provider response, selection, acquisition, license, and registered-byte facts where applicable |
| decoded_evidence | frame timestamps, audio measurements, and inspection result |
| downstream_checks | QA, final review, cache, and delivery verification results |
| external_status | CI job URL/status and any authorized-media limitation |
| reviewer | independent reviewer identity or explicit `AWAITING_REVIEW` |

If a field is unavailable, the item remains `CODE_COMPLETE` or
`TECHNICALLY_VERIFIED`; it cannot become `EVIDENCE_COMPLETE` or `COMPLETE`.

## Required closeout sequence

Execute these steps in order and record each checkpoint:

1. Re-read this plan and the current repository guidance at the actual head.
2. Implement one R3 item without weakening an existing gate.
3. Run targeted success and failure tests for that item.
4. Regenerate schemas and run schema checks when contracts change.
5. Run the full validation suite on the exact commit.
6. Produce the required real/provider-backed artifacts, or record the item as
   blocked by missing authorization; never substitute a fixture silently.
7. Decode and inspect the actual MP4 frames and audio, then hash all evidence.
8. Verify QA, final review, cache invalidation, stale-artifact blocking, and
   local delivery against the same evidence bundle.
9. Check CI status and commit SHA. A queued job is not a pass.
10. Update the ledger and status only after all evidence exists.
11. Stop at draft PR and request independent code and visual review. Do not
    merge or self-approve.

## Exit criteria

R3-1 through R3-5 require code, failure tests, generated schemas where
applicable, and a full validation run. R3-6 requires authorized media and a
runner result. The round remains `REVIEW OPEN — NOT COMPLETE` until every
required evidence-ledger row is `EVIDENCE_COMPLETE`, CI is green on the exact
head, authorized production proof is decoded and inspected, and independent
code and visual review are complete. A local technical pass alone can never
close this plan.
