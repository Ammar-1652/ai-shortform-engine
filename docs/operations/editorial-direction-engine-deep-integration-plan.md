# Editorial Direction Engine: deep integration plan

**Status:** D0–D8 pre-acceptance implementation and technical gates are
implemented in this working tree. Human visual playback and approval remain
the only open acceptance step.

**Revision:** 2026-10-25

### Current implementation checkpoint

Completed in the current round:

- local knowledge sources are rehashed and fail closed on stale, missing,
  escaping, or symlinked bytes;
- `clipforge editorial direction compare` reports deterministic option scores
  and layer counts without writing or approving anything;
- direction options carry bounded `camera_motion` and narrative `transitions`;
- Advanced Hero carries those events through its plan and render input;
- Remotion applies deterministic frame-derived camera transforms with a hold
  fallback;
- twenty-one local motion recipes route to existing allowlisted Remotion components;
- generated schema registry includes the new contracts;
- ADR 0108, the architecture description, operator skills, and implementation
  report record the new boundaries;
- an earlier validation passed: 913 Python tests, 18 browser tests, 63
  renderer tests, 284 generated schemas, and 9 doctor checks with one
  CPU-only GPU warning.

Additional continuation work:

- local knowledge record and release digests are persisted and checked; unsafe
  local source components and analysis evidence symlinks fail closed;
- reference analysis verifies its captured source/evidence bytes, and proposed
  style cards bind the analysis id and digest;
- the motion catalog now has twenty allowlisted recipe routes, verifies recipe
  and renderer-reference hashes, and the renderer has a second typed registry;
- selected recipe ids and the catalog fingerprint flow through direction,
  Advanced Hero plan/render input, output metadata, viewer evidence, QA, cache,
  and stale-plan checks;
- camera trajectory envelopes are validated in both Python contracts and the
  renderer, apply to crop and contain paths, and sample frames include camera,
  transition, and SFX boundaries;
- editorial-arc remapping carries camera and transition events onto the new
  output clock instead of silently dropping them;
- transition SFX references are typed, interval-bound, and checked against the
  selected audio placement.
- knowledge proposals now have typed intake, evaluation, and release admission
  commands; admission retires the previous release and preserves its history;
- six narrative presets are cataloged, hash-bound, and checked against the
  approved motion recipes;
- clean Advanced plans create a hash-bound pilot receipt before browser
  encoding, and render/QA refuse stale or missing receipts;
- the pilot command exposes that gate to operators and the receipt is included
  in the render-input and viewer-evidence cache identity.

The remaining acceptance step is playback of the exact encoded MP4 with audio
and muted playback. Reference analysis still reports unavailable OCR, stem,
and performance evidence explicitly; those are evidence limitations, not
silent passes. The motion fixture proves every admitted route is allowlisted
and deterministic, while the production browser fixture proves a selected
graphic/camera/audio route reaches encoded output. A campaign render remains
blocked when its editorial arc review is stale; that block is intentional.

The current pre-acceptance validation recorded **923 Python tests passed, 2
skipped, 18 browser tests passed, 64 renderer tests passed, 287 generated
schemas, and 9 doctor checks passed with one CPU-only GPU warning**.

**Parent plans:**

- [Editorial Direction Engine integration plan](editorial-direction-engine-integration-plan.md)
- [Editorial knowledge and direction layer](editorial-knowledge-layer-plan.md)
- [Editorial system upgrade plan](editorial-system-upgrade-plan.md)

## What this plan is for

Clipforge already knows how to ingest media, align speech, build a TimeMap,
render Hero and Advanced Hero compositions, attach rights records, checkpoint a
render, run QA, and prepare a local package. The recurring quality failures are
upstream of encoding: the creative decision is underspecified. Codex has been
able to request a caption style, a transition, or a stock asset without first
deciding what the viewer should understand, what visual event proves it, and
why the treatment belongs at that exact moment.

This plan adds a real **directional assistant** in the AI decision plane. It
does not make the renderer autonomous and it does not turn a repository skill
into a second editor.

The operating model is:

```text
Codex reads evidence and campaign policy
  → directional assistant proposes and compares editorial directions
  → Codex selects one direction and records the reason
  → typed direction plan describes every beat and dependency
  → Clipforge validates policy, truth, timing, rights, geometry, and conflicts
  → Remotion executes the validated plan deterministically
  → QA proves mechanics and viewer-facing evidence
  → human watches the exact encoded MP4 and owns final approval
```

The directional assistant must answer, before rendering:

1. What is the one sentence the viewer should understand?
2. Which source moments form a complete hook, body, and payoff?
3. What should be visible, moving, highlighted, or silent at each beat?
4. Which camera motion, transition, graphic, B-roll, caption, and SFX serve
   that purpose?
