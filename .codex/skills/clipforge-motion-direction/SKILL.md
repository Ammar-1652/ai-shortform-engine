---
name: clipforge-motion-direction
description: Create a source-grounded, declarative motion direction brief for Clipforge Hero and Advanced Hero drafts.
---

# Clipforge motion direction

Use this project skill when an operator asks for a stronger short-form presentation,
motion direction, typography treatment, or an improved Hero/Advanced Hero draft.
It is editorial guidance, not a renderer or an approval gate.

## Role and tool boundary

Codex is the `codex_operator`: choose the editorial direction and invoke the
typed Clipforge tools. The system is the `system_enforcer`: it performs media
work, validates rights and timing, renders Remotion compositions, and writes
evidence. A human remains the `human_reviewer` for exact audio/muted playback
and final approval. This skill must return declarative JSON; it must never
return JSX, JavaScript, shell commands, arbitrary effect code, or an approval.

Use the capability routing in the repository `SKILLS.md`. In particular,
send speech work to transcript/alignment services, cuts to an
`EditorialArcDocument`, captions to the shared caption builder, assets through
the licensed asset catalog, and graphics through allowlisted Remotion motion
graphic events. Do not make a skill a second renderer or a second cache.

Until the operator explicitly re-enables the motion-graphics pass, leave
`motion_graphics` empty in every new production brief. This is a temporary
production default: the renderer must not add graphics implicitly, and an
older artifact containing a graphic is not rewritten.

## Read before planning

Read the campaign policy and rights restrictions, source manifest, transcript,
candidate context, forced-alignment evidence, TimeMap, selected profile, current
render input, QA/final-review artifacts, and the existing draft frames. Confirm
that the source and any local assets are authorized. Outside media, music, and
unsupported language claims remain prohibited even if a visual idea would be
attractive.

## Subtitle review is a Codex gate

Before selecting a visual direction, Codex reviews the forced captions against
the source moment. The review must answer two separate questions: “does this
sentence mean something on its own?” and “does it mean the right thing in this
scene?” A low-confidence or context-breaking phrase is corrected from the
source or fails closed. Quran verses, quotations, names, numbers, and other
no-error text are checked against a reliable source when necessary, with the
verification URL or hashed local snapshot recorded. Clear source-supported
emotion can receive an allowlisted emoji annotation, but the emoji is added
beside the spoken words and never replaces them. Persist the result through
`clipforge editorial captions review --review REVIEW.json` with
`campaign=generic` and `reviewer_role=codex_operator`; the system binds its
hash to the alignment and downstream render evidence.

## Produce a constrained brief

Return a concise direction brief with:

1. the exact source-backed opening phrase (or `none` when the excerpt has no
   defensible hook);
2. body caption grouping and any source-grounded punch phrase;
3. exactly three alternatives, each with a hook/body/punch beat, source
   segment order, transcript word evidence, and a score/reason; select one
   automatically by the deterministic score/tie-break rule unless the
   operator explicitly supplies an allowlisted override;
4. one allowlisted style id from `editorial-clean-v1`, `quran-editorial-v1`,
   `quran-readable-v2`,
   `kinetic-caption-v1`, `documentary-broll-v1`, `data-explainer-v1`,
   `paper-explainer-v1`, or `premium-minimal-v1`;
   optionally pair it with one cataloged narrative preset:
   `clean_explainer`, `proof_comparison`, `story_reveal`, `transformation`,
   `quote_emotion`, or `product_cta`. A preset is a routing contract; it does
   not override source evidence, campaign policy, or the selected style;
5. one project-defined safe region: `portrait-safe-v1` for nonessential edge
   content, or `platform-resilient-portrait-v1` when reviewed logos, source
   text, or other important material is close to a horizontal edge. The latter
   keeps the foreground inside an inner band over the existing blurred source
   background so one 1080x1920 file tolerates TikTok and Instagram viewer
   chrome. Its persisted upper-context defaults are 64px, centered, `y=280`,
   and at most two lines. Neither region is a universal platform guarantee.
   Record collision notes for faces,
   source-native text, graphics, B-roll, and captions. Record either
   `source_native_text_status: reviewed_absent` or `annotated`. When a title or
   quote is already burned into the source, record a reviewed `SourceNativeText`
   annotation with its exact phrase, interval, visual scene id, and note so
   duplicate optional typography can be suppressed. `unavailable` cannot enter
   clean production;
