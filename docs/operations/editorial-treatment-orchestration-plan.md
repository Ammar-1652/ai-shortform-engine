# Editorial treatment orchestration plan

**Status:** T0–T8 technical implementation complete on the current branch;
exact encoded generic-campaign playback and human visual acceptance remain
separate review gates.

**Prepared:** 2026-10-25
**Parent plans:**

- [Editorial Direction Engine deep integration plan](editorial-direction-engine-deep-integration-plan.md)
- [Editorial Direction Engine integration plan](editorial-direction-engine-integration-plan.md)
- [Editorial knowledge layer plan](editorial-knowledge-layer-plan.md)

### Implementation checkpoint

The current implementation provides:

- `direction-v3` treatment-aware directions with generated JSON Schema;
- typed use/omission/policy-block/review decisions for every selected beat;
- typed preset policies for B-roll, camera, transitions, SFX, and graphics;
- deterministic hook/payoff camera planning and sparse discontinuity transition
  planning on the canonical TimeMap;
- bounded Envato/Openverse/local provider requests persisted in the direction
  document for Codex selection;
- existing rights-bound acquisition boundaries reused for selected assets;
- treatment fingerprints carried through Advanced Hero plans, render inputs,
  outputs, stale checks, and cache identity;
- `editorial treatment doctor`, `plan`, `show`, and `lint` commands;
- jump-cut interval remapping for treatment decisions and provider requests;
- operator capability and skill routing for the treatment stage;
- deterministic tests for generic treatment, restricted policy blocks, stale
  fingerprints, camera bounds, and Advanced Hero browser integration.

Motion graphics remain disabled by the current production policy. A generic
campaign with preferred B-roll/SFX receives bounded requests and remains in
`needs_review` until Codex selects rights-cleared assets; a compatibility or
restricted direction records a clean omission or policy block. This is an
intentional gate in the current asset workflow, not a renderer fallback.

## Purpose

Clipforge already has typed support for B-roll, SFX, camera motion, zooms, and
transitions. The current weakness is the decision layer above those contracts:
the directional brief treats most of them as optional, presets describe them in
prose, and no deterministic stage turns a beat into a relevant asset request,
camera treatment, transition, or sound cue. As a result, Codex can produce a
valid clean render without making a deliberate treatment decision, and a
renderer cannot safely invent the missing decisions.

This plan adds a **treatment-orchestration stage** between editorial direction
and render-plan construction. It makes the creative choice explicit for every
meaningful beat while keeping campaign policy and source truth in control.

The intended generic workflow becomes:

```text
source, transcript, alignment, visual facts, campaign policy
  -> Codex selects narrative direction and preset
  -> treatment orchestrator classifies every beat
  -> each layer is use / omit-with-reason / blocked-by-policy
  -> approved asset requests are searched and rights-checked
  -> typed camera, cut, transition, B-roll, SFX, caption events are planned
  -> direction lint and pilot render
  -> Remotion executes the exact plan
  -> viewer-quality QA checks relevance, rhythm, clarity, and audio balance
  -> exact artifact goes through existing human review and delivery gates
```

The Tarteel campaign remains a deliberate exception: its campaign rules can
return `blocked_by_policy` for outside footage, added SFX, music, or any other
prohibited layer. That is a successful policy decision, not a missing feature.
For a generic campaign that permits outside editing assets, the same stage
should normally produce at least one relevant visual treatment and one
restrained audio or camera treatment when the source supports them.

## Current verified gap

The following facts are established from the current checkout and must be
addressed by implementation rather than hidden in a fixture:

1. `DirectionDocument` and the motion-direction skill allow `asset_placements`,
   camera events, and transitions, but do not derive them from beat intent.
2. `configs/editorial/presets.json` contains prose such as camera language and
   audio rules. It has no typed per-beat requirements, B-roll role policy, SFX
   cue policy, or omission rules.
3. `direction_service.py` selects a direction option and scores evidence, but
   does not plan or validate treatment coverage.
4. `advanced_build.py` consumes already selected B-roll and SFX placements. It
   cannot determine whether a stock shot is relevant, choose a provider query,
   or decide where an SFX belongs.
5. Envato and Openverse are provider/acquisition boundaries. Discovery and
   license records exist, but neither provider should be called blindly from a
   renderer or treated as an editorial decision.
