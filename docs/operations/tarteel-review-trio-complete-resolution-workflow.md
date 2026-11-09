# Tarteel review-trio complete resolution workflow

**Status:** execution plan; current execution audit is
`tarteel-review-trio-audit-2026-10-24.md`

**Created:** 2026-10-21 (Africa/Cairo)

**Branch at planning time:** `round-35-quran-caption-verification`

**Purpose:** provide one repeatable workflow for resolving the remaining
Tarteel failures: caption and speech coverage, Arabic and Quran accuracy,
unrelated hooks, rough cuts, CTA/logo collisions, missing viewer evidence,
unreviewed t33 replacement, interrupted renders, and the lack of a real
end-to-end production proof.

This plan applies to Hero, Advanced Hero, both background variants, and every
future Tarteel candidate. It does not turn historical MP4s into approved
deliverables. Existing review-trio files remain immutable forensic evidence.

## Completion language

Every run records three separate states:

| State | Meaning |
| --- | --- |
| **IMPLEMENTED** | The code path and typed gate exist. |
| **TECHNICALLY VERIFIED** | Current source-bound evidence, decoded output, and required tests prove the behavior for the exact artifact. |
| **AWAITING HUMAN VISUAL ACCEPTANCE** | A reviewer has not yet watched and accepted the exact MP4 with audio and muted. |

No state may be reported as “PASS”, “production-ready”, or “upload-ready”
until the exact artifact has effective human approval. A failed, stale, or
missing evidence record is a block, not a warning.

## Operating model

The operator supplies editorial judgement and reviewed evidence. The Clipforge
service performs deterministic media work, rendering, validation, checkpointing,
and packaging. A plan, skill, model score, or transcript cannot claim a fact
that has not been checked against the source.

The workflow always follows this dependency order:

```text
campaign rules and rights
  -> source and transcript truth
  -> reviewed speech inventory and alignment
  -> reviewed hook/body/punch arc
  -> crop and overlay exclusion evidence
  -> direction, captions, graphics, and licensed assets
  -> resumable Hero/Advanced render
  -> decoded technical and viewer evidence
  -> independent human watch
  -> final review and local delivery
```

No downstream stage may silently repair a missing upstream decision. When a
gate fails, keep the input and evidence, record the failure, and return to the
earliest invalid stage.

## Phase 0 — establish a clean, reproducible run

1. Record `git status --short --branch`, current HEAD, actual `origin/main`,
   active branch, open draft PR, and the baseline of the frozen Tarteel
   checkpoint. Do not reset or overwrite unrelated work.
2. Read the current campaign hard rules, rights policy, architecture notes,
   TimeMap rules, and the latest execution ledger. Copy the ledger hash and
   plan hash into the run record.
3. Confirm that the source files are inside the authorized work root. Compute
   SHA-256 hashes, probe duration/frame rate/audio, and verify campaign-provided
   rights records and evidence URIs.
4. Inventory existing candidate, transcript, alignment, arc, direction,
   overlay, QA, final-review, and delivery records. Mark each as current,
   stale, historical, or missing. Never infer current status from a filename.
5. Check available memory and renderer/browser prerequisites. Stop competing
   browser, ffmpeg, Remotion, and test processes before a production run. A
   browser crash caused by host exhaustion is recorded as an environment
   failure and rerun on a clean host; it is not converted into a green result.
6. Create a unique run id under the gitignored work root. All intermediate
   files, receipts, logs, and partial outputs are written beneath that run.

**Phase exit evidence:** `run-baseline.json`, source/rights hash inventory,
environment report, and an explicit list of reusable versus stale artifacts.

## Phase 1 — build the source-truth packet

For each source and candidate, create a reviewer-readable inspection packet
before selecting a cut.

1. Extract a timestamped frame strip at scene changes and at a bounded regular
   interval (one second is the default; use a shorter interval for rapid
   reactions). Include source time, frame hash, detected faces and important
   objects, original logo/CTA visibility, and any text visible in the source.
