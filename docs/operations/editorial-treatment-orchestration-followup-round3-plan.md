# Editorial treatment orchestration follow-up round 3

**Review date:** 2026-10-27
**Reviewed head:** `df74bed5854706fafb9b632b5a58a90a29d58240`
**Branch:** `round-36-editorial-knowledge-engine`
**PR:** [#38](https://github.com/Ammar-1652/ai-shortform-engine/pull/38)
**Purpose:** close the evidence and integration gaps found when reviewing the
round-2 implementation against its own acceptance criteria.

**Current status:** `REVIEW OPEN — NOT COMPLETE`.

This status is intentional. Passing local tests, completing a code slice, or
having a draft PR does not authorize changing this plan to `COMPLETE`.

**Implementation checkpoint:** R3-1 through R3-5 have code paths, targeted
failure coverage, a full validation run, and a real provider-backed Advanced
Hero packet. R3-6 is technically exercised with a non-Tarteel campaign source,
but its acceptance gates remain open because this packet has no independently
reviewed speech inventory, no human final playback decision, no local delivery,
and no CI runner result.

### Execution ledger (implementation checkpoint)

The following is the evidence state at the current reviewed head. The ledger
deliberately distinguishes code from real production evidence; a provider
render is still not a human final approval.

| item | status | commit_sha | implementation and test evidence | artifact/provider state | downstream/external state |
|---|---|---|---|---|---|
| R3-1 | TECHNICALLY_VERIFIED | `df74bed` | Immutable `direction-v4` revision and `revise-direction` CLI re-run source-evidence validation, direction lint, motion/preset binding, shared treatment policy, and provider/rights checks before publication; targeted revision/asset tests cover stale, binding-mismatch, idempotence, and confinement cases | Real selected direction is persisted in `var/round3-provider-proof/.../advanced-hero/plans/44532.../direction.json`; the treatment bundle records Drive visual and Envato SFX receipts | Advanced planning consumed the revision and pilot; no human final review; reviewer `AWAITING_REVIEW` |
| R3-2 | TECHNICALLY_VERIFIED | `df74bed` | `TreatmentAssetObservation` and `observe-asset` decode/hash sidecars with source-span sampling, stale-frame rejection, immutable cache behavior, and failed-promotion cleanup; bindings fail closed without observations | Two real observations exist under `var/round3-provider-proof/editorial/treatment-observations/`; their frame hashes are embedded in the treatment bundle | Relevance/collision facts reached planning and render input; no human visual acceptance; reviewer `AWAITING_REVIEW` |
| R3-3 | TECHNICALLY_VERIFIED | `df74bed` | Canonical aligned-word overlap is stored per SFX cue. Decoded-window RMS compares the encoded output against staged speech and SFX references, applies gain/duck policy, requires a non-negative margin, and records `decoded_window_signal_v2`; targeted tests cover v1 compatibility, v2 success, missing references, stale sidecars, resume restaging, and failure cases | Real measurement: `treatment-audio-measurement.json` sha256 `42ebf986d1d637cba550b152f56ba90db78103cb43e5e518c1d8d18819ee8cf9`; integrated `-17.1 LUFS`, true peak `-1.4 dBFS`, margins `12.78 dB` and `4.19 dB` | `qa verify` passes the evidence binding; `qa gate` remains blocked by separate caption speech inventory insufficiency; human listening is still required |
| R3-4 | TECHNICALLY_VERIFIED | `df74bed` | `TreatmentEvidenceBundle` is persisted atomically and embeds validated provider/license receipts, observations, frame hashes, policy decisions, and measured audio facts; it remains hash-bound into render input/viewer evidence/QA/final-review/cache/delivery; schema export/check passes | Real bundle `var/round3-provider-proof/.../treatment-evidence.json` sha256 `84f60c498bc39e895502646c888f58311ca32569c564658c446ab9e1f7750268` | The bundle is readable and hash-bound; final review/delivery remain blocked by QA status and no human approval |
| R3-5 | TECHNICALLY_VERIFIED | `df74bed` | Shared evaluator is called by direction lint, Advanced planning/preflight, QA, and delivery; multiplicity-aware ownership rejects duplicate/omitted events. The resume evidence path and bounded encoded-duration comparison are now covered by tests | Real render consumed exactly the selected treatment event set; no duplicate event receipt was accepted | Full automated validation passes; CI is still pending and independent code/visual review is still required |
| R3-6 | TECHNICALLY_VERIFIED | `df74bed` | Provider-backed acquisition, rights, observation, revision, Remotion render, decoded evidence, QA verification, and delivery preflight paths are exercised by a real non-Tarteel campaign source selected from the authorized Drive root plus a live Envato request boundary; no fixture substituted for the render path | Source sha256 `960ac26e8828bd4235bf4aa58ba6d334fb4415febf4d2a3dd97428b9c2f41b0c`; Advanced MP4 `var/round3-provider-proof/.../advanced.mp4` sha256 `6ec70f23aa18e95a33b7420e32426f428a895d8bcda98095585e6d8a7dc22313`; viewer bundle sha256 `9681ea65d05e8c084715fcc2b2d44905beda4f8aeb275751f6d8b63f53d96274`; contact sheet sha256 `a68cbd96b06465a801ec3ac1542e383f0ff6a9459627211f4f711663e23136f1` | `qa verify` PASS; `qa gate` blocked (`technical insufficient_evidence`, campaign PASS); final review verify blocked `qa_failed`; publish plan blocked `QA status is insufficient_evidence`; CI has no registered self-hosted runner; independent review `AWAITING_REVIEW` |

**R3-6 exact external input required to close the round:**

1. A generic, non-campaign video source placed under the ignored work root,
   with a persisted source ingest record and a `campaign_provided` or provider
   license record whose evidence URI and bytes are verifiable.
2. One relevant visual asset and one SFX selected through an existing provider
   boundary, each with provider response, selection, acquisition, license, and
   registered-byte hashes. A fixture or unlicensed file cannot substitute.
3. Permission to run the generic proof through direction revision, observation,
   Advanced Remotion render, decoded viewer evidence, QA, final review, and
   local delivery. The resulting MP4, frames, audio report, and manifests stay
   under the ignored work root.
4. An online self-hosted runner carrying the `self-hosted`, `linux`, `x64`, and
   `clipforge` labels. The repository currently reports zero registered runners,
   so the queued CI check cannot start from this checkout.

The code commits are `e0e007c` (`feat: require decoded treatment audio
evidence`), `ba57bcf` (`fix: preserve legacy audio evidence compatibility`),
`19a4ede` (`feat: compare decoded speech and effect references`),
`91bc774` (`fix: fail closed on incomplete speech comparison`),
`2af93a8` (`feat: bind audio measurements through QA and delivery`),
`58bba9a` (`feat: embed treatment observations in evidence bundles`),
`500fcdc` (`fix: re-lint treatment direction revisions`), and `537acba`
(`style: format direction revision gate`), and `df74bed`
(`fix: close treatment evidence resume gaps`).
The final validation run must record its exact resulting HEAD below before any
status can advance.

**Exact-head validation result:** `TECHNICALLY_VERIFIED` on
`df74bed5854706fafb9b632b5a58a90a29d58240`:
`./scripts/validate.sh` passed. It records `956 passed, 2 skipped, 18
deselected` in the non-browser partition (VoiceStudio unavailable; Whop not
configured), `18 passed, 958 deselected` in the browser/Remotion partition,
and 64 renderer tests. Ruff, format, mypy, schema check, renderer
lint/typecheck, and doctor (10 pass, 0 warn, 0 fail) also passed. No Chrome,
Node renderer, or ffmpeg worker remains running.

The full provider-backed render was also rerun after the resume and evidence
path fixes. `ffprobe` reports H.264/AAC, 1080x1920, 30/1, 1031 frames,
34.366667 seconds of video and 34.334312 seconds of audio; ebur128 reports
`-17.1 LUFS` and `-1.4 dBFS` true peak. The contact sheet at
`var/round3-provider-proof/projects/f40435ed-77d3-43fc-9fb8-042aea1381f0/sources/2783aafe-9465-4f8e-8177-82d61aaa6f6c/advanced-hero/runs/425e40f4-6736-4a85-abf0-d3ceda05188b/candidates/44532ef7-4f4f-5674-83cd-3e7956b7ccea/viewer-evidence/contact-sheets/full-001.jpg`
was inspected visually. It shows the source, captions, selected contextual
visual, and restrained SFX treatment at the sampled times.
**Final CI result:** `PENDING — a queued or different-head job is not a pass`.
**Independent review:** `AWAITING_REVIEW`.

### Real provider-backed proof packet

The operator selected the Jingle Jared / Rebel Audio campaign from the
authorized Google Drive root. This is a real non-Tarteel campaign source that
exercises the generic profile, but it is not the separate non-campaign source
requested by the original R3-6 acceptance text. Its campaign eligibility is
recorded as `unknown`, so it remains a draft-only proof.

Provider chain used by the packet:

- Drive source: `var/round3-provider-proof/media/what-is-rebel-audio.mp4`,
  sha256 `960ac26e8828bd4235bf4aa58ba6d334fb4415febf4d2a3dd97428b9c2f41b0c`.
- Drive visual asset: registered campaign asset
  `campaign-45f7424d3b56d8ec5b622de4579613520743284c353c6f4ce7a9f3569454e876`,
  with observation `observation-0c99405978f6c7a7aba7fba6bc69b4a8c50702664608e7e508371b6c856dd47f`.
- Envato request: `9ea9ea20-9241-4dbe-8f9b-e392030f611b`; registered SFX
  asset `env-d30e52d3437c505fec60-tag-c3c2e06d`; license certificate sha256
  `9ab3b1dc844d1247253d102bc71b45df834ebca1266d249ae50e6c5c90b73c9f`.
- Canonical treatment bundle:
  `var/round3-provider-proof/projects/f40435ed-77d3-43fc-9fb8-042aea1381f0/sources/2783aafe-9465-4f8e-8177-82d61aaa6f6c/advanced-hero/plans/44532ef7-4f4f-5674-83cd-3e7956b7ccea/treatment-evidence.json`,
  sha256 `84f60c498bc39e895502646c888f58311ca32569c564658c446ab9e1f7750268`.
- Reviewable MP4:
  `var/round3-provider-proof/projects/f40435ed-77d3-43fc-9fb8-042aea1381f0/sources/2783aafe-9465-4f8e-8177-82d61aaa6f6c/advanced-hero/runs/425e40f4-6736-4a85-abf0-d3ceda05188b/candidates/44532ef7-4f4f-5674-83cd-3e7956b7ccea/advanced.mp4`,
  sha256 `6ec70f23aa18e95a33b7420e32426f428a895d8bcda98095585e6d8a7dc22313`.
- Viewer evidence bundle sha256
  `9681ea65d05e8c084715fcc2b2d44905beda4f8aeb275751f6d8b63f53d96274` and
  decoded audio measurement sha256
  `42ebf986d1d637cba550b152f56ba90db78103cb43e5e518c1d8d18819ee8cf9`.

The real packet proves the provider, observation, render, and encoded-audio
paths. It does not prove that all audible speech was independently reviewed:
the caption evidence remains `speech_coverage_status=insufficient_evidence`.
That is why `qa verify` passes its bindings while `qa gate` blocks with
`technical insufficient_evidence`; final-review verification and publish
preflight correctly remain blocked rather than being manufactured.

The same Advanced render command without `--force` returned `cache_hit: true`
for set `425e40f4-6736-4a85-abf0-d3ceda05188b`; `editorial treatment lint`
returned `status=pass`, and the registered Envato SFX returned
`status=verified`, `rights_status=allowed`, and `renderable=true`.

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
