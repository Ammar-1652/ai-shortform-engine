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
3. one allowlisted style id (`editorial-clean-v1` or `legacy-v1`);
4. safe-region and collision notes for faces, source-native text, and captions;
5. optional diagram facts only when both sides, units, labels, values, and source
   word/span provenance are explicit;
6. a validation checklist covering alignment, rights, geometry, and stale
   approvals.

Do not write JavaScript, JSX, CSS, HTML, shell commands, or arbitrary effect
parameters into the brief. Do not fabricate a hook, comparison, chart, speaker,
CTA, or campaign claim. Restraint and omission are valid outcomes.

## Hand-off contract

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

Invoke this skill before `clipforge hero advanced plan` when presentation quality
needs review. After the typed plan is written, run the documented render, QA,
final-review, and local-delivery verification commands. Render drafts remain
unapproved until a human reviews the actual MP4.
