# Tarteel review-trio execution audit — 2026-10-24

**Status:** TECHNICALLY VERIFIED IN CODE; ROLE-ROUTED WORKFLOW READY; REAL-SOURCE ACCEPTANCE REMAINS OPEN

**Reviewed:** 2026-10-24 (Africa/Cairo)

**Branch:** `round-35-quran-caption-verification`

**HEAD:** `4ac0748bbf8efa4dc7f66f6de5b6904945bd824e`

**Baseline:** `origin/main` at
`989bf5d6ec27878d46505dc09becedfc848cd749`

**Draft PR:** #37, open and stacked on `round-34-envato-material-prep`.
This branch has not been merged.

This is an execution review of the current repair plan. It records what the
implementation now prevents, what the current validation actually proves, and
the exact work required in the next round. It does not promote an old render,
proposal sidecar, or historical approval into production evidence.

## Review result

The system-level fixes landed for the previously reported failure classes:

- caption construction is tied to exact forced-word identity, order, text,
  source/output microseconds, frame edges, reviewed speech evidence, and the
  encoded output;
- clean Tarteel renders require a service-issued authorization, current
  render-input dependencies, an accepted editorial arc, transformed overlay
  evidence, and the speech/caption evidence available for that run;
- CTA/logo clearance is evaluated after the final crop/reframe in output
  coordinates, with exclusions for faces, children/body, tablet, captions,
  context, source branding, watermark, and platform rails;
- the renderer uses half-open frame ownership and shared cue windows, and
  resumable chunks cannot be assembled unless their input and dependency
  receipts match;
- QA/cache/final review reject stale source, alignment, caption, overlay,
  arc, render, and viewer evidence;
- final approval for the clean style requires an append-only
  `HumanPlaybackReview` for the exact artifact, with both audio and muted
  observations.

These statements are supported by the focused regression suites and the final
split validation run. They are implementation and technical-validation facts,
not a claim that the Tarteel campaign has a new accepted video.

The responsibility split is now explicit in the system. `codex_operator` is
the editorial brain and may invoke typed source, speech, candidate, Hero,
direction, asset, graphics, render, and QA tools. `system_enforcer` is the
media and evidence layer that owns timing, rights, provenance, cache, stale
checks, QA, and delivery. `human_reviewer` is required for exact audio/muted
playback and final approval. SQLite migration 7 persists the role on review
rows. `clipforge operator roles`, `tools`, `extensions`, and `verify` expose
the routing catalogue. The project entry points are [SKILLS.md](../../SKILLS.md)
and `.codex/skills/clipforge-production-operator/SKILL.md`.

## Evidence checked

The current work root contains no current real-source
`authorization.json`, `caption-coverage.json`, `speech-review.json`,
`viewer-evidence/bundle.json`, `overlay-exclusion.json`, accepted
`editorial-arc-review.json`, or `HumanPlaybackReview` for a Tarteel service
run. The files with names such as `speech-review.proposal.json` and
`editorial-arc-review.proposal.json` explicitly say they are unreviewed
proposals and have not been used as acceptance evidence.

The six MP4s under
`var/work/campaigns/Tarteel/review-trio/` remain historical forensic outputs.
Their manifest records them as review-only or blocked, and the manifest uses
absolute paths and is not a service authorization. They must not be repaired in
place or called upload-ready.

The authorized pilot source remains:

- path: `var/work/campaigns/Tarteel/acquisitions/youtube/tf6zk3FqGwk.mp4`;
- source SHA-256:
  `64ebef09f37368374748a45295c0b8ec9f20d886f4111cb342d7d2d836a55bb1`;
- source asset: `bdafcfaf-73c4-4584-8503-ba6ffb869711`;
- candidate: `89a5a2fa-ce33-5527-b78d-46a685696c9b`;
- source probe: AV1, 1920x1080, 25 fps, 1154.6 seconds, AAC stereo at
  44.1 kHz; source integrated loudness measured about -16.1 LUFS.

