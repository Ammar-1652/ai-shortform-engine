# Editorial Direction Engine integration plan

**Status:** pre-human implementation, admission, pilot, cache, QA, and
production-path gates are implemented; exact encoded playback remains a human
acceptance step in
[the deep integration plan](editorial-direction-engine-deep-integration-plan.md).
**Prepared:** 2026-10-24; deep-integration revision 2026-10-25  
**Integrated execution plan:** [Editorial system upgrade plan](editorial-system-upgrade-plan.md)  
**Baseline inspected:** `round-35-quran-caption-verification` at `4ac0748bbf8efa4dc7f66f6de5b6904945bd824e`  
**Merge baseline:** `origin/main` at `989bf5d6ec27878d46505dc09becedfc848cd749`  
**Working-tree note:** the checkout already contains uncommitted round-35 and
role-boundary work. This plan does not assume that work is merged and does not
authorize editing it in place.

## Purpose

Clipforge already has the foundations for a local production machine: source
ingest, transcript and selected-clip alignment, TimeMap-based synchronization,
Hero and Advanced Hero rendering, rights records, resumable rendering, QA,
review, and local delivery. It also has a Codex/system/human role contract:

* **Codex (`codex_operator`) is the editorial brain.** It reads the policy and
  evidence, chooses the hook, narrative arc, crop, caption treatment, motion,
  B-roll, and sound cues, and submits typed plans.
* **Clipforge (`system_enforcer`) is the muscle.** It executes only validated
  declarative plans and enforces timing, rights, provenance, safe geometry,
  cache identity, stale evidence, QA, and delivery.
* **A human (`human_reviewer`) owns final playback.** The exact encoded MP4
  must be watched with audio and muted playback before final acceptance.

The reviewed external projects add useful knowledge, but they must not become a
second editor, a second renderer, a prompt-execution escape hatch, or an
unverified stock library. This plan creates an **Editorial Direction Engine**
above the existing pipeline. It turns reviewed ideas into typed catalogs,
style cards, reference evidence, and allowlisted Remotion recipes. It puts
Openverse behind the existing asset and rights boundary as an optional
discovery provider. Normal production remains offline after approved assets and
catalogs are present.

This document remains the execution plan. The current working tree contains
the pre-human implementation slice recorded in the implementation report:
typed knowledge admission, direction context and decision traces, six
presets, a 21-route local motion catalog, Openverse discovery/acquisition
boundaries, pilot receipts, viewer evidence, and stale/cache binding through
delivery and final-review evidence. Upstream sources that are still marked
reference-only remain reference-only; no private media, credentials, or
runtime network dependency was added.

The next implementation must follow the deep-integration plan before any new
repository, website, motion pack, or asset provider is called production-ready.
That plan makes the directional assistant an explicit AI decision layer rather
than a larger prompt or a flat catalog. It also defines the camera, transition,
sound, B-roll, and motion-graphics contracts that the deterministic renderer
must execute.

The focused follow-on implementation is documented in the
[editorial treatment orchestration plan](editorial-treatment-orchestration-plan.md).
It defines how a generic campaign receives explicit per-beat decisions and how
restricted campaigns record policy blocks instead of inheriting generic
treatment defaults.

## Required editorial knowledge layer

The [editorial knowledge and direction specification](editorial-knowledge-layer-plan.md)
is a mandatory part of this plan. Repository instructions and future reference
videos must become a versioned source of editorial guidance that Codex actually
uses. An effect catalog, a vendor directory, or a few sentences in SKILL.md
cannot satisfy this requirement.

The layer includes source-grounded guidance cards, narrative patterns,
coordinated style cards, local retrieval, conflict resolution, evaluation
cases, reference-video intake, and feedback. Each editing job receives a
hash-bound context bundle and records which guidance informed its decisions.
The existing operator and motion-direction skills remain the entrypoints.

K1–K8 are implemented as typed local contracts and admission/evaluation
tooling. K6 reference analysis still records unknown creative fields when no
authorized transcript/OCR/performance evidence exists, and K7/K8 remain
subject to the exact encoded playback and independent human decision. This
specification expands the knowledge, skill, reference, and feedback
requirements in the phases below without making an unverified reference or
provider production-ready.

## External material and adoption policy

The integration team must pin an exact commit before importing or adapting any
material. Repository names and URLs in earlier recommendations are not enough;
the execution audit must record the actual repository, commit, path, license,
and hash that were inspected.

### Candidate source registry (audit before adoption)

These are discovery leads, not yet approved dependencies. The execution audit
must resolve redirects, forks, current owners, and license files before using
any of them. In particular, the earlier ReelForge links refer to more than one
project; the plan must select one exact repository and record why.

| Source id | Candidate URL(s) | Audit requirement |
| --- | --- | --- |
| `reelforge` | `https://github.com/Skelf-research/reelforge`; `https://github.com/fahmid-juboraj/reelforge` | resolve the intended project and inspect its actual license/assets |
| `awesome-ai-motion` | `https://github.com/ibelick/awesome-ai-motion`; `https://github.com/gongnyang/awesome-ai-motion` | resolve the current catalog owner; record original, GSAP, font, and media licenses separately |
| `storyboard-director` | `https://github.com/verygoodgraphics/ai-storyboard-director` | verify repository identity, commit, license, and whether code is actually needed |
| `vyral-content-skills` | `https://github.com/vyralcontent/content-skills` | import only source-grounded writing heuristics; exclude unsupported marketing claims |
| `reel-analyzer` | `https://github.com/anthropics/skills/tree/main/skills/reel-analyzer`; `https://github.com/ndpvt-web/reel-analyzer` | verify the exact source and license before copying any code |
| `video-editor-agent` | `https://github.com/krusemediallc/video-editor-agent` | treat as reference-only until its repository and asset license are confirmed |
| `short-form-editing-kit` | `https://github.com/Content-Originals/short-form-video-editing-kit` | verify MIT notice and bundled asset terms |
| `generative-media-skills` | `https://github.com/NYC-Design-Systems/generative-media-skills` | select only needed skills and record methodology/version |
| `cutagent` | `https://github.com/Skelf-research/cutagent` | inspect model/provider assumptions; do not add another renderer |
| `video-shotcraft` | `https://github.com/Vincentwei1021/video-shotcraft` | import recipe metadata only after asset/font license review |
| `prompt-motion` | Prompt Motion reference pages supplied by the operator | capture only authorized references; never treat a page or prompt as executable code |
| `openverse` | `https://api.openverse.org/v1/`; `https://github.com/WordPress/openverse` | pin API contract/terms at implementation time; the provider remains optional and rights-unverified until independently checked |

