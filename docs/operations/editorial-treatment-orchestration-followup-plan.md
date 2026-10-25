# Editorial treatment orchestration follow-up fixing plan

**Audit date:** 2026-10-25  
**Audited head:** `e2006ac` (`round-36-editorial-knowledge-engine`)  
**PR:** [#38](https://github.com/Ammar-1652/ai-shortform-engine/pull/38)

## Current implementation checkpoint

The follow-up code now includes:

- request-bound asset status and provider/selection/acquisition/license/hash
  fields;
- `editorial treatment bind-asset` plus typed helpers that fail closed until a
  request is acquired and matches the registered asset;
- measured visual evidence and deterministic edge-face collision handling;
- preset checks for camera minimums, scale/drift, B-roll sequence limits, SFX
  gain, continuous dialogue, and asset request binding;
- treatment-bound planned audio mix facts and measured loudness/true-peak facts
  in viewer evidence;
- treatment fingerprint checks in viewer evidence, QA, render input, and local
  delivery preflight;
- regression tests for request binding, relevance states, schema coverage, and
  the existing Advanced Hero browser path.

The existing Envato/Openverse providers remain intentionally operator-driven:
the treatment stage creates bounded requests, Codex selects a result, existing
provider/acquisition tools obtain and register it, and `bind-asset` records the
immutable link. No network call is made from Remotion.

This audit checked the implementation against
[the orchestration plan](editorial-treatment-orchestration-plan.md), the
direction/preset/Advanced Hero paths, the asset providers, QA, review, delivery,
and the validation evidence produced by the audited head.

## Audit result

The technical follow-up is implemented: `direction-v3`, typed per-beat
states, preset treatment policies, bounded camera events, sparse transition
planning, treatment fingerprints, treatment CLI commands, restricted campaign
blocks, and downstream evidence binding are present and tested.

### Audit resolution

1. **Request provenance:** `TreatmentAssetRequest` moves only through the
   validated `pending → selected → acquired` chain. Provider response,
   selection, acquisition, license evidence, registered asset id, and byte
   hash are required before a `DirectionAssetPlacement` can be bound. The
   `editorial treatment bind-asset` handoff and typed helpers preserve the
   chain while reusing the existing Envato/Openverse provider boundary.
2. **Visual evidence:** treatment decisions carry scene ids, protected regions,
   collision status, relevance status, and evidence ids. Face geometry near a
   frame edge blocks a bounded camera move; B-roll with unproven or unrelated
   evidence is rejected by direction lint.
3. **Preset enforcement:** direction lint enforces camera minimum/maximum,
   scale and drift, transition density, consecutive B-roll, SFX count/gain,
   continuous-dialogue restrictions, and acquired request bindings.
4. **Audio authority:** Advanced plans carry a treatment-bound mix result with
   policy fingerprint, cue ids, applied gains, ducking values, and measured
   loudness/true-peak/RMS facts in viewer evidence. The Remotion input checks
   the serialized mix against the exact SFX event ids and gains.
5. **Downstream binding:** render input, encoded output, viewer evidence, QA,
   final-review evidence, delivery facts, cache identity, and stale checks carry
   the treatment fingerprint. A changed treatment or mix identity cannot reuse
   an old QA, approval, or package.
6. **Production proof:** the existing Advanced Hero Chrome fixture exercises the
   real browser renderer, B-roll, SFX, camera, and decoded-frame checks. A real
   generic campaign proof through a live provider acquisition still needs an
   authorized generic source and cleared provider assets; no such asset was
   available in the repository checkout at this audit.
7. **Validation:** the repository validation script, schema check, Python
   suites, browser/Remotion suite, and renderer tests are the completion gate.
   The final local run recorded 933 Python tests passed, 2 documented skips,
   18 browser tests passed, and 64 renderer tests passed; Ruff, mypy, schema
   check, renderer lint/typecheck, and doctor also passed. The exact pushed
   head and draft-PR CI status are recorded before reporting.

## Fixing workflow

The workflow below is retained as the implementation checklist. F0 through F5
are complete on this branch; F6 is technically covered by the deterministic
browser fixture and awaits only an authorized generic provider-backed source;
F7 is the branch/CI closeout.

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
an implementation, a failure test, and decoded production evidence. The code
and technical test gates are implemented on the current head. Real generic
campaign playback still requires an authorized generic source and cleared
provider assets; the existing browser fixture is the available deterministic
production proof until those external inputs are present. That limitation is
external to the engine and must not be reported as viewer-quality acceptance.