6. Camera motion and transitions are typed and bounded, but are supplied by
   the direction rather than planned from shot purpose, speaker visibility,
   safe regions, and complete-word boundaries.
7. QA proves that selected events are valid. It does not yet prove that a
   generic edit made a relevant treatment choice, avoided unrelated B-roll, or
   balanced SFX against speech.
8. The temporary production rule keeps new motion graphics disabled unless an
   operator explicitly requests them. This plan does not change that rule.

## Non-negotiable boundaries

The project rules in `AGENTS.md`, `ARCHITECTURE.md`, campaign policy, rights
records, TimeMap contract, and existing review/delivery gates remain
authoritative.

- Codex is the editorial brain. It chooses the story, preset, treatment
  intent, and trade-offs from the evidence bundle.
- Clipforge is the system muscle. It turns only validated declarative choices
  into events, searches through typed providers, checks rights, and rejects
  unsafe or unsupported plans.
- Remotion executes the output clock. It does not choose assets, invent SFX,
  or infer a story from a prompt.
- Every asset used in an edit has an `AssetLicenseRecord` and evidence URI.
- Campaign policy can prohibit a layer. A prohibited layer cannot be enabled by
  a preset, Codex, an upstream skill, or a provider result.
- A missing asset never becomes a random substitute. The plan records a
  compatible fallback or an explicit omission/needs-review outcome.
- No music is introduced where policy prohibits it.
- No outside footage is introduced into a campaign that prohibits it.
- Motion graphics remain disabled by the current temporary production rule
  unless a future explicit operator request and policy review enable them.
- Timing remains integer microseconds and all output events use the existing
  `TimeMap`; no second clock or floating millisecond schedule is introduced.
- Existing approved artifacts remain immutable. A new treatment plan creates a
  new fingerprint and cannot reuse an old approval.

## Responsibility model

### Codex / directional assistant

Codex must:

1. Read the campaign policy, source facts, transcript, alignment, candidate
   context, platform profile, available catalog, and relevant knowledge cards.
2. Select a narrative preset and explain the hook, body, payoff, and CTA.
3. Mark the intended purpose of each beat: orient, explain, prove, react,
   contrast, reveal, resolve, or settle.
4. Request a treatment decision for each meaningful beat. It may choose a
   treatment family and bounded intensity, but it must not supply arbitrary
   JSX, CSS, shell commands, URLs, or executable code.
5. Choose among provider candidates using source relevance, rights, campaign
   policy, and visual continuity evidence.
6. Record why a layer is used or intentionally omitted. “Make it engaging” is
   not an omission reason.
7. Review the pilot and decoded evidence, then revise the declarative plan if
   the result is unclear, cluttered, unrelated, too loud, or unsafe.

### System enforcer

Clipforge must:

1. Validate the plan against campaign policy, source evidence, TimeMap, locale,
   safe regions, provider status, rights, and component capabilities.
2. Convert treatment intents into allowlisted asset queries and typed events.
3. Reject unrelated or unlicensed assets before render input creation.
4. Bound camera paths, transitions, SFX gain, overlap, effect density, and
   simultaneous layers.
5. Persist every decision, provider response, license, hash, fallback, and
   omission reason.
6. Invalidate render, QA, review, and delivery reuse when any treatment
   dependency changes.
7. Produce evidence that the encoded output follows the plan.

### Human reviewer

The human reviewer continues to watch the exact encoded MP4 with audio and
muted playback. Human feedback is append-only and cannot be replaced by a
numeric score or a Codex statement that the edit is good.

## Treatment decision contract

Add a versioned `BeatTreatmentDecision` child to the existing direction plan.
Do not create a parallel review or delivery authority. The decision should
contain:

```text
BeatTreatmentDecision
  schema_version
  beat_id
  output_interval_us
  narrative_purpose
  source_evidence_ids
  visual_subject_ids
  policy_decision
  broll_decision
  camera_decision
  transition_decision
  sfx_decision
  motion_graphics_decision
  caption_decision
  omission_reason
  fallback_decision
  rationale
  selected_asset_request_ids
  selected_asset_ids
  dependency_fingerprint
```

Each layer decision has exactly one state:

- `use`: a typed event or asset request is required and must be fulfilled;
- `omit_with_reason`: the beat is intentionally clean, with a structured
  reason such as `dialogue_clarity`, `no_relevant_asset`, `face_collision`,
  `quiet_payoff`, `short_interval`, or `policy_preference`;
- `blocked_by_policy`: campaign or platform rules prohibit the layer;
- `needs_review`: the evidence is insufficient and the plan cannot proceed to
  a final render.

`blocked_by_policy` and `omit_with_reason` are not interchangeable. The first
  proves that a rule prevented use; the second records a creative choice. A
  generic campaign should fail direction lint if a meaningful beat has no
  decision. Tarteel should pass with explicit blocked decisions for prohibited
  outside media/SFX, provided its approved campaign-specific treatment is
  otherwise complete.

### Layer-specific decision payloads

`BrollDecision`:

- role: `context`, `proof`, `process`, `reaction`, `result`, `contrast`,
  `atmosphere`, or `product_detail`;
- relevance statement tied to a source phrase or visual fact;
- permitted provider classes;
- query concepts and negative concepts;
- crop/reframe requirements;
- output interval and source in-point;
- rights and fallback requirements.

`CameraDecision`:

- mode: `static`, `push_in`, `pull_out`, `follow_subject`, `reframe`, or
  `settle`;
- subject/region evidence;
- start/end scale and position bounds;
- easing and hold interval;
- collision constraints for faces, source text, captions, logos, and CTA;
- reason it improves attention or comprehension.

`TransitionDecision`:

- cut boundary and complete-word proof;
- transition class: clean cut, dissolve, wipe, match cut, or source-native
  transition;
- duration in microseconds;
- visual continuity requirement;
- optional transition SFX link;
- fallback to clean cut.

`SfxDecision`:

- role: accent, reveal, transition, reaction, or settle;
- source event and purpose;
- asset request/asset id and license evidence;
- gain, fade, ducking, and maximum overlap with speech;
- silence-before/after requirements;
- fallback to silence.

`MotionGraphicsDecision` is present for completeness but must be rejected when
the current production flag is disabled. This avoids silently losing the
decision if the feature is enabled in a later round.

## Preset expansion

Extend `configs/editorial/presets.json` with typed treatment policy, while
preserving existing preset compatibility. Prose remains explanatory only; the
enforcer reads the typed fields.

Each preset gains:

```json
{
  "treatment_policy": {
    "beat_coverage": "required_decision",
    "broll": {
      "mode": "eligible|preferred|blocked",
      "roles": ["context", "proof"],
      "min_meaningful_beats": 1,
      "max_consecutive_beats": 2,
      "relevance_threshold": 0.85
    },
    "camera": {
      "mode": "preferred|allowed|blocked",
      "min_events": 1,
      "max_events": 4,
      "max_scale_delta": 0.08,
      "max_subject_drift_px": 80
    },
    "transitions": {
      "mode": "sparse|allowed|blocked",
      "max_per_30s": 3,
      "forbid_on_word_boundary": true,
      "fallback": "clean_cut"
    },
    "sfx": {
      "mode": "accent_only|allowed|blocked",
      "max_cues_per_30s": 3,
      "max_gain_db": -10,
      "speech_duck_db": -6,
      "forbid_on_continuous_dialogue": true
    }
  }
}
```

Initial generic defaults:

- `clean_explainer`: one relevant context/proof opportunity when evidence
  exists, restrained push-in on the hook or takeaway, clean cuts by default,
  one or two speech-safe accents.
- `proof_comparison`: proof B-roll or a valid source-grounded diagram, camera
  movement toward the comparison, transition only at the reveal, one impact
  accent at the evidence reveal.
- `story_reveal`: relevant reaction/context B-roll, gradual push or reframe,
  one reveal transition, sparse riser or impact only if speech remains clear.
- `transformation`: process/result B-roll where available, directional camera
  movement between stages, match cuts or clean cuts, per-stage accents capped
  by the audio policy.
- `quote_emotion`: source footage remains dominant; camera movement is subtle,
  B-roll is optional and must not displace the speaker, SFX usually omitted.
- `product_cta`: product/detail B-roll is preferred when cleared, camera
  settles on the benefit and CTA, one confirmation accent at most.

