# Editorial treatment orchestration follow-up round 5

**Review date:** 2026-11-09
**Reviewed head:** `b7a3234f465e96c8134a1c1ebed63c0de8f9b1d0`
**Branch:** `round-36-editorial-knowledge-engine`
**PR:** [#38](https://github.com/Ammar-1652/ai-shortform-engine/pull/38)
**Base:** `origin/main` as recorded by the branch  
**Status:** `REVIEW OPEN — R5-1/R5-2 IMPLEMENTED; R5-3 CORE GATES IMPLEMENTED; EXTERNAL GATES REMAIN`

This document records the result of a fresh review of the round-4 deep
implementation. It is a fixing plan for the remaining work; it does not claim
that round 4 is complete and it does not approve or deliver an artifact.

## Audit evidence

- The worktree was clean at the reviewed head. The only commits after the last
  validated code commit (`4d9c524`) are documentation commits; no code change
  was hidden by the ledger.
- `./scripts/validate.sh` passed on this checkout: **980 Python tests passed,
  2 documented skips, 18 deselected; 18 browser/Remotion tests passed; 64
  renderer tests passed; schema check, Ruff check/format, mypy, renderer lint,
  renderer typecheck, and doctor all passed**. Doctor reported 10 pass, 0
  warnings, and 0 failures. The skips are the unavailable VoiceStudio live
  smoke and the unconfigured Whop live smoke.
- The focused speech, QA, and ingest regression suite passed **49 tests**.
- `hero advanced verify --draft-only` passes for the owned proof source when
  the operation database and work root are supplied explicitly.
- `final review verify` currently fails with `unsafe_path`; `publish plan`
  fails with `license evidence path escapes the work root`. The source record
  predates the new ingest staging repair and is intentionally immutable.
- PR #38 is still draft/open at exact head `b7a3234f465e96c8134a1c1ebed63c0de8f9b1d0`.
  Its `verify-python` check is **QUEUED** because
  no registered self-hosted runner with the required labels is available.
- The owned proof MP4 and decoded evidence exist under the ignored operation
  work root, but no human playback receipt or effective human final approval
  exists for that exact artifact.

## Round-5 implementation update

Commit `b7a3234f465e96c8134a1c1ebed63c0de8f9b1d0` (plus its parents
`9cbcfe0`, `55fa31c`, `3008ffe`, and `1cd7888`) implements the code-level corrections that can be
verified locally:

- **R5-1 implemented:** generic Codex speech reviews now validate local
  snapshot bytes at load time and at aligned-span validation. Paths are
  confined to the operation root, symlinks and non-files are rejected, hashes
  are recomputed, and URL fragments/control characters are rejected. The
  loader, CLI review command, caption evidence, and Advanced Hero path all use
  the same root-bound checks.
- **R5-2 implemented:** `codex_speech_review_required` is enforced by the
  Advanced Hero planner, render/pilot binding, technical QA direction check,
  and delivery preflight. The false value is accepted only with the legacy v1
  renderer recipe. Directionless historical plans retain their recorded
  compatibility path; directed clean plans cannot become final artifacts
  without the Codex review hash.
- **R5-3 geometry portion implemented:** typed treatment evidence now records
  output-space motion-graphic rectangles and explicit top/bottom platform
  rails. Camera collision protection includes authored motion graphics, and
  the geometry is included in the generated treatment schemas and fingerprints.
  Catalog tags cannot mark B-roll as related before decoded observation
  evidence exists, and a verified visual binding without final output geometry
  is rejected. Campaign CTA/logo clearance continues to use the existing
  decoded `OverlayExclusionEvidence` gate.
- **Evidence binding strengthened:** output-space regions now carry analyzer
  version, confidence, transform dependency, and paired sample timestamps and
  frame hashes where the source observation provides them. Malformed evidence
  is rejected before it can enter a treatment bundle.
- **Source-native text binding strengthened:** new source-native annotations
  may carry the measured post-transform rectangle and dependency hash; legacy
  annotations remain readable with their explicit legacy geometry mode.
- **Protected-role status strengthened:** every treatment beat records explicit
  present, reviewed-absent, or unknown states for faces, active subject, source
  text, logo, CTA, captions, platform rails, B-roll, and motion graphics.
  Decoded B-roll observations upgrade the B-roll role with their region and
  evidence ids.
- **Role policy enforced:** selected B‑roll, motion graphics, and annotated
  source text now fail treatment policy unless their role evidence is measured
  as present.

The focused suite for these changes passed, and the exact-head full validation
passed with **990 Python tests, 2 skips, 18 browser/Remotion tests, and 64
renderer tests**. No generated schema drift or orphaned render process was
observed.

## What is verified as landed

The following code paths are present and covered by the exact-head automated
checks:

1. Codex generic speech-review revisions, immutable revision paths, current
   pointers, source/ASR/transcript binding, corrections, emotions, and exact
   sensitive-span matching.
2. Corrected display alignment without mutating raw ASR or forced alignment.
3. Shaped Arabic/RTL caption rendering through the real Advanced Hero
   composition, including emoji as a separate inline value.
4. Disjoint treatment audio windows, decoded audio evidence, loudness and true
   peak checks, and no-treatment audio sentinel handling.
5. Hash-bound visual treatment observations for selected assets and output
   regions, with the existing collision and treatment policy path.
6. Bounded browser retries, per-unit checkpoints, cleanup, and deterministic
   crash/resume regression coverage.
7. Shared stale/cache bindings, append-only review evidence, QA verification,
   and the future-ingest rights-evidence confinement repair.

These results prove the implemented code and its fixtures. They do not prove
human playback, final approval, delivery, or CI execution.

## Remaining work

### R5-1 — Verify generic local speech snapshots at load time

**Status:** implemented in `1cd7888` and covered by loader/alignment tests.

The remaining Quran canonical-source path is unchanged and continues to use
its stronger official-source policy.

**Fix steps:**

1. Pass the confined work root into the speech-verification validation path.
2. For every local snapshot, reject symlinks and missing/non-regular files,
   confine the path, compute SHA-256, and compare it to
   `snapshot_sha256` before the review can load.
3. Require the snapshot path and hash to be bound into the review digest and
   all downstream render/QA/final-review identities.
4. Parse HTTP(S) evidence URLs with one shared safe-url helper. Reject
   credentials, custom ports, fragments used to carry hidden evidence, unsafe
   schemes, empty hosts, and control characters.
5. Keep Quran canonical snapshots on the existing stronger canonical path; do
   not replace that policy with the generic checker.

**Required tests:** missing snapshot, symlink, changed bytes, wrong hash,
outside-root path, URL credentials, empty host, fragment, unsafe scheme, and a
valid local snapshot that survives an offline render.

**Acceptance:** a generic sensitive-text review cannot load unless its local
snapshot bytes are present, confined, and hash-identical to the reviewed
record.

### R5-2 — Make `codex_speech_review_required` the real policy authority

**Status:** implemented in `1cd7888`. The profile field now drives the
production gates while preserving explicit legacy-v1 and directionless
historical compatibility.

**Fix steps:**

1. Add one helper that resolves the effective speech-review policy from the
   profile, campaign policy, legacy recipe, and draft-only mode.
2. Call it from planning, render-input binding, QA, final-review preflight,
   delivery preflight, and cache validation.
3. Require a current `codex_operator` review for every new clean profile when
   the field is true. Allow an explicit false value only for a documented
   legacy/approved compatibility profile; never let `allow_unapproved` turn a
   clean artifact into a final candidate.
4. Preserve readability of recorded legacy-v1 artifacts without applying new
   defaults to them.
5. Include the resolved policy decision and its source profile in evidence and
   blocker messages.

**Required tests:** profile true without review blocks before Remotion; profile
false only permits the documented legacy path; stale review blocks all
downstream gates; draft-only remains non-deliverable; changed policy
fingerprint invalidates render, QA, review, and delivery.

**Acceptance:** changing the profile field changes actual enforcement, not only
the hash, and every gate reports the same result.

### R5-3 — Complete output-space protected-region and relevance evidence

**Status:** core geometry and relevance gates are implemented in `3008ffe`;
the full decoded role/trajectory acceptance remains open.

The current code emits motion-graphic and platform-rail rectangles in the typed
output-space evidence, protects authored graphics during camera collision
checks, requires decoded observation evidence before a B-roll decision can be
related, and rejects visual bindings without final geometry. Full decoded
active-subject/logo/CTA extrema and a frame-backed semantic relevance evaluator
still require a follow-up round.

**Fix steps:**

1. Add typed output-space observations for every selected protected role,
   including sample timestamps, final crop/reframe transform, confidence,
   analyzer version, and frame hashes.
2. Run the observation pass after the actual portrait transform and camera
   trajectory are known; never reuse source-space rectangles.
3. Add a deterministic relevance evaluator that combines decoded observations
   with source-grounded evidence. Tags may narrow discovery but cannot alone
   produce `related`.
4. Check the full camera envelope, transitions, captions, B-roll, logo, CTA,
   and platform rails for every overlapping interval. Emit stable omission or
   downgrade reasons before render input creation.
5. Bind observation and geometry digests into direction, render input, QA,
   final review, and cache identities.

**Required tests:** matching tags with unrelated frames, changed observation
bytes, portrait crop movement, maximum camera travel, logo/CTA/face/caption
overlap, source-native text, and a selected layer with missing geometry.

**Acceptance:** every visual layer that reaches render input has measured final
coordinates, source-grounded relevance, rights evidence, and collision proof.

### R5-4 — Re-establish a delivery-valid proof packet

**Observed blocker:** the current owned proof source was ingested before the
rights-evidence confinement repair. Its immutable record points outside the
work root, so final review and delivery correctly fail with `unsafe_path`.

**Fix steps:**

1. Ingest a fresh authorized copy using the repaired ingest path and a local
   rights evidence file inside the operation work root.
2. Re-run source probe, transcript, candidate, selected-clip alignment,
   TimeMap, Codex speech review, direction/treatment, pilot, Advanced render,
   decoded evidence, and QA against the new source id.
3. Do not edit or replace the old source record, MP4, review, or evidence.
4. Run final-review and delivery verification against the exact new artifact;
   preserve the old package when any promotion fails.

**Acceptance:** `final review verify`, `publish plan`, and delivery
verification pass their rights/path checks for the fresh source, with all
hashes bound to the new artifact.

### R5-5 — Obtain human playback and final approval

**Observed blocker:** Codex review and QA are not human final approval. The
current owned MP4 has decoded frame/audio evidence but no append-only human
playback receipt and no effective `human_reviewer` final decision.

**Fix steps:**

1. Watch the exact fresh-source MP4 with audio and muted playback.
2. Record the append-only `HumanPlaybackReview` against the exact video hash,
   QA set, render input, and delivery facts.
3. Record an append-only final decision as `human_reviewer`; do not use a Codex
   or automated row for final approval.
4. Re-run final-review verification after approval and confirm any changed
   artifact makes the decision stale.

**Acceptance:** final review reports an effective human approval for the exact
   package, and a changed source/render/QA/rights fact invalidates it.

### R5-6 — Resolve exact-head CI infrastructure

**Observed blocker:** PR #38's `verify-python` check remains queued because no
self-hosted runner with `self-hosted`, `linux`, `x64`, and `clipforge` labels is
registered. A queued job cannot be reported as green.

**Fix steps:**

1. Register an authorized runner with the required labels and repository
   access, without placing credentials in the repository.
2. Rerun CI on exact head
   `b7a3234f465e96c8134a1c1ebed63c0de8f9b1d0`.
3. Record completed job names and conclusions. If the runner remains absent,
   keep CI status `QUEUED` and the round open.

**Acceptance:** the exact reviewed PR head has a completed green CI result;
queued, cancelled, or different-head runs do not qualify.

## Required execution order for the next round

1. Implement R5-1 and R5-2 with typed contracts, generated schemas, and
   failure-path tests.
2. Implement R5-3 and run real decoded observations on an authorized source.
3. Run the full validation suite and confirm no process leakage.
4. Re-ingest the fresh rights-bound proof source (R5-4).
5. Produce the exact production MP4 and decoded packet, then perform human
   playback and final approval (R5-5).
6. Run local delivery verification and package export.
7. Complete exact-head CI (R5-6).
8. Update the round-5 ledger with hashes, paths, test counts, skips,
   limitations, and final statuses. Do not mark the round complete while any
   item remains implementation-gap, unsafe-path, missing-approval, or queued.

## Definition of done

Round 5 can be marked complete only when R5-1 through R5-6 are either
technically verified with evidence or explicitly recorded as a still-active
external blocker. The overall production objective remains **NOT COMPLETE**
until the fresh source passes rights/path checks, the exact MP4 receives human
playback and final approval, local delivery verifies, and CI completes on the
same head.
