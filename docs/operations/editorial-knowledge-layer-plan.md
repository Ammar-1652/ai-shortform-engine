# Editorial knowledge and direction layer: implementation specification

**Status:** K1–K8 implementation and typed admission/evaluation tooling are
shipped. Human visual proof remains the final separate acceptance step.
The final pre-acceptance validation is 923 Python tests passed, 2 skipped, 18
browser tests passed, 64 renderer tests passed, and 287 generated schemas
verified.
The directional-assistant expansion is defined in [the deep integration plan](editorial-direction-engine-deep-integration-plan.md).  
**Parent:** [Editorial Direction Engine integration plan](editorial-direction-engine-integration-plan.md).  
**Integrated execution plan:** [Editorial system upgrade plan](editorial-system-upgrade-plan.md).  
**User requirement:** repository skills, editorial methods, ready-made motion,
and future reference videos must form a durable source of direction for Codex.
Installing files or adding a few prompt sentences does not satisfy this plan.

The knowledge layer supplies the evidence and guidance used by the
[treatment-orchestration plan](editorial-treatment-orchestration-plan.md).
That plan turns the guidance into per-beat B-roll, SFX, camera, zoom,
transition, or explicit-omission decisions; this knowledge layer does not
itself force decorative treatment into a render.

## Responsibility and location

This layer lives in Clipforge's existing AI decision plane. Codex reads it,
chooses an editorial treatment, explains the choice, and submits a typed plan.
The deterministic system finds relevant guidance, validates applicability and
dependencies, executes the plan, and records proof. Human final acceptance
continues through the existing exact-artifact playback workflow.

Repository guidance has two possible outputs: editorial knowledge and usable
implementation. A pack may contribute both. A licensed compatible component
may be reused and customized directly. A useful editorial principle does not
need a new component before it can guide story selection or pacing. Conversely,
an installed component is not a reason to insert that effect into every short.

The direction layer must answer, for every major choice:

* What is the source actually saying and showing?
* Which narrative and visual treatments fit this situation?
* Which guidance supports the choice, and when would that guidance fail?
* Which exact system capability can execute it today?
* Which facts, timing, campaign rules, or viewer needs constrain it?
* Which evidence will show whether the encoded result works?

## Current starting point

Inspection found two existing entry skills, not an empty project:

* `.codex/skills/clipforge-production-operator/SKILL.md` routes actions to
  tools and defines Codex/system/human responsibilities.
* `.codex/skills/clipforge-motion-direction/SKILL.md` provides direction
  guidance, allowlisted treatments, and a typed direction handoff.
* Its `references/tarteel-style-library.md` contains campaign-specific story,
  typography, layout, sound, and identity advice.
* `docs/third_party/motion-skills.lock.json` pins selected iart-ai references.
* `DirectionDocument`, `EditorialArcDocument`, `MotionStyleSpec`, the asset
  catalog, and the operator capability catalog already cover parts of the
  intended execution path.

The Tarteel reference explicitly says verified performance data was not
provided. It also combines historical layout recommendations with general
craft heuristics. Preserve that material and its provenance, but classify its
individual statements before treating them as current campaign direction.
The implementation must find and report conflicts with later campaign rules;
neither document order nor a heading such as "proven" establishes authority.

## Deliverable architecture

Use a small set of entry skills above a versioned local knowledge library.
Do not paste every upstream SKILL.md into the operator skill.

```text
reviewed repository guidance       authorized reference videos
            |                         |
            v                         v
     pinned source record       frame/audio/text analysis
            |                         |
            +------------+------------+
                         v
            observations and guidance cards
                         |
             scope/conflict/evidence review
                         v
          story patterns + style cards + motion recipes
                         |
              versioned library release
                         v
candidate + campaign + capabilities -> relevant direction context
                         |
                         v
                Codex editorial choice
                         |
                         v
             typed direction and scene plan
                         |
                         v
      existing Hero/Advanced Hero -> QA -> human review
                         |
                         v
       attributed feedback -> proposed knowledge revision
```

The library may grow without rewriting skills, installing a second editor,
or shipping a new runtime for each reference video. Adding executable recipes
still follows normal reviewed code and renderer integration.

## Knowledge records and evidence types

Extend the parent plan's contracts instead of creating competing plan or
review authorities. Every record needs a stable id, schema version, content
hash, revision/parent link, scope, and provenance. Production-derived records
must also preserve existing `ArtifactProvenance` and source-asset bindings.
Upstream knowledge has its own repository/page identity; never fabricate a
campaign source id for a repository document.