The source was probed and a representative frame was inspected, but no human
audio/muted watch or accepted source-bound speech/arc/overlay review was
recorded during this audit. OCR is unavailable because Tesseract is not
installed; no OCR proof is claimed.

## Plan execution matrix

| Gate | Result | What is proven | What remains |
|---|---|---|---|
| R1 authorization and path confinement | **IMPLEMENTED / TECHNICALLY VERIFIED** | Service authorization, exact batch/dependency binding, copied/mutated/symlink/output-path rejection; renderer and browser regressions pass | Produce one real service receipt from a newly reviewed Tarteel run |
| R2 speech, caption, and audio coverage | **IMPLEMENTED / TECHNICALLY VERIFIED** | Typed coverage report, forced-word/text checks, half-open cue/word edges, encoded hash and staged-audio binding, stale rejection | Human-review the current source speech inventory and produce a real report with decoded cue-edge frames |
| R3 transformed CTA/logo clearance | **IMPLEMENTED / TECHNICALLY VERIFIED** | Typed exclusions and final-transform binding, candidate collision rejection, entrance/hold/exit geometry checks | Annotate and inspect the real source’s faces/children/tablet/captions/branding/rails; produce real exclusion evidence |
| R4 hook/body/punch continuity | **IMPLEMENTED / TECHNICALLY VERIFIED** | Accepted hash-bound arc is required; invalid ordering, overlaps, cut-through words, missing beats, and unreviewed openings reject | Create a reviewer-accepted source-bound arc and shot strip; do not reuse proposal sidecars |
| R5 Arabic, Quran, reaction, and nasheed coverage | **IMPLEMENTED / TECHNICALLY VERIFIED** | Raw ASR preservation, reviewed correction contract, separate Quran canonical evidence, explicit captioned/excluded interval semantics | Listen to the selected source, correct ordinary Arabic, caption or explicitly exclude every retained reaction/nasheed interval, and inspect Arabic shaping/color frames |
| R6 replacement for t33 | **OPEN** | Old malformed source-map output remains blocked by its manifest | Select a coherent replacement event, align it, build a closed arc, and render only through the service |
| R7 viewer-quality and human playback | **IMPLEMENTED / TECHNICALLY VERIFIED** | Viewer bundle generation, contact/crop sheets, loudness facts, artifact binding, stale invalidation, final playback contract | Generate the real bundle and record an independent audio + muted `HumanPlaybackReview` |
| R8 real-source end-to-end proof | **OPEN** | Resumable multi-unit path and final gates are covered by tests | Execute one real multi-cut Hero and Advanced Hero run, resume it once, verify all gates, and stop at an unapproved draft |

## Validation evidence

The earlier isolated validation run is recorded at
`var/work/validation/tarteel-repair-20261024/final/validate.log`:

- Python non-browser: **877 passed, 2 skipped, 18 deselected**;
- browser/Remotion: **18 passed, 872 deselected**;
- renderer: **62 tests passed across 12 files**;
- schemas matched;
- Ruff, mypy, renderer lint, and TypeScript typecheck passed;
- doctor: **9 pass, 1 GPU warning, 0 fail**. The warning only says that the
  host GPU could not be confirmed; the validated path is CPU-capable.

The two skips are the explicitly unavailable VoiceStudio live smoke and the
unconfigured Whop live smoke. No test was changed to hide a failure. No
browser, ffmpeg, Remotion, Node, or pytest process was left by the validation
run.

The focused audit regression group rerun after this review collected and
passed **68 tests** across caption evidence, render authorization, transformed
overlay direction, editorial arcs, viewer evidence, and final playback.

The role and operator-catalogue additions added another **7 focused tests**;
the final full run above includes them.

After those additions, `./scripts/validate.sh` was rerun on the current
worktree. Its console result was **877 passed, 2 skipped**, **18 browser
passed**, renderer **62 passed**, with schemas, mypy, Ruff, lint, typecheck,
and doctor passing as listed above. The earlier log remains the preserved
pre-role baseline; the current result is recorded in this audit to avoid
mistaking the older ignored log for the newer run.

## Remaining work for the next round