5. What must not happen because it would obscure, distort, or distract?
6. What evidence will prove that the encoded result actually follows the plan?

No effect, asset, or style is eligible merely because it is available.

## Non-negotiable boundaries

The project rules in `AGENTS.md`, `ARCHITECTURE.md`, campaign policy, rights
records, alignment evidence, TimeMap contract, review gates, and stale-artifact
rules remain authoritative. This plan cannot relax them.

- Codex is the editorial brain and must make the narrative and visual choice.
- Clipforge is the system muscle and must reject invalid or unsafe choices.
- Remotion is the production renderer and the only production clock.
- A human is the final viewer and approval authority.
- Source footage, speech, Quran text, claims, and campaign restrictions cannot
  be changed to make a style work.
- Music, outside footage, and unverified languages remain policy-controlled.
- No network request, website, repository, MCP, browser session, or remote font
  is required during an offline production render.
- No natural-language field may contain JSX, CSS, HTML, shell commands, or
  executable JavaScript.
- A direction that has no defensible hook or complete arc is rejected or marked
  `needs_review`; the system does not manufacture one.

## Integration status by source

The following table is the required destination for every resource previously
requested. “Integrated” means the source has a local typed representation,
provenance, a decision route, tests, and a production render proof. A URL in a
skill file or a paragraph in documentation is not integration.

| Resource | Intended job | Deep integration route | Current state | Completion proof |
| --- | --- | --- | --- | --- |
| iart-ai TikTok Video Skills | short-form structure, captions, platform-aware presentation | admitted guidance cards → hook/beat/caption rules → direction lint | pinned guidance; limited cards | direction context names card ids and a rendered fixture passes caption/beat checks |
| iart-ai Motion Design Skills | art direction, composition, animation principles, Remotion vocabulary | motion grammar cards → scene-intent routing → local recipes | pinned guidance; four local recipes | ten or more recipes render twice and pass safe-area/locale tests |
| iart-ai Kinetic Typography Skills | purposeful text entrance and emphasis | caption/motion recipes with shaping and timing constraints | pinned guidance; partial local adaptation | Arabic, Japanese, English, and short-cue fixtures prove readable output |
| Concat | fonts, selected motion references, transition vocabulary | separately licensed fonts + local Remotion adaptations | fonts and two adaptations exist | font hashes, notices, deterministic browser render, no AGPL runtime copied |
| ReelForge | direction-before-copy, intensity curve, beat grid, gallery routing, pilot gate | `EditorialDirectionPlan` + `ArcSpec` + `MotionRecipeRegistry` + pilot receipt | reference only | direction lint blocks blank-canvas scenes and pilot is required before full render |
| Awesome AI Motion | motion technique catalog and intent lookup | `MotionTechnique` cards with intent, duration, risk, fallback, provenance | reference/candidate | selected recipe is allowlisted and renders through Remotion |
| Storyboard Director | physical scene facts and continuity | `SceneSpec` requires visible subject/action, continuity, and failure conditions | reference only | scene plans reject vague “cinematic” instructions |
| Vyral Content Skills | hook families, script patterns, platform variants | evidence-bound hook and script pattern cards | reference only | three source-grounded hook options and no unsupported performance claims |
| Reel Analyzer workflow | frame/audio/transcript reference analysis | authorized `ReferenceAnalysis` → evaluated `StyleCard` | partial local analyzer | deterministic metrics and human observations are separated and admitted |
| Video Editor Agent | review loops, sound-design pass, evidence packet | revision records and four-level QA packet | architecture reference | failed viewer evidence creates an append-only revision, not silent mutation |
| Short-form Editing Kit | brief, shot list, rights and mobile delivery checks | mapped into existing contracts and delivery gate | architecture reference | no parallel rights or delivery authority exists |
| Generative Media Skills | skill packaging, progressive disclosure, evaluation discipline | local skills with references, examples, failure cases, EVAL files | methodology reference | fresh-agent evaluation can follow the skill without implementation internals |
| CutAgent | Hook Lab and style harness | direction alternatives and A/B plan identity | reference only | same source/copy can render two direction variants with different plan hashes |
| Video Shotcraft | recipe cards, camera moves, transitions, sound-design cards | typed shot recipes and local Remotion components | reference only | recipe cards include input schema, intensity, collision limits, and SFX cue |
| Prompt Motion | motion references and recipe ideas | local normalized reference and recipe records | reference-only unless individually admitted | each admitted recipe has file-level license and deterministic component proof |
| Openverse | image/audio discovery | optional provider → independent rights verification → asset catalog | provider boundary; live disabled | fake image/SFX acquisition completes rights, probe, render, QA, delivery |
| Envato MCP/bridge | subscribed asset discovery and download evidence | provider request → operator download → license record → relevance-tagged asset | discovery/acquisition path exists but campaign policy still controls use | selected asset has URL, license, hash, tags, source role, and decoded proof |
| Google Drive campaign system | campaign policy, reference clips, style and identity evidence | checkpoint import → source records → reference analysis/style cards | read and used as guidance; not a runtime dependency | every campaign direction context includes checkpoint and reference-analysis ids |
| Remotion official docs | deterministic frame animation and transitions | renderer implementation rules and test recipes | production dependency | no timers/random/fetch; repeated render pixels and timing match |
| TikTok/Meta/YouTube guidance | safe zones, native vertical format, hook and caption constraints | platform profile data, conservative inner safe region, viewer QA | guidance incorporated, never treated as guarantee | safe-zone geometry is checked against known UI overlays and documented as approximate |

