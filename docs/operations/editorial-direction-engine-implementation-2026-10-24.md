# Editorial Direction Engine implementation report

**Branch:** round-36-editorial-knowledge-engine  
**Baseline:** 4ac0748bbf8efa4dc7f66f6de5b6904945bd824e  
**Status:** IMPLEMENTED W0–W8 pre-human contracts and binding gates plus the deep-integration slice (knowledge byte verification, direction comparison, camera/transition contracts, native recipe routing, pilot receipts, viewer evidence, and delivery/final-review dependency binding); TECHNICALLY VERIFIED on the existing real Tarteel Hero and Advanced Hero paths; HUMAN VISUAL ACCEPTANCE remains pending.

## Implemented

* Strict knowledge contracts for pinned sources, observations, evaluation
  cases, guidance cards, narrative patterns, style cards, conflicts, releases,
  context bundles, decision alternatives, traces, feedback, and reference
  metrics/analysis.
* Local knowledge release at
  configs/editorial/knowledge/library.json, with source hashes for the
  current motion-direction skill, Tarteel style library, iart lock, and native
  Remotion motion source.
* Deterministic local retrieval scoped by language, platform, campaign/profile,
  and tags. Contexts carry source facts, unknowns, selected/rejected ids,
  knowledge release id, source hashes, and motion-catalog fingerprint.
* CLI commands for knowledge doctor, verify, list, show, context, feedback,
  reference analysis/show/verify/propose-style-card, and motion catalog
  doctor/list/show/verify.
* Direction plans can bind a hash-verified knowledge context and optional
  decision trace through the knowledge-context and knowledge-decision-trace
  options.
* Twenty-one approved local motion recipes routed to existing deterministic Remotion
  component ids, with fallbacks, purposes, bounded parameters, language and
  profile compatibility, provenance, and recipe fingerprints.
* Knowledge verification now rehashes every local source locator beneath the
  repository root and fails on changed, missing, escaping, or symlinked bytes.
  The direction skill source hash is refreshed whenever that skill changes.
* Direction options now carry optional bounded `camera_motion` and narrative
  `transitions`. The builder converts them into Advanced Hero render events;
  the renderer applies frame-derived camera transforms, and transition choices
  remain tied to interior TimeMap cuts. Historical direction documents with
  empty arrays remain readable.
* `clipforge editorial direction compare` reports the deterministic ranking and
  layer counts for a three-option brief without writing or approving anything.
* Authorized local reference intake that runs ffprobe, deterministic scene
  detection, scene-midpoint frame decoding, contact-sheet generation, and
  ebur128 when audio exists. It records duration, audio duration, loudness,
  true peak, median shot duration, and cut density with evidence logs while
  keeping hook, transcript, caption, payoff, CTA, and stem identity unknown
  until evidence exists. Measured references can produce an inactive,
  reviewable style-card proposal.
* Openverse discovery and selection contracts/provider boundary. Live access is
  disabled by default; fake/offline normalization, bounded requests, license
  evaluation, response hashes, independent evidence matching, and immutable
  selection sidecars are implemented. Verified selections can be acquired
  through a confined, hashed, ffprobe-validated path and registered through the
  existing local asset/license boundary.
* Operator catalogue entries and agent documentation route these capabilities
  through the Codex/system/human role model.
* Campaign execution writes a hash-bound checkpoint and JSONL stage journal;
  `campaign resume` reuses only source records that pass current evidence
  checks. Release snapshots bind code/config dependencies to the checkpoint,
  and force attempts use a new checkpoint identity.
* Advanced plans, render inputs, draft outputs, cache records, QA direction
  checks, and the Remotion worker carry knowledge-context and decision-trace
  fingerprints. Direction lint blocks invalid source continuity and excessive
  optional layer density before planning.
* Openverse selections with independently verified evidence can be acquired
  into a confined, hashed, ffprobe-validated local manifest. Acquisition does
  not itself register an editorial asset or grant campaign permission.
* Clean Tarteel Advanced Hero now stages the exact Amiri Quran font bound by
  the reviewed Quran sidecar, rejects stale or unconfined font bytes, and
  includes the font dependency in the render identity.
* Caption evidence decoding uses bounded FFmpeg frame batches instead of one
  unbounded `select` expression, so long word-level Arabic coverage cannot
  fail after a successful render because the expression parser is too long.