These are routing defaults, not promises that every clip needs decoration. The
planner must downgrade to a clean treatment when source evidence, timing, or
policy makes an asset harmful.

## Treatment-orchestration stages

### T0 — Baseline and policy matrix

Before implementation:

- confirm the current branch, origin/main, open PR, and exact parent plan
  revisions;
- inventory direction schemas, preset loader, asset provider boundary,
  `advanced_build.py`, `advanced_service.py`, renderer event types, QA, cache,
  final review, and delivery bindings;
- create a campaign-policy matrix for at least one generic campaign and
  Tarteel;
- identify all current omission reasons and add stable enum values instead of
  free-form strings;
- preserve the temporary motion-graphics-off flag.

**Gate:** no implementation starts until each current field has a producer,
transform, consumer, and verifier recorded in the plan audit.

### T1 — Typed treatment contracts and fingerprints

- add `BeatTreatmentDecision` and layer-specific payloads with generated JSON
  Schema;
- add policy capability fields for outside footage, B-roll, SFX, music,
  camera, transitions, and graphics;
- add decision fingerprints to direction, render input, artifact provenance,
  QA, final review, and delivery manifests;
- add migration/compatibility readers for older direction documents;
- reject unknown keys and missing decision states.

**Gate:** old plans remain readable and immutable; new plans cannot reach
render input without a treatment decision for every meaningful beat.

### T2 — Beat classification and treatment planner

Implement a deterministic planner above `advanced_build.py`:

1. Split the selected arc into semantic beats from source spans and existing
   shot boundaries.
2. Classify each beat using source transcript, visual subject facts, speaker
   evidence, energy, phrase boundaries, and campaign purpose.
3. Select candidate treatment families from the selected preset.
4. Generate bounded provider search requests for relevant B-roll/SFX only.
5. Generate camera events and transition candidates using the output TimeMap.
6. Run collision checks before proposing a treatment.
7. Emit `use`, `omit_with_reason`, `blocked_by_policy`, or `needs_review` for
   each layer.
8. Record rejected alternatives and why they lost.

The planner must not choose media by filename, popularity, or visual beauty
alone. Relevance requires a source phrase/visual fact and a role that helps
the viewer understand the beat.

**Gate:** a fixture with no external assets produces explicit omissions; a
fixture with approved relevant assets produces typed placements; an unrelated
asset is rejected before render input creation.

### T3 — Asset discovery and acquisition orchestration

Add a resumable, checkpointed asset stage for campaigns that allow external
editing assets:

```text
beat treatment decision
  -> provider request
  -> bounded Envato/Openverse/local catalog search
  -> Codex relevance selection
  -> license and campaign policy check
  -> acquire/download with provenance
  -> probe/decode/hash/register
  -> asset placement candidate
```

Requirements:

- network calls happen only in provider tools, never during Remotion render;
- Envato discovery and MyToolsPlan download remain separate and auditable;
- Openverse metadata is not a license guarantee;
- every result carries provider id, landing URL, license, evidence URI, hash,
  tags, and source role;
- interrupted acquisition resumes from a checkpoint without promoting partial
  files;
- no-result and provider-unavailable states produce explicit fallback or
  `needs_review`;
- a campaign with outside media prohibited never calls acquisition for that
  layer.

**Gate:** fake provider fixtures complete image/B-roll and SFX acquisition;
missing, changed, or conflicting rights block the plan; cache hits revalidate
the evidence.

### T4 — Camera, zoom, and transition planning

Implement a camera/transition planner that uses the same output clock:

- derive candidate moments from hook, reveal, reaction, proof, and payoff
  beats;
- use face/subject/source-text regions and safe areas to calculate bounds;
- choose slow bounded motion for sustained speech and stronger movement only
  at a semantic change;
- never move a face, Quran text, logo, CTA, or caption outside its protected
  region;
- place transitions only at complete-word boundaries and interior cuts;
- prefer clean cuts when a transition has no narrative purpose;
- smooth audio across cuts and preserve source speech continuity;
- use `clean_cut` as the deterministic fallback.

Camera movement must be represented as explicit start/end values and validated
at maximum envelope, not as a vague “make it dynamic” instruction. Transition
events must carry duration, fallback, and any linked SFX cue.

**Gate:** frame sampling proves subject/safe-region bounds, no word is split,
no transition overlaps a prohibited interval, and output/source mapping stays
correct across jump cuts.

