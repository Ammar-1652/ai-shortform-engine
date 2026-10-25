# Tarteel review-trio follow-up plan

**Superseded for current status by**
[tarteel-review-trio-audit-2026-10-24.md](tarteel-review-trio-audit-2026-10-24.md).
The ordered remediation details below remain useful for the next execution
round; the audit is the authoritative evidence matrix.

**Created:** 2026-10-20 (Africa/Cairo)

**Scope:** remaining work after the R1/R2 implementation slice on
`round-35-quran-caption-verification`.

This document is an execution plan, not an acceptance statement. The current
branch still contains uncommitted work and draft PR #37 remains open against
`round-34-envato-material-prep`. The six files in
`var/work/campaigns/Tarteel/review-trio/` remain immutable forensic outputs.

For the complete ordered workflow, gate matrix, resumable-run rules, and
required checkpoint files, use
[the complete resolution workflow](tarteel-review-trio-complete-resolution-workflow.md).

## Audit findings

- The typed Advanced render authorization, caption-edge report, viewer-evidence
  bundle, and speech-review loader exist in code and have focused regression
  coverage.
- The current `var/work` tree contains **zero** `authorization.json`,
  `caption-coverage.json`, `viewer-evidence/bundle.json`, or
  `speech-review.json` files. No real Tarteel source has completed the current
  service path.
- The historical review-trio directory contains 18 MP4 files, including
  staged and duplicate intermediate outputs. The six named delivery variants
  are technically 1080x1920 with audio, but their manifests identify them as
  review-only or blocked and do not contain current service receipts.
- The historical manifest records `tarteel-12` and `tarteel-33` as provisional
  source-map renders. `tarteel-33` still has no replacement arc. OCR was not
  available (`tesseract` was not installed), and no human audio/muted watch
  record exists.
- Full validation previously reached `842 passed, 2 skipped, 3 failed`; the
  three failures were Chrome resource failures after host memory fell to about
  210 MiB. The isolated browser pair and the non-browser suite passed. This is
  an environment blocker for a clean full run, not proof of production
  acceptance.

## Remaining gates and exact remediation

### R3 — transformed CTA and logo clearance

The versioned `OverlayExclusionEvidence` contract and clean-render gate are
implemented. The next round must create and validate real source-bound
sidecars, then complete the decoded proof:

1. Supply a sidecar bound to source hash, candidate, TimeMap, final crop
   trajectory, campaign overlay spec, and renderer recipe.
2. Record sampled output frames across CTA entrance, hold, exit, and maximum
   motion extent. Each sample must contain transformed rectangles for faces,
   full child/body regions, tablet, timed captions, upper context line,
   source-native logo, added watermark, and TikTok/Instagram inner rails.
3. Keep unknown annotations distinct from an empty exclusion list. Missing
   body/tablet/logo/platform evidence must block a Tarteel render.
4. Make the solver persist all candidate rectangles, rejected collision
   reasons, winning rectangle, margins, and sample ids. The renderer must
   consume the winning rectangle and fail if it differs from the sidecar.
5. Decode entrance, hold, exit, and maximal-overlap frames from both blur and
   palette variants. Prove that the CTA and any added logo stay clear for the
   whole visible interval. Add cache invalidation for every evidence hash.

### R4 — semantic hook/body/punch continuity

The clean Tarteel planner and render input now require an accepted,
source-bound `EditorialArcReview` sidecar and carry its digest. The next round
must create the real review evidence and connect it to the source inspection:

1. Require an immutable `EditorialArcReview` sidecar beside every selected
   `EditorialArcDocument`; bind it to source, transcript, visual analysis,
   alignment, and the exact arc bytes.
2. Generate a reviewer-readable shot strip with source timestamps, output
   order, transcript spans, representative frame hashes, and excluded lead-in
   ranges.
3. Require explicit continuity decisions between hook/body and body/punch,
   claim closure, reviewer identity, and a speech-safe opening boundary.
4. Reject an unrelated hook, an omitted setup, a cut through a forced word,
   and a repeated source range. Keep the approved `احنا اليوم بإذن الله`
   opening scoped to its current candidate rather than applying it globally.
5. Bind the sidecar digest into planning, render input, QA, final review, and
   cache lookup. A changed cut or beat must invalidate every downstream record.

