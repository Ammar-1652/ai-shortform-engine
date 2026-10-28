# Tarteel review-trio repair: next execution round

**Status:** SUPERSEDED EXECUTION RUNBOOK — see
`tarteel-review-trio-audit-2026-10-24.md` for the current audit and next-round
exit plan

**Reviewed:** 2026-10-24 (Africa/Cairo); the earlier 2026-10-20 entries below
are retained as execution history

**Document role:** authoritative remaining-work runbook. Proposed contracts
and tests below are work to implement, not claims of existing capability.

**Branch reviewed:** `round-35-quran-caption-verification`

**HEAD reviewed:** `4ac0748`

**Parent plan:** [tarteel-review-trio-system-repair-plan.md](tarteel-review-trio-system-repair-plan.md)

**Current evidence ledger:** [tarteel-review-trio-execution-ledger.md](tarteel-review-trio-execution-ledger.md)

## Review conclusion (historical 2026-10-20 slice)

The first implementation slice is technically healthy but incomplete. It
closes several ways an unsafe Tarteel plan could be accepted, and the focused
tests are green. The full suite has one browser-fixture regression caused by
the new authorization gate. It does not yet prove that a newly reviewed Tarteel
source can travel through the service path and produce a reviewable Advanced
Hero draft.

The six files under `var/work/campaigns/Tarteel/review-trio/` remain forensic
baseline artifacts. They were created by the old manual batch path and are not
new evidence. No existing video is promoted, overwritten, or called upload
ready by this review.

## Execution audit — 2026-10-20

The first execution slice was re-audited against the current checkout and
artifacts. The result is **not complete**:

| Area | Current result | Evidence |
| --- | --- | --- |
| R1 service authorization | Implemented; full-suite clean run blocked by host browser memory pressure | `tests/test_render_authorization.py` and the real round-29 face-follow/contain browser smoke pass; per-candidate receipts are retained. The current full run reached 842 passed but three browser jobs failed only after host memory fell to ~210 MiB; no authorization assertion failed. |
| R2 caption/audio evidence | Partial; decoded speech and real service QA pending | Generated MP4 capture now binds cue/word edge frames, staged audio and output hash. When a reviewed `speech-review.json` exists, the service checks source/ASR/transcript hashes, validates coverage of every retained source range, stages the exact typed review, and binds it into the report; missing review remains `insufficient_evidence`. No real Tarteel service manifest has the report. |
| R3 transformed CTA clearance | Partial implementation | face samples now map through the selected crop window into foreground coordinates; branding sizing samples retained source ranges and staging rejects changed reviewed CTA timing/geometry/logo visibility. Typed all-exclusion evidence and decoded entrance/hold/exit proof remain |
| R4 semantic arc evidence | Partial implementation | clean planning/render/cache/QA now require an accepted hash-bound `editorial-arc-review.json`; no real source-bound sidecar or reviewer-readable shot strip exists yet |
| R5 Arabic/reaction/nasheed contract | Open | no ordinary-Arabic correction/coverage decision contract or persisted decoded Arabic evidence |
| R6 replacement for t33 | Open | no new reviewed candidate, alignment, arc, or Hero decision; current source evidence still contains malformed repeated ASR |
| R7 viewer-evidence QA | Partial; human watch and R3/R5 inputs remain open | clean service renders now emit a hash-bound `ViewerEvidenceBundle` with decoded frames, 4:5/1:1 crop previews, contact sheets, and ebur128 facts; QA/cache validate the bundle, while missing human watch remains `INSUFFICIENT_EVIDENCE`. Isolated browser evidence passes; full validation is host-memory constrained. |
| R8 real-source service proof | Open | no real Tarteel run contains a service-issued authorization; artifact scan found zero `authorization.json` files under `var/work` |

The existing six review-trio MP4s remain immutable forensic artifacts. Their
hashes match their manifest entries and their dimensions/audio streams are
technically valid, but they are not evidence of the new service path. The
manifest still has absolute paths and no `diagnostic_only` field. Four outputs
remain explicitly provisional or blocked by the manifest, and the two
forced-alignment outputs remain review-only pending human approval.

The current full validation attempt reached **842 passed, 2 skipped, 3
failed**. All three failures were browser resource failures under host memory
pressure (Chrome page/setup crashes while available memory fell to roughly
210 MiB); the isolated browser pair and the complete non-browser suite pass.
This is recorded as an external validation blocker, not converted into a
skip or a code-level PASS claim.

The technical checks that did pass were: 32 focused Python tests across the
new authorization/caption/QA/overlay/browser-isolation coverage; schema check;
renderer lint, typecheck and 59 Vitest tests; and doctor with 10 passes and no
warnings. These results prove contract behavior only. They do not close the
real-source or viewer-evidence gates.

### Required fixes before the next audit

1. **Finish R1 without weakening the production gate.** Update the
   round-29 real-browser fixture to create a canonical `batch-input.json`,
   stage regular media, issue the same service authorization used by
   `advanced_service`, and then invoke the worker. Add a regression proving
   the fixture cannot render when the receipt is absent. Re-run the complete
   suite and require zero failures.
2. **Implement R2 as a persisted artifact.** Add a versioned coverage report
   containing source/audio intervals, effective TimeMap segments, forced word
   ids, caption cue ids, and decoded first/middle/last/half-open-endpoint frame
   records. Bind it to the encoded MP4 hash and fail QA for gaps, cut-through
   words, provisional words, audio/video duration mismatch, or missing decoded
   evidence.
3. **Implement R3 in transformed output coordinates.** Persist every sampled
   CTA candidate, final transform digest, sampled frame ids, exclusion boxes
   for faces, children/tablet, captions, context line, watermark, source logo
   and platform rails, plus the selected rectangle. Require dense entrance,
   hold and exit samples and fail closed when no candidate is clear.