The next round must be evidence-first and must use the existing service path.
It must not create another manual batch renderer or fabricate a review record.

### 1. Start from a clean, resumable campaign run

1. Verify the branch, source SHA, rights record, candidate binding, alignment
   model/evidence status, and current campaign rules.
2. Create a new run directory below `var/work` with a relative-path baseline,
   source/rights inventory, tool versions, and an append-only progress file.
3. Stage only regular local files. Recompute every staged hash. Refuse symlinks,
   external paths, and old review-trio batch files.
4. If the process is interrupted, resume only completed units whose receipts
   still match. Leave the prior package untouched on any failure.

### 2. Produce reviewed speech and caption evidence

1. Inspect the selected source audio and transcript around the intended clip,
   including all dialogue, reactions, laughter, and nasheed.
2. Preserve the raw ASR/alignment hashes. Write ordinary-Arabic corrections
   with observed text, source span, reviewer, and evidence note.
3. Keep Quran canonical verification separate. Use the verified Uthmani text
   only for the retained Quran span; never infer a Quran word from a fuzzy ASR
   token.
4. Mark every retained audible interval `captioned` or `reviewed_excluded`.
   A gap, uncertain retained word, duplicate interval, stale hash, or cut
   through speech must fail before rendering.
5. Generate the typed coverage report and decode first/middle/last plus exact
   half-open cue/word-edge frames. Inspect Arabic joining, direction, green /
   white / red word state, and readable line geometry manually.

### 3. Build and accept the editorial arc

1. Review neighboring shots before choosing the hook. The hook must preview
   the same event that the body explains and the punch resolves.
2. Use explicit source/output spans with speech-safe boundaries. The approved
   `احنا اليوم بإذن الله` opening is scoped to its candidate and must not become
   a campaign-wide default.
3. Include a setup/body, a meaningful Quran or child response payoff, and a
   clean ending. Remove the irrelevant `زين، الحمد لله` lead-in where the
   reviewed arc excludes it.
4. Create a source-timestamped shot strip with representative frame hashes,
   transcript spans, output order, excluded ranges, continuity decisions, and
   reviewer identity. Only then write the accepted arc sidecar.

### 4. Solve transformed overlay placement

1. Measure the final crop/reframe first; do not size CTA/logo in source
   coordinates and hope it survives the portrait transform.
2. Sample CTA entrance, hold, exit, and maximum motion frames. Annotate full
   child/body regions, tablet, faces, captions, upper context, source-native
   logo, added watermark, and TikTok/Instagram rails.
3. Solve all candidate rectangles, persist rejected reasons and the winning
   rectangle, and make the renderer consume that exact rectangle.
4. Decode the same edge samples for both dark-blur and palette variants. Any
   collision, cropped logo, or platform-unsafe position fails the run.

### 5. Run, inspect, and verify the real output

1. Render Hero and Advanced Hero through the CLI/service with the same reviewed
   semantic plan. Do not use historical MP4s as a substitute.
2. Interrupt after a completed unit and resume. Verify the final assembled
   artifact, audio continuity, source-to-output TimeMap, caption edges, and
   output duration.
3. Generate the viewer bundle, ffprobe facts, ebur128/true-peak/silence facts,
   full contact sheet, 4:5/1:1 crop sheets, and CTA/caption edge frames.
4. Watch the complete clip once with audio and once muted. Record an
   append-only `HumanPlaybackReview` tied to the exact artifact and hashes.
5. Run Advanced verify, QA verify/gate, final-review verify, delivery verify,
   and cache/stale checks. Stop at an unapproved draft for independent visual
   review; do not call it upload-ready.

## Exit criteria for the next round

The campaign remains blocked from delivery until R1–R8 have current evidence.
The next round may be called technically complete only when the real run
contains authorization, speech/caption coverage, accepted arc, transformed
overlay exclusions, viewer evidence, and a successful resumable Hero and
Advanced Hero render. It may be called accepted only after a human has watched
the exact artifact with audio and muted playback and recorded the required
append-only review. Historical MP4s, clean CI, proposal sidecars, and metadata
claims cannot replace those records.