* Tarteel CTA placement now considers a reviewed upper foreground slot,
  avoids a visible source logo, prefers the payoff beat when every candidate
  overlaps speech, and excludes top-clipped detector boxes from automatic
  placement. The mandatory decoded overlay-exclusion sidecar remains the
  final clearance authority for faces, children, tablet, captions, branding,
  and platform rails.
* Legacy Hero now uses the same global 120-frame checkpointed video units as
  Advanced Hero. Its exact staged audio is converted directly to PCM and
  muxed once after all video receipts pass, so a Chrome crash cannot discard
  completed work or create AAC drift at chunk boundaries. The operator can
  resume a failed run with `clipforge hero render --resume RUN_ID`.
* Codex operator arc reviews and Tarteel overlay-clearance evidence can be
  rebased append-only when source ranges, timing, geometry, and inspected
  frames remain identical; stale alternatives are preserved and final human
  playback remains separate.

## Validation

The full repository validation completed successfully:

* Python: **923 passed, 2 skipped, 18 deselected**
* Browser/Remotion: **18 passed, 925 deselected**
* Renderer: **64 tests passed across 12 files**
* Ruff, format check, mypy across **301 source files**; 598 files formatted
* JSON Schema export/check: **287 schema files**
* Doctor: **9 pass, 1 GPU warning, 0 fail**; GPU warning reports CPU-only path
* Operator catalogue verification: **38 advertised capabilities**
* No live Openverse call was made; default status remains disabled.

The continuation reran the full suite after admission, preset, pilot, and
delivery-identity changes: **923 Python passed, 2 skipped, 18 deselected; 18
browser passed; 64 renderer passed; 287 schemas verified; 9 doctor checks
passed with one CPU-only GPU warning**.

The reference analyzer was exercised against an authorized local Tarteel
sample. It wrote a verified analysis sidecar with a measured duration and
explicit unknown creative metrics. It did not pretend that one probe proved a
hook, caption style, sound design, or performance outcome.

The Codex decision-trace command was also exercised against a generated
context. It rejected an out-of-context record and wrote a hash-bound trace
sidecar that the direction-plan CLI can bind.

## Real Tarteel production proof

The current authorized source was rendered through the production Remotion
Advanced Hero path after the knowledge context, decision trace, reviewed arc,
Arabic forced alignment, Quran.com evidence, speech inventory, measured CTA
assets, overlay-exclusion proof, and staged font all matched their hashes.

* Source: `bdafcfaf-73c4-4584-8503-ba6ffb869711`
* Candidate: `89a5a2fa-ce33-5527-b78d-46a685696c9b`
* Run/checkpoint: `2407a9f7-e66f-431e-b22c-8739fa82d268`
* MP4: `var/work/projects/3865ea49-98ce-446e-ae4a-c4f384b0c9fe/sources/bdafcfaf-73c4-4584-8503-ba6ffb869711/advanced-hero/review-drafts/runs/2407a9f7-e66f-431e-b22c-8739fa82d268/candidates/89a5a2fa-ce33-5527-b78d-46a685696c9b/advanced.mp4`
* MP4 SHA-256: `0f4b6d37a48b0ca0303f77581a970e08f9e996a211ef506bbe4d51503f50aa3c`
* Encoded facts: 1080×1920, 30 fps, 1284 frames, 42.800s video, 42.778s
  audio, H.264/AAC, 48 kHz stereo.
* Loudness: −15.7 LUFS integrated, −2.5 dBFS true peak, 5.8 LU LRA.
* Caption coverage: `candidates/89a5a2fa-ce33-5527-b78d-46a685696c9b/caption-coverage.json`
* Viewer evidence: `candidates/89a5a2fa-ce33-5527-b78d-46a685696c9b/viewer-evidence/bundle.json`
* Contact sheets: the `viewer-evidence/contact-sheets/` directory under the
  same candidate run contains full-frame and platform-crop sheets.

Decoded frames were inspected at the first caption, Quran active-word cue,
CTA entrance/hold/exit, and final frame. The selected CTA is readable during
its hold and clears the reviewed child/face/tablet/caption regions in the
current proof. The render is a Codex operator draft only: no human playback
record or final approval was created.

The same authorized source also completed the checkpointed legacy Hero path:

* Hero run/set: `8dc57cdd-9fc8-47dd-aad7-199b84698cd9`
* MP4: `var/work/projects/3865ea49-98ce-446e-ae4a-c4f384b0c9fe/sources/bdafcfaf-73c4-4584-8503-ba6ffb869711/hero/runs/8dc57cdd-9fc8-47dd-aad7-199b84698cd9/candidates/89a5a2fa-ce33-5527-b78d-46a685696c9b/hero.mp4`
* MP4 SHA-256: `4d0e12dbfbe2f9f96ab3043dc4642f1d8c74004da41f38e37e825066c186c597`
* Encoded facts: 1080×1920, 30 fps, 1365 frames, 45.5s, H.264/AAC,
  48 kHz stereo.
* Checkpoint receipts: `candidates/89a5a2fa-ce33-5527-b78d-46a685696c9b/checkpoints/`

The first single-session Hero attempt crashed around frame 1359; the new run
completed through checkpointed video units and direct audio conversion. This
proves recovery/continuity technically, but does not replace human visual
review of the Hero draft.

## Remaining staged work

* Reference OCR/caption layout/transcript timing, human narrative observations,
  and human watch evidence remain unavailable where the local evidence engine
  cannot provide them. Deterministic scene-midpoint frames, contact sheets,
  typed intake/evaluation/admission, and release retirement are implemented;
  for example:
  `var/work/editorial/analyses/analysis-004b33f5132887f0/contact-sheets/contact-001.jpg`.
* The motion catalog now has twenty-one hash-bound production routes and six
  narrative presets, with a second renderer allowlist and catalog fingerprint
  in Advanced Hero inputs. The route harness verifies every route and the
  production browser fixture exercises the selected route; exact visual
  acceptance remains human.
* Reference-analysis loading now rechecks the authorized source and evidence
  bytes. Proposed style cards retain the analysis id and digest, so changed
  reference evidence cannot silently reuse an old style decision.
* Knowledge fingerprints reach Advanced Hero inputs, manifests, cache records,
  direction QA, delivery facts, final-review evidence, and the Remotion
  worker. Delivery cache identity now also binds the selected preset, pilot,
  motion catalog, recipe ids, knowledge release/context, and decision-trace
  hashes.
* Openverse acquisition requires current policy, hashed independent license
  capture, confined bytes, media probing, and the existing local asset
  registration/rights boundary. It does not fetch or independently verify a
  landing page; the operator must supply that captured evidence.
* Direction lint, hash-bound pilot receipts, decoded viewer evidence, and
  technical/mechanics/semantic QA gates are implemented. Human playback is
  deliberately separate and remains the final acceptance step.

The current release snapshot was captured and verified with
`release_id=release-0af1f31a73f1a62f0b5766b1` and fingerprint
`0af1f31a73f1a62f0b5766b1863339a0de9d55ce6d01d8e690fea57bc308a66c`.

The current Codex-operated Tarteel draft was then rendered through the real
Remotion path after automatic arc and overlay-proof revalidation:

* Run/checkpoint: `afc710b4-b4da-4d7d-bc90-6a24fb70e374`
* MP4: `var/work/projects/3865ea49-98ce-446e-ae4a-c4f384b0c9fe/sources/bdafcfaf-73c4-4584-8503-ba6ffb869711/advanced-hero/review-drafts/runs/afc710b4-b4da-4d7d-bc90-6a24fb70e374/candidates/89a5a2fa-ce33-5527-b78d-46a685696c9b/advanced.mp4`
* MP4 SHA-256: `de0612c7f26aad5058f5bda9cb463fb2066164567714782764ca803aff9e61ac`
* Encoded facts: 1080×1920, 30 fps, 1284 frames, 42.8s, H.264/AAC,
  48 kHz stereo.
* Loudness: −15.7 LUFS integrated, −2.5 dBFS true peak, 5.8 LU LRA.
* Direction: `motion-quran-challenge-v1`, one bounded push-in camera event,
  one native Quran graphic, and three declared transitions. No SFX asset was
  selected because the campaign catalog has no current rights-cleared SFX.
* Viewer evidence: `candidates/89a5a2fa-ce33-5527-b78d-46a685696c9b/viewer-evidence/bundle.json`

Decoded-frame inspection confirmed the Quran illustration reaches encoded
pixels, the camera route is present in the render input, captions remain in
the lower lane, and branding/CTA proof is bound to the new transform.
* The real Advanced Hero source run and the checkpointed Hero source run are
  technically verified. Human final playback and approval remain required.