4. **Implement R4 before selecting another idea.** Require source scene ids,
   transcript span ids, beat summaries, hook-to-body and body-to-punch
   continuity decisions, claim closure and reviewer identity in an immutable
   arc-review sidecar. Produce a transcript/shot strip that a reviewer can
   inspect.
5. **Implement R5 as a source-bound correction and coverage contract.**
   Preserve the raw ASR hash, corrected Arabic text, locale, evidence spans,
   reviewer, and per-interval `captioned` or `reviewed_excluded` decision.
   Keep Quran canonical verification separate from ordinary dialogue and
   persist decoded Arabic glyph/color evidence.
6. **Complete R6 from the frozen campaign checkpoint.** Reject the current
   malformed candidate evidence, select one replacement event with a single
   subject, obtain reviewed Hero and direction decisions, forced-align the
   selected clip, and build a closed arc. Retained reactions and nasheed must
   be captioned; otherwise they must be cut and recorded as excluded.
7. **Implement R7 and bind QA to it.** Add the viewer-evidence bundle with
   ffprobe/loudness facts, decoded frames/contact sheet, platform crop masks,
   caption and overlay evidence, and a human-watch record. Missing or stale
   evidence must be `INSUFFICIENT_EVIDENCE` and must invalidate final review,
   cache reuse and delivery.
8. **Run R8 only after R1–R7.** Create one new Hero and Advanced service run
   from the frozen checkpoint, retain both frame variants from the same
   semantic plan, inspect complete audio and muted playback, verify QA and
   final-review staleness, and stop at an unapproved draft for independent
   visual review.

## Evidence checked

The following checks were run against the current working tree:

- Focused caption, QA, overlay, arc, Advanced Hero, browser-isolation, and
  renderer-regression tests: passed (exit code 0).
- `uv run clipforge schema check`: passed.
- `uv run clipforge doctor`: 10 pass, 0 warn, 0 fail.
- The current full validation: `823 passed, 2 skipped, 1 failed`; the failure
  is `test_remotion_face_follow_keeps_the_marker_and_contain_keeps_bars`,
  because its browser batch has no service-issued authorization. Renderer
  lint/typecheck passed and Vitest reported `59 passed`.
- Earlier caption/reframe browser smoke recorded `2 passed`. The current
  affected group now passes `21 passed` after the authorization fixture and
  caption-evidence repair. The full validation still needs to be rerun from
  the current head. Neither fixture is Tarteel production evidence.
- `uv run clipforge candidate list
  0ba39097-3732-4938-961b-b9216aa59a4b --work-dir var/work`: current candidate
  excerpts contain repeated and malformed ASR text such as `انا اتسعه`; they
  are not a reviewed transcript for a Tarteel production arc.
- `uv run clipforge hero list
  bdafcfaf-73c4-4584-8503-ba6ffb869711 --work-dir var/work`: one stored Hero
  candidate is visible, but no reviewed Tarteel editorial arc or new Advanced
  service run was produced from it during this review.
- The baseline `review-manifest.json` contains six absolute media paths and
  has no machine-readable `diagnostic_only` field. Its statuses correctly say
  that several outputs are provisional or pending, but the manifest itself is
  not a service-generated acceptance record.

## What landed correctly

These items are implemented and covered by tests:

1. Advanced planning rejects a Tarteel plan without an editorial arc, rejects
   `operator_override` arcs, and requires a reviewed opening word and note.
2. Caption construction requires forced alignment and checks one-to-one,
   ordered word coverage. QA reloads the persisted alignment and compares
   word ids, microsecond intervals, and frame intervals.
3. Editorial arc validation rejects overlapping ranges, cuts inside forced
   words, missing forced words, non-closed beats, and invalid hook/body/punch
   ordering.
4. Tarteel CTA planning uses output-clock face samples and fails closed when
   the supplied candidate rectangles all overlap measured faces. CTA sizing
   remains bound to a source-frame measurement hash.
5. Remotion Advanced Hero is launched through the service backend with an
   authority marker, rejects debug/fixture events, rejects remote media URLs,
   validates allowlisted styles, and checks the typed overlay contract.
6. Resumable render checkpoints verify input and renderer dependency hashes,
   retain per-unit receipts, render one continuous audio unit, and assemble a
   final encoded output only after all units validate.
7. Generated schemas, renderer type checks/tests, focused Python tests and
   doctor pass. The full Python suite still has the R1 browser-fixture failure.

These are implementation outcomes only. They do not constitute viewer
acceptance or a successful real-source Tarteel production run.

## Problems that remain

### R1 — The manual-batch quarantine is not an enforceable artifact boundary

**Execution status (2026-10-20): IMPLEMENTED IN CODE — full-suite confirmation
pending.** `AdvancedRenderAuthorization` is emitted by the
Advanced service only after it has written the canonical `batch-input.json`
and verified every staged local input.  The renderer verifies that receipt,
the canonical batch digest, full typed input, authorized output location,
chunk frame ownership, and staged file hashes before it imports Remotion.  It
rejects the edited-input, changed-media, moved-output, copied-full-run and
copied-checkpoint, altered-range, missing-receipt and symlink cases covered by
focused tests. A durable receipt is retained under each candidate. The live
worker dependency comparison and complete zero-failure validation remain in
the exit evidence. This is an integrity mechanism, not a sandbox against the
local owner.

**Observed evidence:** the old `review-trio/build_inputs.py` and its batch
files remain in the ignored work root. The renderer now requires
`CLIPFORGE_RENDER_AUTHORITY=advanced_service`, but that value is only an
environment string. A caller that sets the same value can still present a
hand-edited batch. No test currently proves rejection of a copied batch with
fabricated parent hashes, a missing service run record, or a path outside the
service run directory. The baseline manifest also contains absolute paths and
no `diagnostic_only` marker.