If a candidate URL is unavailable, redirects to an unrelated project, lacks a
license, or contains bundled assets whose terms cannot be separated, mark that
source `reference_only` or `rejected`; do not substitute a similarly named
repository silently.

### Adopt guidance and compatible implementations

| Source | Planned use | What may be copied | What must be reimplemented or rejected |
| --- | --- | --- | --- |
| ReelForge / direction-first short-form projects | direction before copy, intensity curves, beat grids, pilot-scene gates, gallery-first review | written concepts and small metadata structures after license review | renderer, GPU/OpenGL path, beat/music assumptions, arbitrary generated code |
| Awesome AI Motion | motion catalog, intent routes, effect cards, recipes, overuse warnings | licensed guidance, metadata, and compatible ready-made components | adapt incompatible timing/runtime behavior; review GSAP, fonts, and media separately |
| AI Storyboard Director | scene facts, continuity, director-first planning | planning vocabulary and contract ideas after license review | no free-form cinematic prose as a render plan; no second scene engine |
| Vyral Content Skills | hook families, retention structures, platform adaptations | heuristics with provenance | unsupported retention percentages, generic “viral” scores, invented claims |
| Reel Analyzer-style workflows | authorized reference analysis, frame/audio/transcript metrics | analysis methodology after license review | scraping, unauthorized platform downloads, copied code with unclear license |
| Video Editor Agent | style harness, sound-design pass, review loop, evidence packet | architectural ideas after code/asset license review | black-box agent control, unverified dependencies, automatic approval |
| Short-form Editing Kit | brief, shot list, rights manifest, safe-area and delivery checklist | schemas/checklist concepts after license review | a parallel delivery gate or rights database |
| Generative Media Skills | small skill/evaluation format | only selected guidance with attribution | importing a large unreviewed skill bundle or executable prompts |
| CutAgent | Hook Lab, storyboard and style harness | concepts after license review | alternate model/provider and renderer |
| Video Shotcraft | shot recipes, transition and sound-design cards | licensed guidance, recipe metadata, compatible code and separately cleared assets | unbounded effects, uncleared media/fonts, an uncontrolled second renderer |
| Prompt Motion | motion-reference and recipe catalog | normalized metadata; directly vendor compatible components when their per-file licenses permit it | runtime web dependency, arbitrary code execution, assumption that a reference grants a license |
| Openverse | optional image/audio discovery and acquisition metadata | API responses for selected requests and required attribution | license guarantee, scraping, unbounded pagination, automatic insertion into renders |

The first implementation gate is a **provenance lock** under the ignored work
root plus a small repository manifest containing only source URLs, commits,
paths, licenses, attribution, and file hashes. Large videos, reference media,
fonts, and downloaded assets remain outside Git. If a source license is missing,
ambiguous, or incompatible with the intended use, the source stays
`reference_only` and its code/assets are not copied.

### Ready-made motion adoption is allowed

The system may use an existing motion implementation directly when it passes
the following checks. Reimplementation is a fallback for incompatible
runtimes, not a blanket requirement.

1. **Compatible component:** a Remotion/React component can be vendored or
   pinned as a dependency, wrapped with typed props, and executed by the
   existing Remotion renderer. Its implementation, dependency versions, and
   license notices are recorded in the recipe provenance.
2. **Compatible library:** a permissively licensed animation library can be
   added to the renderer only when it is needed by an approved recipe, its
   version is locked, its license is compatible, and deterministic browser
   tests cover it. A catalog entry alone never grants permission to add the
   library.
3. **Separate pre-render adapter:** a motion that requires another runtime may
   be used as a bounded, deterministic overlay only after an architecture
   decision. The adapter must receive typed inputs, use the same output clock,
   produce a hash-bound artifact, and pass the same QA, rights, and cache
   gates. It cannot silently become a second editor or clock.
4. **Incompatible or unsafe material:** arbitrary remote code, unreviewed
   scripts, nondeterministic browser effects, unlicensed bundled media, and
   components that bypass TimeMap, safe-area, or caption rules remain blocked.

Every imported file must be classified separately as **code**, **font**,
**image/video**, **audio**, **documentation**, or **dependency**. A repository's
top-level license applies only where it says it applies. A MIT repository may
still contain an OFL font, a CC image, a proprietary sample, or a dependency
under another license. The manifest records each file's license and
obligations instead of treating the repository name as one clearance decision.

For common licenses, the practical handling is:

* MIT/BSD/ISC: modification and commercial use are normally allowed; retain
  the copyright and license notice.
* Apache-2.0: modification and commercial use are normally allowed; retain the
  license/NOTICE material, preserve notices, and mark meaningful changes.
* GPL/AGPL/LGPL: perform a compatibility review before linking or bundling;
  GPL/AGPL can impose source-distribution obligations on a combined work, and
  LGPL has its own relinking and notice conditions.
* SIL OFL fonts: follow the font license, preserve the license, and check
  reserved-font-name and redistribution rules. A font is not cleared merely
  because the motion repository is MIT.