| Record | Contents and purpose |
| --- | --- |
| `KnowledgeSource` | Exact repo/commit/path or authorized video id/hash, license and notices, permission for analysis versus reuse, capture version, allowed uses, source snapshot hash |
| `ReferenceObservation` | Specific frame/time interval, what was seen or heard, method, confidence, limitations, and links to frame/audio evidence |
| `EditorialGuidanceCard` | One actionable principle with triggers, prerequisites, rationale, steps, limits, counterexamples, supported capabilities, and evidence |
| `NarrativePattern` | Hook/body/payoff relationship, required source facts, continuity constraints, repetition rules, alternatives, and semantic failure cases |
| `EditorialStyleCard` | Coordinated story, captions, visual identity, motion, B-roll, pacing, sound, and ending; scope and permitted variation |
| `MotionRecipe` | Existing parent-plan recipe contract: implementation/asset identity, timing, typed parameters, purpose, compatibility, provenance, and tests |
| `KnowledgeConflict` | Conflicting record revisions, scope, authority, resolution or unresolved status, and reason |
| `KnowledgeRelease` | Exact admitted record revisions, source locks, conflicts, evaluations, and a manifest hash for reproducible retrieval |
| `DirectionContextBundle` | Relevant cards, source/campaign facts, excluded alternatives, unknowns, capability availability, and hashes presented to Codex |
| `EditorialDecisionTrace` | Selected/rejected card and recipe revisions, source evidence, reasons, deviations, and bindings to the actual direction plan |
| `EditorialFeedback` | Exact render/plan/scene, observed defect or preference, reviewer role, timestamps, evidence, severity, and proposed revision |

Separate what each record proves:

* **Source observation:** a cut, frame, caption state, spoken phrase, or
  audible event was observed at a recorded interval.
* **Editorial heuristic:** an author or Codex proposes that a treatment is
  useful under stated conditions. This is advice, not measured performance.
* **Implementation evidence:** an approved component renders the specified
  behavior deterministically with tested timing and geometry.
* **Viewer review:** a particular artifact was inspected or accepted for
  stated reasons. Codex inspection and human playback remain distinct.
* **Performance evidence:** actual outcomes are bound to the existing
  analytics records, metric definitions, observation dates, and sample sizes.
  Popularity alone does not prove that an edit technique caused success.

An `unknown` observation stays unknown. Example: a transient in a mixed audio
track does not identify the original SFX file, stem gain, or ducking settings.
Visual Arabic proof cannot establish alignment model evidence. Guessed fonts,
emoji meanings, facial identity, or measured retention must not become facts.

## Required guidance-card format

Each card must include more than a tip or effect name:

1. **Intent:** the viewer problem it solves.
2. **Applicability:** source genre, narrative situation, locale/shaping,
   campaign scope, runtime capability, and required evidence.
3. **Method:** the editorial reasoning and ordered actions Codex should take.
4. **Parameters:** bounded defaults with units, allowed variation, and a clear
   distinction between suggestions and campaign-mandated values.
5. **Coordination:** interaction with voice, captions, faces, B-roll, source
   branding, motion, CTA, and quiet moments.
6. **Avoid when:** negative examples and an omission/alternative path.
7. **Tools:** actual capability ids and valid typed outputs; unsupported
   actions are explicitly unavailable until implementation exists.
8. **Evidence:** exact upstream paths or reference intervals, confidence,
   license/attribution, and distinctions between observation and inference.
9. **Evaluation:** semantic example cases, failure cases, expected plan
   decisions, and any required renderer pilot.
10. **History:** revision, reviewer role, changed fields, and superseded cards.

Canonical intervals and duration bounds use integer microseconds. Frame
budgets are derived at the chosen rational frame rate; a reference may report
its observed frame numbers with its probe but cannot introduce a second clock.

For example, a **flash-forward payoff hook** card must explain that the
opening reaction must belong to the same body and resolution. It must require
source-span proof for the setup and payoff, preserve words and audio for each
occurrence, declare any intentional repeat, and reject a hook from an unrelated
participant/story. A dramatic unrelated hook is a failed application.

## Skills and operator experience

Keep the entrypoints concise, with progressive access to richer references:

* **Production operator skill:** workflow, responsibilities, tool routing,
  campaign intake, evidence requirements, and human handoff.