**Root cause:** authority is asserted at process launch rather than proven by
an immutable service-issued run authorization bound to the exact input and
parent artifacts.

**Next-round fix:** add a versioned `AdvancedRenderAuthorization` sidecar,
created only by `advanced_service`, containing the run id, input digest,
source/visual/candidate/Hero/alignment/TimeMap/direction/arc/style/font/audio
digests, renderer dependency digest, and a work-root-relative batch name. The
renderer must load that sidecar from its run directory and reject any mismatch
before bundling. Add a diagnostic-only marker and root-relative paths to a new
baseline report without rewriting old media. Add a production test that
mutates one parent hash, copies a batch, moves the output, and sets the
environment marker; all cases must fail.

**Exit evidence:** a service-created authorization verifies; a manually copied
or edited batch fails even when the environment marker is present; the old
manifest is explicitly classified as diagnostic-only and is not referenced by
delivery.

### R2 — Caption checks do not yet prove audio coverage or decoded cue edges

**Execution status (2026-10-20): PARTIAL.** Preflight and QA both reject
forced-word interval drift and duplicate ids. `CaptionAudioCoverageReport`
binds the staged audio hash, effective map/alignment, final render-input
hash, encoded MP4 hash and decoded cue/word-edge frames; QA and cache lookup
recheck it. A generated-media regression passes. The report explicitly keeps
speech completeness at `insufficient_evidence` because R5's reviewed audible
speech inventory and real-source Tarteel validation do not exist yet.

**Observed evidence:** the new validator proves forced-word identity and
timing, and the current slice persists report/frame evidence for generated
clean renders. QA still lacks a real Tarteel report to consume, and the
source-speech inventory/reviewed-exclusion contract is not implemented. There
is no real-source regression for a source speech interval outside the caption
map. Existing browser tests are generic fixtures.

**Root cause:** caption metadata validation and encoded-media validation are
separate; neither currently produces a single evidence object for the staged
audio, effective TimeMap, and decoded output frames.

**Next-round fix:** create a deterministic audio/caption coverage report from
the effective forced alignment and TimeMap. Reject provisional words, gaps,
cut-through-word ranges, duplicate ids, and any retained aligned speech
interval without a caption or explicit reviewed exclusion. After encoding,
decode the first, middle, last, and exact endpoint frame for every cue and
store a relative-path frame manifest with artifact hash. Add tests for jump
cuts, equal-distribution input, short words, exact endpoints, and audio/video
duration mismatch.

**Exit evidence:** the old t33-style 11-second gap fails before render and in
QA; a real newly aligned clip has a complete coverage report and decoded cue
edge evidence bound to its MP4 hash.

### R3 — CTA clearance is still face-only and not transformed-space proof

**Execution status (2026-10-20): PARTIALLY IMPLEMENTED.** Face samples now
map through the selected output crop window before placement, so a crop/zoom
cannot reuse raw source-normalized rectangles. The solver still needs the
typed exclusion report for child/tablet, captions, context, source logo,
watermark and platform rails, plus decoded CTA entrance/hold/exit evidence.

**Observed evidence:** placement now receives timed face samples, but the
solver still evaluates four fixed rectangles in normalized source coordinates.
It does not test tablet/child boxes, source-native logo, upper context line,
caption rectangles, watermark, or platform-safe margins. It does not persist
all candidates and sampled frame ids. Face samples are filtered to the CTA
interval but are not required to be dense across CTA entrance, hold, and exit.

**Root cause:** exclusion geometry is solved before the final foreground
transform and is reduced to an aggregate face-overlap check.

**Next-round fix:** introduce a typed `OverlayExclusionEvidence` contract.
Compute final foreground transform first, map all exclusions into foreground
coordinates, sample the entire CTA animation with denser entrance/exit points,
and test intersection against faces, child/tablet regions, source logo,
captions, context line, watermark, and platform rails. Measure the native CTA
alpha bounds and persist candidate rectangles, winner, sampled frame ids,
analyzer version, and evidence hash. Fail closed when no rectangle is valid.
Apply the same proof to an added watermark.

**Exit evidence:** tests cover face, tablet, caption, source-logo, and no-safe-
position failures; a real render has a decoded CTA contact sheet and matching
exclusion evidence for every sampled CTA frame.

### R4 — Arc review records structure but not semantic continuity evidence

**Observed evidence:** the arc schema enforces three ordered beats and exact
forced words, but `purpose` is free text. No persisted shot strip or reviewed
continuity artifact is required. The validator cannot establish that a hook's
person/challenge/payoff is the subject developed by the body, so the old
unrelated-hook behavior can only be caught by human inspection.

**Root cause:** the story contract has boundaries and source bindings, but no
reviewable evidence object for beat-to-beat continuity.

**Next-round fix:** add an immutable `EditorialArcReview` sidecar containing
source frame/scene ids, transcript span ids, beat summaries, continuity
decision, claim closure, and reviewer identity. Require every beat to bind to
at least one source scene and require a reviewed continuation relation between
adjacent beats. Generate a transcript/shot strip before Advanced planning.
Do not infer semantic continuity from an LLM sentence alone; the reviewer
decision and source evidence remain authoritative.

**Exit evidence:** the old t33 arc is rejected or marked rejected with a reason;
the replacement arc has a shot strip, complete transcript spans, and explicit
hook-to-body and body-to-punch continuity decisions.

### R5 — Arabic correction, reactions, and nasheed exclusions are not a full contract

**Observed evidence:** forced alignment is required and existing Quran review
and font bindings are checked, but there is no production transcript-correction
sidecar for ordinary Arabic, no typed distinction between dialogue/reaction/
nasheed coverage, and no explicit exclusion record for retained but
uncaptioned speech. Decoded Arabic glyph/color evidence is not persisted.