2. Generate a source audio waveform and listen through every proposed range.
   Record speech, recitation, laughter, reactions, nasheed, silence, overlap,
   and uncertain audio. ASR is a locator; it is not the final truth.
3. Bind raw ASR, transcript, visual analysis, alignment, and source hashes to
   the packet. Preserve the original text and source timestamps beside any
   correction.
4. For Quran passages, identify the likely ayah online from the spoken
   context, verify it against a reliable canonical source, and record the
   exact Uthmani display text and reference. Keep canonical Quran verification
   separate from ordinary Arabic spelling correction.
5. Measure the original logo and any source-native CTA in the source frame.
   Record its relative size, safe margins, and visible interval. This becomes
   the reference for an added asset; it is not permission to enlarge it.

**Phase exit evidence:** source inspection packet, corrected transcript review,
frame strip/contact sheet, audio notes, Quran references where applicable, and
rights/provenance records. A missing source fact is `insufficient_evidence`.

## Phase 2 — create complete speech and caption evidence (R5)

1. Build a source-bound speech inventory covering every retained source range.
   Each interval is exactly one of `dialogue`, `recitation`, `reaction`,
   `nasheed`, `silence`, or `uncertain`; each is explicitly `captioned` or
   `reviewed_excluded`.
2. Force-align the selected clip using the existing alignment pipeline. Store
   integer microseconds, word ids, source spans, output spans, and the
   `TimeMap` digest. Reject stale maps and duplicate or overlapping intervals.
3. Write an ordinary-Arabic correction record for every changed word. Include
   raw ASR, corrected display text, context, source window, reviewer, and the
   reason for the correction. Do not hide an uncertain word in a caption.
4. Write the separate Quran canonical record. An unverified Quran word cannot
   receive the verified green treatment. Preserve diacritics and the selected
   canonical font when the campaign requires it.
5. Group captions into readable one-line phrases without losing words,
   punctuation, laughter, or numbers. Keep active-word coloring as a style of
   the caption, never as a replacement caption. For Arabic, animate whole
   shaped runs or lines when segmentation is uncertain; never reverse letters
   manually.
6. Test every cue at first frame, midpoint, every word edge, and the first
   frame after the endpoint. Verify the audio word, video frame, and displayed
   word refer to the same source moment. Short cues must remain visible long
   enough to read.
7. Decode the final render and record glyph bounds, direction/joining, text
   color, and caption safe-area placement. OCR may supplement this evidence;
   it cannot replace listening or visual review.

**Phase exit evidence:** accepted speech review, Arabic corrections, Quran
verification, caption/audio coverage report, decoded cue-edge frames, and no
unaccounted audible interval. Any missing reaction or nasheed caption blocks
the clean render.

## Phase 3 — select a coherent editorial arc (R4 and R6)

1. Review neighboring source context before choosing a hook. A hook may be a
   later strong moment only when the body returns to the same event and closes
   the promise. Do not use a dramatic but unrelated reaction.
2. Define the arc as explicit source/output spans: opening hook, setup/body,
   escalation or demonstration, and payoff/punch. Record why each beat is
   needed and what claim it supports.
3. Set opening and closing boundaries on speech-safe frames. Do not cut through
   a word, leave duplicated syllables, retain “زين الحمدلله” when it is outside
   the selected question, or introduce a silence caused by a bad trim.
4. Preserve segment list order in the `TimeMap`; do not sort by source time.
   Prove that every segment is intentional, no source range is repeated, and
   the same people/event remain understandable after a jump cut.
5. For t33, discard the malformed arc and rediscover a replacement from the
   frozen source checkpoint. The replacement must include the nasheed or mark
   it reviewed-excluded with a reason. It must have a coherent payoff before
   rendering.
6. Produce `editorial-arc-review.json` with exact source spans, transcript
   spans, representative frame hashes, continuity decisions, claim closure,
   reviewer identity, and accepted opening boundary.