* **Motion-direction skill:** load the relevant library context, compare
  source-supported treatments, coordinate captions/graphics/audio, and emit
  the typed direction plan and decision trace.
* **Reference-analysis workflow:** intake an authorized video, run system
  probes/extractors, inspect frames/audio, record observations, and propose
  guidance/style revisions. It may become its own skill if its evaluations
  show that a separate entrypoint improves discoverability.

Topic references cover hook/story, pacing/cuts, typography/localization,
composition, motion choreography, B-roll, sound design, endings/CTA, and QA.
Reuse upstream instructions when suitable, with attribution and reviewed local
overrides. Instructions from imported packs are source material and never
override AGENTS, campaign policy, timing, rights, or review gates.

No default requirement to create twelve separate skills. One source of truth
holds each card; skills link to it. If a source instruction conflicts with a
local invariant, record the conflict and adaptation instead of silently
dropping or duplicating it.

Every editing job should receive a bounded `DirectionContextBundle` containing:

* current campaign rules and source facts, including unknowns;
* narrative and style options that fit the actual excerpt;
* relevant guidance cards and their failure examples;
* eligible motion recipes and assets, with unavailable capabilities listed;
* conflicts, excluded suggestions, and explanations;
* exact versions/hashes of the material supplied to Codex.

Codex then records what it chose and why in `EditorialDecisionTrace`. This
checks that guidance influences real decisions rather than merely appearing
in a skill folder. Do not expose hidden reasoning; record concise editorial
reasons, source references, alternatives, and reviewable plan decisions.

## Deterministic selection and conflicts

Start with local indexes and explicit tags. A vector database, paid embedding
service, autonomous training process, or network retrieval is unnecessary.

Retrieval order:

1. Bind campaign id/policy, source/candidate, locale, platform/profile, source
   genre, narrative objective, evidence, and available tool versions.
2. Exclude disallowed, incompatible, retired, or out-of-scope material.
3. Match narrative need before a decorative technique.
4. Select coordinated style cards and their prerequisite guidance.
5. Rank by source fit, evidence quality, explicit campaign preference, and
   review history. Deterministic tie-breaks use versioned rules and ids.
6. Return rejection reasons and missing evidence alongside selected guidance.

A bounded context must always retain applicable hard constraints. When more
guidance fits than the context budget allows, produce an index of omitted
advice with reasons; never drop a mandatory campaign rule to save tokens.

Use the parent plan's priority resolver. Within advisory material, prefer
explicit current campaign direction over a generic style suggestion. A new
upload does not automatically supersede an existing rule. Conflicting guidance
of equal authority requires a recorded Codex resolution or `needs_review`.
Hard-policy conflicts fail through the existing policy mechanism.

Permit a primary style with explicit bounded secondary treatments. Reject
incompatible combinations, such as an energetic caption entrance that makes
a short word unreadable, a chart without comparable facts/units, or a motion
recipe that collides with required Quran captions.

## Adding future reference videos

The same intake workflow must accept more references without code changes:

1. **Register:** bind authorized file, source hash, provenance, permission for
   analysis, reuse restrictions, campaign, locale, and optional outcome data.
   Permission to study a video does not permit reusing its footage or audio.
2. **Probe and extract:** use system tools for ffprobe, transcript, shot/cut
   candidates, adaptive frame samples, cue edges, waveform, loudness, and
   contact sheets. Do not treat one frame per second as full motion proof.
3. **Inspect complete context:** examine playback when available, transition
   windows, narrative order, visual identity, caption states, reactions,
   sound accents, silence, ending, and CTA. Record unavailable audio/playback
   or OCR proof; extract samples/stems only when the tool/evidence supports it.
4. **Describe:** distinguish observed facts, interpretation, and unknowns.
   Record why the hook relates to the body and why the payoff resolves it.
5. **Generalize cautiously:** propose a reusable pattern, exact applicability,
   counterexample, local implementation route, and campaign exceptions.
   Preserve useful one-reference ideas as hypotheses; do not invent a minimum
   sample count or call them performance-proven.
6. **Compare:** detect overlap and conflict with current cards and the source
   campaign rules. Suggest extension, revision, separate scoped variant, or
   rejection, with reasons.
7. **Evaluate:** test source fit and failure cases. For a visual/motion recipe,
   render a representative pilot using the production composition and inspect
   encoded frames and audio. Record limits by locale and capability.