6. one required `context_line` for every new production direction (the
   `direction-v2` contract). It is one typed, scene-specific sentence with an
   allowlisted emoji, a full-output interval, and exact transcript evidence or
   explicit human-review metadata. It must not duplicate a timed caption. The
   renderer owns the upper safe-lane geometry and keeps it below search/header
   UI; arbitrary HTML or emoji strings are rejected. Historical `direction-v1`
   artifacts remain readable but cannot be used as a new clean production
   direction without this line;
7. optional diagram facts only when both sides, units, labels, values, and source
   word/span provenance are explicit;
8. optional native `motion_graphics` only when an allowlisted illustration conveys
   a source-grounded fact more clearly than captions alone. Each record must name
   an allowlisted `template`, integer-microsecond output `interval`, exact source
   evidence ids, a `MotionPurpose`, display text copied exactly from one bound
   evidence item, and safe-region geometry above the reserved caption lane.
   Templates are `credit_card` (evidence must contain both “credit” and “card”),
   `travel_postcard` (travel, Philippines, vacation, beach, tropical, or Airbnb),
   `business_identity` (business, founder, or enterprise identity), and
   `business_spotlight` (a quantitative trend or value claim with explicit
   numeric evidence such as an amount, unit, or change). A generic mention of
   “company” is insufficient for a trend chart. Do not
   use a graphic as a generic decoration, replacement caption, or way to invent a
   hook. Graphics must not overlap each other; omission is the correct choice when
   no template fits;
9. optional `camera_motion` events when a bounded move helps orient, follow,
   reveal, emphasize, or settle a source-grounded beat. Bind each event to
   evidence, an integer-microsecond interval, a target, an intensity envelope,
   and a hold fallback. Do not add constant zooms or movement while the viewer
   must read a caption;
10. optional `transitions` only at reviewed interior TimeMap cuts. Each one
    names its narrative purpose, allowlisted style, evidence, and optional SFX
    placement. A clean cut is the default for ordinary conversation;
11. optional `asset_placements` only for locally registered, rights-cleared media
   that has a real source-grounded reason. Each placement must name `asset_id`,
   `kind` (`graphic` or `audio`), an integer-microsecond output `interval`,
   `source_in_us`, one or more evidence ids, a `purpose`, and a concise
   `relevance_note`; for clean B-roll, copy the exact reviewed `asset_tags`
   from the asset catalog and name at least one tag in the relevance note. SFX
   may also set a bounded `gain_db`; clean production defaults to a restrained
   -18 dB cap with a short deterministic envelope. Never distribute assets
   evenly or add a whoosh/impact merely to create motion;
10. a validation checklist covering alignment, rights, geometry, stale
   approvals, and complete-word TimeMap boundaries. Reject a cut that
   intersects a spoken word so the picture cannot lose its leading phoneme.

All new production styles use the shared platform-safe text policy: every
spoken caption is grouped into exactly one readable line, with a plan-time
word/character budget and no renderer wrapping fallback. The upper context
sentence and lower caption lane are kept inside the same inner portrait band;
the system checks their animated bounds against the top search/header, side
rails, and bottom description/action UI. A line that cannot fit at the pinned
local font size fails planning and must be regrouped from complete words.

When the operator requests a multi-moment recut, produce a separate typed
`EditorialArcDocument` for `--editorial-arc-file`. It must name exact forced
word ids and source ranges for ordered hook/body/punch segments. Do not reuse a
Hero caption map after changing the TimeMap; the Advanced planner remaps the
forced words and persists the new alignment. Segment output order may reorder
source moments, but every segment must carry its own forced speech interval.
Segments that begin inside an ongoing sentence must explicitly set
`continuation: true`; otherwise the validator rejects the cut so a visually
neat recut cannot start speech on a fragment by accident.