**Phase exit evidence:** shot strip, accepted arc review, hash-bound arc,
forced-alignment digest, and a written explanation of hook/body/punch
continuity. An arc without reviewed frames is not accepted.

## Phase 4 — solve framing and transformed overlay clearance (R3)

1. Use the final crop/reframe trajectory and TimeMap. Compute all positions in
   output portrait coordinates after transform; do not use source coordinates
   for CTA, logo, captions, or graphics.
2. Sample every CTA entrance, hold, exit, and maximum camera-motion extent.
   At each sample annotate faces, complete child/body regions, tablet, captions,
   upper context line, source logo, added watermark, and platform inner rails.
3. Store these observations in `overlay-exclusion.json`, bound to source hash,
   candidate, TimeMap, crop trajectory, overlay spec, and renderer recipe.
   Distinguish unknown from empty. Missing body, tablet, logo, caption, or rail
   evidence blocks the render.
4. Solve CTA/logo placement against the sampled transformed rectangles. Persist
   all candidates, rejected collision reasons, winning rectangle, margins, and
   sample ids. The renderer must consume the winning rectangle and fail if its
   geometry differs from the sidecar.
5. Keep added CTA as the licensed alpha video asset, muted unless the direction
   explicitly allows its audio, and sized from the measured source reference.
   Place it in the viewer attention region only when that region is clear.
6. Render dark-blur and palette-frame variants from the same semantic cut. The
   variant may change background treatment and frame color; it may not change
   speech timing, caption content, arc, or overlay clearance proof.
7. Decode platform crops for 9:16, 4:5, and 1:1. Prove that the rounded frame
   and important content remain coherent after the expected left/right crop.

**Phase exit evidence:** source-bound overlay exclusion sidecar, solver report,
decoded CTA/logo edge frames, safe-region report, and platform-crop contact
sheets for each variant.

## Phase 5 — direction, graphics, and licensed assets

1. Build a direction brief from the source-truth packet and accepted arc. It
   names the purpose of each motion graphic, caption treatment, transition,
   and sound effect. No decorative diagram or unrelated Envato footage is
   allowed.
2. Use Remotion components only for source-grounded emphasis, diagrams,
   callouts, and transitions with a `MotionPurpose`. Keep animation
   deterministic from `useCurrentFrame` and the validated props.
3. Add Envato or other external editing assets only with persisted license,
   evidence URI, source hash, and campaign clearance. Footage must match the
   spoken subject; music remains prohibited by campaign policy. Sound effects
   sit below speech and are measured in the final mix.
4. Use the selected licensed local Arabic/Quran font. Record font file hashes
   and fallback coverage in render dependencies. Missing or unlicensed fonts
   fail preflight.
5. Bind style profile, direction, asset licenses, component recipes, caption
   plan, overlay proof, and audio mix policy into the render fingerprint. Any
   change must create a new artifact and stale all downstream approvals.

**Phase exit evidence:** direction document, asset/license manifest, motion
purpose list, style/font dependency hashes, and a render fingerprint preview.

## Phase 6 — run a resumable real-source pilot

1. Select the first source-bound arc that passes Phases 0–5. Use the actual
   production CLI and Remotion path; do not manually assemble an MP4 or use a
   colored fixture as proof.
2. Stage canonical batch, render input, authorization receipt, speech review,
   arc review, overlay evidence, direction, and licensed assets. Confirm every
   relative path is inside the run root and every digest matches.
3. Render the multi-segment clip in bounded units. After each completed unit,
   persist checkpoint, artifact hash, frame range, audio range, and evidence
   status. A crash must leave a resumable state that identifies the missing
   unit rather than restarting or silently stitching duplicate footage.
4. Verify an intentional interruption by stopping after a completed unit and
   resuming. Confirm the final MP4 has one continuous output clock, no repeated
   segment, and matching audio/video duration.
5. Produce both blur and palette variants only after the pilot semantic arc
   and caption/audio evidence pass. Each variant gets its own render hash,
   decoded evidence, and QA record.

