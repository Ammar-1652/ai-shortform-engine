# Round 4 deep implementation plan

**Purpose:** implement the remaining treatment, Codex subtitle-review, audio,
visual-evidence, and render-recovery repairs as one coherent system change.

**Audit source:**
[editorial-treatment-orchestration-followup-round4-plan.md](editorial-treatment-orchestration-followup-round4-plan.md)

**Planning head:** `53c5879ef1c1c43ee8ee2e28a6dce8e7e86eaec2`  
**Branch:** `round-36-editorial-knowledge-engine`  
**PR:** [#38](https://github.com/Ammar-1652/ai-shortform-engine/pull/38)  
**Status:** `PLAN READY — IMPLEMENTATION NOT STARTED`

This plan is intentionally deeper than a one-file patch. Each change must move
through the typed contract, service, renderer adapter, QA/evidence, cache, and
documentation layers together. Existing approved artifacts remain immutable.

## Non-negotiable boundaries

- Codex is the editorial brain and subtitle reviewer. It chooses source-grounded
  wording, corrections, sensitive-text checks, emotion annotations, treatment,
  and direction through typed commands.
- ClipForge is the system enforcer. It owns TimeMap conversion, persistence,
  rights, path confinement, rendering, evidence, QA, cache identity, stale
  invalidation, and delivery gates.
- A human reviewer remains the only final playback approver.
- Raw ASR and forced alignment remain immutable evidence. Reviewed display text
  is a separate derivation.
- Source time and output time remain separate. Every source interval is mapped
  through `TimeMap`; no floating milliseconds or second timing system is added.
- Existing Tarteel Quran canonical verification is preserved and remains
  stronger than the generic speech-review path.
- Legacy artifacts remain readable. New clean production cannot silently reuse
  legacy semantics or new defaults.
- No database migration is added unless an implementation phase proves that an
  append-only sidecar cannot carry the required evidence.
- No provider, browser, model, or network call is added to normal offline
  rendering after evidence has been acquired and verified.

## System shape after implementation

```text
source + raw ASR + forced alignment + TimeMap
    → Codex speech review revision
        → corrected display-alignment derivation
            → caption / emoji / sensitive-text evidence
                → editorial direction + treatment decisions
                    → output-space geometry and audio windows
                        → Advanced render input
                            → Remotion render with resumable chunks
                                → decoded viewer/audio evidence
                                    → QA and shared policy evaluation
                                        → final review facts
                                            → human playback approval
                                                → local delivery
```

Each arrow carries a hash-bound typed artifact. A downstream stage must reject a
missing, stale, mutable, or mismatched parent rather than reconstructing it.

## Phase 0 — Establish the implementation boundary

Before code changes:

1. Read `AGENTS.md`, `ARCHITECTURE.md`, `SKILLS.md`, ADR 0101, ADR 0111,
   ADR 0112, the round-3 plan, and this plan.
2. Confirm branch, `origin/main`, PR head, and clean worktree.
3. Create a new numbered architecture ADR for the cross-cutting contract
   changes. The ADR must explain why the generic speech review is separated from
   raw alignment, why sidecars remain append-only, and how legacy documents are
   read.
4. Record the current generated-schema count and current SQLite version.
5. Do not modify production media or rewrite approved artifacts while building
   fixtures.

**Exit gate:** baseline facts are recorded and a new implementation commit can
be reviewed independently from the historical audit.

## Phase 1 — Define compatible contracts first

### 1.1 Speech review revision contract

Add a versioned generic review model without breaking stored
`TarteelSpeechReview` documents. The compatible model must express:

- review id and immutable revision id;
- source, candidate, source hash, ASR hash, transcript hash, alignment hash,
  and TimeMap hash;
- reviewer role (`codex_operator` for production Codex review);
- locale and review timestamp;
- reviewed source intervals;
- original forced-word ids and original ASR text;
- optional `SpeechCaptionCorrection` records;
- optional `SpeechEmotionAnnotation` records;
- sensitive-text classification and `SpeechVerification` records;
- provenance and parent artifact ids.

A correction must include:

- exact source word ids;
- original display text;
- corrected display text;
- source interval wholly inside one retained TimeMap segment;
- locale;
- evidence kind;
- Codex review note;
- no HTML, newline, or unsafe markup.

An emotion annotation must include:

- exact source word/span ids;
- one allowlisted emotion id and emoji;
- source interval;
- Codex rationale/evidence;
- mapped output interval derived by the system, never supplied by Codex.

A sensitive verification must include:

- subject kind;
- exact source word/span ids;
- expected verified text;
- either a valid HTTP(S) evidence URL or a confined local snapshot path;
- snapshot SHA-256 when local;
- note and verification status.

The model must reject an empty-host URL, credentials in the URL, a missing
snapshot, a changed snapshot, a verification bound to another interval, and a
sensitive span without evidence.

### 1.2 Corrected display-alignment contract

Do not mutate `ForcedAlignmentDocument`. Add a deterministic derivation that:

1. loads raw alignment;
2. validates the speech-review revision and all correction word ids;
3. applies reviewed display text while preserving word ids, source times,
   output times, segment indices, and TimeMap;
4. computes a display-alignment hash;
5. emits the exact caption words consumed by `_captions()` and Remotion.

This derivation must be used by Advanced Hero, caption evidence, QA, final
review, cache fingerprints, and delivery facts.

### 1.3 Audio window v2 contract

Keep v1 readable. Add a v2 structure that stores, per SFX/narration cue:

- all disjoint speech-overlap windows;
- all complementary silence windows;
- source/output clock for every window;
- exact aligned-word ids;
- duck amount and gain policy;
- decoded measurement rows for every expected window.

No v2 contract may store one union interval when the source contains a gap.

### 1.4 Visual observation v2 contract

Extend treatment observations with:

- asset hash and media kind;
- sampled frame paths and timestamps;
- analyzer version;
- labels and confidence;
- source-grounded relevance evidence;
- final output-space rectangles;
- protected roles: face, active subject, source text, logo, CTA, caption,
  platform rail, B-roll;
- crop/reframe/camera dependency hashes.

### 1.5 Render checkpoint contract

Add a resumable per-candidate receipt containing:

- run and candidate id;
- batch/input/renderer dependency hashes;
- completed frame/chunk ranges;
- output partial file hash and byte count;
- browser attempt count;
- last error category;
- resume eligibility;
- process cleanup status.

Partial output never becomes the final MP4 or an approval target.

**Phase 1 exit gate:** schemas are typed, generated, backwards-compatible, and
unit tests reject malformed, stale, unbound, and unsafe records.

## Phase 2 — Implement the speech-review services

Update together:

- `src/clipforge/schemas/campaign.py`
- `src/clipforge/schemas/registry.py`
- `src/clipforge/campaign/quran.py`
- `src/clipforge/campaign/speech.py`
- `src/clipforge/cli/editorial_cmd.py`
- `src/clipforge/hero/caption_evidence.py`
- `src/clipforge/hero/advanced_service.py`
- `src/clipforge/schemas/advanced.py`
- generated schemas under `schemas/generated/`

Required behavior:

1. `editorial captions review` writes a new immutable review revision. It never
   overwrites a previous review. A current-pointer sidecar may be updated only
   if it names the new immutable revision and its hash.
2. The command loads the current source, ASR, transcript, Hero plan, alignment,
   and TimeMap and rejects stale inputs before writing.
3. The command validates every correction, emotion annotation, and sensitive
   verification against source word ids and retained segments.
4. Generic clean production requires a Codex review. Exploratory drafts may
   remain `draft_only` with `insufficient_evidence` but cannot pass final review
   or delivery.
5. Tarteel Quran paths continue through the existing canonical review and Amiri
   font checks.
6. Review evidence records the original wording and the reviewed display
   wording, so a reviewer can understand what changed and why.

### Speech-service tests

Add tests for:

- English/French corrected words and punctuation;
- Arabic display corrections;
- numbers and proper names;
- correction crossing a jump cut;
- unknown word ids and stale TimeMap;
- sensitive URL and snapshot validation;
- required sensitive verification;
- immutable review revisions and current-pointer updates;
- no review blocks new clean production;
- legacy artifact remains readable;
- stale review invalidates render input and QA.

**Phase 2 exit gate:** Codex can correct a caption without changing raw ASR or
forced alignment, and the exact corrected display artifact is hash-bound.

## Phase 3 — Implement shaped multilingual caption rendering

Update together:

- `apps/renderer/src/captions/CaptionPlate.tsx`
- `apps/renderer/src/captions/layout.ts`
- `apps/renderer/src/captions/*.test.ts`
- `apps/renderer/src/hero/AdvancedHeroDraft.tsx`
- `apps/renderer/src/hero/advanced.test.ts`
- Python browser fixtures under `tests/`

Rules:

1. Arabic and uncertain RTL text render as whole shaped runs even when word
   status metadata exists.
2. Active-word emphasis uses a shaped-run/line overlay or a safe range strategy;
   it must not split joining characters.
3. Emoji is a separate inline element with explicit direction and spacing.
4. English/French may use word-level emphasis with exact cue boundaries.
5. Japanese keeps grapheme/punctuation behavior from the existing layout path.
6. Caption bounds remain inside the selected safe region after camera movement.

Proof:

- render English, French, Arabic, Japanese, and Quran-style fixtures through
  the real Remotion composition;
- decode frames before, during, and after the active word;
- inspect Arabic shaping visually;
- prove emoji does not alter the caption text or line geometry.

**Phase 3 exit gate:** multilingual caption frames are readable, correctly
shaped, word-timed, and safe-area compliant.

## Phase 4 — Implement exact audio windows

Update together:

- `src/clipforge/schemas/treatment.py`
- `src/clipforge/hero/advanced_build.py`
- `apps/renderer/src/hero/AdvancedHeroDraft.tsx`
- `src/clipforge/hero/viewer_evidence.py`
- `src/clipforge/qa/technical.py`
- `src/clipforge/qa/service.py`
- `src/clipforge/publish/preflight.py`
- `src/clipforge/review/final_gate.py`
- audio/treatment tests and generated schemas

Implementation:

1. Intersect every cue with every aligned word independently.
2. Preserve disjoint windows and reviewed silence gaps.
3. Remotion ducks only while the current frame is inside an overlap window.
4. Decode every expected overlap and silence window after encode.
5. Require v2 `intelligibility_status=pass` for new clean treatment output.
6. Keep v1 receipts readable but do not use v1 for new clean plans.
7. Include audio-window version, source gain, SFX gain, duck policy, and
   measurement hash in cache identity.

**Phase 4 exit gate:** a cue spanning two speech phrases does not duck through
the pause, and decoded evidence proves both windows separately.

## Phase 5 — Implement complete visual geometry and relevance

Update together:

- `src/clipforge/schemas/treatment.py`
- `src/clipforge/hero/treatment.py`
- `src/clipforge/hero/treatment_assets.py`
- `src/clipforge/hero/advanced_build.py`
- `src/clipforge/hero/advanced_service.py`
- `src/clipforge/hero/treatment_policy.py`
- `src/clipforge/qa/technical.py`
- `src/clipforge/publish/preflight.py`
- treatment observation, collision, and browser tests

Implementation:

1. Decode selected visual assets at bounded, source-relevant timestamps.
2. Persist labels, confidence, relevance score, frame hashes, and analyzer
   facts in immutable observations.
3. Derive output-space rectangles after crop, reframe, camera, frame layout,
   and platform safe-region transforms.
4. Include source text, logo, CTA, face, active subject, caption, platform
   rails, and B-roll regions.
5. Run collision checks against the full camera envelope, not only the first
   frame.
6. Require numeric relevance plus source evidence for `related`; tags alone
   cannot authorize B-roll.
7. Store stable omission reasons when policy or geometry removes a layer.

**Phase 5 exit gate:** every selected visual layer has measured final geometry,
rights evidence, and a source-grounded relevance decision.

## Phase 6 — Enforce the review gate and stale propagation

Update together:

- profile/policy schemas and configs;
- `src/clipforge/hero/advanced_service.py`;
- `src/clipforge/policy/engine.py`;
- `src/clipforge/qa/technical.py`;
- `src/clipforge/publish/preflight.py`;
- `src/clipforge/review/final_gate.py`;
- cache and stale-artifact tests;
- `SKILLS.md`, operator skills, architecture docs, and ADR.

Rules:

1. New clean directions require a Codex speech-review revision.
2. Legacy-v1 artifacts remain readable but cannot be silently reinterpreted.
3. Any change to source, ASR, transcript, alignment, TimeMap, correction,
   sensitive verification, emoji annotation, font, style, observation, audio
   policy, treatment, or renderer dependency creates a new identity.
4. QA, final review, and delivery load the same evidence bundle and review
   revision rather than trusting a digest alone.
5. A final review cannot approve a draft-only render or incomplete speech
   evidence.
6. The current review pointer cannot authorize an older render revision.

**Phase 6 exit gate:** stale review, stale correction, stale evidence, and stale
asset cases block every downstream gate consistently.

## Phase 7 — Make browser rendering bounded and resumable

Update together:

- `src/clipforge/hero/advanced_service.py`
- `src/clipforge/hero/advanced_backend.py`
- `src/clipforge/media/process.py` if process-group behavior needs extension;
- `apps/renderer/scripts/render-advanced-hero.mjs`
- checkpoint/manifest schemas;
- render and recovery tests.

Implementation:

1. Add a bounded total render deadline and maximum browser retries.
2. Persist frame/chunk receipts before each attempt and after each completed
   range.
3. On failure, kill the browser and process group, preserve the checkpoint,
   and mark the exact error.
4. Resume only matching source, input, renderer, style, font, and dependency
   hashes.
5. Render only missing chunks and stitch deterministically.
6. Run post-render evidence only after the complete encoded file exists and
   passes duration/hash checks.

**Phase 7 exit gate:** a deterministic crash-at-frame-N test resumes and
produces a complete MP4 with complete viewer/audio evidence; no process or
partial file is mistaken for success.

## Phase 8 — Real proof and final validation

Use an authorized campaign source from the existing Drive/work root. Do not
require a separate non-campaign video unless a specific provider-policy test
needs it; campaign-provided media is valid when its rights record and campaign
rules are persisted.

Run, in order:

1. source inspection and rights verification;
2. ASR, transcript, selected-clip alignment, and TimeMap;
3. Codex speech review with corrections, sensitive verification, and emotions;
4. direction/treatment planning and provider asset binding;
5. visual observations and geometry checks;
6. pilot render;
7. full Remotion render with checkpointing;
8. decoded frames, Arabic/RTL proof, caption edges, audio windows, loudness,
   true peak, and complete muted/audio watch packet;
9. QA verify and QA gate;
10. final review verify and human playback decision;
11. local delivery verify and package hash;
12. cache hit, stale review, stale asset, changed source, and resume checks;
13. full `./scripts/validate.sh`, schema check, Ruff, mypy, renderer checks,
   and doctor;
14. exact CI result on the final PR head.

## Conflict-prevention matrix

| change | must invalidate | must remain compatible |
|---|---|---|
| speech review/correction | caption alignment, render input, viewer evidence, QA, final review, delivery, cache | raw ASR and forced alignment |
| sensitive verification | speech review, render input, QA, final review, delivery | Quran canonical review contract |
| emoji annotation | caption/render input, viewer evidence, cache | spoken caption text and word ids |
| audio window v2 | treatment fingerprint, audio mix, render input, viewer evidence, QA, cache | v1 receipts read-only |
| visual observation/geometry | treatment evidence, direction revision, render input, QA, cache | old artifact bytes |
| browser renderer/checkpoint | renderer dependency, render input, run receipts, cache | completed immutable MP4s |
| profile/policy | direction, treatment, render input, QA, delivery | legacy artifacts with recorded recipe |

No phase may alter a downstream artifact in place. Every invalidation must be
visible as a stale error or a new immutable revision.

## Required implementation reporting

For each phase, record:

- files and schemas changed;
- exact tests and failure cases;
- generated schema count;
- cache/stale behavior;
- real decoded-frame/audio evidence;
- provider and rights facts;
- process cleanup status;
- remaining external gates.

The system may be called technically verified only after the exact implementation
head passes all automated checks. It may be called ready for human review only
when a complete real MP4, decoded evidence, QA packet, and local playback target
exist. It may not be called complete or delivery-ready before human approval and
all external CI/provider gates are green.