**Root cause:** all spoken material is represented as generic aligned words;
the system does not require a reviewed decision when ASR is wrong or a selected
non-dialogue segment is intentionally omitted.

**Next-round fix:** add a source-bound transcript correction document with
reviewer, evidence spans, immutable raw-ASR hash, corrected text, and locale.
Add a coverage decision per retained source interval: `captioned` or
`reviewed_excluded`, with a reason and arc binding. Keep Quran canonical text
and pronunciation verification separate. Decode Arabic frames and measure
bright glyph pixels, line bounds, active-word color changes, and duplicate
layers. Treat OCR as supplementary and report unavailable packs explicitly.

**Exit evidence:** dialogue, reactions such as `هههه`, and any retained nasheed
are fully aligned/captioned or explicitly cut/excluded; Quran display text is
canonical and visibly distinct; Arabic frame evidence is stored.

### R6 — The old t33 idea has no replacement candidate

**Observed evidence:** no new reviewed t33 replacement candidate, Hero
decision, forced alignment, direction, or arc exists. The six t33 outputs are
still the old manual/provisional batch. The current candidate listing for the
available Tarteel source is visibly malformed and cannot be used as production
transcript evidence.

**Root cause:** the system gates now stop the old idea, but the source review
and replacement selection work has not yet been completed.

**Next-round fix:** review authorized source scenes and transcript evidence,
select a replacement whose hook/body/punch concerns one event, record the
candidate decision, run selected-clip forced alignment, create Hero and
direction reviews, and then create a reviewed arc. If nasheed is retained it
must be fully captioned; otherwise the arc must cut it out.

**Exit evidence:** replacement candidate id, source shot strip, reviewed
transcript, forced alignment, Hero review, direction, arc, and no reference to
the old t33 batch in the new render set.

### R7 — Viewer-quality QA now has objective evidence, but not human acceptance

**Execution status (2026-10-20): PARTIAL.** Clean browser renders now write a
versioned `ViewerEvidenceBundle` after encoding. It includes first/middle/last
decoded frames, 4:5 and 1:1 crop previews, contact sheets, encoded dimensions,
duration, and ebur128 loudness/true-peak facts. QA verifies the bundle hash,
encoded-media hash, render-input/style/font dependencies, service artifact id,
batch authorization digest, and every evidence-file hash. Cache reuse also
rejects missing or stale bundles. No human watch is synthesized: a bundle
without audio-and-muted playback observations remains `INSUFFICIENT_EVIDENCE`.
No real Tarteel service artifact has yet supplied the remaining R3/R5 evidence.

**Root cause:** technical QA previously had no persisted viewer evidence, so a
valid MP4 could be mistaken for viewer acceptance. The new objective bundle
closes that gap, while human/editorial review remains intentionally separate.

**Remaining fix:** feed the R2 caption report, R3 transformed overlay evidence,
R4 arc review, and R5 Arabic/speech evidence into the bundle; expose the bundle
through show/verify/final-review/delivery surfaces; and record a real human
watch only after an independent reviewer watches both with audio and muted.
Missing or stale evidence must continue to invalidate QA, final review, cache,
and delivery on any output-changing dependency.

**Exit evidence:** a technically valid MP4 with a caption gap or unsafe CTA
cannot pass QA; objective evidence paths are work-root-relative and hashes
match the encoded file; old QA becomes stale after a style, font, arc, crop,
caption, overlay, source, or audio-policy change; and a human watch is present
before visual acceptance.

### R8 — No real-source service render has passed the complete chain

**Observed evidence:** no newly reviewed Tarteel Hero/Advanced service run was
created during this review. The real-source re-entry check is blocked by the
malformed current transcript evidence and missing reviewed arc/coverage bundle.
The six baseline MP4s are diagnostic and cannot serve as exit evidence.

**Root cause:** upstream evidence is not yet authoritative, and the visual QA
bundle is not implemented.

**Next-round fix:** after R1–R7, re-enter only from the frozen checkpoint,
verify source/rights hashes, create a new reviewed candidate and arc, render
Hero then Advanced through the CLI, generate both approved frame variants from
the same semantic plan, decode and inspect complete clips with audio and
muted playback, run QA/final-review verification, and stop at draft review.

**Exit evidence:** exact service run id, relative artifact paths and hashes,
ffprobe/loudness reports, decoded frame/contact sheets, cache/stale checks, and
an explicit human-review state. No upload or final approval is manufactured.

## Ordered execution for the next round

Follow the detailed work packages below. Start with P0 and finish R1. Define
the common evidence references once, then implement R2, R3, R4 and R5. Connect
their reports to QA in R7 before spending on the replacement source render in
R6/R8. R6 source inspection may happen earlier, but final acceptance depends on
R7. Do not create another production path to bypass an unfinished package.

### P0 — Establish the execution state and evidence interfaces

**Inputs to read:** this file; the parent repair plan; `AGENTS.md`;
`ARCHITECTURE.md`; `docs/architecture/time-mapping.md`;
`docs/architecture/tarteel-campaign-hard-rules.md`;
`docs/operations/tarteel-campaign-checkpoint-2026-10-17.md`; ADRs 0064, 0068,
0071, 0076, 0083, and 0090–0095. Read any additional applicable AGENTS files.

1. Record `git status --short --branch`, full HEAD SHA, local and remote main
   refs, branch tracking, diff stat, and untracked files. Inspect open PRs and
   active work before choosing the existing repair branch or an isolated
   worktree. Do not assume the audit SHA is still current.
2. Preserve the dirty working tree, old media, existing approvals and logs.
   The audit baseline was branch `round-35-quran-caption-verification`, HEAD
   `4ac0748`, plus substantial uncommitted changes. Do not reset or start by
   reproducing those changes.