8. **Admit:** Codex may review editorial knowledge and propose an active local
   release under its operator role; new executable code follows independent
   code review. Human final review remains required for deliverable videos.
9. **Publish version:** append a release and update the local index/skill
   reference. Do not rewrite earlier observations or user review records.

The next applicable edit must demonstrate that retrieval can find the new
pattern, select it when appropriate, and reject it for a deliberately
inappropriate candidate. This is the acceptance test for learning from a
reference; merely saving the MP4 or transcript is insufficient.

## Knowledge lifecycle and updates

Track separate dimensions rather than one misleading "approved" flag:

* **Permission:** analysis allowed; reuse allowed; blocked; unknown.
* **Knowledge state:** captured; analyzed; proposed; evaluated; active;
  superseded; withdrawn.
* **Evidence state:** observed; heuristic; technically demonstrated;
  viewer-reviewed; performance-associated, each with its actual evidence.
* **Implementation availability:** guidance-only; supported by existing tools;
  needs component; incompatible; retired.

A useful narrative heuristic may become active guidance without claiming a
rendered technique or causal performance proof. A motion recipe can only be
production-eligible when its implementation, rights, and required tests pass.
An active knowledge card grants neither human approval nor asset clearance.

Upstream updates are explicit intake events. No live fetch occurs while
editing or rendering. Compare the new commit with the pinned one, rerun the
affected evaluations, preserve notices, and publish a new local release.
Record changed assumptions even when code stayed identical.

Use feedback tied to a particular plan/render/scene. A rejection creates a
defect and a proposed rule or card change. It does not automatically penalize
all uses of a style, silently adjust scores, or invalidate unrelated renders.
Aggregate only comparable review/outcome data with known denominators.

## Cache and historical integrity

Every direction context pins its knowledge-release manifest, resolver version,
selected cards, omitted/conflicting advice, campaign policy, and inputs. A
decision trace binds those hashes to the typed plan, which already feeds
render, QA, review, and delivery identity.

Adding an unrelated reference does not rewrite a historical plan. A newer
library does not silently restyle an old approved output. A new plan made with
updated guidance receives a new identity; a changed chosen recipe, font,
asset, policy, or render dependency invalidates reuse through existing gates.

An advisory card being superseded is different from revoked media rights or a
verified unsafe component. Preserve historical interpretation for the former;
apply explicit existing policy/rights revocation and stale-evidence handling
for the latter. Record the reason; never silently reinterpret an old approval.

## Proposed repository shape and commands

Choose the final paths in the parent plan's architecture ADR. Prefer extending
existing direction/operator modules over creating duplicate catalogs.

```text
.codex/skills/clipforge-production-operator/SKILL.md
.codex/skills/clipforge-motion-direction/SKILL.md
.codex/skills/clipforge-motion-direction/references/knowledge-index.md
configs/editorial/knowledge/             # small admitted cards and index
docs/third_party/                        # source locks, licenses, notices
docs/editorial/evaluations/              # example and failure scenarios
src/clipforge/editorial/knowledge/       # intake, retrieval, validation
src/clipforge/schemas/                  # typed records, schema registry

<work-root>/editorial/references/        # private source/reference media
<work-root>/editorial/observations/      # extracted evidence
<work-root>/editorial/proposals/         # unadmitted cards and conflicts
<work-root>/editorial/releases/          # campaign/private library releases
<work-root>/editorial/contexts/          # per-job direction packets
```

Public, reusable guidance may be committed after license review. Private
reference text, campaign facts, transcripts, media, credentials, or contact
sheets stay under the ignored work root. Committed skills reference private
records by id and scope, never by embedding their contents.

The shipped CLI capabilities are:

```text
clipforge editorial knowledge list/show/verify
clipforge editorial knowledge intake/evaluate/admit
clipforge editorial reference analyze-reference/propose-style-card
clipforge editorial knowledge conflicts/resolve
clipforge editorial knowledge conflicts/resolve
clipforge editorial knowledge context
clipforge editorial knowledge feedback
```

Inspect commands are read-only. Write commands explicitly name inputs and
produce append-only outputs; admission does not create a review approval.
The operator capability catalog and `--help` expose only shipped commands.
The existing entry skills must keep working before these commands exist.

## Ordered implementation work packages