* Creative Commons media: check the exact variant. BY requires attribution;
  NC blocks commercial use; ND blocks adaptations; SA can impose share-alike
  obligations. Openverse metadata is only a lead until the original source is
  independently verified.

The delivery package must contain the notices and attribution required by the
selected dependencies. The final MP4 does not remove obligations attached to
bundled fonts, sound, images, video, or libraries. This is why ready-made
motions are usable while a flat copy of an entire repository is unsafe.

Openverse is specifically treated as unverified discovery metadata. Openverse's
own API documentation says that access is rate limited and that pagination is
bounded; its terms prohibit scraping and state that Openverse does not verify
individual licenses or attribution. The plan therefore requires independent
landing-page and license evidence before an asset can become a Clipforge
`AssetLicenseRecord`. [Openverse API documentation](https://api.openverse.org/v1/)
and [Openverse terms](https://github.com/WordPress/openverse/blob/main/documentation/terms_of_service.md)
are execution-time references, not runtime dependencies.

Awesome AI Motion's public repository describes its original work as MIT while
separately retaining licenses for GSAP and bundled fonts. The plan imports
catalog knowledge only after recording those per-file terms. Compatible
components may be used directly; incompatible behavior is adapted into the
existing Remotion path. [Awesome AI Motion](https://github.com/gongnyang/awesome-ai-motion)
is not allowed to become an uncontrolled second production renderer.

## Target pipeline

The resulting production path is:

```text
campaign policy + rights + source manifest
        ↓
source / transcript / visual / forced-alignment evidence
        ↓
authorized reference analysis + campaign style card (optional)
        ↓
versioned knowledge release + relevant guidance context
        ↓
hook and narrative variants bound to exact source spans
        ↓
EditorialDirectionPlan
        ↓
direction priority resolver + direction lint
        ↓
pilot scene (highest-risk beat) and visual/audio smoke
        ↓
typed Advanced Hero plan and render input
        ↓
Remotion recipe registry + shared captions + typed B-roll/SFX
        ↓
resumable production render
        ↓
technical QA + editorial-mechanics QA + semantic viewer evidence
        ↓
human audio/muted playback of the exact MP4
        ↓
final review and local delivery
```

The two external paths are intentionally separate:

```text
Prompt Motion/reference packs → local recipe catalog → approved MotionSpec → Remotion
Openverse API → normalized discovery → operator selection → rights verification
                 → local acquisition → AssetLicenseRecord → typed placement → Remotion
```

Neither path may call the renderer directly. Neither path may write a review
decision. Neither path may replace `TimeMap`, the existing asset catalog, or
the final-review gate.

## Execution phases and gates

Each phase is a separate implementation slice on a dedicated `round-XX-*`
branch. A phase may not silently continue after a gate failure. The branch must
preserve the existing dirty work and be created from the verified merge
baseline after the repository owner decides which prior changes are in scope.

### Phase 0 — establish a clean implementation baseline

1. Record `git status`, current branch, current HEAD, `origin/main`, open PRs,
   and the actual merge baseline.
2. Read `AGENTS.md`, `ARCHITECTURE.md`, `SKILLS.md`, the operator and motion
   skills, ADRs 0069, 0070, 0073, 0081–0101, provider-boundary documents, and
   the campaign checkpoint relevant to the first fixture.
3. Run the read-only operator catalogue commands:

   ```bash
   uv run clipforge operator roles
   uv run clipforge operator tools
   uv run clipforge operator extensions
   uv run clipforge operator verify
   ```

4. Verify that the current role-boundary implementation and the existing
   uncommitted round-35 work are not accidentally mixed into a new branch.
5. Identify the smallest existing direction contract that can be extended.
   Do not create a second `DirectionDocument` family if the current contract
   can carry the new fields.
6. Record a no-network baseline: normal schema checks, unit tests, renderer
   tests, and `doctor` must pass before new provider code exists.

**Gate:** a written baseline record, no changed production behavior, and a
branch with an explicit scope. If the current branch is not clean enough for a
reviewable branch, stop and report the exact files that must be separated.

### Phase 1 — upstream audit and provenance lock

For every cited repository or page:

1. Fetch once into a temporary ignored inspection directory. Do not install
   globally and do not run unreviewed `npx`, shell, browser automation, or
   repository scripts.
2. Record repository URL, actual owner/name, commit/tag, selected paths, file
   hashes, declared license, bundled asset licenses, and any attribution text.
3. Inspect shell scripts, package scripts, network calls, font/media folders,
   and generated code before deciding whether anything is reusable.
4. Classify each item as `adopt_metadata`, `reimplement`, `reference_only`, or
   `reject` with a reason.
5. Store the provenance lock outside Git for large inspection material and
   commit only the small manifest needed to reproduce the audit.

Required lock entries include:

* ReelForge/direction-first source;
* Awesome AI Motion catalog and any selected effect cards;
* Storyboard Director;
* Vyral Content Skills;
* Reel Analyzer/reference-analysis source;
* Video Editor Agent;
* Short-form Editing Kit;
* Generative Media Skills methodology and selected skills;
* CutAgent;
* Video Shotcraft;
* Prompt Motion references and selected recipes;
* Openverse API documentation and provider terms.

**Gate:** no recipe or provider can be marked production-eligible until its
source, commit, license, attribution, and local modification record exist.

Also classify upstream editorial instructions as observations, heuristics,
campaign-specific requirements, implementation instructions, or unsupported
claims. Extract cards with applicability, method, avoid-when examples, tool
routes, and evaluations under the knowledge-layer specification. Compatible
code may be classified `adopt_component` or `adopt_dependency`; reusable
editorial instructions may be classified `adopt_guidance`.

### Phase 2 — canonical editorial contracts

Extend the current typed direction model or add the smallest compatible
versioned contracts. Prefer append-only sidecars over a SQLite migration unless
inspection proves that durable relational queries cannot be supported by the
existing architecture.

Add or extend:

* `EditorialBrief` — objective, audience, platform, language, policy, source,
  prohibited claims, and required CTA policy.
* `EditorialDirectionPlan` — the parent of every creative decision, bound to
  source, transcript, alignment, candidate, profile, TimeMap, and hashes.
* `EditorialStyleCard` — observed reference patterns and confidence, never a
  universal platform claim.
* `HookVariant` — exact source evidence, hook family, visual event, purpose,
  risk, and measured/observed support.
* `SceneSpec` — ordered source span, narrative purpose, visible subject/action,
  crop, caption, B-roll, motion, audio, transition, continuity, and failure
  conditions.
* `MotionSpec` and `MotionTechnique` — approved recipe id, parameters,
  interval, purpose, fallback, component, compatibility, and provenance.
* `CaptionSpec` — font identity/hash, lines, anchor, safe region, shaping,
  active-word behavior, duration, and language compatibility.
* `BrollSpec` — asset/license id, source in-point, output interval, purpose,
  relevance evidence, crop, and fallback.
* `AudioPlan` — dialogue, narration, music policy, SFX, ambience, silence,
  gain, fades, ducking, and overlap rules.
* `ReferenceAnalysis` — permission, source hash, transcript/frame/audio
  measurements, confidence, analyzer version, and contact-sheet references.
* `DirectionLintReport` — errors, warnings, infos, rejected alternatives,
  resolver decisions, and analyzer versions.
* `EditorialRevision` — append-only revision reason, parent plan hash,
  changed evidence, changed dependencies, and reviewer role.
* `PresetDefinition` and `EditorialEvidence`.

Include the knowledge specification's source/card/release/context/decision
records in this design. Prefer extending existing typed contracts. Do not add
a parallel review authority or fabricate media provenance for a repository
document. A direction plan binds its `DirectionContextBundle` and
`EditorialDecisionTrace`, including selected and rejected guidance revisions.

`EditorialDirectionPlan` must carry at least:

```text
project/campaign/source/candidate/transcript/alignment/profile ids
language and platform
selected preset and style-card ids
hook variants and selected hook
ordered hook/body/payoff/CTA scenes
energy curve and beat grid
motion, caption, B-roll, and audio plans
reference-analysis ids and evidence notes
priority resolver output and rejected alternatives
source/artifact/dependency hashes
schema version and planner version
```

Every child must point back to the parent plan and exact source evidence. Text
must remain structured data, not HTML or executable JSX. The plan may contain
operator-reviewed summaries only when it also contains source evidence and a
review note.

**Gate:** generated JSON Schema, round-trip validation, unknown-key rejection,
stale dependency rejection, and compatibility tests for existing direction and
Advanced Hero documents.

### Phase 3 — priority resolver and editorial presets

Implement a deterministic resolver with this order:

1. legal, campaign, safety, and rights policy;
2. source truth, transcript, TimeMap, and verified evidence;
3. narrative clarity and factual accuracy;
4. caption readability and accessibility;
5. continuity, pacing, and emotional progression;
6. brand/style preset;
7. decorative motion.

The resolver returns the selected decision and every rejected alternative with
the rule that won. Examples: a style cannot move a caption outside the safe
region; a transition cannot split a word; B-roll cannot override rights; a
motion recipe cannot cover a face or caption; a hook cannot invent a claim; a
language preset cannot claim unverified alignment; music policy can remove an
audio option.

Create data-driven presets. Initial presets:

* `clean_explainer` — question/promise → explanation → takeaway;
* `proof_comparison` — claim → evidenced comparison → conclusion;
* `story_reveal` — curiosity → withheld context → source-grounded reveal;
* `transformation` — problem → steps → visible result;
* `quote_emotion` — strong quote → context/reaction → emotional close;
* `product_cta` — problem → demonstration → benefit → action.

Each preset defines hook families, body/payoff/CTA rules, pace and energy
curve, permitted motion families, caption style, font fallback, B-roll roles,
SFX policy, audio mix, prohibited combinations, minimum holds, and lint rules.
Existing Clipforge styles remain compatible. A preset is eligible only when
the candidate and campaign evidence support it; omission is valid.

**Gate:** the same submitted operator choices and evidence produce equivalent
validated plan content and dependency identity, excluding recorded timestamps;
unsupported source structure rejects the preset; a preset cannot force a
chart, transition, B-roll, SFX, headline, or music.

Codex may propose different editorial choices on separate runs. Deterministic
validation and rendering apply to the recorded plan; this gate does not claim
that language-model reasoning is deterministic.

### Phase 4 — motion catalog and Prompt Motion adapter

Create a local catalog under the existing motion/direction boundary, not a
second renderer. Proposed files (adapt to the actual package layout after
inspection):

```text
src/clipforge/editorial/
  motion_catalog.py
  motion_registry.py
  motion_lint.py
  provenance.py
src/clipforge/schemas/motion_catalog.py
src/clipforge/cli/editorial_motion_cmd.py
configs/editorial/motion-techniques.json
configs/editorial/motion-recipes.json
docs/operations/provenance/prompt-motion-lock.json
```

Every `PromptMotionReference` stores source URL, creator, platform, type,
permission/licensing state, captured hash, tags, attribution, and analysis
version. Every `MotionRecipe` stores:

* recipe id/version and source reference;
* scene intent and compatible scene types;
* beat/timing/easing/transition/camera behavior;
* typography, color, layer, caption, RTL, and accessibility constraints;
* duration range, attention cost, readability risk, and overuse warning;
* required/optional inputs and strict parameter schema;
* local Remotion component and fallback component;
* provenance, attribution, and license state;
* deterministic rendering requirements.

Initial catalog target: 20–30 audited recipes, selected from these families:

* phrase/active-word emphasis;
* scale pulse and underline draw;
* highlight plate and quote reveal;
* directional slide and masked reveal;
* split comparison and proportional bar/chart build;
* progress/checklist/diagram build;
* freeze-frame label and focus callout;
* controlled crop push and match cut;
* blur-to-sharp reveal and restrained wipe;
* CTA hold and silence-to-impact transition.

Do not copy arbitrary JS, JSX, CSS, HTML, shell commands, fonts, GSAP, or
media from Prompt Motion. A compatible ready-made component may be vendored or
locked as a dependency when its exact file license, dependency licenses,
attribution, and deterministic Remotion behavior are verified. Wrap it with
typed props, safe-area/caption collision checks, tests, provenance, and a
fallback. If it cannot satisfy those conditions, reimplement the behavior as
an audited Remotion component or keep it reference-only. Only `approved`
recipes may enter an editorial plan. Other states are `reference_only`,
`experimental`, or `blocked`.

Add read-only/controlled-write commands:

```text
clipforge editorial motion doctor
clipforge editorial motion list
clipforge editorial motion show REFERENCE_ID
clipforge editorial motion recipes
clipforge editorial motion import --file FILE
clipforge editorial motion verify REFERENCE_ID
clipforge editorial motion render RECIPE_ID
```

`import` validates before writing; `render` only renders a local fixture; no
command scrapes or executes an upstream page.

**Gate:** at least ten recipes render twice through local Remotion with
identical input and identical output; missing component, unsafe parameter,
missing attribution, unsupported language, or unapproved source blocks use.

### Phase 5 — reference analysis and style cards

Implement a local, opt-in analyzer for files the operator is authorized to
use. It must not scrape TikTok, Instagram, YouTube, or other services, replay
credentials, or bypass access controls.

`ReferenceAnalysis` extracts:

* first visual change and hook duration;
* words/second, transcript timing, and silence windows;
* shot duration distribution and cut density;
* caption line count, position, font weight/color, and active-word behavior;
* B-roll ratio and visual relevance annotations;
* motion intensity and transition types over time;
* face/subject framing and crop behavior;
* SFX/voice/music layer timing, gains, ducking, and silence before payoff;
* payoff and CTA position/hold.

Each analysis stores source permission, source hash, analyzer version,
confidence, frames/contact sheet, waveform, transcript, and metric provenance.
Several analyses may produce a `StyleCard` with observed ranges and sample
counts. Ranges are evidence for a campaign direction, not universal retention
guarantees. Style cards are invalidated if an analyzed reference, analyzer
version, or permission record changes.

Follow the knowledge specification's register → observe → propose → evaluate
→ admit workflow. Keep sound/visual observations, editorial interpretations,
and performance claims distinct. New references become scoped cards and local
library revisions without requiring renderer code changes unless a genuinely
new executable technique is needed. No automatic rewrite of the entry skill
or current campaign rules is allowed. A newer source record creates a new
analysis/style revision; it must not reinterpret historical plans.

**Gate:** a fixture reference produces deterministic metrics; a missing
permission or changed source hash blocks style-card publication; no metric is
used as a performance claim without analytics evidence.

### Phase 6 — shared Remotion execution

Keep the current Remotion version, entrypoint, and browser isolation. Add a
typed registry and components under the existing renderer structure, for
example:

```text
apps/renderer/src/editorial/
  EditorialScene.tsx
  CaptionLayer.tsx
  MotionTechniqueLayer.tsx
  BrollLayer.tsx
  DiagramLayer.tsx
  AudioCueLayer.tsx
  PresetPreview.tsx
  DirectionDebugOverlay.tsx
  motionRegistry.ts
```

The renderer receives validated `EditorialDirectionPlan`/`MotionSpec` data. It
never invents a hook, writes arbitrary CSS/HTML, or interprets a natural
language prompt. Every component:

* uses `useCurrentFrame`/`useVideoConfig` and explicit frame intervals;
* preserves canonical TimeMap and output-frame semantics;
* is deterministic and does not use timers, random values, or network calls;
* respects safe regions, face/source-native-text collision data, and caption
  lanes;
* supports RTL/locale constraints or declares a safe fallback;
* validates props and has a fallback path;
* can be rendered in isolation and in Hero and Advanced Hero.

The first production integration should use the existing Advanced Hero path.
Hero must accept the plan only through its existing typed adapter, preserving
legacy output when no plan is supplied. No new standalone editor is allowed.

**Gate:** browser smoke proves the selected recipe appears only in its interval,
captions stay in bounds, B-roll and SFX align to their output intervals, and
the same plan renders identically twice.

### Phase 7 — Openverse discovery and rights-bound acquisition

Implement Openverse behind the asset provider boundary, for example:

```text
src/clipforge/assets/providers/openverse.py
src/clipforge/schemas/openverse.py
src/clipforge/assets/openverse_policy.py
src/clipforge/cli/openverse_cmd.py
```

Configuration must be opt-in and secret-safe:

```text
CLIPFORGE_OPENVERSE_API_BASE=https://api.openverse.org/v1
CLIPFORGE_OPENVERSE_CLIENT_ID=      # outside repository/artifacts
CLIPFORGE_OPENVERSE_CLIENT_SECRET=  # outside repository/artifacts
CLIPFORGE_OPENVERSE_TIMEOUT_SECONDS
CLIPFORGE_OPENVERSE_MAX_RESULTS
CLIPFORGE_OPENVERSE_USER_AGENT
CLIPFORGE_OPENVERSE_LIVE=0          # default disabled
```

The provider supports bounded image/audio search, details, pagination within
configured limits, license filters, duration/type filters, response
normalization, safe transient retry, 429 handling, cache identity, timeout,
and malformed-response rejection. It never scrapes pages, requests unbounded
pages, downloads every result, invents direct URLs, or treats a result's
license field as proof.

Add typed models:

* `OpenverseSearchRequest` and `OpenverseSearchResponse`;
* `OpenverseMediaRecord`;
* `OpenverseLicenseEvidence`;
* `OpenverseSelection`;
* `OpenverseAcquisitionAttempt`;
* `OpenverseAcquisitionManifest`.

Normalize provider, media id/type, title, creator/URL, source, landing/direct
URLs, license/version/URL, attribution, duration, dimensions, file type, tags,
source-response hash, timestamps, and policy/rights state. Unknown fields are
not silently copied into a public manifest.

Use the existing `AssetLicenseRecord` for clearance. Initial policy defaults:

* public domain/CC0: eligible only after landing-page verification;
* CC-BY: eligible with persisted attribution;
* CC-BY-SA: only if the campaign policy accepts share-alike obligations;
* CC-BY-NC: blocked for monetized/commercial output;
* CC-BY-ND: blocked for transformed/mixed output;
* unknown, missing, conflicting, dead, or unverifiable evidence: blocked.

Two-stage flow:

```text
search (read-only)
→ normalize and policy-evaluate candidate metadata
→ operator selects one record
→ revalidate response, landing page, license and policy
→ download into bounded staging inside work root
→ reject symlinks/traversal/outside paths
→ hash, probe, decode and verify media type
→ create AssetLicenseRecord and attribution
→ atomically promote asset and manifest
```

Proposed commands:

```text
clipforge assets openverse doctor
clipforge assets openverse search
clipforge assets openverse list
clipforge assets openverse show MEDIA_ID
clipforge assets openverse select MEDIA_ID
clipforge assets openverse acquire SELECTION_ID
clipforge assets openverse verify ACQUISITION_ID
clipforge assets openverse resume ACQUISITION_ID
```

Search/doctor/show/verify are read-only. Selection and acquisition are
append-only and resumable. A failed promotion preserves the previous verified
package. A changed response, license, policy, downloaded hash, or provider
version creates stale evidence and blocks render reuse.

**Gate:** fake provider tests complete one image and one SFX fixture through
selection, rights, acquisition, probe, direction placement, Advanced Hero,
QA, and delivery. Live Openverse smoke is opt-in and never required by CI.

### Phase 8 — audio, B-roll, and caption planning

Add explicit roles instead of allowing a catalog hit to become decoration.

`BrollSpec` roles: context, proof, reaction, process, result, contrast,
atmosphere, product detail, SFX, and ambience. Each placement names the scene,
asset/acquisition id, source in-point, output interval, visual purpose,
relevance evidence, crop strategy, rights, and fallback.

`AudioPlan` layers: source dialogue, optional narration, policy-allowed music,
SFX, foley/texture, and intentional silence. Every cue names purpose,
timestamp, duration, asset id, gain, fade, ducking, speech-overlap policy,
rights evidence, and source hash. The system rejects SFX that has no narrative
or visual event, excessive simultaneous layers, clipping, or speech masking.
Existing music prohibition and audio loudness gates remain authoritative.

Caption styles define local font identity and hash, fallback stack, weight,
line/character limits, safe anchor, backplate/stroke/shadow, active-word mode,
minimum hold, punctuation, shaping, RTL behavior, and locale support. Arabic,
Japanese, Quran evidence, and unsupported-language fail-closed rules stay in
the existing campaign and language contracts.

**Gate:** fixture tests prove full spoken-word coverage, no duplicate words,
correct phrase holds, safe geometry, RTL handling, SFX gain/ducking, and
source/voice alignment at first, interior, and final cue boundaries.

### Phase 9 — direction lint, pilot gate, and QA integration

Add `editorial lint` before planning, before a pilot render, before full
render, and before delivery. Use severity:

* `error` blocks the stage;
* `warning` appears in review and needs an explanation;
* `info` records a style observation.

Minimum lint rules:

* missing or weak source-grounded hook;
* no coherent body/payoff/CTA when required;
* unsupported or unapproved motion recipe;
* excessive effect density or repeated transition;
* unsupported language or missing alignment evidence;
* cut through a spoken word or duplicate source span;
* caption outside safe area or too short to read;
* B-roll/SFX without rights, relevance, or valid interval;
* face/source-native text collision;
* unsupported claim or chart unit;
* no quiet/contrast moment when the selected preset requires one;
* insufficient CTA/final hold;
* stale style/reference/asset/plan dependencies.

Pilot gate:

1. Select the highest-risk or peak scene.
2. Render it with the production Remotion component.
3. Run direction lint, frame evidence, caption evidence, and audio probe.
4. Block the full render until the pilot passes or a Codex editorial revision
   records why a warning is accepted.

Integrate into existing QA rather than creating a parallel gate:

1. Technical: decode, dimensions, codec, freezes, black frames, loudness,
   clipping, duration, and hashes.
2. Editorial mechanics: word-safe cuts, caption coverage, B-roll/SFX timing,
   transition overlap, CTA hold, and no duplicate layers.
3. Semantic viewer evidence: hook clarity, relevant visuals, face/caption
   visibility, motion purpose, payoff clarity, audio intelligibility.
4. Human packet: exact MP4 hash, contact sheet, waveform, transcript/timing,
   lint report, selected frames, and reference/style evidence.

**Gate:** stale or missing evidence is `INSUFFICIENT_EVIDENCE`, never a pass;
only the exact final package can be submitted to human playback.

### Phase 10 — CLI, review surface, and operator skill

Add commands following existing CLI conventions:

```text
clipforge editorial doctor
clipforge editorial analyze-reference
clipforge editorial style-card
clipforge editorial presets
clipforge editorial plan
clipforge editorial show
clipforge editorial lint
clipforge editorial verify
clipforge editorial preview
clipforge editorial motion doctor/list/show/recipes/import/verify/render
clipforge assets openverse doctor/search/list/show/select/acquire/verify/resume
```

Read-only commands must leave database rows, sidecars, and artifact bytes
unchanged. `plan` and `lint` may write only their documented append-only plan
or report artifacts after all validation succeeds.

The review surface must show the selected preset, hook/body/payoff/CTA, energy
curve, scene list, motion recipes, caption style, B-roll roles, SFX cues,
style-card/reference evidence, lint findings, rejected alternatives, and exact
dependency hashes. It must never expose credentials or absolute paths.

Build the navigation, topical references, and guidance-card structure in
`.codex/skills/clipforge-production-operator/SKILL.md` and
`clipforge-motion-direction/SKILL.md` during early knowledge-layer work.
Only advertise new command invocations after their implementations exist.
Add examples that show Codex retrieving applicable guidance, choosing and
rejecting alternatives, and invoking typed tools. Skills must produce a
direction context and decision trace, not become a hidden renderer or approval
stage. Include failure cases and fresh-agent evaluations from the knowledge
specification.

**Gate:** a new agent can follow `AGENTS.md → ARCHITECTURE.md → SKILLS.md →
skill → operator catalogue` and discover every capability, boundary, input,
output, and stop condition without reading implementation internals.

### Phase 11 — cache, stale evidence, and compatibility hardening

Add fingerprints for every output-changing dependency:

* EditorialDirectionPlan and parent source/alignment/TimeMap hashes;
* preset and resolver version;
* style-card/reference analysis hashes;
* motion-reference and recipe version/hash;
* Remotion component/renderer version;
* font file hash and caption style;
* B-roll/SFX acquisition and license evidence;
* Openverse request/response/policy/provider version;
* crop/reframe and audio mix policy.

Bind the exact knowledge release, retrieved guidance, conflicts, resolver
version, and operator decision trace. Adding unrelated reference material
does not silently invalidate a pinned historical plan. Applying updated
guidance creates a new plan identity; rights revocation or an unsafe component
continues to block reuse through explicit existing policy/stale mechanisms.

Changed source, transcript, alignment, plan, style card, recipe, component,
font, asset bytes, license, provider response, policy, or audio plan must create
a cache miss and invalidate affected QA, final approval, and local delivery.
Unchanged inputs may reuse only a verified artifact with matching producer,
dependency, and stale evidence.

Do not reinterpret old plans with new preset defaults. Legacy documents remain
readable with their recorded recipe. If a stored shape must change, add a
versioned reader or an explicit too-old/too-new error. A SQLite migration is
allowed only after proving sidecars cannot express the required query and must
include old-file behavior and tests.

**Gate:** cache and stale tests cover unchanged hit, source change, alignment
change, plan/style/recipe/font/asset/audio change, stale QA, stale human final
approval, changed license metadata, and failed promotion rollback.

### Phase 12 — fixture chain and production proof

Build one deterministic fixture chain and three materially different treatments
from the same authorized candidate:

```text
authorized source
→ transcript and visual evidence
→ selected-clip alignment
→ EditorialDirectionPlan
→ direction lint
→ pilot scene
→ Openverse fake discovery/rights/acquisition where policy allows
→ Advanced Hero production render
→ decoded frames/contact sheet and ebur128
→ technical/editorial/semantic QA
→ exact human playback target
→ final review only after a real person watches
→ local delivery package
```

Use at least `clean_explainer`, `proof_comparison`, and `story_reveal` (or
source-supported alternatives). Render Hero and Advanced Hero where both are
eligible. Include one RTL fixture, one B-roll/SFX fixture, one CTA fixture, and
one no-external-asset fixture. Do not use synthetic colored blocks as proof of
viewer quality.

If authorized real media is unavailable, complete deterministic and browser
fixtures but report real-source visual acceptance as unavailable. Never create
human playback or final approval records from tests.

## Required file and module map

The exact names must follow the existing package layout, but the implementation
should land in these boundaries:

```text
src/clipforge/schemas/
  editorial_direction.py       # plan, brief, scenes, presets, evidence
  motion_catalog.py             # reference/recipe/registry contracts
  reference_analysis.py         # frame/audio/transcript evidence
  openverse.py                  # discovery/acquisition contracts
  audio_plan.py                 # cues, ducking, silence, policy

src/clipforge/editorial/
  direction_plan.py             # plan construction and dependency binding
  priority.py                   # deterministic conflict resolver
  presets.py                    # data-driven preset loader
  lint.py                       # direction lint and pilot gate
  reference_analyzer.py         # authorized local analysis
  style_cards.py                # aggregate observations
  motion_catalog.py             # local catalog and provenance validation
  motion_registry.py            # recipe → Remotion component mapping

src/clipforge/assets/providers/openverse.py
src/clipforge/assets/openverse_policy.py
src/clipforge/assets/openverse_acquisition.py

src/clipforge/cli/editorial_cmd.py
src/clipforge/cli/editorial_motion_cmd.py
src/clipforge/cli/openverse_cmd.py

apps/renderer/src/editorial/
  EditorialScene.tsx
  CaptionLayer.tsx
  MotionTechniqueLayer.tsx
  BrollLayer.tsx
  DiagramLayer.tsx
  AudioCueLayer.tsx
  PresetPreview.tsx
  DirectionDebugOverlay.tsx
  motionRegistry.ts

configs/editorial/presets/
configs/editorial/motion-techniques.json
configs/editorial/motion-recipes.json
configs/editorial/knowledge/
docs/operations/provenance/
docs/editorial/evaluations/
docs/adr/0102-editorial-direction-engine.md
docs/adr/0103-prompt-motion-reference-catalog.md
docs/adr/0104-openverse-rights-bound-provider.md
```

Do not create all of these files in one speculative commit. The file map is a
boundary map for the staged work.

## Test matrix

### Contracts and policy

* schema export/check for every new model;
* unknown keys, malformed intervals, unsupported locale, unsafe text/URLs;
* source/transcript/alignment/TimeMap/style-card mismatch;
* priority conflicts return the higher-priority decision and rejection reason;
* preset selection is deterministic and source-supported;
* missing evidence blocks rather than downgrading to a warning.

### Knowledge, skills, and continuing reference intake

Run the knowledge specification's acceptance scenarios: fresh-agent operation,
repo guidance affecting a real plan, new-reference admission and retrieval,
irrelevant-hook rejection, campaign/locale conflict handling, direct component
reuse, historical replay, and scoped feedback. Verify that unrelated viral
references are excluded and unverified performance remains a labelled
observation. Checking for keywords in a skill is insufficient.

### Motion and Prompt Motion

* missing reference, missing attribution, unknown recipe, invalid component;
* untrusted executable payload, HTML, shell, remote URL, or unsafe parameter;
* fallback component selection;
* effect density and safe-area violations;
* repeated render byte/digest determinism;
* at least ten approved recipe fixtures through Remotion;
* changed recipe/component/renderer invalidates caches and approvals.

### Reference analysis

* authorized local file succeeds;
* missing permission, changed source hash, malformed media, missing audio, or
  OCR/transcript uncertainty is explicit;
* frame/timing metrics are deterministic;
* style-card aggregation records sample count, confidence, and analyzer hash;
* no network or platform scraping occurs in normal tests.

### Openverse

* anonymous and configured-auth modes without logging secrets;
* timeout, 401, 429, 5xx, malformed JSON, oversized response, missing results;
* bounded pagination and rate-limit backoff;
* CC0/public-domain/CC-BY acceptance only with evidence;
* CC-BY-SA policy branch;
* NC, ND, unknown, missing, conflicting, dead, or stale evidence blocked;
* missing landing/direct URL, remote-path rejection, traversal, symlink,
  outside-root staging, changed bytes, corrupt media, unsupported codec;
* interrupted acquisition and failed atomic promotion preserve prior package;
* read-only commands do not mutate bytes or rows;
* cache hit revalidates every linked evidence record.

### Renderer and QA

* clean explainer, proof comparison, story reveal, RTL caption, B-roll/SFX,
  CTA, and no-external-asset fixtures;
* first/mid/last and cue-edge frames;
* captions inside safe region and no duplicate text layer;
* source/voice/B-roll/SFX interval alignment;
* no face/source-native-text collision;
* loudness, true peak, ducking, silence, clipping, and layer count;
* pilot gate blocks a full render on an error;
* technical, mechanics, semantic, and human-review packet evidence remain
  separate.

### Full repository checks

Run targeted tests first, then:

```bash
./scripts/validate.sh
uv run clipforge schema check
uv run clipforge operator verify
uv run clipforge editorial verify
uv run clipforge assets openverse doctor
pnpm --dir apps/renderer lint
pnpm --dir apps/renderer typecheck
pnpm --dir apps/renderer test
```

Live Openverse smoke is opt-in, bounded, and separately reported. Normal CI
must pass without credentials or network. Stop and clean up all browser,
Remotion, ffmpeg, Node, and test processes.

## Documentation and review deliverables

Before implementation is called complete, add:

1. ADR for the Editorial Direction Engine and any necessary provider boundary
   decisions.
2. Motion catalog authoring and provenance guide.
3. Prompt Motion audit lock with exact commits, paths, licenses, and hashes.
4. Openverse setup, rate-limit, attribution, and independent-license-check
   guide.
5. Preset, caption, B-roll, audio, reference-analysis, and lint references.
6. Operator runbook with exact command sequence and stop conditions.
7. Review-surface documentation describing every creative choice and evidence.
8. Operations validation report with test counts, rendered paths/hashes,
   provider status, cache/stale results, OCR availability, and limitations.
9. Versioned knowledge release, source/guidance locks, reference intake and
   conflict workflow, per-edit decision traces, and semantic evaluation report.

The final report must distinguish:

* **IMPLEMENTED** — the code and contracts exist;
* **TECHNICALLY VERIFIED** — deterministic tests and production renderer proof
  passed;
* **AWAITING HUMAN VISUAL ACCEPTANCE** — a person still needs to watch the
  exact final MP4 with audio and muted playback;
* **REFERENCE-ONLY/BLOCKED** — an upstream source or provider lacks the
  permission, license, or evidence needed for production.

Do not call the provider integration production-ready merely because its API
responds or its tests pass. Do not call an editorial preset successful without
decoded-frame and audio inspection of a real production composition.

## Sequencing and stop conditions

The safe implementation order is:

```text
baseline and provenance
→ knowledge inventory, conflicts, contracts and schemas
→ guidance cards, local selection, and operator skill navigation
→ priority resolver and presets
→ motion catalog and ten local recipes
→ reference analysis/style cards
→ Remotion adapter
→ Openverse discovery
→ acquisition and rights binding
→ B-roll/audio/caption integration
→ lint/pilot/QA
→ CLI/review/skill docs
→ cache/stale hardening
→ full fixture and real-source proof
```

Develop knowledge packages K1–K8 alongside these phases as specified in
[the knowledge-layer plan](editorial-knowledge-layer-plan.md). Source guidance
must influence planning before motion effects are selected; skills cannot be
deferred to a final documentation task.

Stop before the next phase when:

* the preceding phase's gate is red;
* the upstream license or attribution is unclear;
* a plan would need executable code or arbitrary HTML;
* an Openverse result lacks independently verified rights;
* a source or alignment hash is stale;
* the renderer would need a second clock or a second production path;
* a visual claim cannot be tied to source evidence;
* a real-source render cannot be inspected;
* human playback is unavailable.

The first implementation PR should therefore be **catalog/contracts only** if
the upstream provenance lock is not complete. Do not begin with a broad vendor
drop, a network provider, or a visual-effects rewrite.
