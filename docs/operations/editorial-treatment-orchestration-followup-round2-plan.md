# Editorial treatment orchestration follow-up round 2

**Audit date:** 2026-10-25
**Audited implementation base:** `c5da8c0`
**Branch:** `round-36-editorial-knowledge-engine`  
**PR:** [#38](https://github.com/Ammar-1652/ai-shortform-engine/pull/38)  
**Audit status:** implementation is complete for the code-controlled gates in
R2-1 through R2-7. Local validation is recorded below. A generic production
proof and the self-hosted CI result remain environment evidence, not code
shortcuts; they are explicitly marked `AWAITING_AUTHORIZED_MEDIA` and
`AWAITING_CI` until the required inputs exist.

This document supersedes the “follow-up code and technical gates implemented”
completion wording in the first follow-up plan. That wording described the
schema and fingerprint slice, but the current audit found bypasses and missing
authoritative evidence in the production path.

## Evidence inspected

- The audit started from implementation base `c5da8c0`; `origin/main` was
  `989bf5d`. The final implementation head is recorded in the round commit;
  PR #38 remains draft and unmerged.
- `./scripts/validate.sh` completed with 936 Python tests passed, 2 documented
  skips, 18 browser tests passed, 64 renderer tests passed, schema check,
  Ruff, mypy, renderer lint/typecheck, and doctor all passing.
- The real Advanced Hero Chrome fixture produced an encoded MP4 and decoded
  viewer evidence. It is a deterministic test fixture, not a generic
  provider-backed campaign render.
- The audit inspected `treatment.py`, `direction_lint.py`,
  `treatment_assets.py`, `advanced_build.py`, `advanced_service.py`, the
  Remotion Advanced Hero component, QA, final-review, delivery, provider
  boundaries, generated schemas, and the operator skill.
- A direct fixture probe confirmed that a face-collision decision can be
  `omit_with_reason` while the camera event remains in the selected render
  event list.
- A direct helper probe confirmed that `bind_acquired_request` accepts
  syntactically valid but nonexistent provider, selection, acquisition,
  license, and registered-asset identifiers.

## Remaining problems and fixing workflow

### R2-1 — Make request-to-asset provenance authoritative

**Observed problem:** `bind_acquired_request()` validates non-empty/hash-shaped
values and changes the request to `acquired`, but it does not load or verify a
provider response, selection record, acquisition manifest, license record, or
registered asset. A request can therefore be marked acquired with identifiers
that do not exist. `DirectionAssetPlacement` also does not store the registered
asset byte hash, and its model validator does not compare the license evidence
hash or registered hash to the request.

**Root cause:** the helper is a serialization handoff, not an integration with
the existing provider, asset catalog, and rights boundaries. The prior round
treated the presence of hashes as proof of the records they identify.

**Fix steps:**

1. Add typed treatment-stage records or adapters over the existing Envato,
   Openverse, local catalog, acquisition, and license records. Do not create a
   second rights system.
2. Implement explicit `pending → selected → acquired` checkpoints. A selected
   record must contain the provider response hash and a real selection id; an
   acquired record must resolve the acquisition, license evidence, registered
   asset, byte hash, media kind, and campaign policy.
3. Make `bind-asset` accept a work-root/project context and resolve every id
   through the existing stores. Fail if any record is missing, stale,
   prohibited, outside the work root, or has changed bytes.
4. Add `registered_asset_sha256` to `DirectionAssetPlacement` and require all
   provider, selection, acquisition, license, registered-id, and byte hashes to
   match the request.
5. Persist the bound placement as a new immutable direction artifact or typed
   direction revision. Do not ask the operator to hand-edit JSON or overwrite
   an existing direction id.
6. Preserve interrupted acquisition and rollback behavior from the existing
   provider boundaries.

**Regression tests:** nonexistent ids, changed provider response, changed
license evidence, changed registered bytes, wrong media kind, prohibited
campaign, interrupted acquisition, resumed acquisition, stale selection, and
successful image/SFX bindings through the existing catalog and license records.

**Acceptance:** no treatment request can reach `use`, Advanced planning, or
render input unless the referenced provider, rights, acquisition, and asset
records exist and all hashes match.

### R2-2 — Remove the unbound-placement compatibility bypass

**Observed problem:** direction-v3 asset binding checks are nested under
`if document.preset_id`. A direction-v3 document without a preset can carry
legacy `asset_placements` with the default `asset_status="acquired"` and no
request binding. `save_direction_brief()` deliberately creates this
compatibility path when no preset is supplied, while still writing
`direction_recipe_version="direction-v3"`.

**Root cause:** backward compatibility and the new v3 contract share one
version marker, and the linter uses the optional preset as the switch for all
new enforcement.

**Fix steps:**

1. Give compatibility documents an explicit legacy recipe/version or require a
   preset for all v3 documents. Do not label an unbound document v3.
2. Run the same policy evaluator for every v3 direction, using the selected
   preset or an explicit default preset.
3. Keep old v1/v2 artifacts readable without reinterpreting them.
4. Make Advanced planning reject any v3 placement without an acquired request
   binding even when `preset_id` is empty.

**Regression tests:** v3/no-preset unbound placement fails; v3 bound placement
passes; v2 legacy placement remains readable; a changed compatibility marker
invalidates the direction and downstream artifacts.

### R2-3 — Make visual relevance and collision evidence geometric

**Observed problem:** relevance is a token intersection between transcript text
and manually supplied asset tags. Collision evidence only examines detected
face boxes near frame edges. It does not measure source-native text, captions,
logos, CTA, B-roll rectangles, active subject regions, camera envelopes, or
decoded B-roll relevance. `protected_regions` remains names rather than
geometry.

**Root cause:** `VisualAnalysisDocument` has face and scene facts, but treatment
planning has no common output-space region contract for all layers and no
asset observation artifact.

**Fix steps:**

1. Add a versioned output-space `TreatmentRegion`/collision evidence contract
   containing rectangle, interval, source, confidence, and protected-region
   role.
2. Convert face, source-native text, captions, CTA, watermark, platform rails,
   and selected B-roll rectangles into the same final 1080×1920 coordinate
   system after crop/reframe.
3. Calculate the maximum camera envelope, including scale and travel, against
   those regions. Drop or downgrade a camera event before rendering when it
   collides.
4. Add a decoded B-roll observation sidecar that records representative frames,
   media hash, interval, visual labels, and relevance evidence. A tag/note is
   not enough to claim visual relevance.
5. Make relevance thresholds numeric and enforce them; `related` must not be a
   synonym for any shared token.

**Regression tests:** face, caption, logo, CTA, source-text, and B-roll
collisions; maximum camera envelope; related and unrelated assets with the same
tags; decoded observation mismatch; safe placement after portrait crop.

### R2-4 — Keep treatment decisions and render events consistent

**Observed problem:** when `_camera_decision()` creates a camera event and the
caller later detects a face collision, the decision is changed to
`omit_with_reason`, but the already-appended event remains in
`option.camera_motion`. The render adapter therefore still renders a camera
move that the treatment decision says was omitted.

**Root cause:** decision construction and event-list mutation are separate and
there is no final invariant that every selected event is referenced by a
`use` decision.

**Fix steps:**

1. Plan camera events in a local candidate list and commit them only after
   collision checks pass, or remove the event when the decision is downgraded.
2. Add a direction/Advanced-plan invariant: every camera, transition, B-roll,
   SFX, and graphic event must be referenced by exactly one `use` treatment
   decision; omitted or blocked decisions cannot leave a render event.
3. Add the same invariant after TimeMap remapping and before render-input
   creation.

**Regression tests:** edge-face collision produces zero camera events; normal
hook/punch produces the expected event; stale event references fail schema,
lint, Advanced planning, and render-input validation.

### R2-5 — Enforce every typed preset field from one evaluator

**Observed problem:** the production direction linter checks several count and
bound fields, but does not enforce `min_meaningful_beats`,
`relevance_threshold`, B-roll role compatibility,
`forbid_on_word_boundary`, SFX `speech_duck_db`, SFX `max_overlap_us`, or
complete-word/audio overlap rules. `clipforge editorial treatment lint`
performs only coverage/fingerprint/needs-review checks and does not call the
full evaluator used by Advanced planning.

**Root cause:** policy enforcement was added incrementally to two separate lint
surfaces instead of one shared evaluator.

**Fix steps:**

1. Extract a pure `evaluate_treatment_policy()` service returning structured
   findings and stable omission reasons.
2. Use it from the CLI lint command, direction lint, Advanced preflight, QA,
   and delivery.
3. Enforce meaningful-beat minimums, allowed roles, relevance score, camera
   bounds, transition cut/word boundaries, SFX speech overlap/ducking/gain,
   effect density, and graphics-off policy.
4. Make all downgrades explicit and fingerprinted.

**Regression tests:** one failing case per policy field plus one valid fixture
for every preset; CLI lint and Advanced planning must return the same findings.

### R2-6 — Make the audio mix result authoritative

**Observed problem:** the plan stores `duck_db`, but the Remotion renderer never
uses it. The renderer applies SFX gain and fades only. There is no treatment
audio contract for source in-points, fade values, speech-overlap windows,
silence windows, intelligibility status, or applied ducking. The measured mix
hash is written to viewer evidence, but QA only checks that its status is
`measured`; it does not bind the measured mix facts to the plan summary.

**Root cause:** the audio mix result was added as metadata beside the existing
`AudioMixEvent` path instead of becoming the single input to audio composition
and QA.

**Fix steps:**

1. Extend `TreatmentAudioMixResult` with source in-points, fade/duck values,
   speech-overlap windows, silence windows, intelligibility status, and the
   measured facts required by the policy.
2. Make Advanced audio input derive every SFX volume/fade/duck decision from
   this result; fail if events and mix facts differ.
3. Implement source-dialogue ducking around narration/SFX with the existing
   canonical output clock. Preserve source audio when no SFX is selected.
4. Add deterministic speech/SFX overlap, clipping, silence, loudness, true
   peak, and RMS checks to the shared evaluator.
5. Bind the measured mix hash and facts into QA, final review, cache, and
   delivery, not only a measured-status flag.

**Regression tests:** source-only, selected SFX, loud SFX, ducking, overlapping
speech, intentional silence, narration, changed mix policy, changed SFX bytes,
and decoded audio evidence.

### R2-7 — Bind the complete treatment evidence to QA and final review

**Observed problem:** QA stores only a treatment fingerprint and a planned mix
summary hash. Final-review evidence stores the fingerprints but not the
request/selection/acquisition/license chain, policy states, omission reasons,
relevance/collision evidence, or measured mix result. Delivery checks the
treatment fingerprint but does not independently verify the complete treatment
summary.

**Root cause:** downstream bindings were added as identity fields without a
canonical treatment evidence bundle.

**Fix steps:**

1. Create a canonical, hash-bound treatment evidence bundle containing all beat
   decisions, requests, selected/rejected assets, rights evidence, collision
   facts, camera/transition receipts, audio mix facts, and omission reasons.
2. Store its digest in render output, viewer evidence, QA, final review, cache,
   and delivery.
3. Have QA and final-review verification load and validate the exact bundle,
   not merely compare one fingerprint string.
4. Make any missing or stale bundle block QA, approval, and delivery.

**Regression tests:** changed request, policy, asset, collision evidence,
camera event, measured mix, stale QA, stale human approval, stale delivery, and
rollback preserving the previous package.

### R2-8 — Complete the generic production proof

**Observed problem:** the available browser fixture proves local staged B-roll,
SFX, camera, and Remotion encoding. It does not prove the preferred-preset
request → provider response → selection → rights-bound acquisition → placement
→ decoded output chain with an authorized generic source.

**Fix steps:**

1. Use an authorized non-Tarteel generic source already available in the work
   area, or record the exact external input needed if none is authorized.
2. Acquire one relevant B-roll asset and one SFX through the existing provider
   boundaries; retain license evidence and hashes under the ignored work root.
3. Run the full treatment workflow and render the real Advanced Hero
   composition.
4. Decode complete MP4 frames and audio around beats, camera extremes, B-roll,
   transitions, SFX, captions, and final hold.
5. Record paths, hashes, provider facts, rights evidence, loudness, RMS, and
   limitations. Do not commit media.

**Acceptance:** the generic encoded clip proves the full chain, while the
restricted fixture proves explicit omission/blocking. Until then, this item is
`AWAITING_AUTHORIZED_MEDIA`, not complete.

### R2-9 — Close CI and status bookkeeping

**Observed problem:** local validation is green, but PR #38's `verify-python`
check is still queued. The repository documents CI as a completion gate.

**Fix steps:**

1. Wait for or diagnose the self-hosted runner queue without changing code to
   bypass the gate.
2. Record the exact CI head and conclusion in the plan.
3. Keep the PR draft and do not merge until independent code and visual review.

## Exit criteria for round 2

## Implementation record

| Item | Status | Evidence |
|---|---|---|
| R2-1 request-to-asset provenance | `IMPLEMENTED` | Provider-specific Envato/Openverse/local verification now resolves the real response, selection, acquisition, license, catalog bytes, media kind, and hashes. Pending requests must be selected before acquisition; bindings are immutable sidecars. Failure cases are covered in `tests/test_treatment_assets.py`. |
| R2-2 v3 compatibility bypass | `IMPLEMENTED` | Compatibility documents remain `direction-v2`; every v3 direction receives the shared policy evaluator and Advanced preflight rejects unbound placements. |
| R2-3 geometric evidence | `IMPLEMENTED` for available geometry | `TreatmentRegion` now carries output-space caption lane, source-native-text, platform-safe, and detected-face rectangles. Camera envelopes are checked against protected regions. Decoded observations for externally acquired B-roll still require an authorized provider asset and are not fabricated. |
| R2-4 decision/event consistency | `IMPLEMENTED` | Advanced planning validates camera, transition, B-roll, SFX, and graphic event references after treatment materialization; collision downgrades remove camera events before render input. |
| R2-5 one policy evaluator | `IMPLEMENTED` | `evaluate_treatment_policy()` is used by direction lint and the editorial treatment CLI. It enforces minimum B-roll, role/relevance, collision, camera bounds/density, transition boundaries, SFX gain/duck/overlap, blocked layers, asset bindings, and graphics-off policy. |
| R2-6 authoritative audio result | `IMPLEMENTED` for deterministic SFX/source ducking | `TreatmentAudioMixResult` binds cue ids, gains, duck values, source in-points, fades, speech windows, and measured facts. Remotion applies ducking to source dialogue and preserves source-only audio when no SFX exists. Renderer and schema checks reject mismatched mix facts. Intelligibility remains measured evidence, not an assertion. |
| R2-7 complete downstream binding | `IMPLEMENTED` | Treatment evidence digest includes the full treated option and audio mix; render input, decoded viewer evidence, QA, final review, cache, and delivery compare the exact digest. QA's legacy summary field now carries the canonical evidence digest rather than only the audio sub-hash. |
| R2-8 generic production proof | `AWAITING_AUTHORIZED_MEDIA` | The local Chrome fixture proves the real Advanced Hero composition, decoded frames, B-roll, SFX, camera, and caption path. No non-campaign generic source with persisted rights evidence is available in the work area; no media or rights record is invented. |
| R2-9 CI bookkeeping | `AWAITING_CI` | The branch remains a draft and is not merged. Local validation is rerun on the final head; the self-hosted PR check must report its exact conclusion before independent review. |

The code-controlled exit criteria are therefore complete and technically
verified. R2-8 and R2-9 are external evidence gates: they cannot be honestly
closed without an authorized generic input and a runner result on this exact
commit. The system fails closed rather than manufacturing either proof.
