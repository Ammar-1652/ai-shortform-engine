# Tarteel review-trio system repair plan

**Status:** IN EXECUTION — code gates technically verified; real-source visual
production proof remains pending

**Prepared:** 2026-10-19 (Africa/Cairo)

**Repository:** `Ammar-1652/ai-shortform-engine`

**Planning branch:** `round-35-quran-caption-verification`

**Planning HEAD:** `4ac0748`

**Scope:** repair the production pipeline that creates Tarteel Hero and
Advanced Hero drafts. The six existing `review-trio` files are diagnostic
evidence only and must not be repaired in place or treated as delivery
artifacts.

## Current execution entrypoint — 2026-10-24

Read the current execution audit first:
[tarteel-review-trio-audit-2026-10-24.md](tarteel-review-trio-audit-2026-10-24.md).
It records the verified implementation, exact current evidence inventory, and
the detailed next-round steps. The older runbook remains useful for its
work-package details but is explicitly superseded at its header.

Follow the detailed work packages in
[the remaining-work runbook](tarteel-review-trio-system-repair-next-round.md#ordered-execution-for-the-next-round).
It contains P0 setup, code locations, numbered implementation steps,
regression requirements, evidence gates, restart instructions and the
real-source acceptance sequence.

The 2026-10-24 audit supersedes the earlier intermediate validation numbers:
the split `./scripts/validate.sh` completed with **870 passed, 2 skipped** in
the non-browser process and **18 browser tests passed** in the isolated browser
process. Renderer, schema, type, lint, and doctor checks also passed. The
current audit confirms the code gates are technically verified, while R2–R8
still need current real-source evidence and human playback. Existing passing
tests and old MP4s do not establish campaign acceptance.

## Purpose

This plan addresses the repeated failures reported in the latest trio:

- `tarteel-22` dark-blur and palette captions do not stay synchronized with
  the spoken audio;
- `tarteel-12` begins with the irrelevant `زين، الحمد لله` exchange instead of
  the reviewed memorization question;
- the CTA overlaps the children in the foreground picture;
- `tarteel-33` uses a hook that does not lead into the body and omits captions
  during Yasser's nasheed;
- earlier hard rules were documented but were bypassed by a manual batch
  generation path.

The goal is a reusable system repair. A future Tarteel render must either
produce a source-grounded, synchronized, collision-safe draft or stop before
rendering. A technically encoded MP4 is not sufficient.

## Evidence and current boundary

The following evidence is the starting point for execution:

| Evidence | Finding | Consequence |
|---|---|---|
| `var/work/campaigns/Tarteel/review-trio/build_inputs.py` | Copies a previous render input, divides cue text duration equally among tokens, fabricates dependency hashes, and writes batches directly for the renderer. | This is not a valid production path. It must be quarantined and blocked from campaign delivery. |
| `review-trio/tarteel-12/*/batch.json` | The first cue is `زين، الحمد لله.`. | The opening boundary was never represented as an explicit reviewed arc decision. |
| `review-trio/tarteel-33/*/batch.json` | Captions stop for approximately 11 seconds while source speech continues. | Caption presence checks do not prove full spoken coverage. |
| `review-trio/*/batch.json` | All three ideas inherit `cta_left_permille=60`, `cta_top_permille=520`, and `cta_width_permille=243`. | CTA placement was copied across different visual scenes rather than solved after the final crop and zoom. |
| `src/clipforge/campaign/overlays.py` | Placement chooses one of four fixed regions from aggregate face boxes. | It does not prove clearance for every CTA frame against faces, children, tablet, source logo, captions, or watermark. |
| `apps/renderer/src/hero/AdvancedHeroDraft.tsx` | CTA is composited at the supplied coordinates with a high z-index. | Renderer faithfully paints an unsafe plan; it cannot compensate for missing placement evidence. |
| `src/clipforge/qa/technical.py` | Viewer QA checks that cues and words exist and match text, but not that all audible speech is covered after encoding. | A sparse or stale caption map can pass metadata checks. |
| `docs/architecture/tarteel-campaign-hard-rules.md` | Campaign rules require canonical Quran text, safe CTA, reviewed context, frame inspection, and source-grounded arcs. | The rules must become mandatory inputs and decoded-output gates in the actual production path. |

The files under `var/` remain outside Git and are retained for forensic
comparison. They are not evidence of an approved or upload-ready artifact.

## Execution log

The entries below record the earlier implementation slice and its validation
at that time. They are historical; use the current execution entrypoint and
remaining-work runbook for today's status. This slice does not make any
existing review-trio MP4 uploadable.

- `hero_caption_pieces()` is followed by a one-to-one forced-word coverage
  check. Missing, duplicate, reordered, provisional, or drifted word timing
  fails before the Advanced plan is accepted.
- Technical QA reloads the persisted Hero or editorial alignment and compares
  every rendered caption word's id, microsecond interval, and frame interval.
  A sparse caption map such as the old t33 map now fails QA.
- Tarteel CTA placement fails closed when no candidate foreground rectangle is
  clear of the measured face boxes. It no longer chooses the least-overlapping
  unsafe rectangle.
- The Advanced Remotion script requires a service-only launch marker. A direct
  production batch invocation is rejected; the renderer backend supplies the
  marker inside the Clipforge service.
- Tarteel editorial arcs must use `selection_mode=reviewed`; an
  `operator_override` arc cannot become a production story decision.
- Tarteel arcs now record an explicit `opening_word_id` and review note. The
  service rejects a reviewed-looking arc that leaves the opening implicit.
- CTA face evidence is mapped onto the plan output clock and must contain a
  sample inside the CTA interval; source-wide face boxes are not silently used
  as a substitute for interval evidence.
- Focused tests currently pass for caption coverage, QA alignment coverage,
  CTA clearance, browser launch authority, and Advanced Hero regressions.
- The full repository validation now passes with `812 passed, 2 skipped`,
  schemas matching, renderer lint/typecheck passing, renderer Vitest `59
  passed`, and doctor `10 pass, 0 warn, 0 fail`.
- The real Remotion browser smoke for caption rendering and reframing passes
  (`tests/test_round30_caption_browser.py` and
  `tests/test_round29_reframe_browser.py`: `2 passed`).
- The Tarteel arc contract now records an explicit reviewed opening word and
  note; generated schemas are exported and `clipforge schema check` passes.
- The real-source re-entry check remains blocked at the evidence boundary:
  current candidate/transcript data for the reviewed t12 source is not a
  faithful reviewed transcript, and the older tf6 Hero listing has no readable
  transcript sidecar. No old manual batch is being reused to bypass this.

The next execution slice must add time-indexed exclusion geometry for CTA
placement, complete decoded-frame viewer QA, and an end-to-end service render
from a newly reviewed candidate. No production acceptance has been claimed.

### Execution review — 2026-10-19

The first slice was reviewed against every phase and the current artifacts.
The focused tests, schema check, doctor, full validation, and renderer browser
smoke remain green, but the plan is not complete: the baseline manifest is not
machine-marked diagnostic-only, service authority is not bound to an immutable
authorization record, CTA proof is still face-only, semantic arc continuity
has no shot-strip evidence, Arabic/reaction/nasheed correction evidence is
incomplete, viewer QA has no persisted decoded-frame bundle, and no new
real-source service render has passed the chain. The current Tarteel source
candidate evidence is also not faithful enough to re-enter production.

The detailed findings, causes, tests, and ordered repair sequence are recorded
in [tarteel-review-trio-system-repair-next-round.md](tarteel-review-trio-system-repair-next-round.md).
The parent plan remains **IN EXECUTION** until that document's R1–R8 exit
evidence is produced.

## Root-cause model

### 1. Manual render-input fabrication

The direct `build_inputs.py` path took a prior template and altered fields
without creating the corresponding Hero plan, forced alignment, TimeMap,
direction, editorial arc, Quran review, asset bindings, and QA records. It
also created hashes of candidate labels rather than hashes of the files and
contracts they claimed to represent. This allowed a browser render to look
structurally valid while its evidence chain was false.

**System requirement:** production campaign commands must reject a batch that
was not emitted by the service layer and whose hashes cannot be recomputed
from persisted artifacts. The renderer script remains a local execution tool,
not a campaign planning interface.

### 2. Caption timing was treated as layout data

The manual helper implements `words()` by splitting a sentence and distributing
its duration evenly. That is not forced alignment. It ignores Arabic shaping,
short-word readability, pauses, reactions, speech onset, and the exact source
range after a cut. A later audio remux also separated the browser video pass
from the audio policy and post-encode timing proof.

**System requirement:** captions must be generated only from the alignment
bound to the exact effective TimeMap. The same staged picture and audio must
enter the Remotion render, and the encoded result must be probed before a
render receipt is eligible for QA.

### 3. Editorial arc was implied rather than reviewed

`idea_id` and a context title were treated as if they were a script. The
system had typed `EditorialArcDocument` support, but the manual trio did not
provide an arc. Therefore no contract recorded the exact hook boundary, the
body's continuation, the punch, or why one selected moment belonged with the
next.

**System requirement:** a candidate idea is a proposal. A Tarteel production
plan needs an immutable, source-bound arc whose segments contain forced word
ids, complete claim closure, output order, and a human-reviewed purpose.

### 4. CTA clearance was a declared fact, not measured proof

The overlay contract says `faces_and_captions_clear_v1`, but the current
placement helper uses four fixed coordinates and aggregate face detections.
It does not account for the actual final foreground transform or the animated
CTA bounds on every frame. The renderer then paints the CTA at those
coordinates. This explains the CTA covering children despite a clearance label.

**System requirement:** placement is calculated after final framing and
caption layout. Every sampled CTA frame must be checked against exclusion
regions. A missing safe location blocks the plan.

### 5. Caption coverage was mistaken for caption existence

The t33 batch includes a small set of captions but leaves audible material
unrepresented. The existing QA verifies cue shape and token equality; it does
not verify source speech coverage, reaction coverage, or post-render caption
coverage.

**System requirement:** a production clip must have either a forced-aligned
caption for every audible spoken/reaction interval or an explicit reviewed
decision to exclude that source range. Uncaptioned speech is a hard failure.

### 6. Review was asserted from technical metadata

The trio manifest recorded technical-looking statuses even though the three
ideas did not pass the official candidate/Hero/Advanced/QA/final-review path.
No complete watch-through was used as acceptance evidence.

**System requirement:** status names must be derived from persisted service
records. A hand-written manifest cannot create a pass, approval, or delivery
eligibility. Human visual acceptance remains separate from technical QA.

## Planned architecture

The repaired path must have one authoritative chain:

```text
authorized source
  -> candidate evidence
  -> rough preview and human candidate decision
  -> selected-clip forced alignment
  -> Hero plan and human Hero decision
  -> reviewed editorial direction
  -> reviewed hook/body/punch arc
  -> final crop and exclusion geometry
  -> caption coverage and CTA placement proof
  -> Advanced render (paired picture/audio)
  -> decoded-frame and audio QA
  -> human final review
  -> local delivery
```

The renderer may receive only the typed `AdvancedHeroRenderInput` emitted by
the service. A fixture batch may still be used by renderer unit tests, but it
must carry a test-only marker and cannot be accepted by campaign production.

## Execution phases

### Phase 0 — Quarantine and baseline

1. Record the actual branch, HEAD, `origin/main`, worktree state, open PR
   state, and the hashes of the six diagnostic MP4s.
2. Preserve all six MP4s, contact sheets, manifests, and batch inputs under
   the ignored work root. Add a machine-readable `diagnostic_only` marker if
   the existing sidecar format permits it; do not rewrite the media.
3. Add a production-path test that rejects a campaign render input with any of
   the following:
   - fabricated or missing parent artifact bindings;
   - `hero_review_status=pending` in a delivery command;
   - provisional alignment;
   - missing Editorial Arc for Tarteel;
   - missing direction or Quran review;
   - an input created outside the service's run directory.
4. Do not use the six outputs as before/after acceptance. They are the failed
   baseline.

**Exit evidence:** baseline manifest, source and output hashes, a failing
regression test for the manual-batch bypass, and a clean statement that no
delivery package points to these files.

### Phase 1 — Make the canonical production path exclusive

1. Trace the CLI commands that create Advanced plans and render runs. Ensure
   the renderer receives an input only after the service has loaded and
   revalidated:
   `source_sha256`, `visual_sha256`, `candidate_set_sha256`, `hero_plan_sha256`,
   `alignment_sha256`, `time_map_sha256`, `direction_sha256`,
   `editorial_arc_sha256`, style/font fingerprints, asset licenses, and the
   campaign policy hash.
2. Remove any production caller that writes a render batch by copying another
   candidate's JSON. Keep such helpers under tests or explicitly named local
   diagnostics and make them fail if used with a campaign profile.
3. Ensure the renderer dependency hash, recipe version, and all input-file
   hashes are written to the run checkpoint before browser work starts.
4. Ensure a failed browser run records a failed unit and can resume only when
   all bindings match. No partial output may be promoted.

**Exit evidence:** a fresh service-created draft input for a test candidate;
the same input verifies; a manually edited/copy-derived input is rejected.

### Phase 2 — Repair the time and caption contract

1. Require forced alignment for every captioned production clip. Approximate
   ASR and reviewed subtitle text remain locating evidence only.
2. Build captions from the selected alignment after applying the exact ordered
   TimeMap. Preserve source word ids, source and output microseconds, frame
   boundaries, punctuation, whitespace normalization, Arabic joining, and
   reactions such as `هههه`.
3. Do not divide cue duration evenly among tokens. For every word, preserve
   measured boundaries and use a deterministic readable minimum that never
   moves the word outside its cue or the source speech interval.
4. Add an audio-coverage validator that compares aligned speech intervals to
   caption intervals on the effective output clock. It must identify:
   - audible words outside caption coverage;
   - cues whose first/last word is outside the source speech interval;
   - a cut inside a forced word;
   - repeated or missing word ids;
   - a caption that survives the TimeMap but no longer matches its staged
     audio.
5. Render the picture and audio from the same staged TimeMap in one Advanced
   run. Remove any production reliance on video-only rendering followed by a
   manual audio remux.
6. After encoding, probe zero starts, duration, frame count, audio duration,
   sample rate, channel layout, and decoded audio. Run cue-boundary checks at
   the first, middle, last, and exact endpoint frames.

**Exit evidence:** a positive test where a jump cut remaps captions correctly;
negative tests for equal-distribution words, missing t33 coverage, a cut inside
a word, and an audio duration mismatch; a decoded production clip whose first
and last cue boundaries agree with the source.

### Phase 3 — Make the opening and story arc enforceable

1. Require a persisted Tarteel `EditorialArcDocument` for every new Advanced
   plan. It must contain ordered `hook`, `body`, and `punch` segments, exact
   forced word ids, source ranges, continuation flags, claim closure, and a
   source-grounded purpose.
2. Add an explicit opening boundary field to the arc or direction contract.
   The planner must reject a plan when the first rendered caption/audio starts
   before that boundary unless the reviewed arc explicitly includes that
   material.
3. For `tarteel-12`, the replacement plan must begin at the reviewed
   memorization question and omit `زين، الحمد لله`. The exact boundary belongs
   to this candidate's reviewed evidence; it must not become a campaign-wide
   hard-coded offset.
4. Require semantic continuity evidence:
   - the hook introduces the same subject, person, challenge, or payoff that
     the body develops;
   - the body includes the setup needed to understand the punch;
   - the punch resolves the question or reaction without an unrelated topic;
   - every cut preserves its own audio and caption map.
5. Add a review artifact containing a transcript/shot strip for each beat. The
   operator must be able to inspect the selected source moments before the
   Advanced render is planned.
6. Do not force an idea from the 60-idea library into production. Ideas are
   candidates for review, not executable scripts.

**Exit evidence:** an arc validator rejects the old t12 opener and old t33
sequence; a valid replacement arc shows contiguous, source-grounded beats;
the hook/body/punch review artifact has no unrelated segment.

### Phase 4 — Fix CTA and watermark placement after framing

1. Preserve the campaign rule that the CTA is the official animated alpha
   video. It stays in the original foreground picture and remains muted.
2. Compute the final foreground transform first: source dimensions, rounded
   frame, zoom, crop or contain strategy, platform-safe band, and per-frame
   reframe trajectory.
3. Convert exclusion regions into the same foreground coordinate space:
   - every face/child bounding box over the CTA interval;
   - Sheikh and tablet boxes when available;
   - source-native logo and branding regions;
   - caption rectangles and upper context line;
   - watermark rectangle and platform-safe margins.
4. Generate candidate CTA positions and sizes from measured native CTA geometry.
   Test every sampled frame of the CTA animation, with denser samples at
   entrance and exit. A position is valid only if intersection with all hard
   exclusions is zero and the CTA remains readable.
5. If no valid position exists, shorten or move the CTA interval only when a
   reviewed caption-free source beat remains; otherwise fail the plan. Never
   fall back to a fixed coordinate.
6. Perform the same calculation for an added official watermark when the
   source-native logo is absent after reframing. Add exactly one watermark.
7. Persist the placement candidates, winning geometry, exclusion evidence,
   sampled frame ids, analyzer version, and measurement hash in the render
   input and QA evidence.

**Exit evidence:** negative tests for a face crossing the selected CTA region,
a tablet collision, a caption collision, and an unsafe crop; a positive test
where the solver moves the CTA to a safe region; decoded-frame proof for the
CTA interval of a real Tarteel draft.

### Phase 5 — Enforce complete caption coverage and Arabic correctness

1. Split the caption validator into ordinary dialogue, Quran text, reactions,
   and source-native text. Source-native text is not a substitute for spoken
   captions.
2. Quran display text must come from the existing canonical review, with its
   evidence hash and local Quran font binding. Canonical correction may change
   display spelling, but it must retain measured word timing and must not be
   reported as pronunciation verification.
3. For ordinary Arabic dialogue, use the selected forced alignment and a
   human-reviewed transcript correction path when ASR is wrong. Raw ASR must
   remain immutable; a correction must record reviewer, evidence, source span,
   and transcript hash.
4. Require captions for all audible dialogue and intentional reactions. A
   nasheed segment is either fully aligned and captioned, or it is excluded by
   an explicit editorial decision with a source-range cut. It may not remain as
   silent captionless speech.
5. Render active coloring by forced `word_id`. Do not match repeated Arabic
   words by visible string. Render whole shaped runs/lines for Arabic when
   segmentation is uncertain.
6. Decode Arabic frames and check bright glyph pixels, line bounds, active
   color changes, and no duplicate caption layer. OCR is supplementary and is
   reported unavailable if the required engine/language pack is absent.

**Exit evidence:** t33's prior uncovered interval causes QA failure; a fully
captioned replacement passes coverage; Quran and non-Quran captions are visibly
distinct and correctly colored in decoded frames.

### Phase 6 — Repair the t33 editorial selection

1. Mark the current t33 idea as rejected in the review notes; do not patch its
   captions to make the unrelated story appear coherent.
2. Mine or review a replacement candidate from the six authorized sources.
   The replacement must have a complete, understandable story in the source
   order or a reviewed multi-segment arc. It must include all speech that the
   final cut retains.
3. Prefer a reaction or educational idea whose hook and punch are both about
   the same event. Do not use the nasheed hook unless the body continues that
   same moment and its captions are available.
4. Create a rough preview first, then record the human candidate decision,
   forced alignment, Hero review, direction, and arc. No Advanced render is
   allowed from the idea library alone.

**Exit evidence:** a replacement candidate id, shot strip, reviewed transcript,
complete alignment, and arc decision. The old t33 outputs remain diagnostic.

### Phase 7 — Strengthen viewer-quality QA

1. Keep technical QA for media facts, rights, hashes, and policy. Add a
   required viewer-quality evidence bundle for each encoded artifact.
2. The bundle must include:
   - complete MP4 ffprobe report;
   - loudness, true peak, silence, and event-window RMS/peak reports;
   - decoded frames before/during/after every cue and cut;
   - dense frames across the CTA interval;
   - contact sheet at full portrait size;
   - TikTok and Instagram crop-mask sheets;
   - caption coverage and active-word evidence;
   - CTA/watermark exclusion evidence;
   - a complete-watch record with audio and muted playback.
3. A missing evidence item is `INSUFFICIENT_EVIDENCE`, never a pass.
4. QA must bind to the exact encoded artifact hash. Changing source, arc,
   alignment, caption text, crop, CTA geometry, font, style, or audio policy
   invalidates QA, final approval, cache reuse, and delivery reuse.
5. Human final review remains append-only and must reference the exact final
   artifact, not a prior draft or a contact sheet alone.

**Exit evidence:** a test proves a technically valid MP4 with an unsafe CTA or
caption gap cannot pass viewer QA; an unchanged artifact is a cache hit; each
listed dependency change creates a miss and stale-evidence failure.

### Phase 8 — Production proof and campaign re-entry

1. Use the frozen Tarteel checkpoint for source and rights identity. Do not
   reacquire or manually transcode official sources.
2. Produce one new Hero and one new Advanced draft for the replacement idea,
   plus the corrected t12 plan only after its own reviewed candidate and arc
   exist. Generate blur and palette variants from the same semantic plan.
3. Watch each complete clip with audio and with captions muted. Inspect all
   output frames at 1080×1920 and under both platform crop masks.
4. Run the repository checks and the campaign verification commands only after
   the focused tests pass.
5. Stop at draft review. Do not manufacture a candidate, Hero, or final
   approval, and do not publish.

## Contract and cache changes to plan before coding

Any stored contract change must receive an ADR, generated schemas, migration or
explicit compatibility behavior, and stale-artifact tests. The implementation
should evaluate these fields before writing a render job:

| Contract need | Required persisted facts |
|---|---|
| Source-bound arc | arc id/hash, candidate/source ids, ordered segments, beat, purpose, claim closure, opening boundary |
| Caption evidence | alignment id/hash, transcript correction id/hash when used, word ids, source/output times, coverage report hash |
| CTA safety | final transform hash, exclusion-region hash, sampled frame ids, chosen rectangle, native-size measurement hash |
| Render provenance | service run id, source/visual/plan/style/font/recipe/audio hashes, renderer dependency hash |
| Viewer QA | artifact hash, decoded-frame bundle hash, audio report hash, crop-mask report hash, human review id |
| Replacement idea | idea id, source evidence ids, rejected/selected status, reason, reviewed script/arc binding |

The render cache key must include every output-changing item. A changed
caption correction, forced alignment, TimeMap, arc, crop trajectory, CTA
placement, font, style, frame/palette, renderer recipe, or audio policy must
produce a new artifact identity and invalidate downstream evidence.

## Test matrix

### Unit and contract tests

- manual/copy-derived production input is rejected;
- fabricated hash or missing parent artifact is rejected;
- provisional alignment is rejected;
- equal-distribution word timings are rejected;
- Arabic punctuation, joining, `هههه`, and repeated words preserve ids;
- exact TimeMap boundaries and jump cuts map captions and audio correctly;
- cut inside a forced word is rejected;
- t12's `زين، الحمد لله` opener is rejected by its reviewed opening boundary;
- hook/body/punch segments must be ordered, source-bound, complete, and
  semantically evidenced;
- no coherent relation between hook and body blocks the plan;
- caption coverage gaps block QA;
- CTA collision with face, child, tablet, watermark, caption, or source logo
  blocks the plan;
- solver chooses a valid alternative when one exists;
- no safe CTA position fails closed;
- native logo visibility controls exactly one watermark;
- blur and palette variants share semantic inputs but have distinct style/cache
  identities;
- style, font, frame, crop, arc, caption, alignment, source, renderer, or
  audio-policy changes miss cache and stale QA/final review;
- old artifacts remain readable and immutable.

### Renderer tests

- real `AdvancedHeroDraft` receives paired picture/audio staging;
- captions render once, in the lower lane, with forced-word emphasis;
- Arabic whole-line animation does not split shaped runs incorrectly;
- CTA uses the supplied solved rectangle and never silently relocates;
- no debug/fixture components can enter production inputs;
- first, last, and exact endpoint frames respect half-open intervals;
- frame geometry stays inside the platform-safe region after maximum motion;
- the encoded frame contains no large unintended bars, duplicate logo, or CTA
  over an exclusion region.

### Production smoke tests

For at least one real authorized source and one valid replacement candidate:

1. Run Hero through the CLI.
2. Record the human Hero decision only after watching the rough/hero draft.
3. Create direction and editorial arc.
4. Run Advanced Hero through the CLI with the selected blur and palette styles.
5. Decode and inspect the complete MP4s.
6. Run QA, final review verification, and delivery preflight. Delivery should
   remain blocked until a genuine final approval exists.

The smoke must explicitly include a no-caption baseline, cue-edge frames,
CTA interval frames, source-logo visibility, and muted playback. Tesseract is
optional; its absence must be stated rather than treated as OCR success.

## Validation commands for execution

Run focused tests first, then the complete suite:

```bash
uv run pytest tests/test_tarteel_overlay_direction.py tests/test_tarteel_delivery_policy.py tests/test_advanced_hero.py
pnpm --dir apps/renderer test
./scripts/validate.sh
uv run clipforge schema check
uv run clipforge doctor
pnpm --dir apps/renderer lint
pnpm --dir apps/renderer typecheck
```

For the campaign, execute the documented source verification commands from
the frozen checkpoint before planning. Then use only the CLI production path
for candidate preview, Hero, Advanced Hero, QA, final review, and delivery
verification. Capture command output, exact artifact paths, hashes, ffprobe
facts, audio reports, decoded-frame paths, and cache/stale behavior.

## Acceptance criteria

The repair is ready for independent review only when all of the following are
true:

- no campaign render can be created by the manual batch shortcut;
- t22 captions are generated from current forced alignment and remain synced
  after encoding;
- t12 begins at its reviewed memorization question and does not include the
  `زين، الحمد لله` filler;
- CTA placement is measured after final framing and is clear of faces,
  children, tablet, captions, watermark, and source branding across its full
  interval;
- the old t33 idea is rejected and a replacement has a source-grounded
  hook/body/punch arc;
- all retained speech and reactions, including any selected nasheed, are
  captioned or explicitly excluded by the arc;
- decoded frames prove caption visibility, active-word coloring, logo policy,
  frame geometry, and platform-safe placement;
- audio and video share the exact effective TimeMap, with no manual remux;
- QA and final review are bound to the exact artifact and become stale after
  any output-changing dependency changes;
- required tests pass and any skipped test is explained;
- no video is called PASS, upload-ready, or production-ready before human final
  visual acceptance.

## Execution handoff

When implementation begins, start at Phase 0 on a new dedicated round branch
from the actual current baseline. Keep this document unchanged as the plan
unless scope changes; record deviations in an execution log and add an ADR for
architecture changes. Do not delete or overwrite the six diagnostic outputs.

The first implementation commit should be the production-path rejection and
artifact-binding tests. The first human-reviewable result should be a newly
created service-run draft with a complete evidence bundle, not a regenerated
copy of the current trio.