3. Store this execution's logs and media under a new ignored work-root
   directory. Maintain an execution ledger with package id, state, input
   hashes, changed files, test command/exit/count, evidence paths/hashes,
   unresolved issue, and exact next step. Allowed states:
   `not_started`, `in_progress`, `implemented`, `technically_verified`,
   `blocked`, `awaiting_human_review`.
4. Confirm the latest full-suite failure before editing the fixture:
   `uv run pytest tests/test_round29_reframe_browser.py -ra`.
   Capture the traceback. If it differs from the recorded missing
   authorization error, investigate the current cause.
5. Specify common evidence references: versioned typed documents, candidate
   and source identity, producer job/tool/version, parent artifact identities,
   content hashes, work-root-relative paths, and status with explicit reason.
   Reject missing files, symlinks, traversal, unknown versions and hash
   mismatches. A report describing a render must bind its final encoded hash.
6. Record material architecture decisions in the next available ADR number
   and update `ARCHITECTURE.md` during implementation. Register/export new
   schemas. Prefer existing artifact rows and sidecars; do not add a SQLite
   migration unless a real persistence requirement demands it.

**Completion evidence:** ledger and source/artifact inventory exist; baseline
failure is reproduced; evidence interfaces and compatibility approach are
documented. Proposed contract names in this plan may be adapted to existing
conventions, but their required facts and gates must remain.

### R1 work package — Finish authorization and preserve rendering coverage

**Primary files:** `hero/render_authorization.py`, `hero/advanced_service.py`,
`hero/render_checkpoint.py`, `schemas/render_checkpoint.py` under
`src/clipforge/`; `apps/renderer/scripts/render-authorization.mjs` and
`render-advanced-hero.mjs`; `tests/test_render_authorization.py`,
`tests/test_round29_reframe_browser.py`, `tests/test_round30_caption_browser.py`.

1. Refactor browser-test setup into a shared helper using typed render input,
   canonical batch creation and the production authorization issuer. The
   helper must only create fixtures, never disable worker validation.
   Keep the original decoded face-follow/contain assertions.
2. Inventory every caller of `RemotionAdvancedRenderBackend.render_batch`
   and direct Advanced Node entrypoint. Update legitimate test callers to
   satisfy the contract. Ordinary operators must enter through the service.
3. Check full-render, audio-only and video-chunk modes separately. The current
   JavaScript applies the canonical run-location check only when
   `renderMode === undefined`; prove copied checkpoint batches cannot skip
   that check. Validate the canonical final target for every mode before
   deriving the permitted checkpoint output.
4. Confirm renderer dependency identity is actually checked at the correct
   boundary, not merely accepted because it resembles a SHA. Bind the
   current worker recipe and its local dependencies; reject stale worker
   receipts before expensive rendering. Persist durable per-candidate
   authorization evidence so later candidates cannot erase the earlier
   candidate's audit trail.
5. Exercise the actual service with missing or changed persisted parents.
   A test passing arbitrary matching strings to the issuer is only a unit
   test; it does not prove that the service loaded valid source, Hero,
   alignment, TimeMap, direction, arc, font and asset evidence.
6. Create a separate diagnostic inventory for the six old review-trio files,
   with relative paths, computed hashes, `diagnostic_only=true`, reasons and
   no delivery eligibility. Keep original files and manifest intact. Prove
   no delivery entrypoint treats the inventory or a copied batch as approval.
7. Preserve the distinction between a local integrity receipt and a security
   boundary: the filesystem owner can modify local files. No claim of
   unforgeable authorization is warranted without a separate trusted issuer.

**Required regressions:** valid full/audio/chunk work; absent receipt;
changed parent/input/media/worker digest; traversal and symlink; copied full
and checkpoint runs; malformed frame ranges; duplicate candidate entries;
two-candidate receipt retention; interrupted authorized run/resume.

**Exit:** real browser face-follow and caption tests execute their pixel
assertions; service tests reject stale parents; all modes enforce the same
run binding; diagnostic inventory is excluded from delivery.

### R2 work package — Prove timing, speech coverage and encoded caption edges

**Primary files:** `hero/captions.py`, `hero/editorial_arc.py`,
`hero/advanced_build.py`, `hero/advanced_service.py`, `preview/trim.py`,
`qa/technical.py`, `schemas/hero.py`, `schemas/advanced.py`; shared caption
components in `apps/renderer/src/captions/`; tests for caption coverage,
staging clock, editorial arcs and production browser captions.

1. Write a regression for a caption word whose interval starts earlier or
   ends later than its aligned word. Current `validate_caption_word_coverage`
   tests containment, whereas `_caption_alignment_problems` tests exact
   equality. Unify the invariant before rendering and in QA: word id, order,
   source binding, output microseconds and derived frames must agree.
   Phrase display holds may extend; active-word timing must not be stretched.
2. Reject duplicate ids in the alignment itself, provisional alignment,
   mismatched TimeMap/source/candidate identity and invalid producer evidence.
   Reuse `validate_current_alignment_evidence` at existing live callers.
3. Build `CaptionAudioCoverageReport` (proposed) from the effective TimeMap,
   alignment, caption plan and reviewed source speech inventory. Map source
   spans through the canonical mapper in output segment order. Every retained
   aligned word must have exactly one rendered word binding.
4. Account for speech absent from ASR as well as words present in it. A word
   list cannot prove that untranscribed speech does not exist. Compare the
   selected audio against reviewed dialogue/reaction/nasheed spans from R5;
   optional VAD may flag uncertain intervals but cannot prove completeness.
   Natural silence is allowed. Unexplained audible spans block coverage.
5. Validate staged picture and speech start, duration, rate and paired map.
   Preserve the one-continuous-audio checkpoint recipe. Reject cuts through
   aligned words and inspect speech onset/tail around every cut, including
   first/last consonants. Do not hide timing errors with audio fades.