**Phase exit evidence:** real Hero and Advanced artifacts, checkpoint ledger,
resume log, authorization receipt, input/output hashes, and variant manifests.

## Phase 7 — deterministic technical and viewer QA

Run QA against the encoded MP4, not only JSON or source code.

1. Use `ffprobe` to record width, height, display aspect, frame rate, duration,
   frame count, codecs, pixel format, sample rate, channels, color range, and
   encoder metadata.
2. Run `ebur128`, true-peak, per-window RMS, and silence detection. Confirm
   source audio preservation when narration is absent, ducking when it is
   present, no sharp SFX peaks, and no near-silent result.
3. Decode first, middle, last, every cut boundary, every caption edge, every
   CTA edge, every graphic interval, and the final second. Build contact sheets
   and platform-crop sheets.
4. Check full transformed bounds against safe regions. Verify no black bars
   were introduced by an accidental contain policy, no debug markers leaked,
   no caption is duplicated or split incorrectly, and no source logo/face is
   covered.
5. Compare caption frames to a valid caption-free baseline. Prove bright glyph
   pixels, correct active-word color, Arabic joining/direction, and one-line
   bounds. Record OCR as unavailable when the engine or language pack is absent.
6. Require `ViewerEvidenceBundle`, `CaptionAudioCoverageReport`, speech review,
   arc review, and overlay exclusion evidence to be current and hash-bound.
   Missing evidence is `INSUFFICIENT_EVIDENCE`; observed failure is `FAIL`.

**Phase exit evidence:** technical QA, viewer evidence bundle, caption/audio
report, contact sheets, loudness report, and a machine-readable gate result.

## Phase 8 — independent human watch and final review

1. A reviewer watches the exact MP4 once with audio and once muted. The review
   covers hook clarity, continuity, speech/caption sync, Quran text, Arabic
   shaping, CTA/logo size and placement, graphics meaning, SFX balance,
   platform crops, and ending quality.
2. Record a `HumanPlaybackReview` with exact artifact/source/plan/video hashes,
   reviewer, date, player, audio/muted observations, timestamps, and any
   rejection reason. It is stored in the existing append-only final-review
   sidecar, not by mutating the immutable viewer-evidence bundle. Never
   generate this record from automated metrics.
3. If rejected, return to the earliest relevant phase. A caption error returns
   to Phase 2; an unrelated hook returns to Phase 3; a collision returns to
   Phase 4; a sound-level failure returns to Phase 5 or the audio mix stage.
4. Only after the exact artifact is accepted may final review and local
   delivery be recorded. Human approval is append-only and bound to the final
   artifact hash.

## Phase 9 — variants and campaign handoff

1. Reuse the accepted semantic plan and TimeMap to produce dark-blur and
   palette-frame versions. Do not reselect footage while changing the style.
2. Re-run transformed overlay samples, caption edges, platform crops, audio
   metrics, and human watch for each variant. One approved variant does not
   approve another.
3. Write the caption/hashtags/rules sidecar as UTF-8 with explicit RTL
   direction and one platform-ready paragraph. Validate it in a real viewer,
   not only in a terminal. Preserve campaign rules in the sidecar.
4. Verify delivery package paths, manifest digests, rights records, stale
   approval checks, and absence of credentials, absolute private paths, or
   generated media in Git.

## Gate matrix and recovery

| Gate | Required input | Deterministic check | Human check | Failure action |
| --- | --- | --- | --- | --- |
| Source truth | hashes, rights, frame/audio packet | path confinement, probe, parent/provenance | source context reviewed | keep input; repair packet |
| Speech | ASR, transcript, alignment, inventory | coverage, intervals, TimeMap digest | listen to uncertain speech | correct/re-align; no render |
| Quran | canonical reference and display text | source/transcript/hash binding | verify pronunciation/context | mark unverified; block green styling |
| Arc | shot strip and arc review | continuity, no repeats, boundary checks | hook/body/punch review | replace arc or candidate |
| Overlay | transformed exclusion samples | collision and safe-region solver | inspect CTA/logo frames | move/resize/recompute evidence |
| Direction/assets | style, purpose, licenses | allowlist, rights, recipe hashes | relevance and restraint | remove or replace asset |
| Render | authorization and checkpoint | output facts, frame/audio continuity | watch after encode | resume missing unit or fail run |
| QA | decoded evidence bundles | hashes, loudness, glyphs, crops | visual interpretation | return to earliest failed phase |
| Final review | exact artifact | stale/effective approval checks | audio and muted watch | reject append-only; package unchanged |