The sources above contribute different kinds of knowledge. Platform guidance is
not a replacement for campaign evidence; reference clips are not proof of
causal performance; and a permissive code license does not clear bundled fonts,
images, audio, or dependencies.

## What “deeply integrated” means

Every adopted source must pass five gates:

1. **Provenance gate.** Record exact URL, owner, commit or capture date, path,
   file hash, license, attribution, modifications, and asset restrictions.
2. **Knowledge gate.** Convert useful instructions into scoped guidance cards,
   patterns, style cards, or recipe metadata with applicability and
   `avoid_when` cases. Separate observation, heuristic, policy, and measured
   outcome.
3. **Decision gate.** Give Codex a tool and skill route that retrieves the
   relevant knowledge, compares alternatives, and records the selected and
   rejected choices. The source must change a typed plan, not only a prompt.
4. **Execution gate.** Map the plan to a local allowlisted component or
   provider. Validate parameters, safe areas, locale, timing, rights, and
   fallbacks before rendering.
5. **Proof gate.** Render a real or authorized fixture, decode frames and
   audio, inspect the viewer-facing result, and keep the evidence bound to the
   exact plan and dependencies.

If a source fails one gate, it remains `reference_only`, `experimental`, or
`blocked`; it is never silently treated as production knowledge.

## Directional assistant architecture

### Inputs

The assistant receives a read-only context bundle containing:

- campaign policy, prohibited content, CTA rules, and rights restrictions;
- source manifest and source hash;
- transcript, language, and forced alignment evidence;
- visual analysis: faces, active-speaker evidence, source-native text, object
  regions, shot boundaries, and crop eligibility;
- candidate scores and operator/Codex review decisions;
- TimeMap and complete-word boundary information;
- available fonts, motion recipes, assets, licenses, and provider status;
- selected platform profile and safe region;
- relevant knowledge release and conflict trace;
- prior rendered artifacts and any human feedback.

The assistant must fail closed when alignment, source evidence, campaign policy,
or knowledge context is stale or missing. It may propose `needs_review`; it may
not invent evidence to complete a plan.

### Outputs

Add or extend the typed contracts so the direction plan contains:

```text
EditorialDirectionPlan
  objective, audience, platform, locale
  selected_preset, style_card, knowledge_context
  hook_variants[3], selected_hook, rejected_hooks
  ordered scenes: hook → setup/body → escalation → payoff → CTA/hold
  intensity_curve and beat_grid
  camera_specs
  motion_specs
  transition_specs
  caption_specs
  broll_specs
  audio_plan
  collision map and safe-region proof
  source/evidence/dependency hashes
  direction decision trace and lint report
```

Each option must carry exact source span ids, visual evidence ids, a visual
event at frame zero, and a reason. A hook phrase without a corresponding
on-screen event is incomplete. A motion event without a communication purpose
is invalid. A stock asset without a relevance note is invalid.

### Decision sequence

Codex follows this sequence for every production candidate:

1. **Understand.** Read policy, source, transcript, visual analysis,
   alignment, and current artifacts.
2. **Map the story.** Identify complete source-grounded hook, body, payoff, and
   ending. Preserve participant continuity. A flash-forward hook must return to
   the same scene and finish the arc.
3. **Choose a direction family.** Select one preset and style card; record why
   alternatives were rejected.
4. **Set the energy curve.** Use a bounded curve, not constant motion. The
   curve must include a readable opening, a controlled build, a payoff peak,
   and a clean ending hold.
5. **Route every beat.** For each scene choose one visual purpose, one primary
   motion family, a camera treatment, caption behavior, and optional asset/SFX.
6. **Resolve conflicts.** Apply priority in this order: policy/rights → source
   truth/timing → narrative clarity → accessibility → continuity/pacing → brand
   style → decoration.