6. After final normalization/encoding, decode by integer frame index: cue
   start, middle, last owned frame, preceding frame where available, and first
   frame outside the cue. Use the renderer's defined quantization; never seek
   the exact total-output endpoint as if it owned a frame.
7. Deduplicate decoded frame files across cues but retain all cue references.
   Persist frame index, output microseconds, mapped source/segment, cue/word
   identity, relative image path/hash and encoded MP4 hash. Include every
   word-highlight change, cut boundary, first and final frame.
8. Use production-composition caption-free comparisons for glyph evidence.
   Distinguish actual glyphs and active-word colors from backing-panel
   variance. Geometry/pixel checks support visual review; they do not prove
   Arabic spelling or that the correct word was spoken.

**Required regressions:** old equal-duration distributor; widened/shifted word
timings; 11-second retained speech gap; natural silence allowed; missing
reaction; very short words; multiple/reordered source segments; cut-through
words; exact cue endpoints; non-integer time rejection and rational frame
rates per AGENTS; staged and encoded AV mismatch. Alignment metadata alone
must never be labeled measured lip-sync proof.

**Exit:** preflight and QA share the same timing invariant; a report binds
staged audio, map, reviewed speech inventory and every decoded cue boundary to
the final MP4. R5/R7 integration is required before marking R2 complete.

### R3 work package — Solve CTA and logo placement after the final transform

**Primary files:** `campaign/overlays.py`, `schemas/campaign.py`,
`hero/advanced_service.py`, `hero/advanced_build.py`,
`apps/renderer/src/hero/AdvancedHeroDraft.tsx` and its layout helpers;
`tests/test_tarteel_overlay_direction.py`.

1. Inventory the exact crop, zoom, foreground bounds, rounded frame, caption
   lane and context/logo layout used by each approved campaign variant.
   Freeze one typed transform consumed by planning, rendering and QA; avoid
   independent Python/TypeScript geometry formulas without parity tests.
2. Measure native CTA/logo size ratios from the actual selected source
   spans, not their minimum-to-maximum envelope across excluded footage.
   Retain measurement frame hashes and bounds. White-pixel heuristics alone
   must not certify that a complete source logo is visible after cropping.
3. Build timed exclusions for faces, full important character regions,
   tablet, source-native text/logo and generated overlays. Record annotation
   provenance/confidence; missing child/tablet geometry is unknown, not empty.
   Persist reviewed annotations when an analyzer cannot supply reliable ones.
4. Map exclusions to final output coordinates after the foreground transform.
   Measure the animated CTA's visible alpha bounds, preserve its aspect ratio,
   and include its maximum entrance/exit extent. Resolve the current width/
   height assumptions against actual asset dimensions.
5. Evaluate candidate time windows and placements over the whole animation.
   Prefer every output frame for short CTAs; if evidence is sampled, define
   a conservative motion envelope and reject uncovered intervals. Persist
   candidates, collisions, rejected reasons, winning bounds and sample ids.
6. Use a versioned clearance margin and explicit platform crop profiles.
   Require readable size, visibility in the source picture and clearance
   from all exclusions. If no location works, try another grounded moment;
   otherwise block with evidence rather than shrink to unreadability.
7. Apply equivalent proof to added logos. Check source-logo visibility after
   the final crop; avoid duplicates when it remains fully visible. Follow
   the latest approved upper-logo campaign exception where applicable,
   rather than overriding it with the older foreground-only rule.
8. Bind `OverlayExclusionEvidence` to source, visual annotations, transform,
   CTA asset, alpha recipe, fonts/layout, interval and plan hashes. Decode
   entrance/hold/exit and maximal-overlap frames for the final MP4.

**Required regressions:** face, body/tablet, caption, context, source-logo,
watermark and platform-rail collision; moving child between samples; overlay
aspect mismatch; incomplete evidence; no safe position; crop/zoom/variant
change invalidates clearance; no duplicated source logo.

**Exit:** the solver and renderer agree on final bounds, both background
variants have their own verified evidence, and no hard exclusion intersects
the CTA or added logo throughout its visible interval.

### R4 work package — Require a coherent story and intentional opening

**Primary files:** `schemas/arc.py`, `hero/editorial_arc.py`,
`hero/advanced_service.py`, `hero/direction_service.py`,
`cli/hero_advanced_cmd.py`, review surfaces; `tests/test_editorial_arc.py`.

1. Add `EditorialArcReview` with source/arc/transcript/scene hashes, beat ids,
   transcript spans, representative frame references, subject/event labels,
   hook promise, body development, payoff, adjacent-beat continuity verdicts,
   reviewer identity/role and reasons. Labels alone do not prove continuity.
2. Generate a shot strip and exact transcript in output order, showing source
   timestamps, cuts and excluded lead-ins. Review enough neighboring context
   to detect misleading assembly, unresolved pronouns and abrupt starts.
3. Require an explicit opening word and speech-safe boundary with evidence.
   Exclude `زين الحمد لله` in the memorization-question edit; do not ban the
   phrase globally. Keep `احنا اليوم بإذن الله` as the approved opening for
   the application/Quran clip only.
4. Reject a hook introducing a different subject from the body unless the
   arc explicitly develops and closes that connection. The old t33 food/
   Yasser hook cannot be accepted just because it attracts attention.
5. Preserve legitimate cold-open repetition only under an explicit reviewed
   recipe, if supported. Current repeated-source/word gates must not be
   bypassed. If this requires a contract change, defer it to a separate ADR;
   avoid repeated segments for this repair's proof.
6. Keep source containment inside the supported approved Hero scope.
   Do not stitch across sources or widen approved ranges without the proper
   candidate/Hero workflow. Semantic review must not manufacture publication
   approval; an AI assessment and a human review decision are distinct.