### R5 — Arabic, reaction, and nasheed coverage

1. Create source-bound correction sidecars for every ordinary-Arabic spelling
   correction. Preserve raw ASR, corrected display text, source window,
   locale, reviewer, and listening/context evidence.
2. Complete one speech inventory per retained source map. Mark every interval
   as dialogue, recitation, reaction, nasheed, silence, or uncertain and use
   `captioned` or `reviewed_excluded` explicitly.
3. Require observed text for all captioned audible intervals. A sidecar with a
   gap, stale ASR/transcript hash, duplicate interval, or unsupported locale
   must fail closed.
4. Add decoded Arabic glyph and active-color evidence for cue start, middle,
   word edges, and cue end. Verify joining and direction visually; OCR is
   supplemental and cannot substitute for review.
5. Keep Quran canonical Uthmani verification separate from pronunciation and
   ordinary dialogue correction. Do not color unverified Quran words green.

### R6 — replacement for t33

1. Re-open the frozen campaign checkpoint and rediscover current source,
   transcript, visual, and rights bindings. Do not reuse the malformed t33
   source map.
2. Review neighboring shots and audio around candidate moments. Select a
   single coherent event with the same subject in hook, body, and payoff.
3. Record a new arc review, forced alignment, direction, and speech inventory.
   Caption any retained reaction or nasheed; omit it only with an explicit
   reviewed-excluded interval.
4. Render one unapproved diagnostic through the service, inspect the decoded
   cut boundaries, and repair the shared planner or renderer if drift or an
   irrelevant hook appears.

### R7 — viewer-quality acceptance

1. Keep objective decoded evidence, operator observations, and human watch
   records as separate contracts. Do not synthesize a watch record.
2. Require the viewer bundle, caption report, overlay exclusion evidence,
   arc review, and speech inventory for clean Tarteel QA. Missing or stale
   evidence is `INSUFFICIENT_EVIDENCE`; proven collisions or bad timing are
   `FAIL`.
3. Add a controlled evidence-only resume path after encoding. It must reuse a
   verified MP4, regenerate missing reports, and leave the prior package
   untouched when evidence generation fails.
4. On a clean host, run both browser smoke jobs twice, then decode full,
   platform-cropped, cue-edge, CTA-edge, and final frames. Watch each clip
   once with audio and once muted and record the reviewer observations.

### R8 — real-source end-to-end proof

1. Use only the authorized Tarteel source files already in the frozen work
   area. Recompute source and rights hashes before planning.
2. Produce one real multi-segment Hero and Advanced Hero draft through the CLI
   and service. Verify resumability by interrupting after a completed unit and
   resuming from the checkpoint.
3. Produce blur and palette variants only after the semantic arc, speech,
   overlay, caption, and viewer gates pass for the pilot.
4. Run Advanced verify, QA verify/gate, final-review verify, delivery verify,
   and package checks. Prove that an unapproved, stale, or evidence-mismatched
   artifact cannot be exported.
5. Record exact MP4/contact-sheet paths, hashes, ffprobe facts, loudness facts,
   renderer/backend, source spans, and human-watch status. Do not call any
   output upload-ready until a human approves that exact artifact.

## Required validation sequence

```bash
uv run pytest tests/test_render_authorization.py tests/test_caption_evidence.py \
  tests/test_tarteel_overlay_direction.py tests/test_editorial_arc.py \
  tests/test_viewer_evidence.py -ra
uv run pytest -m 'not browser' -q -ra
uv run clipforge schema export
uv run clipforge schema check
uv run mypy
uv run ruff check .
pnpm --dir apps/renderer lint
pnpm --dir apps/renderer typecheck
pnpm --dir apps/renderer test
./scripts/validate.sh
```

The full validator must be rerun on a host with enough memory for Chrome. A
resource failure must remain recorded with its exact failed test and available
memory. No browser, ffmpeg, Remotion, or test process may remain running.

## Exit condition for the next audit

The next audit can close this plan only when R1–R8 each have current evidence,
the real service artifacts contain authorization and viewer/caption reports,
all intended variants have decoded frame and human-watch records, the full
validation is clean, and effective human approval exists for any artifact
called deliverable.
