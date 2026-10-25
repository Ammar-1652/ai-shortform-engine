# Editorial treatment orchestration follow-up fixing plan

**Audit date:** 2026-10-25  
**Audited head:** `e2006ac` (`round-36-editorial-knowledge-engine`)  
**PR:** [#38](https://github.com/Ammar-1652/ai-shortform-engine/pull/38)

This audit checked the implementation against
[the orchestration plan](editorial-treatment-orchestration-plan.md), the
direction/preset/Advanced Hero paths, the asset providers, QA, review, delivery,
and the validation evidence produced by the audited head.

## Audit result

The core technical slice is implemented: `direction-v3`, typed per-beat
states, preset treatment policies, bounded camera events, sparse transition
planning, treatment fingerprints, treatment CLI commands, and restricted
campaign blocks are present and tested. The following claims in the parent
plan still need work before the orchestration layer can be called fully
implemented.

### Remaining gaps

1. **Asset requests stop at a request record.** `TreatmentAssetRequest` is
   emitted and displayed, but there is no typed request-to-provider-response,
   selection, acquisition, license, registered-asset, and final-placement
   chain. Existing Envato/Openverse commands remain independent manual tools.
   A generic preferred preset can therefore stay in `needs_review` without a
   resumable treatment asset stage.
2. **Relevance is declared rather than evaluated.** B-roll query terms come
   from transcript text and clean production checks catalog tags and a
   `relevance_note`. The planner does not use visual subject/source-text/face
   evidence or decoded B-roll observations to prove that the asset helps the
   beat.
3. **Collision planning is textual.** `protected_regions` is a list of names;
   the planner does not calculate face, source-text, caption, logo, CTA, and
   B-roll geometry before accepting camera movement.
4. **Preset policy enforcement is incomplete.** Lint checks selected counts,
   but does not enforce every typed field such as meaningful-beat minimums,
   consecutive B-roll limits, relevance thresholds, scale/drift limits, or
   all speech/SFX overlap rules.
5. **SFX metadata is not the mix authority.** Gain, ducking, and overlap are
   stored in treatment decisions, while the Advanced audio path still relies
   on placement/profile values. No treatment-bound mix result proves applied
   ebur128, true peak, RMS, fades, ducking, or silence windows.
6. **QA/review/delivery bind indirectly.** The treatment fingerprint reaches
   direction, Advanced plan, and render input, but QA, final review, and local
   delivery do not expose and directly verify treatment summaries, request ids,
   policy states, relevance evidence, or the treatment mix result.
7. **Generic production proof is incomplete.** Browser tests prove local
   B-roll/SFX placements and Remotion execution. They do not prove the generic
   preferred-preset path from treatment request through provider selection,
   rights-bound acquisition, placement, and decoded viewer inspection.
8. **CI is not final evidence.** Local validation completed, but the exact PR
   head's `verify-python` check was queued during this audit.

## Fixing workflow

### F0 — Freeze audit evidence

- Preserve this audit and the exact `e2006ac` validation evidence.
- Recheck the exact PR head and CI status before each follow-up commit.
- Keep motion graphics disabled while these gaps are fixed.
- Keep Tarteel's outside-media and no-added-SFX blocks as regression fixtures.

**Gate:** follow-up work starts from the audited head and does not reinterpret
historical direction-v1/v2 artifacts.

### F1 — Complete request-to-asset provenance

Add request ids to `DirectionAssetPlacement` and bind each request to provider
response/selection/acquisition ids, response hash, license evidence hash,
registered asset hash, and an acquisition status. Add a resumable treatment
asset stage that reads requests, invokes the existing provider boundary, lets
Codex select a candidate, revalidates policy and rights, acquires/registers/
probes the asset, and emits an immutable placement bound to the request.

Changed requests, responses, licenses, or bytes must invalidate treatment,
plan, QA, final review, cache, and delivery evidence.

**Tests:** fake image/SFX providers; no-result/provider-unavailable;
missing/changed license; interrupted acquisition; changed bytes; stale
response; prohibited campaign; request-to-placement hash binding.

### F2 — Add visual relevance and collision evidence

Feed current visual analysis and platform-safe geometry into treatment planning.
Record subject/region ids, source-native text, face/active-speaker evidence,
caption/logo/CTA/B-roll rectangles, camera maximum envelopes, collision results,
and decoded relevance observations. Reject or downgrade an asset or camera move
when it is unrelated, obscures important content, or has too little hold time.

**Tests:** related/unrelated assets with identical licenses; face and source-text
collisions; caption/logo/CTA collisions; B-roll hold length; maximum camera
envelope frame samples.

### F3 — Enforce every preset policy field

Use one evaluator from direction lint and Advanced preflight. Enforce meaningful
B-roll/camera minimums, consecutive-B-roll limits, relevance thresholds, role
compatibility, scale/drift bounds, transition density, SFX gain/ducking/overlap,
continuous-dialogue rules, and the graphics enabled/disabled state. Every
downgrade must carry a stable omission or policy-block reason.

**Tests:** one failing case per policy field and one valid plan for every
preset.

### F4 — Make the audio pass authoritative

Add a treatment-bound audio mix result containing selected SFX, source
in-points, requested/applied gain/fade/duck values, speech-overlap windows,
silence windows, ebur128/LRA/true-peak/RMS facts, intelligibility status, and
the audio policy fingerprint. The Advanced audio builder must consume this
result or fail. Omitted/blocked SFX must produce no added audio.

**Tests:** source-only, selected SFX, loud/clipping SFX, ducking, continuous
speech, silence, changed mix policy, and decoded audio proof.

### F5 — Bind treatment evidence to QA, review, and delivery

Extend the existing QA/viewer-evidence/final-review/delivery payloads with the
treatment fingerprint and summary, request ids, selected/rejected assets,
policy states, omission reasons, relevance/collision evidence, audio mix hash,
and camera/transition evidence. Stale or missing treatment facts must block the
existing gates; do not create a parallel approval system.

**Tests:** stale treatment QA, stale final approval, stale delivery, missing
treatment evidence, and promotion rollback preserving the prior package.

### F6 — Prove the generic path with encoded output

Use an authorized generic campaign source to render:

- a preferred-preset clip with relevant B-roll and SFX selected through the
  request/acquisition stage;
- a no-asset fallback with explicit omissions;
- a multi-cut clip with camera movement and one semantic transition;
- a restricted campaign clip proving policy blocks.

Decode each MP4 around beats, cuts, camera extremes, transitions, B-roll, and
SFX. Inspect complete audio and muted playback, safe areas, relevance, sync,
and audio balance. Record hashes, provider/license facts, frame evidence,
ebur128/true-peak/RMS, and exact paths.

**Gate:** the generic clip proves the user-facing treatment workflow; the
restricted fixture proves safe omission.

### F7 — Close the audit

Rerun `./scripts/validate.sh`, the full renderer checks, and CI on the exact
head. Update the parent plan with actual counts and output paths. Mark only
verified phases complete and retain external limitations explicitly.

## Completion condition

The parent plan may be marked fully implemented only after every gap above has
an implementation, a failure test, and decoded production evidence. Until
then its status is **technical slice implemented; follow-up required**.