7. Bind review hashes to planning, QA and cache. A changed first word, cut,
   subject or payoff invalidates the effective arc review.

**Required regressions:** unrelated hook rejected; omitted setup; missing
scene/span evidence; stale arc review; irrelevant lead-in; valid same-event
reordered arc; cuts do not clip consonants; review cannot approve publication.

**Exit:** every retained beat has inspectable audio/visual context and a
recorded continuity decision; the old t33 arc has a recorded rejection reason.

### R5 work package — Correct Arabic while preserving what was actually said

**Primary files:** `schemas/hero.py`, `schemas/campaign.py`,
`campaign/quran.py`, alignment producers/callers, `hero/captions.py`,
`apps/renderer/src/captions/CaptionPlate.tsx`; Quran, caption and language
evidence tests.

1. Define a versioned correction sidecar binding immutable raw ASR, source
   hash, source ranges, original text, corrected text, locale, reviewer,
   listening/context evidence and uncertainty. Preserve raw ASR and create a
   new derived artifact; do not overwrite transcript history.
2. Classify selected intervals as dialogue, recitation, reaction, nasheed,
   silence or uncertain. Record what remains in the edit and its caption
   treatment. Ordinary retained speech/nasheed cannot be silently excluded
   from captions; a proposed exception must be policy-allowed and explicitly
   reviewed. Cutting a span is different from leaving it audible uncaptioned.
3. Review Arabic against the audio and neighboring meaning. Context may
   suggest a correction but cannot authorize invented speech. Represent
   observed laughter with an approved reaction cue such as `هههه`; do not
   assign invented word-level alignment to nonlexical sound.
4. Search authoritative Quran sources when recitation appears; store the
   fetched canonical snapshot, exact verse reference, URL and hash. Map the
   audible span to canonical text and preserve omission/mispronunciation
   evidence. Canonical text correctness is separate from pronunciation.
   Ambiguous matches remain unresolved.
5. Re-align corrected selected speech with the supported pinned aligner.
   Preserve model identity, input hashes and existing live-evidence checks.
   Never evenly redistribute corrected words, rescale old word timings, or
   promote fake alignment to verified live evidence.
6. Encode the approved coloring states explicitly: ordinary active words
   follow measured word intervals; verified-correct recitation words become
   green while active then white; verified incorrect words remain red within
   the displayed cue; unverified words are never falsely green.
7. Check all word transitions, not just the first word. Preserve Arabic joining,
   diacritics and RTL order; fit the approved single-line caption layout using
   phrase grouping and measured glyph bounds. Pin local font identities/
   hashes, and invalidate layout evidence when text or fonts change.
8. Decode real Arabic output. Record shaping inspection, readable bounds,
   baseline comparison and color transitions. List installed OCR packs;
   unavailable OCR or listening capability must be reported, never replaced
   by a claim that an image or transcript proves speech accuracy.

**Required regressions:** raw ASR immutability; corrected word changes trigger
re-alignment; unsupported locale; uncertain Quran match; stale canonical
snapshot; missing/replaced font; every-word coloring; laughter and nasheed
coverage; one-line RTL bounds; incorrect word persistence.

**Exit:** selected material has reviewed text and complete timing/coverage;
decoded Arabic is readable and follows the approved coloring policy.

### R7 work package — Make evidence mandatory for QA and reuse

**Primary files:** `schemas/qa.py`, `schemas/advanced.py`,
`hero/advanced_service.py`, `hero/render_checkpoint.py`, `qa/service.py`,
`qa/technical.py`, `review/final_gate.py`, `publish/preflight.py`,
`publish/service.py`, `campaign/production.py` and relevant CLI commands.

1. Assemble `ViewerEvidenceBundle` from R2/R3/R4/R5 reports after the final
   encoded output exists. Include source/run/candidate identity, plan/recipe/
   profile/font/asset hashes, MP4 hash, probe facts, measured integrated
   loudness/true peak, event-window SFX measurements, decoded frames, contact
   sheets and configured platform-crop previews.
2. Keep objective results, operator observations and human-watch records as
   separate typed facts. A frame dump without assessment is not a passing
   visual test. A claimed complete watch needs reviewer identity, artifact
   hash, coverage and observations; do not create one automatically.
3. Make absence/uncertainty insufficient evidence and proven defects fail.
   Reuse existing QA status enums and aggregation; do not invent a parallel
   gate or allow a success average to cancel a failed hard rule.
4. Persist evidence atomically and checkpoint generation stages. A crash
   after encoding must permit verified evidence generation to resume without
   blindly re-rendering. Incomplete evidence must not promote a final package.
5. Separate render-byte reuse from approval reuse. Unchanged bytes may be
   reused where verified, but a changed policy or evidence invalidates QA and
   effective final approval. Source/clock/caption/style/font/overlay/audio/
   recipe changes invalidate the appropriate render dependencies too.
6. Include evidence digests in Advanced artifact/QA/final-review/delivery
   bindings. Avoid circular hashes: evidence binds encoded bytes and input
   hashes; the manifest references evidence; QA references the manifest;
   final review references QA. Keep historical artifacts readable under
   their recorded recipe, without treating missing evidence as current
   campaign acceptance.
7. Expose evidence/blockers through existing show/verify/review surfaces.
   Resolve relative paths at access time with confinement checks; exported
   evidence contains no credentials or absolute private filesystem paths.

**Required regressions:** absent/corrupt/stale bundle; modified frame file;
wrong MP4; missing watch decision; changed each dependency in isolation;
unchanged render cache hit; evidence-only regeneration; stale final approval;
campaign resume parity; failed export leaves the previous package intact.