Do not write JavaScript, JSX, CSS, HTML, shell commands, or arbitrary effect
parameters into the brief. Do not fabricate a hook, comparison, chart, speaker,
CTA, or campaign claim. Restraint and omission are valid outcomes.

## Hand-off contract

The brief is declarative JSON, not executable code. Its top-level fields are
`direction_id`, `project_id`, `source_asset_id`, `candidate_id`,
`source_sha256`, `hero_plan_sha256`, `time_map_sha256`, `alignment_sha256`,
`visual_analysis_sha256`, `options` (exactly three), `selected_option_id`,
`selection_mode`, `style_id`,
`style_fingerprint`, `safe_region_id` (`portrait-safe-v1` or
`platform-resilient-portrait-v1`), and provenance.
Each option contains `style_id`, `beats`, `evidence`, `segment_order`,
`context_line`, `motion_graphics`, `asset_placements`, `motion_recipe_ids`,
`camera_motion`, `transitions`, `selection_score`, and `selection_reason`;
the persisted direction also carries the verified `motion_catalog_sha256`.
Every beat contains a `kind`
(`hook`, `body`, or `punch`), source segment ids, evidence ids, and exact
source-grounded display text. A brief that cannot populate these fields must
be rejected rather than filled with invented copy.

The operator converts the brief to the typed Clipforge plan and runs the normal
Hero/Advanced Hero workflow. The deterministic renderer consumes only validated
events and the pinned style profile. It uses `useCurrentFrame`, canonical
microseconds, and the project safe region. Unsupported diagram kinds, unsafe
geometry, debug markers, missing alignment evidence, unlicensed assets, and
stale approvals must fail closed.

Use the audited upstream references recorded in
`docs/third_party/motion-skills.lock.json` for composition vocabulary only. The
packs are not downloaded at production time and are not a pipeline dependency.

For the Tarteel campaign, read
`references/tarteel-style-library.md` after the campaign policy and before
choosing a direction. It contains a bounded style library derived from the
operator-supplied reference clips and official platform guidance. The library
is a routing aid, not evidence that any format guarantees reach or retention.

## Operator invocation

Invoke this skill before planning when presentation quality needs review. Save
the JSON brief outside Git (under the work root or another operator-controlled
input location), then validate and bind it to the current approved Hero
candidate:

The normal routing is: inspect with `source inspect` / `vision show`, extract
speech with `transcript run` and `hero align`, mine with `candidate mine`,
record Codex editorial promotion with `review decide --reviewer-role
codex_operator` and `hero review decide --reviewer-role codex_operator`, then
bind this brief with `direction plan`. Use the Advanced Hero service for the
TimeMap, crop, captions, graphics, B-roll, SFX, Remotion render, checkpoints,
decoded evidence, and QA. Do not make this skill perform those media actions
itself.

Before binding, compare the three declarative alternatives without rendering:

```text
clipforge editorial direction compare direction.json
```

This command only reports the deterministic score and layer counts. It does not
rewrite the brief or create an approval.

```text
clipforge hero advanced direction plan SOURCE_ID CANDIDATE_ID \
  --brief direction.json --style auto --db PATH --work-dir PATH
clipforge hero advanced plan SOURCE_ID CANDIDATE_ID \
  --reframing contain --db PATH --work-dir PATH
clipforge hero advanced render SOURCE_ID --db PATH --work-dir PATH
clipforge hero advanced direction verify SOURCE_ID CANDIDATE_ID \
  --db PATH --work-dir PATH
```

Use `--style PRESET_ID` only for a deliberate operator override. The direction
artifact is immutable in the candidate plan directory; changing the brief,
style, font dependency, TimeMap, source, alignment, or rights evidence changes
its hash and makes the old plan/render/QA/final-review evidence stale. Render
drafts remain unapproved until a human reviews the actual encoded MP4 and
decoded frames.
