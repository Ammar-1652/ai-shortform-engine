---
name: clipforge-production-operator
description: Operate the local Clipforge short-form pipeline as Codex's editorial brain while routing every media action through typed system tools.
---

# Clipforge production operator

Use this skill when Codex must take a source from intake through a reviewable
Hero or Advanced Hero draft. Codex decides the story and direction. Clipforge
executes media work and enforces rights, timing, provenance, cache, QA, and
delivery rules. A human owns final playback approval.

## Read first

Read `AGENTS.md`, `ARCHITECTURE.md`, `SKILLS.md`, the campaign policy and
checkpoint, then the source manifest, transcript, visual analysis, candidate
context, alignment, profile, and current artifacts. Read
`clipforge-motion-direction/SKILL.md` when choosing visual treatment and its
Tarteel reference when the campaign is Tarteel.

Run the read-only capability checks before editing:

```bash
uv run clipforge operator roles
uv run clipforge operator tools
uv run clipforge operator extensions
uv run clipforge operator verify
uv run clipforge editorial doctor
uv run clipforge editorial knowledge verify
uv run clipforge editorial motion verify
uv run clipforge operator release capture --work-dir var/work
```

Reference knowledge follows the typed lifecycle: `editorial knowledge intake`
creates an unadmitted proposal, `editorial knowledge evaluate` attaches
evaluation cases, and `editorial knowledge admit` creates a new active release
while retiring the prior release. Admission never approves a video artifact.

## Route decisions to tools

- Source facts and speech go through source/media/transcript/alignment tools.
- Candidate selection and hook/body/punch cuts become typed candidate reviews
  and `EditorialArcDocument` records. Codex uses `--reviewer-role
  codex_operator` for candidate and Hero decisions.
- Captions come from forced alignment and the shared caption builder. Preserve
  observed text, Arabic shaping, Quran evidence, and the canonical TimeMap.
  New production directions also require one reviewed upper context sentence;
  spoken captions are grouped into one readable line inside the shared
  platform-resilient inner band. A cue that cannot fit is regrouped from
  complete words or fails closed.
- Crops use Advanced Hero reframing and output-space geometry.
- B-roll, images, fonts, and SFX use the registered asset catalogue, license
  records, relevance tags, and typed placements. Envato search/fetch is only
  for explicitly selected, permitted assets.
- Illustrations use allowlisted Remotion motion-graphic events with a purpose,
  source evidence, interval, and safe geometry. Do not write JSX or arbitrary
  animation into a plan.
- Current temporary production default: do not select or render motion-graphic
  events. Keep `motion_graphics` empty unless the operator explicitly requests
  a later motion-graphics pass and the campaign policy permits it.
- Camera movement uses the selected direction option's bounded `camera_motion`
  events. Bind each move to a source evidence interval, keep its scale/travel
  inside the preset envelope, and fall back to a hold when tracking or safe
  geometry is insufficient.
- Transitions use typed `transitions` selected for a narrative purpose. They
  start at interior TimeMap cuts, never split a forced word, and may carry a
  separately licensed SFX cue. A plain conversational cut uses no decorative
  transition.
- Encoding uses `hero advanced render`; an interrupted run resumes only from
  matching receipts. QA uses `qa run` and `qa gate`.
- Clean Advanced plans create a pilot receipt during planning. Verify it with
  `hero advanced pilot` before encoding; a missing or stale receipt blocks the
  render. This is a system preflight and does not replace human playback.

Editorial guidance comes from the versioned local knowledge release. Build a
hash-bound context with the editorial knowledge context command, inspect its
selected and excluded cards, and pass it to the direction plan command with
the knowledge-context option. A skill or external repository may guide the
choice but cannot inject code or write approval.

Ready-made motion recipes are usable only when the motion catalog verifier
marks their local Remotion component, provenance, license, safe-area behavior,
and fallback valid. Select a recipe for a communication purpose; never add
every approved recipe to a clip.

Campaign runs write a durable checkpoint and stage journal. Verify the current
release and checkpoint before resuming. A force run creates a new checkpoint
identity and keeps the previous history. Openverse acquisition remains a
separate rights-bound asset step; discovery or acquisition alone does not make
an asset eligible for a render.

## Editorial choice

Choose one source-supported direction: editorial-clean, Quran-readable,
kinetic-caption, documentary-B-roll, data-explainer, paper-explainer, or
premium-minimal. Tarteel may also use challenge/question reveal,
mistake-to-correction, reaction-first, app-proof, interview volley, montage,
or flash-forward payoff when the source actually contains the complete arc.
Omit a style when its evidence is absent. Never force a chart, transition,
headline, B-roll, SFX, or hook that changes the source meaning.

## Handoff

Inspect decoded frames, cue edges, cuts, crop previews, audio loudness, and the
complete muted and audio story. Generate the exact human playback target, then
stop for the human to watch and decide. Do not create a `HumanPlaybackReview`,
final approval, or delivery record on a person's behalf.