**Exit:** a technically valid MP4 with missing captions, unsafe CTA or
unreviewed continuity cannot pass the campaign gate. Historical approvals
never authorize new bytes.

### R6/R8 work package — Review sources, replace t33 and prove the whole path

**Inputs:** frozen campaign checkpoint; authorized source files; campaign
rules/assets and idea library; newly implemented evidence pipeline.

1. Rediscover current source, candidate, transcript, alignment, Hero and
   review bindings. Recompute actual media hashes and check rights. Earlier
   source IDs are lookup hints only. Do not use the malformed repeated-ASR
   candidates as reviewed evidence.
2. Inspect selected source audio and shots with neighboring context. Produce
   R5 corrections first, then one coherent t33 replacement story with setup,
   development and payoff. Preserve the user-approved t22 and t12 intent.
3. Draft an editorial table per idea: source spans, actual words, visual
   content, beat purpose, opening, ending, cut rationale, overlays, exclusions
   and required review state. Aim for the requested 40–45 seconds or longer
   when the source supports it; never pad by repetition or irrelevant moments.
4. Use existing candidate/Hero/direction/arc services. Inspect current
   `--help` for command arguments and record the exact runnable invocation
   with discovered IDs. Do not write `batch.json` manually or copy a previous
   plan and change dependency labels. If a required human approval is absent,
   use only the supported unapproved draft path and report that state.
5. Render a short diagnostic sample of the actual production composition to
   inspect caption size, title location, zoom, frame, CTA/logo and colors.
   Correct the shared plan/component if it fails; regenerate stale evidence.
6. Produce a full multi-segment real-source Hero/Advanced proof. A single
   contiguous clip cannot prove cut/merge sync. Include a real crop/zoom and
   animated CTA; use purposeful graphics/SFX only where appropriate and
   cleared. No music or unrelated outside footage.
7. Produce both dark-source-blur and source-palette variants for each of the
   three intended stories after the pilot proof succeeds. Reuse the semantic
   plan and audio/map; variant geometry/style still needs its own hashes,
   overlay proof and decoded QA. Confirm the renderer can actually express
   both approved frame/backdrop combinations before starting the batch.
8. Decode the final files, compare all cut/cue/CTA boundaries, inspect platform
   crop previews and review complete playback with audio and muted playback.
   Check the start/middle/end of each segment for AV drift; matching stream
   duration alone is insufficient. If the operator lacks playback capability,
   record the missing inspection and leave visual acceptance pending.
9. Exercise interruption/resume in a controlled test run. Verify chunk
   ownership, byte hashes, continuous audio and failure cleanup; compare
   resumed output semantically to an uninterrupted run. Do not require
   byte-identical encodes unless encoding settings guarantee determinism.
10. Run service verify, QA, final-review and package checks using actual CLI
    help. Prove unapproved/stale output is blocked from export. Produce a
    deliverable only after an effective human approval for those exact bytes.

**Exit:** first a complete multi-segment service proof, then six new
reviewable variants with source/plan/run/evidence ids and hashes. The original
review-trio files remain unchanged. Technical completion and human visual
acceptance must be reported separately.

### Validation, handoff and restart protocol

Run focused tests after each package. These commands refer to current tests;
add the new report/geometry/continuity/cache regressions to their owning
suites as they are implemented:

```bash
uv run pytest tests/test_render_authorization.py tests/test_browser_isolation.py -ra
uv run pytest tests/test_caption_coverage.py tests/test_qa_caption_coverage.py tests/test_editorial_arc.py -ra
uv run pytest tests/test_tarteel_overlay_direction.py tests/test_advanced_hero.py -ra
uv run pytest tests/test_round29_reframe_browser.py tests/test_round30_caption_browser.py -ra
uv run clipforge schema export
uv run clipforge schema check
```

Export schemas only after intentional contract edits. When implementation is
stable, run `./scripts/validate.sh` and save the complete output and exit code.
It stops on its first failed command; do not claim later steps ran after a
failure. The previous audit's renderer/schema/doctor successes were separately
run, because its validation script stopped at pytest.

Record skip reasons, browser availability, actual render backend, model/OCR
capabilities, test counts, media paths/hashes, measured audio facts and
remaining limitations. Verify no child render/test processes remain. Review
the diff for secrets/media and update README/operator docs for changed
commands. End implementation with a coherent commit and draft PR under
repository conventions; record CI status for that exact head and do not merge.

At every handoff, update this document's status matrix and the execution
ledger. On resumption, read them, verify current code and evidence hashes,
then continue the earliest incomplete dependency. Never interpret a previous
summary, a passing unit test, or the word “implemented” as viewer acceptance.

## Required next-round tests

- copied/manual batch with an environment marker is rejected;
- fabricated parent hash, missing authorization, absolute output path, and
  output outside the run directory are rejected;
- diagnostic baseline is marked `diagnostic_only` and cannot be delivered;
- jump-cut caption/audio mapping, exact endpoint frames, cut-through-word,
  equal-distribution timing, short-word readability, and source audio gaps;
- CTA collision against face, child/tablet, caption, source logo, watermark,
  upper context, and platform rails; no-safe-position failure;
- overlay evidence covers entrance, hold, and exit samples and binds the
  final transform hash;
- semantic hook/body/punch continuity requires a reviewed shot strip;
- Arabic correction preserves raw-ASR hash and Quran review provenance;
- nasheed/reaction coverage is captioned or explicitly excluded;
- viewer evidence is required, artifact-hash bound, and becomes stale after
  each output-changing dependency;
- a full Remotion service render from a newly reviewed candidate produces the
  evidence bundle and remains pending human final review.

## Round completion rule

This next-round document is complete only when R1–R8 have their exit evidence.
Until then, the parent plan remains **IN EXECUTION** and the system remains
blocked from calling any of the old review-trio outputs upload-ready.
