---
name: clipforge-motion-direction
description: Create a source-grounded, declarative motion direction brief for Clipforge Hero and Advanced Hero drafts.
---

# Clipforge motion direction

Use this project skill when an operator asks for a stronger short-form presentation,
motion direction, typography treatment, or an improved Hero/Advanced Hero draft.
It is editorial guidance, not a renderer or an approval gate.

## Read before planning

Read the campaign policy and rights restrictions, source manifest, transcript,
candidate context, forced-alignment evidence, TimeMap, selected profile, current
render input, QA/final-review artifacts, and the existing draft frames. Confirm
that the source and any local assets are authorized. Outside media, music, and
unsupported language claims remain prohibited even if a visual idea would be
attractive.

## Produce a constrained brief

Return a concise direction brief with:

1. the exact source-backed opening phrase (or `none` when the excerpt has no
   defensible hook);
2. body caption grouping and any source-grounded punch phrase;
3. exactly three alternatives, each with a hook/body/punch beat, source
   segment order, transcript word evidence, and a score/reason; select one
   automatically by the deterministic score/tie-break rule unless the
   operator explicitly supplies an allowlisted override;
4. one allowlisted style id from `editorial-clean-v1`,
   `kinetic-caption-v1`, `documentary-broll-v1`, `data-explainer-v1`,
   `paper-explainer-v1`, or `premium-minimal-v1`;
5. the project-defined `portrait-safe-v1` region (not a universal platform
   guarantee) and collision notes for faces,
   source-native text, graphics, B-roll, and captions. Record either
   `source_native_text_status: reviewed_absent` or `annotated`. When a title or
   quote is already burned into the source, record a reviewed `SourceNativeText`
   annotation with its exact phrase, interval, visual scene id, and note so
   duplicate optional typography can be suppressed. `unavailable` cannot enter
   clean production;
6. optional diagram facts only when both sides, units, labels, values, and source
   word/span provenance are explicit;
7. optional native `motion_graphics` only when an allowlisted illustration conveys
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
8. optional `asset_placements` only for locally registered, rights-cleared media
   that has a real source-grounded reason. Each placement must name `asset_id`,
   `kind` (`graphic` or `audio`), an integer-microsecond output `interval`,
   `source_in_us`, one or more evidence ids, a `purpose`, and a concise
   `relevance_note`; for clean B-roll, copy the exact reviewed `asset_tags`
   from the asset catalog and name at least one tag in the relevance note. SFX
   may also set a bounded `gain_db`; clean production defaults to a restrained
   -18 dB cap with a short deterministic envelope. Never distribute assets
   evenly or add a whoosh/impact merely to create motion;
9. a validation checklist covering alignment, rights, geometry, stale
   approvals, and complete-word TimeMap boundaries. Reject a cut that
   intersects a spoken word so the picture cannot lose its leading phoneme.

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
`style_fingerprint`, `safe_region_id` (`portrait-safe-v1`), and provenance.
Each option contains `style_id`, `beats`, `evidence`, `segment_order`,
`motion_graphics`, `asset_placements`, `selection_score`, and `selection_reason`; every beat contains a `kind`
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

## Operator invocation

Invoke this skill before planning when presentation quality needs review. Save
the JSON brief outside Git (under the work root or another operator-controlled
input location), then validate and bind it to the current approved Hero
candidate:

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