7. **Pilot.** Render the highest-risk beat before the full composition.
8. **Inspect.** Decode frames at every cue, cut, camera extreme, graphic state,
   and final hold; inspect audio and muted playback.
9. **Revise.** Create an append-only revision with defect, evidence, and changed
   dependency. Never mutate a previously approved artifact.

### Direction families

Start with six data-driven presets and let campaigns add scoped presets only
   through the same evidence and evaluation process:

| Preset | Arc | Camera language | Motion/asset language | Reject when |
| --- | --- | --- | --- | --- |
| `clean_explainer` | question → explanation → takeaway | slow push or subject-safe hold | underline, phrase emphasis, one relevant cutaway | no clear explanation or takeaway |
| `proof_comparison` | claim → evidence → difference → conclusion | two stable framing states | split, bars, labels, proportional reveal | no explicit comparable facts |
| `story_reveal` | curiosity → context → reveal → reaction | restrained push toward reveal | mask, reveal, reaction cut, one transition accent | hook and payoff are unrelated |
| `transformation` | problem → steps → result | progressive crop or match direction | progress, step cards, result hold | no visible change or sequence |
| `quote_emotion` | strong quote → context → reaction | face-safe, minimal drift | quote reveal, low-density emphasis | quote cannot stand without invented context |
| `product_cta` | problem → demonstration → benefit → action | product/subject tracking | app proof, callout, CTA hold | CTA would obscure people or source proof |

The preset is a routing policy, not a style prison. Codex can select a local
variant when the source supports it; the plan must state the deviation.

## Camera-motion system

Camera movement is a controlled communication layer, not a constant zoom.
Create a `CameraMotionSpec` with:

- `intent`: orient, follow, reveal, emphasize, transition, or settle;
- `target`: reviewed subject/face/object region or a fixed safe anchor;
- `path`: hold, push_in, pull_out, pan_x, pan_y, drift, parallax, or match_cut;
- `interval`: integer microseconds and frame bounds;
- `scale_start`/`scale_end`, position bounds, and maximum crop loss;
- easing and acceleration limits;
- intensity band (`quiet`, `gentle`, `active`, `peak`);
- face, source-native-text, graphic, and caption collision constraints;
- fallback (`hold` or `contain`) when tracking confidence is insufficient;
- source evidence and plan dependency hash.

The planner uses this priority:

1. Keep the active speaker and required source text visible.
2. Use a hold when the viewer must read or understand a sentence.
3. Use a gentle push or drift to maintain attention during a long shot.
4. Use a stronger move only at a source-grounded reveal, reaction, or payoff.
5. Settle before a cut or caption regroup so the viewer does not read while the
   frame is still travelling.

Initial profile limits are deliberately conservative and must be measured in
   output space: gentle push `1.00–1.06`, active push `1.00–1.10`, peak push
   `1.00–1.14`; horizontal or vertical travel is at most 6% of the safe inner
   frame per second for gentle, 12% for active, and 18% for peak. A source or
   campaign may lower those limits. No move may cross a face, logo, Quran text,
   caption, or platform-safe lane.

For each tracked shot, store a trajectory and confidence. A detected face is
not an active speaker; tracking only supplies a candidate target. The assistant
must bind the target to transcript/visual evidence or choose a fixed safe
anchor. Reframing proof must include the full motion envelope, not just start
and end frames.