### T5 — Sound-design pass

Implement a separate pass after visual treatment planning:

- keep source dialogue/narration as the dominant layer;
- select SFX only for a declared event purpose;
- calculate gain, fade, ducking, and maximum overlap from the preset policy;
- reject loud or sharp assets before rendering;
- insert intentional silence around a reveal or payoff when direction calls for
  it;
- do not use a whoosh on every cut;
- do not add music unless the campaign permits it;
- preserve source audio when no added sound is selected.

The pass should output an `AudioPlan` with per-cue waveform/probe evidence and
an audio-window report. It must be possible to omit SFX cleanly without
changing dialogue timing.

**Gate:** ebur128, true peak, RMS windows, clipping, silence, ducking, and
speech/SFX overlap checks pass. A generic edit with selected SFX must prove
that speech remains intelligible; Tarteel must prove the policy block.

### T6 — Renderer integration

Connect the completed treatment decisions to the existing production paths:

- direction service emits decisions and fingerprints;
- advanced plan builder consumes only validated decisions;
- Hero and Advanced Hero use shared typed event adapters;
- Remotion receives local staged assets and explicit event timing;
- no provider request or network fetch occurs in React/Remotion;
- absent assets use the declared fallback, never a silent random substitute;
- temporary graphics-off policy remains enforced.

**Gate:** the same plan rendered twice produces matching event metadata and
deterministic pixels/audio within the existing encoder tolerance.

### T7 — Viewer-quality QA and review evidence

Extend QA beyond “the event exists”:

**Narrative relevance**

- B-roll supports the spoken phrase and is not merely topical decoration;
- camera motion points attention at the intended subject;
- the transition expresses a change or stays a clean cut;
- SFX reinforces a visible/audible event.

**Rhythm and continuity**

- cut density is appropriate for the preset;
- no repeated transition pattern becomes distracting;
- no duplicated syllables, silence gaps, or sharp audio edits;
- movement settles before important captions or payoff text.

**Viewer readability**

- captions remain inside platform safe areas;
- faces, source text, logos, and CTA are not covered;
- B-roll has enough hold time to understand its purpose;
- SFX is below the speech dominance threshold.

The review packet must include contact sheets at beat/cut/camera/SFX bounds,
waveform and loudness reports, plan decisions, selected/rejected assets,
omission reasons, and exact artifact hashes.

**Gate:** a human can determine from the packet why each treatment exists and
can open the exact MP4 for final review.

### T8 — Cache, stale evidence, and delivery

Bind the following to the treatment fingerprint:

- source/transcript/alignment/TimeMap hashes;
- preset and knowledge release;
- treatment decisions and omission reasons;
- provider request/response hashes;
- asset/license/font/SFX hashes;
- camera and transition recipe versions;
- audio policy and mix plan;
- renderer/component versions.

Any change to these inputs must miss the render cache and invalidate affected
QA, final approval, and delivery reuse. Old approved packages remain valid only
for their exact old plan and artifact.

**Gate:** unchanged treatment is a cache hit; changed B-roll, SFX, camera,
transition, policy, asset bytes, or preset is a miss and stale approvals block
delivery.

## CLI and operator workflow

Follow existing CLI conventions and keep read-only commands side-effect free:

```text
clipforge editorial treatment doctor
clipforge editorial treatment plan --candidate CANDIDATE --preset PRESET
clipforge editorial treatment show PLAN_ID
clipforge editorial treatment lint PLAN_ID
clipforge editorial assets shortlist PLAN_ID
clipforge editorial assets acquire PLAN_ID
clipforge editorial treatment pilot PLAN_ID
clipforge editorial treatment render PLAN_ID
clipforge editorial treatment verify PLAN_ID
```

The operator sequence is:

1. Codex loads campaign policy and source/evidence context.
2. Codex selects a preset and writes the narrative direction.
3. The planner emits beat treatment decisions and bounded provider requests.
4. Codex reviews relevance candidates; system acquires only selected cleared
   assets.
5. System runs direction lint and the pilot gate.
6. Codex inspects pilot frames/audio and revises the declarative plan if needed.
7. System renders the full Hero/Advanced Hero artifact with checkpoints.
8. QA verifies technical, timing, relevance, geometry, and audio evidence.
9. Final review and delivery use the exact artifact and fingerprints.