When a process stops, the resume command must read the checkpoint and verify
source, input, plan, style, asset, and evidence digests before continuing. A
changed digest starts a new artifact lineage. A failed promotion leaves the
previous package intact. No sidecar is copied across candidates merely because
the filenames match.

## Execution order for the next run

The next execution proceeds in this order and stops at the first failed gate:

1. Produce the Phase 0 baseline and source-truth packet.
2. Complete speech, Arabic, Quran, reaction, and nasheed evidence for the
   selected arc.
3. Replace t33 with a reviewed coherent arc; do not repair its old unrelated
   hook in place.
4. Generate accepted arc reviews and transformed overlay exclusion sidecars.
5. Run one real Hero and Advanced pilot, intentionally resume once, and inspect
   decoded output.
6. Run technical QA, viewer evidence, and independent human watch.
7. Produce the second background variant and repeat its gates.
8. Run the full validation sequence, update the ledger, and prepare a draft PR.
9. Stop for independent code and visual review. Do not merge or publish.

## Validation commands

Run targeted checks while iterating, then the full suite after the real pilot:

```bash
uv run pytest tests/test_render_authorization.py tests/test_caption_evidence.py \
  tests/test_tarteel_overlay_direction.py tests/test_editorial_arc.py \
  tests/test_viewer_evidence.py -ra
uv run pytest -m 'not browser' -q -ra
uv run pytest -m browser -q -ra
uv run clipforge schema export
uv run clipforge schema check
uv run mypy
uv run ruff check .
uv run ruff format --check .
pnpm --dir apps/renderer lint
pnpm --dir apps/renderer typecheck
pnpm --dir apps/renderer test
./scripts/validate.sh
```

`./scripts/validate.sh` runs these two pytest partitions in separate processes;
both are mandatory. Run browser smoke twice on a clean host when practical. Record exact counts,
skips, failed tests, memory condition, artifact paths, hashes, and remaining
limitations. Leave no browser, ffmpeg, Remotion, Node, or test process behind.

## Required checkpoint files

An execution is reviewable only when the run contains, at minimum:

- `run-baseline.json` and source/rights hash inventory;
- source frame strip/contact sheet and audio review notes;
- `speech-review.json`, Arabic correction records, and Quran verification;
- `editorial-arc-review.json` and shot strip;
- `overlay-exclusion.json` and solver samples;
- direction, asset-license, font, and render dependency manifests;
- authorization receipt, render checkpoint, and renderer logs;
- `CaptionAudioCoverageReport`, `ViewerEvidenceBundle`, technical QA, and
  loudness reports;
- independent `HumanPlaybackReview` for every variant, with audio and muted
  observations bound to the exact artifact;
- final-review and delivery manifests, only when the exact artifact is
  approved.

## Current blockers this workflow must resolve

At the current audit, the code gates and focused tests exist, but the work root
does not contain current real-source authorization, caption/audio coverage,
viewer-evidence, speech-review, overlay-exclusion, or accepted arc sidecars.
Ordinary Arabic/reaction/nasheed review, a coherent t33 replacement, human
watch, and a real multi-cut service render remain open. OCR is unavailable in
the current environment. The full validator has also experienced Chrome
resource failures when host memory is exhausted. These facts keep the campaign
blocked until the corresponding phases produce current evidence.

The completion record must update the execution ledger with the actual run
hashes and distinguish implementation from technical verification and human
acceptance. Historical MP4s and prior approval labels cannot satisfy these
gates.