The Remotion implementation uses `useCurrentFrame`, rational FPS, canonical
microsecond intervals, `interpolate`/`spring`, and clamped easing. It may use
the official transition and camera primitives only through pinned local
dependencies. Remotion documents frame-derived interpolation and deterministic
rendering, and warns that timers or stateful animation can flicker when frames
render out of order. [Remotion animation math](https://www.remotion.dev/docs/animation-math),
[Remotion flickering](https://www.remotion.dev/docs/flickering), and
[Remotion camera example](https://www.remotion.dev/docs/maps) are the reference
materials for this adapter.

## Motion-graphics teaching and execution

Codex needs more than names such as “kinetic typography” or “make it cool.”
Every motion recipe must teach a communication relationship:

```text
source evidence → viewer question → visual metaphor → motion grammar
  → timing envelope → caption/face collision rule → sound cue → fallback
```

Each recipe card contains:

- a one-sentence purpose;
- when to use and when not to use;
- required source evidence;
- frame-0 state and beat-by-beat states;
- input geometry and parameter ranges;
- intensity and attention cost;
- locale/shaping requirements;
- supported asset roles;
- audio counterpart and gain envelope;
- safe-area/collision rules;
- local Remotion component and fallback;
- at least one good and one bad render fixture;
- provenance and license obligations.

The first recipe families are:

1. phrase emphasis and active-word highlight;
2. quote reveal and source-grounded context line;
3. focus callout/underline/spotlight;
4. split comparison and proportional bar reveal;
5. checklist/progress/step build;
6. map/route or process diagram when source facts support it;
7. freeze-frame reaction label;
8. controlled crop push and match cut;
9. masked reveal and blur-to-sharp reveal;
10. CTA hold and final result seal.

The plan intentionally bans “effect soup.” One scene has one primary motion
purpose and at most one supporting accent. The system removes a recipe when
the caption, face, source proof, or speech becomes less clear.

Ready-made components may be used directly when all of the following are true:

- the exact component and dependency licenses permit the intended use;
- bundled fonts, media, sounds, and shaders have separate records;
- the component can be wrapped with typed props and no arbitrary code input;
- it uses Clipforge's output clock and deterministic frame functions;
- it passes safe-area, locale, collision, and cache tests;
- a fallback exists and the recipe remains offline-capable.

Otherwise the behavior is reimplemented locally. “Open source” is not a
single license for every file in a repository. Keep license notices, record
modifications, and include required attribution in the delivery manifest.

## Transition system

Transitions must signal a relationship between shots. Add a `TransitionSpec`:

- `purpose`: cut, time_shift, location_change, reveal, emphasis, or settle;
- `from_scene`, `to_scene`, and exact boundary;
- `style`: clean_cut, j_cut, l_cut, dissolve, wipe, push, blur_dissolve,
  match_cut, or source-native transition;
- duration and easing;
- visual intensity and maximum overlap;
- optional SFX cue and gain;
- caption/audio continuity requirements;
- evidence and fallback.

Default routing:

- `clean_cut` for continuous conversation or a word-safe jump cut;
- `j_cut`/`l_cut` when the incoming/outgoing speech provides continuity;
- `dissolve` for a time or emotional change, not to hide a bad edit;
- `wipe` or `push` only when direction/location changes or the source motion
  supports it;
- `match_cut` when shapes, gestures, or actions genuinely match;
- `blur_dissolve` for a reviewed reveal or mood shift, sparingly;
- `none` when a transition would draw attention away from the speech.

The transition catalog must cap density per preset, forbid stacking transitions,
and reject a boundary inside a spoken word. Transition overlap must be reflected
in the TimeMap and audio plan; no hidden second clock is allowed. Remotion's
official `TransitionSeries` provides typed timing/presentation primitives and
explicitly supports audio transitions; use it only through a pinned version and
the local adapter. [Remotion transitions](https://www.remotion.dev/docs/transitions)
and [transition timing](https://www.remotion.dev/docs/transitioning) are the
reference sources.

## B-roll, Envato, Openverse, and campaign assets

The directional assistant decides **whether a supporting asset is needed before
searching**. It writes an asset brief:

```text
scene_id
spoken/source claim
visual role: context | proof | reaction | process | result | atmosphere
must-show / must-not-show
search terms and rejected synonyms
required orientation/duration
rights source and campaign policy
output interval and source in-point
crop and subject-safe region
fallback: source footage, graphic, or omission
```

Asset relevance is evaluated against the claim, not the keyword alone. A desk
clip is not evidence for a finance claim merely because the search said
“office.” If no asset is semantically relevant and licensed, omit it or draw a
source-grounded Remotion illustration.

Envato MCP and the subscription bridge remain provider tools. The system must
persist the item URL, download/license evidence, file hash, dimensions,
duration, tags, and campaign permission in the existing asset record. The
bridge must never make a downloaded asset automatically eligible. The operator
still selects the item and the direction plan still names the scene purpose.

Openverse remains optional discovery. Its API documents rate limits and bounded
pagination, and its terms state that catalog license metadata is not verified;
independent landing-page evidence is required. [Openverse API](https://api.openverse.org/v1/)
and [Openverse terms](https://github.com/WordPress/openverse/blob/main/documentation/terms_of_service.md)
are the authority for provider behavior.

Campaign-provided footage and Drive references use the same provenance model.
The Google Drive campaign checkpoint provides policy, identity, references,
and source maps; it is imported into a local checkpoint and is not fetched at
render time. Reference clips can teach style only after permission, hash,
analysis, and human observation. They do not authorize copying a sequence or
claiming measured performance.

## Audio and SFX direction

Sound design is a first-class directional choice, with separate layers for
source dialogue, narration, music (only when policy permits), SFX, ambience,
and intentional silence. Each cue has:

- source event and visual purpose;
- exact interval and pre/post-roll;
- asset/license id and waveform facts;
- gain, fade, ducking, and overlap policy;
- fallback or omission rule.

Default behavior:

- dialogue remains dominant and never gets masked by a transition hit;
- SFX are short, filtered, and restrained; no “whoosh on every cut”;
- a transition SFX may bridge a scene only when the transition has a narrative
  purpose;
- leave a short quiet window before a key quote or payoff when the source
  permits it;
- source audio is not duplicated when a cut reuses a moment;
- all post-mix output is measured with integrated loudness, true peak, RMS,
  silence detection, and channel facts.

Adobe's first-party audio guidance supports classifying dialogue, music, SFX,
and ambience separately, unifying loudness, repairing dialogue, and using
compression/EQ for clarity. Clipforge will implement only the deterministic
subset available in its existing audio path, not add Premiere as a runtime
dependency. [Adobe Essential Sound](https://helpx.adobe.com/premiere/desktop/add-audio-effects/adjust-volume-and-levels/audio-editing-with-essential-sound-panel.html)
and [dialogue clarity](https://helpx.adobe.com/ca/premiere/desktop/add-audio-effects/adjust-volume-and-levels/improve-dialogue-clarity.html)
are craft references, not production dependencies.

## Knowledge and learning loop

Future repositories, websites, campaign references, and viral clips enter the
same loop:

1. **Register:** record source, permission, license, capture date, hash, and
   intended scope.
2. **Observe:** extract frame changes, shot boundaries, transcript timing,
   caption layout, camera path, transitions, SFX/voice relation, and payoff.
3. **Interpret:** write a guidance card with applicability, tradeoffs,
   `avoid_when`, and confidence. Keep performance claims separate.
4. **Propose:** Codex proposes a pattern, style card, or recipe revision with
   examples and a rejected-alternative trace.
5. **Evaluate:** run deterministic tests and render controlled comparisons with
   the same source/copy where possible.
6. **Admit:** a reviewer or explicit policy admits the revision into a versioned
   knowledge release.
7. **Use:** direction contexts pin the release and selected cards. Old plans are
   not reinterpreted when the library changes.
8. **Feedback:** human review and measured campaign analytics create an
   append-only revision proposal; they never silently rewrite a card.

The assistant should retrieve only the relevant cards, not dump the entire
library into a prompt. Retrieval is filtered by campaign, language, scene
intent, source evidence, platform, and risk. Conflict resolution preserves
system invariants over upstream advice.

## Implementation sequence

Each work package stays on a dedicated `round-XX-*` branch and ends at a draft
PR. Do not begin the next package until its gate passes.

### D0 — baseline and source audit

- verify branch, merge baseline, dirty work, current schemas, and current
  knowledge hash state;
- audit each source in the table above at exact commit/capture path;
- update the provenance lock with selected files, licenses, notices, and
  classifications;
- rehash all local knowledge sources and make `knowledge verify` detect stale
  bytes before doing anything else.

**Gate:** no stale local source, no missing provenance, no unreviewed source is
marked production-eligible, and existing validation remains green.

### D1 — directional assistant contract

- add/extend `EditorialBrief`, `DirectionOption`, `SceneSpec`, `BeatGrid`,
  `IntensityCurve`, `CameraMotionSpec`, `MotionSpec`, `TransitionSpec`,
  `BrollSpec`, `AudioCue`, `DecisionTrace`, and `DirectionLintReport`;
- add schema versions and generated schemas;
- include selected/rejected options and evidence ids;
- carry knowledge release, style card, resolver, and dependency hashes through
  render input, QA, final review, and delivery;
- preserve v1 readers and explicitly reject too-new/too-old shapes.

**Gate:** unknown keys, missing parents, stale TimeMap, stale knowledge,
unsupported locale, and unbound evidence fail before render.

### D2 — Codex directional assistant and skills

- expand `clipforge-motion-direction` with the exact read order, decision
  sequence, presets, camera/transition/audio rules, and examples;
- expand `clipforge-production-operator` with capability routing, tool calls,
  checkpoint/recovery, and stop conditions;
- add compact reference files for hook families, scene intents, camera paths,
  transition routing, sound cues, and asset briefs;
- add fresh-agent EVAL cases: choose direction, reject unrelated B-roll, reject
  decorative motion, and repair a weak hook without inventing claims;
- expose a typed `editorial direction propose/compare/plan/show` command.

**Gate:** a fresh agent can create three evidence-bound options and a decision
trace without reading implementation files or producing executable code.

### D3 — knowledge and reference analysis

- implement register/observe/propose/evaluate/admit status transitions;
- expand the local analyzer for frame-0, first-change, cut density, caption
  geometry, camera envelope, transition class, SFX timing, silence windows,
  and payoff/CTA position;
- keep automated metrics, Codex observations, human observations, and
  performance analytics in separate fields;
- create a campaign style card only after permission, hash, and evaluation.

**Gate:** changed reference bytes or analyzer version invalidate the card; no
  card can make an unsupported performance claim.

### D4 — motion and camera recipe registry

- extend the catalog to at least 20 audited recipes across typography,
  illustration, camera, transitions, and CTA;
- decide for each recipe whether to vendor, pin, adapt, or keep reference-only;
- add typed parameters, safe-area bounds, locale support, intensity, fallback,
  and good/bad fixtures;
- implement camera trajectory validation and motion-envelope proof;
- use ready-made components only after file-level license and determinism
  checks; retain notices and hashes.

**Gate:** ten recipes render twice with identical pixels, no unsafe geometry,
  and no component can receive arbitrary code or network input.

### D5 — asset and sound direction

- make the assistant emit asset briefs before search;
- connect Envato, Openverse, campaign-provided, and local assets to the same
  rights/relevance boundary;
- add semantic relevance checks and rejected-search evidence;
- add SFX role, gain, ducking, and overlap validation;
- add source/audio-only/b-roll fixtures and a no-asset fallback.

**Gate:** unrelated B-roll, missing license, missing evidence, loud SFX, speech
  masking, or an asset outside the selected interval blocks the plan/render.

### D6 — Remotion execution

- add a registry-backed `EditorialScene`, `CameraLayer`, `MotionLayer`,
  `TransitionLayer`, `CaptionLayer`, `BrollLayer`, `AudioCueLayer`, and
  `DirectionDebugOverlay`;
- route Hero and Advanced Hero through the same validated plan adapter;
- keep all animation frame-derived and deterministic;
- reserve platform-safe caption/context lanes and face/source-native-text
  regions before placing graphics;
- add resumable browser chunks and receipts to every expensive render path.

**Gate:** a selected recipe, camera path, transition, B-roll, caption, and SFX
  appear exactly in their intervals in an encoded MP4; the browser render can
  resume after a forced crash.

### D7 — direction lint, pilot, and viewer QA

- run lint after plan, before pilot, after pilot, before full render, and before
  delivery;
- render a peak/hardest scene first;
- decode first 3 seconds, every cut, every caption edge, every graphic state,
  every camera extreme, payoff, CTA, and final frame;
- produce contact sheets, waveform/loudness reports, transcript overlays, and
  a muted-playback packet;
- require human playback of the exact final MP4.

**Gate:** technical, editorial-mechanics, and semantic viewer evidence all pass;
  human approval remains separate and append-only.

### D8 — cache, release, and production proof

- include every style, recipe, component, font, asset, license, sound, camera,
  knowledge, and plan dependency in the fingerprint;
- invalidate QA, review, and delivery when any output-changing dependency changes;
- render three materially different directions from one authorized candidate,
  including one no-external-asset and one B-roll/SFX treatment;
- run Hero and Advanced Hero where eligible, inspect frames and complete audio;
- publish a draft PR with direct MP4/contact-sheet paths and limitations.

**Gate:** the result is reviewable but not marked approved or production-ready
  until an independent human reviews the exact package.

## Test and evidence matrix

### Direction and knowledge

- stale local source hash, missing source, unsafe locator, and changed release;
- three options with one deterministic selection and rejected alternatives;
- hook/body/payoff continuity and unrelated-hook rejection;
- preset incompatibility and unsupported locale;
- future reference admission, conflict resolution, and feedback revision.

### Camera and motion

- hold, gentle, active, peak, invalid amplitude, missing target, tracking
  fallback, face collision, source-text collision, and full-envelope bounds;
- deterministic repeated render and no timer/random/network lint;
- Arabic shaped runs, Japanese grapheme-safe layout, and one-line caption
  budgets;
- graphic purpose, source evidence, semantic labels, and omission when no
  template fits.

### Transitions and timing

- word-safe cut, exact frame boundary, J/L cut, dissolve, wipe, match cut,
  overlapping transition, duplicate speech, and TimeMap digest mismatch;
- SFX cue exactly aligned to transition with gain and fade checks;
- transition density limit and no transition on a plain conversational cut.

### Assets and audio

- relevant and unrelated B-roll, missing/changed license, acquisition hash,
  Openverse stale response, Envato license evidence, and campaign-provided
  rights;
- source-only audio, SFX-only, narration ducking, silence, clipping, loudness,
  true peak, and speech intelligibility;
- failed asset promotion leaves the previous verified package intact.

### Production proof

- Hero and Advanced Hero production render;
- browser crash/resume from a checkpoint;
- frame evidence before/at/after caption, camera, motion, transition, and CTA;
- contact sheet and complete playback target;
- cache hit for unchanged plan and miss for every output-changing dependency;
- stale QA/final review blocks delivery.

## Operator invocation after implementation

The exact command sequence will follow the repository's CLI names after D1, but
the workflow is fixed:

```text
clipforge operator roles/tools/extensions/verify
clipforge editorial knowledge context --campaign CAMPAIGN --release RELEASE
clipforge source inspect SOURCE
clipforge transcript run SOURCE
clipforge hero align SOURCE CANDIDATE
clipforge candidate mine SOURCE
clipforge editorial direction propose SOURCE CANDIDATE --knowledge-context CONTEXT
clipforge editorial direction compare SOURCE CANDIDATE
clipforge editorial direction plan SOURCE CANDIDATE --option OPTION_ID
clipforge editorial direction lint SOURCE CANDIDATE
clipforge hero advanced pilot SOURCE CANDIDATE
clipforge hero advanced render SOURCE --resume
clipforge qa run ARTIFACT
clipforge final review verify ARTIFACT
clipforge delivery verify ARTIFACT
```

Asset searches happen only after the direction plan emits a typed brief. The
operator may then use Envato MCP, Openverse, or an approved campaign provider;
the selected asset must return to the plan with its rights and relevance
evidence before rendering.

## Completion definition

The plan is complete only when:

1. Codex can choose and explain a direction from evidence before it chooses
   effects or assets.
2. Every scene has a purpose, source evidence, camera treatment, caption rule,
   motion choice, transition choice, and optional asset/audio treatment.
3. At least six presets and 20 audited motion/camera/transition recipes are
   available, with local fallbacks.
4. Ready-made components are used where permitted and adapted only where
   required; licenses and notices are preserved.
5. Envato/Openverse/Drive assets are searched from a typed brief and cannot
   enter a render without rights, relevance, hash, and interval evidence.
6. Camera movement is subject-aware, bounded, safe-area checked, and absent
   when it harms readability.
7. Transitions and SFX are sparse, purposeful, speech-safe, and time-bound.
8. The knowledge layer learns from authorized references without copying clips
   or inventing performance claims.
9. Hero and Advanced Hero execute the same direction contracts and remain
   resumable after browser failure.
10. QA includes technical, mechanics, semantic viewer evidence, and exact human
    playback; green CI alone is insufficient.

The final report must distinguish `IMPLEMENTED`, `TECHNICALLY_VERIFIED`, and
`AWAITING_HUMAN_VISUAL_ACCEPTANCE`. It must list every source that remains
reference-only, every recipe not yet production-eligible, and every external
limitation. “Perfect,” “viral,” or “guaranteed retention” is never an
acceptance state.

## Research basis

The plan uses first-party and repository sources inspected on 2026-10-25:

- [Remotion core idea and frame model](https://www.remotion.dev/docs/idea)
- [Remotion animation math](https://www.remotion.dev/docs/animation-math)
- [Remotion deterministic rendering/flickering guidance](https://www.remotion.dev/docs/flickering)
- [Remotion transitions](https://www.remotion.dev/docs/transitions)
- [Remotion timing](https://www.remotion.dev/docs/timing)
- [TikTok creative guide](https://ads.tiktok.com/business/en/guides/video-advertising-guide?redirected=1)
- [TikTok creative best practices](https://ads.tiktok.com/resources/help/article/creative-best-practices?lang=en&q=ACO&redirected=1-2)
- [TikTok Creative Codes](https://ads.tiktok.com/business/library/Creative_Codes_ENG.pdf)
- [TikTok safe-zone requirements](https://ads.tiktok.com/resources/help/article/tiktok-reservation-topview?lang=en)
- [Meta Reels safe-zone guidance](https://www.facebook.com/business/ads/facebook-instagram-reels-ads)
- [YouTube Shorts discovery guidance](https://support.google.com/youtube/answer/11914225?co=YOUTUBE._YTVideoType%3Dshorts&hl=en-GB)
- [Openverse API](https://api.openverse.org/v1/)
- [Openverse terms](https://github.com/WordPress/openverse/blob/main/documentation/terms_of_service.md)
- [ReelForge direction-first workflow](https://github.com/gongnyang/reelforge/blob/main/README-en.md)
- [Vyral Content Skills](https://github.com/vyralcontent/content-skills)
- [Video Shotcraft](https://github.com/Vincentwei1021/video-shotcraft)
- [Generative Media Skills methodology](https://github.com/calesthio/generative-media-skills/blob/main/METHODOLOGY.md)
- the pinned iart-ai lock at `docs/third_party/motion-skills.lock.json`;
- the operator-supplied Google Drive campaign checkpoint and its local Tarteel
  style/reference records.

Platform recommendations and repository claims are treated as heuristics or
documentation, not proof that a visual treatment will perform. Campaign
analytics and human review remain the only way to establish performance for a
specific audience and source.