| Package | Work | Required proof |
| --- | --- | --- |
| K1: inventory | Extract existing skill/reference statements, classify authority/evidence, preserve source locks, list current conflicts | No historical rule is silently removed; Tarteel conflicts are visible |
| K2: records | Extend typed direction contracts with knowledge ids, releases, context, decisions, and feedback | Strict schemas, lineage, versioning, unsafe-input and missing-parent tests |
| K3: library | Import selected repo guidance, narrative patterns, style cards, and directly usable recipes with per-file provenance | Every active card has applicability, avoid-when, tools, and evaluation cases |
| K4: selection | Build deterministic local retrieval and conflict resolution | Same context yields same selected/rejected cards; policy survives context limits |
| K5: operator use | Update existing skills and capability catalog for implemented tools; emit direction context and decision trace | A fresh agent can select and execute a coherent direction from the docs |
| K6: reference intake | Analyze authorized videos and propose scoped patterns/style changes | Frames, audio, captions, narrative, unknowns, and permissions are all represented |
| K7: evaluations | Connect production pilots, semantic scenarios, review feedback, and release checks | New reference affects a suitable future edit and is rejected where unsuitable |
| K8: production binding | Carry chosen knowledge, implementation, and evidence identities through render/QA/final review | Changed chosen dependencies cannot reuse an old final approval |

K1–K5 are prerequisites for claiming a reliable direction layer. The parent
plan's final CLI/docs phase cannot be the first time skills see the knowledge.
Add the navigation and reference structure early, then enable each new command
only when its implementation is real. K6–K8 complete ongoing learning and
production evidence. Implement new recipes and providers in their existing
parent-plan stages; these packages must not fork the media pipeline.

## Acceptance and regression scenarios

Use deterministic contract/retrieval tests and source-specific editorial
evaluations. A schema test cannot establish that a story is coherent.

1. **Fresh agent:** with no chat history, the entry files identify campaign
   rules, tools, relevant style choices, exact inputs/outputs, and final stop.
2. **Repo guidance:** selected upstream principles materially affect a real
   direction plan, with citations, rejected options, and executable routes.
3. **New reference:** adding one authorized clip creates a versioned proposed
   card; after evaluation it is discoverable in an appropriate later edit.
4. **Irrelevant hook:** an exciting Yasser opening followed by an unrelated
   Aisha body is rejected for an explicit arc mismatch.
5. **Unnecessary opening:** an unrelated greeting before the actual question
   is identified by the selected pattern and scene review, not a campaign-wide
   ban on every greeting.
6. **Sparse source:** missing payoff or weak coverage produces a documented
   needs-review/alternate-direction outcome; the operator never fabricates
   three unsupported hooks to fill a template.
7. **Caption and sound:** reference analysis represents active words, line
   layout, transition timing, audible accents, speech masking, and unknown SFX
   identity; production pilot checks the corresponding behavior.
8. **Policy conflict:** a reference's music or external footage is excluded
   for a campaign that prohibits it, while eligible typography guidance may
   remain usable.
9. **Locale and domain:** Arabic shaping and Quran verification retain their
   own evidence gates; a generic English kinetic style cannot override them.
10. **Ready-made recipe:** a licensed compatible component is selected and
    customized directly with typed parameters, tests, hashes, and notices.
11. **Conflicting revisions:** older logo/CTA/layout advice cannot override a
    current campaign direction because it was retrieved first or read last.
12. **Replay:** an old context/plan remains interpretable after a library
    update; altered selected dependencies create a new plan/artifact identity.
13. **Feedback:** a defect on one encoded artifact creates a scoped revision
    proposal with evidence, leaving prior records and unrelated styles intact.
14. **Performance honesty:** an allegedly viral clip without analytics is
    labelled an observed reference, with no invented retention guarantee.
15. **Tool failure:** missing media, OCR, sound evidence, recipe, or model is
    reported specifically; a skill cannot write success to cover a failed tool.

Each evaluation records the source/context, allowed decisions, forbidden
decisions, reviewer role, plan/artifact hashes, observed result, and remaining
limits. Do not grade by checking for the presence of a sentence in SKILL.md.

## Completion boundary

This layer is ready for independent review only when an unfamiliar agent can
use the entry skills to retrieve grounded guidance, produce a coherent typed
plan, execute it through the system, explain its major choices, and carry
evidence to the existing final playback gate. At least one suitable new
reference and one unsuitable reference must exercise the full admission and
selection path.

Report code implementation, technical verification, editorial inspection,
and human acceptance separately. Catalog size, installed skill count, or a
green unit-test run cannot establish viewer quality or future virality.