No command should imply that a provider search, pilot render, or technical QA
is human approval.

## Test and proof matrix

### Contracts and policy

- every meaningful beat requires a decision;
- `use`, `omit_with_reason`, `blocked_by_policy`, and `needs_review` are
  distinct and serialized;
- Tarteel blocks outside B-roll/SFX while a generic campaign permits them;
- unsupported provider, locale, style, or policy combinations fail closed;
- old direction documents remain readable and immutable;
- generated schemas are regenerated and checked.

### Asset relevance and rights

- relevant B-roll selected;
- unrelated B-roll rejected;
- missing/unknown/changed license rejected;
- asset hash or provider response change invalidates plan;
- interrupted acquisition resumes safely;
- provider unavailable yields declared fallback or review state;
- no external asset is added to a prohibited campaign.

### Camera and transitions

- static, push-in, pull-out, reframe, and follow-subject bounds;
- face/source-text/CTA/caption collision;
- jump-cut and exact-boundary mapping;
- transition only at complete-word boundaries;
- clean-cut fallback;
- max density and no repeated decorative transitions;
- repeated render timing/metadata deterministic.

### Audio

- source-only audio unchanged when no SFX is selected;
- SFX gain/fade/ducking and true peak limits;
- speech remains intelligible;
- SFX does not overlap prohibited speech windows;
- intentional silence preserved;
- changed SFX or mix policy misses cache;
- Tarteel policy block is proven.

### Real production proof

Render through the real Remotion production composition for a generic campaign:

1. clean dialogue beat with camera motion only;
2. relevant B-roll beat with a restrained transition;
3. SFX accent beat with measured ducking;
4. multi-cut clip with at least two treatment families;
5. no-asset fallback;
6. Tarteel policy-block fixture with no outside B-roll/SFX.

Decode the MP4s and inspect the whole clip with audio and muted playback. Do
not use color fixtures or a handwritten HTML substitute. Record exact paths,
hashes, frame samples, audio reports, provider/license evidence, and known
limitations. The current motion-graphics-off rule applies to these fixtures
unless an explicit later round enables it.

## Documentation and provenance deliverables

Implementation must add or update:

- an ADR for treatment orchestration and per-beat decision states;
- generated schema and contract documentation;
- preset treatment-policy reference;
- provider query/relevance/acquisition procedure;
- camera and transition recipe reference;
- sound-design and loudness policy;
- viewer-quality QA rubric;
- operator skill instructions with a generic campaign example and a Tarteel
  prohibition example;
- provenance manifests for every adopted recipe, font, B-roll, and SFX.

The docs must distinguish `IMPLEMENTED`, `TECHNICALLY_VERIFIED`, and
`AWAITING_HUMAN_VISUAL_ACCEPTANCE`. A passing lint or provider response is not
visual acceptance.

## Completion definition

This plan is implemented only when:

1. Every meaningful beat in a generic campaign has an explicit treatment
   decision, even when the decision is to omit a layer with a reason.
2. Presets contain typed B-roll, SFX, camera, and transition policies.
3. Codex can request relevant asset candidates and the system can acquire,
   license, hash, stage, and verify them without network calls in Remotion.
4. B-roll relevance is checked before render and after decoded output.
5. Camera motion/zoom is bounded by subject and platform safe regions.
6. Cuts and transitions preserve complete words and audio continuity.
7. SFX are purposeful, gain-controlled, speech-safe, and policy-aware.
8. Tarteel and other restricted campaigns prove explicit policy blocks rather
   than silently inheriting generic treatment defaults.
9. Viewer-quality QA catches unrelated assets, clutter, harsh cuts, excessive
   motion, and speech-masking SFX.
10. Any treatment dependency change invalidates stale QA, final review, cache,
    and delivery reuse.
11. A real generic-campaign Remotion render demonstrates the full path, and a
    restricted-campaign fixture demonstrates safe omission.
12. Human review remains the final gate for the exact encoded artifact.

Until these conditions are met, the capability status is **planned** or
**partially implemented**, not production-ready. The existing Advanced Hero
support is an execution capability; this plan supplies the missing editorial
decision and evidence layer that should make those capabilities routine for
eligible campaigns.
