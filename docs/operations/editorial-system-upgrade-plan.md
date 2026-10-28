# Clipforge editorial system upgrade plan

**Status:** W0–W8 pre-human foundations and binding gates implemented. W6
resumable rendering, encoded viewer evidence, cache checks, delivery/final
review dependency binding, and one real Tarteel Advanced Hero source run are
technically verified. Independent human playback remains required; a fresh
Tarteel render also remains intentionally blocked until its stale editorial
arc receives a new review.

**Prepared:** 2026-10-24

**Scope:** consolidate the editorial knowledge layer, direction engine,
reference analysis, motion catalog, optional asset discovery, resumable
execution, viewer-quality QA, and Drive-inspired release/checkpoint practices
without creating a second editor or a second source of truth.

This plan is the implementation contract for the next upgrade rounds. It is
deliberately broader than a renderer change. The system needs a controlled
decision layer, a durable execution record, and evidence-based gates around
the existing media pipeline. Adding components without these boundaries would
recreate the current failure mode: isolated features that do not reach the
render, QA, review, cache, or delivery contracts consistently.

## 1. Target result

Clipforge should operate as one local production machine with three distinct
roles:

| Role | Owns | Must not do |
| --- | --- | --- |
| **Codex / editorial operator** | Reads policy and evidence, chooses the story, selects a preset, chooses hook/body/payoff, decides crop, captions, B-roll, motion, SFX, and CTA, explains each decision | Execute arbitrary renderer code, bypass rights, invent source claims, approve publication, or treat a heuristic as measured performance |
| **Clipforge system** | Executes typed plans, maps one canonical TimeMap, renders, probes, checkpoints, caches, validates rights, QA, stale evidence, and delivery | Make unreviewed editorial choices, silently substitute assets, repair invalid plans, or hide failures |
| **Human reviewer** | Watches the exact encoded artifact with audio and muted playback and records final acceptance or rejection | Approve a different artifact, approve from metadata alone, or have an automated decision recorded as human approval |

The intended flow is:

```text
campaign + source intake
  -> current release and policy lock
  -> source/transcript/alignment/visual evidence
  -> reference and knowledge context
  -> Codex editorial decision trace
  -> typed direction plan and scene graph
  -> rights-bound asset/motion resolution
  -> pilot scene and direction lint
  -> resumable Hero/Advanced Hero render
  -> decoded-frame/audio/viewer QA
  -> human final playback
  -> exact delivery package
  -> append-only feedback and future knowledge proposal
```

There is one control plane, one media plane, one AI decision plane, one asset
plane, and one review plane. The Google Drive workflow may be an optional
archive or synchronization adapter later; it must not become a competing
database, renderer, or approval authority.

## 2. Current state and separation of done from staged

The current checkout contains uncommitted work from earlier rounds and the
round-36 editorial knowledge implementation. Do not infer that dirty files are
merged or that a passing test suite means the whole upgrade is complete.

The implementation work has now added release snapshots, durable campaign
execution checkpoints, measured reference analysis, inactive style-card
proposals, semantic direction lint, knowledge-aware Advanced Hero identities,
and a confined rights-bound Openverse acquisition path. The full validation
suite is green, but metadata and tests cannot replace real production render
proof or human visual acceptance.

### Foundations already present

- typed knowledge records, source records, guidance cards, style cards,
  releases, context bundles, decision traces, and feedback;
- local motion recipe catalog and Openverse discovery/selection boundary;
- `editorial` CLI, motion CLI, reference-analysis CLI, and operator capability
  entries;
- direction documents can bind a knowledge context and decision trace;
- pinned motion guidance and campaign style references;
- existing TimeMap, Hero, Advanced Hero, rights, authorization, checkpoint,
  viewer-evidence, QA, final-review, and delivery contracts;
- role documents and skills that distinguish Codex, system, and human work.

### Still staged or incomplete

- transcript/OCR/caption-layout and human narrative review for reference
  admission (the analyzer now records deterministic scene/audio/cut metrics,
  scene-midpoint frames, and a contact sheet, but it does not infer the
  unknown creative fields);
- broader production visual comparisons across the motion catalog (the
  allowlist, deterministic route harness, and one encoded browser fixture are
  implemented; each campaign still needs a purposeful selected recipe and a
  fresh pilot);
- independent landing-page evidence capture for Openverse (the acquisition,
  hashing, probe/decode, rollback, and existing asset-license registration path
  is implemented, but Clipforge does not scrape a landing page);
- a separately recorded human playback decision and the complete semantic
  four-level review packet for any newly rendered campaign artifact;
- an independent human playback decision for the technically verified Hero
  and Advanced Hero drafts; the first legacy Hero browser crash around frame
  1359 is now covered by the checkpointed Hero path and its successful rerun,
  while the original failed attempt remains immutable evidence;
- a fresh Tarteel editorial-arc review after any Hero-plan change; the stale
  arc gate prevents a new direction-layer render until that review exists.

The implementation sequence below treats the existing code as a foundation and
does not rewrite old artifacts or reinterpret old plans with new defaults.

## 3. Architecture boundaries and conflict rules

### 3.1 One authority per concern

| Concern | Canonical authority | Examples of forbidden duplicates |
| --- | --- | --- |
| Current code/release | Git branch and pinned local release record | A Drive document silently overriding the checkout |
| Campaign policy | Existing policy engine and campaign hard-rule documents | A style card weakening a campaign gate |
| Source truth | Registered source asset, transcript, alignment, visual evidence, and TimeMap | A reference video or LLM claim replacing source evidence |
| Editorial choice | Typed direction plan plus decision trace | Renderer defaults deciding the story |
| Time | `TimeMap` and integer microseconds | Milliseconds, floating-point timelines, or a second clock |
| Motion | Versioned local motion recipe catalog and allowlisted Remotion registry | Arbitrary JavaScript or CSS supplied in a plan |
| Rights | Existing `AssetLicenseRecord` and compliance gate | Openverse metadata or a prompt saying “licensed” |
| Render state | Append-only run journal/checkpoint and verified artifact receipts | A directory scan guessing what finished |
| Technical/viewer QA | Existing QA contracts plus viewer-evidence and playback records | A pixel heuristic calling the edit acceptable |
| Final acceptance | Exact-artifact human final-review decision | Automated approval or approval copied from an older artifact |
| Historical records | Append-only sidecars and immutable artifacts | Rewriting old reviews, releases, or checkpoints |

When two records disagree, the system must return a conflict with both ids,
hashes, scopes, and an actionable resolution. It must not choose by file order,
mtime, or “latest-looking” text.

### 3.2 Priority resolver

All direction and asset decisions use this order:

1. legal, campaign, safety, rights, and language policy;
2. source truth, transcript, alignment, TimeMap, and verified evidence;
3. narrative clarity and factual accuracy;
4. caption readability and accessibility;
5. continuity, pacing, and emotional progression;
6. brand/style preset;
7. decorative motion.

A lower level can narrow a valid choice but cannot override a higher level. The
resolver records selected and rejected alternatives, not just the winner.

### 3.3 No hidden fallbacks

Contain, crop, face-follow, B-roll, SFX, caption styles, fonts, and motion
recipes are explicit plan fields. A requested strategy that is unavailable or
unsafe is a failed plan or a documented alternative requiring a new decision;
it is never silently changed in the renderer.

## 4. Workstreams and dependency graph

The work is split into nine workstreams. Each stream has an exit gate. A later
stream cannot claim completion while an earlier dependency is only a stub.

```text
W0 baseline/release lock
  -> W1 run journal and checkpoints
  -> W2 knowledge/context release
  -> W3 reference analysis and style admission
  -> W4 direction resolver and presets
  -> W5 motion/assets adapters
  -> W6 pilot/render integration
  -> W7 viewer/editorial QA and review packet
  -> W8 delivery/cache/stale-evidence binding
  -> W9 feedback and future release lifecycle
```

W2 and W3 may be developed in parallel after W0, but W4 cannot select
knowledge that has not been released, W5 cannot select unverified assets, and
W6 cannot render a plan that has not passed the W4/W5 gates.

## 5. Workstream W0: baseline, release, and change isolation

### Purpose

Make the starting point reviewable before changing contracts or behavior.

### Implementation steps

1. Record branch, HEAD, actual `origin/main`, remotes, dirty paths, open PRs,
   and the exact merge baseline.
2. Classify every dirty file as pre-existing, part of this upgrade, or
   unrelated. Never stage or reset the whole working tree.
3. Create a round branch from the real baseline using the repository's
   `round-XX-*` convention.
4. Create a local release record containing code SHA, schema registry hash,
   renderer package lock hash, policy/config fingerprints, and enabled
   capabilities.
5. Add a `release verify` read-only command that checks the same facts later.
6. Write a change map before editing: contracts, writers, readers, render
   adapters, cache keys, QA readers, review readers, and delivery readers.

### Exit gate

The release record verifies from a clean process, the change map lists every
affected call path, and no old artifact is reinterpreted under new defaults.

## 6. Workstream W1: durable run controller and checkpoints

This is the part inspired by the Drive workflow's strongest operational
behavior: bounded stages, explicit progress, readback, and safe recovery.

### Contract additions

Add versioned typed records, preferably as append-only JSON sidecars under the
existing work root unless a SQLite migration is proved necessary:

- `ProductionRunRequest`: project/campaign/source/candidate ids, selected
  profile, requested stage set, operator, policy and release fingerprints;
- `ProductionRun`: immutable request hash, current status, stage sequence,
  start/end, parent run, and failure reason;
- `RunStageReceipt`: stage id, input/dependency hashes, status, attempt,
  output artifact ids, elapsed time, and error details;
- `RunCheckpoint`: last verified stage, per-unit receipts, manifests, and
  checkpoint hash;
- `RunRecoveryDecision`: why a stage is reusable, stale, retryable, or blocked;
- `ReleasePointer`: current code/config/knowledge release and activation time.

Statuses are derived from receipts. A directory containing a file is not a
success state. Use a closed set such as `planned`, `running`, `blocked`,
`failed`, `cancelled`, `succeeded`, `stale`, and `needs_review`.

### Controller rules

- one controller call owns one bounded stage;
- each stage validates its inputs before starting and writes its receipt only
  after output facts and hashes are verified;
- progress is written after every candidate/chunk/unit;
- checkpoint writes are atomic and followed by readback verification;
- `resume` reuses only receipts whose source, plan, renderer, policy, release,
  font, asset, and dependency hashes still match;
- a failed stage never promotes partial output or overwrites a prior good
  package;
- `retry` creates a new attempt and preserves the failed attempt;
- cancellation is explicit and resumable only through validated recovery;
- stale evidence blocks downstream stages rather than being auto-repaired.

### Required commands

Follow current CLI conventions:

```text
clipforge run plan
clipforge run start RUN_ID
clipforge run status RUN_ID
clipforge run show RUN_ID
clipforge run verify RUN_ID
clipforge run resume RUN_ID
clipforge run cancel RUN_ID
clipforge run recover RUN_ID
```

Read-only commands must not change bytes, rows, receipts, or timestamps.

### Exit gate

An injected failure at each stage boundary leaves the previous package intact;
resume reruns only missing/stale work and reaches the same final hashes as a
clean run. A status command can prove exactly where a crash stopped.

## 7. Workstream W2: knowledge library, releases, and context

### Purpose

Turn skills, reviewed repositories, campaign rules, and authorized reference
videos into evidence-backed direction instead of a flat prompt folder.

### Data flow

```text
source/skill/reference registration
  -> observations and guidance cards
  -> conflicts and evaluation cases
  -> admitted knowledge release
  -> bounded DirectionContextBundle
  -> Codex decision trace
```

### Required behavior

1. Each source records exact URL/repository, commit or file hash, path,
   license, attribution, permission for analysis/reuse, and allowed use.
2. Each observation distinguishes observed fact, inference, heuristic, and
   unknown. Unknown does not become a default.
3. Each guidance card includes intent, applicability, method, parameters,
   coordination rules, avoid-when cases, tool ids, evidence, evaluations, and
   revision history.
4. Each style card coordinates story, captions, motion, B-roll, audio, and
   ending. A font or transition by itself is not a style card.
5. Each release pins exact record revisions and a manifest hash. Old releases
   remain immutable.
6. Context retrieval is deterministic and bounded. It returns selected cards,
   excluded cards, conflicts, unknowns, missing capabilities, and hashes.
7. Decision traces record selected and rejected guidance, source evidence,
   deviations, and the exact direction plan that consumed them.

### Conflict and scope rules

Campaign rules outrank generic references. A reference may be study-only even
when reuse permission is absent. Performance claims require actual analytics
records; popularity alone is not causal evidence.

### Exit gate

A newly admitted reference is retrieved for a suitable candidate and rejected
for an unsuitable one. A changed source, card, or release makes the context
stale and blocks a render that still points at the old hash.

## 8. Workstream W3: reference analysis and style-card admission

### Purpose

Make the system learn from approved videos without copying footage or treating
one viral example as universal truth.

### Analysis stages

1. register the authorized local file and permission scope;
2. hash and probe it under the work root;
3. extract transcript, alignment if available, shot candidates, adaptive frame
   samples, cut windows, waveform, loudness, caption observations, and contact
   sheets using existing deterministic tools;
4. inspect complete context when playback is available;
5. record hook, body, payoff, CTA, visual changes, framing, caption behavior,
   B-roll purpose, motion intensity, transitions, silence, and SFX as observed
   facts with timestamps;
6. mark OCR, language, stem, speaker, and causal performance facts unknown when
   the evidence is unavailable;
7. propose reusable patterns with applicability and counterexamples;
8. run a production pilot for any visual/motion recipe;
9. admit only the approved pattern/style revision into a new knowledge release.

### Required analysis record

`ReferenceAnalysis` must include source hash, permission, probe facts, analysis
version, extraction evidence, observations, unknowns, confidence, and links to
frame/audio/transcript evidence. It must never contain copied campaign footage
as a new production asset.

### Exit gate

At least one reference analysis can explain an observed edit with evidence and
produce a style-card proposal that passes a suitable and unsuitable evaluation
case. The system states which proof was unavailable.

## 9. Workstream W4: direction resolver and editorial presets

### Canonical plan

Extend the existing `EditorialDirectionPlan`/`DirectionDocument` rather than
creating another plan format. It must carry:

- campaign/source/candidate/transcript/alignment/profile ids;
- active policy and knowledge release/context hashes;
- hook, body, payoff, CTA and their source spans;
- energy curve and beat grid;
- ordered scene specs;
- crop/reframe strategy;
- caption style and locale rules;
- B-roll roles and exact intervals;
- motion recipes and bounded parameters;
- SFX/audio cues and mix policy;
- rejected alternatives and decision rationale;
- all source, asset, font, recipe, and plan hashes.

### Initial presets

Implement data-driven presets, not renderer conditionals:

- `clean_explainer`: question, explanation, takeaway;
- `proof_comparison`: claim, comparable proof, conclusion;
- `story_reveal`: related flash-forward, setup, reveal;
- `transformation`: problem, steps, visible result;
- `quote_emotion`: exact quote, context, emotional close;
- `product_cta`: problem, demonstration, benefit, action.

Each preset defines allowed hook/body/payoff combinations, pace bounds,
caption rules, motion families, B-roll roles, SFX limits, CTA hold, prohibited
combinations, and evaluation cases.

### Resolver algorithm

1. bind campaign policy and evidence;
2. reject unsupported locale/profile/capability choices;
3. generate source-grounded hook/body/payoff alternatives;
4. apply the priority resolver;
5. select a coordinated style card and compatible recipe family;
6. validate scene continuity and source-span ownership;
7. record rejected alternatives and unresolved questions;
8. emit the typed plan and decision trace.

The resolver must refuse an attractive hook that is unrelated to the body, a
chart without comparable facts, a B-roll item without semantic relevance, a
caption style that cannot shape the locale, or an SFX cue that competes with
speech.

### Exit gate

The same candidate can produce at least three materially different valid
plans, each with explicit rationale, while an unrelated hook and unsupported
effect are rejected before rendering.

## 10. Workstream W5: motion and asset adapters

### 10.1 Motion catalog

Prompt Motion, iart packs, Concat, Shotcraft, and similar sources are treated as
catalog/reference inputs. A ready-made component may be reused when its exact
file license, dependency licenses, runtime compatibility, deterministic clock,
and safe props are verified. Otherwise the behavior is reimplemented locally.

Every recipe records:

- source commit/path/hash and license/attribution;
- implementation/component id and version;
- purpose and compatible scene types;
- bounded parameters and duration range;
- caption/RTL/safe-area compatibility;
- attention cost and readability risk;
- fallback component;
- tests and local modifications.

The renderer receives recipe ids and typed parameters. It never receives
arbitrary code, HTML, URLs, or shell commands.

Initial implementation target is 20–30 restrained Remotion techniques, but a
recipe counts only after a production-composition render and decoded-frame
test, not after a catalog entry.

### 10.2 Openverse and other asset providers

Search is optional discovery. Selection is not clearance. Acquisition must:

1. revalidate response and landing-page/license evidence;
2. apply campaign policy and asset-license rules;
3. stage inside the work root with byte limits;
4. reject symlinks/traversal/outside paths;
5. hash, probe, decode, and verify media type;
6. create the existing `AssetLicenseRecord` with evidence URI;
7. atomically promote the asset and manifest;
8. preserve previous package bytes if promotion fails.

Use the same boundary for Envato, campaign assets, fonts, SFX, and future
providers. No provider creates an implicit allow. Music remains prohibited when
campaign policy says so.

### Exit gate

An approved motion recipe and an independently cleared asset both complete the
same typed plan path. A missing license, stale response, changed bytes, or
unsupported recipe blocks planning before a render job is inserted.

## 11. Workstream W6: pilot and production render integration

### Render sequence

1. verify current release, policy, source, TimeMap, context, decision trace,
   plan, fonts, motion recipes, and assets;
2. run direction lint;
3. render the highest-risk/pilot scene through the real Remotion composition;
4. decode pilot frames and inspect geometry, captions, motion, face clearance,
   and audio cue timing;
5. only if the pilot passes, authorize the full Hero/Advanced Hero render;
6. render browser chunks plus one continuous audio path under the existing
   resumable checkpoint mechanism;
7. atomically assemble and verify the exact artifact;
8. write viewer-evidence and QA inputs bound to its hash.

Hero and Advanced Hero consume the same canonical plan and TimeMap. The
renderer is an executor: it cannot change story order, caption timing, crop
policy, or asset choice to make an invalid plan render.

### Synchronization requirements

- picture and speech are staged from the same ordered TimeMap;
- cuts occur on validated word/phrase boundaries or are explicitly marked;
- each caption cue has a half-open interval and first/last-frame test;
- B-roll and SFX have output intervals plus source in-points;
- narration and source dialogue obey the declared mix/ducking policy;
- render duration and zero-start checks run before browser work.

### Exit gate

The pilot and complete output use the same input hashes, resume after an
intentional interruption, and decode to the expected duration, frame rate,
safe geometry, caption coverage, and audio duration.

## 12. Workstream W7: viewer-quality QA and review packet

QA has four levels and may not collapse them into one green boolean.

### Level 1: technical

Decode, dimensions, frame rate, duration, codec, color/pixel facts, black or
frozen frames, audio stream, loudness, true peak, silence, and artifact hashes.

### Level 2: editorial mechanics

Word/cut boundaries, duplicate speech, caption coverage, punctuation, locale
shaping, safe areas, B-roll intervals, transition overlap, CTA hold, and source
range repetition.

### Level 3: semantic/viewer quality

Hook/body relation, story continuity, meaningful visual change, relevant B-roll,
purposeful motion, subject/face clearance, caption readability, SFX balance,
payoff clarity, and clean ending.

### Level 4: human playback

The exact MP4 is watched with audio and muted playback. The reviewer records
the artifact hash, device/player, observations, defects, and decision. No
metadata-only pass can satisfy this level.

The review packet contains contact sheets, cue-edge frames, waveform/loudness,
transcript and source spans, direction lint, selected/rejected decisions, asset
rights, and the final MP4 hash.

### Exit gate

Technical success cannot mask viewer-quality failure. Missing or stale evidence
is `INSUFFICIENT_EVIDENCE`; it is not a pass.

## 13. Workstream W8: cache, stale evidence, review, and delivery binding

Every output-changing dependency becomes part of the identity:

- source and source-media hash;
- transcript, alignment, TimeMap, candidate and arc hashes;
- campaign policy and profile;
- knowledge release/context/decision trace;
- direction plan and preset;
- motion recipe/component/dependency;
- font files and font config;
- asset and license evidence;
- audio/mix/narration policy;
- renderer and schema versions.

Change any one and the render must miss cache and invalidate affected QA,
effective final approval, and delivery reuse. Old artifacts remain verifiable
under their recorded recipe.

Delivery requires:

1. current release and source/policy identity;
2. verified render and all dependency receipts;
3. current technical and viewer QA;
4. effective human final playback approval for the exact artifact;
5. rights/compliance pass;
6. package manifest with relative paths, hashes, attribution, and required
   campaign copy;
7. atomic promotion preserving the previous package on failure.

## 14. Workstream W9: feedback and future learning

Feedback is append-only and tied to the exact artifact, plan, scene, cue,
reviewer role, and evidence. It may propose:

- a card revision;
- a new style variant;
- a motion recipe change;
- a caption/font change;
- an audio rule;
- a campaign exception;
- a rejected pattern.

Feedback never edits a past release or silently changes a preset. A proposed
revision becomes active only after the relevant evaluation cases and provenance
checks pass and a new knowledge release is published.

## 15. Schema and migration policy

1. Extend existing contracts instead of creating parallel direction, asset,
   review, or QA documents.
2. Every new document carries `schema_version` and a stable id/content hash.
3. Add readers for older documents or fail explicitly with a migration command;
   never silently rewrite old JSON.
4. Regenerate `schemas/generated/` and run `clipforge schema check` for every
   contract change.
5. Use a numbered SQLite migration only when append-only sidecars cannot
   represent the required query or atomicity. Test old files and rollback.
6. Keep legacy Hero/Advanced Hero behavior unchanged when no new context or
   direction plan is supplied.
7. Do not add a second time representation, cache store, provider boundary, or
   approval database.

## 16. Testing and evidence matrix

### Contract and resolver tests

- schema generation and old-document compatibility;
- missing parent, wrong hash, unknown key, stale context, and conflict;
- priority resolver and rejected alternatives;
- all six presets and three materially different plans;
- unsupported locale/profile/capability rejection;
- source-grounded hook/body/payoff continuity;
- exact TimeMap and frame-boundary behavior.

### Motion and asset tests

- approved recipe renders deterministically twice;
- missing component, bad parameter, unsafe URL/code, and fallback;
- font hash/change invalidation;
- Openverse/provider timeout, 429, malformed response, unknown license,
  missing landing evidence, changed bytes, corrupt media, symlink/traversal,
  failed promotion, and cache revalidation;
- no music when campaign policy prohibits it;
- every used asset has a persisted cleared license record.

### Run/recovery tests

- crash at every stage boundary;
- checkpoint readback and byte stability;
- resume reuses only valid receipts;
- changed source/plan/release invalidates reuse;
- failed promotion leaves previous package intact;
- read-only status/show/verify do not mutate state;
- no orphan browser, Node, ffmpeg, or test process.

### Production proof

Using authorized local media, render at least:

- one Hero and one Advanced Hero;
- no narration and narration/ducking when policy permits;
- B-roll and SFX with relevance and rights;
- one motion-heavy and one restrained preset;
- English plus each currently supported non-English layout;
- a real interrupted/resumed run.

Decode representative frames at hook, every cue boundary, motion entrance,
motion midpoint/exit, B-roll start/end, payoff, CTA, and final frame. Inspect
the complete clips with audio and muted playback. OCR is supplemental; missing
language packs must be reported, never converted into an exact-text pass.

## 17. Operational workflow for a new AI operator

The operator skill and README should direct a new agent through this exact
sequence:

1. inspect current release, branch, dirty state, campaign checkpoint, and
   capability doctor;
2. read campaign policy and hard gates;
3. register/verify source, rights, transcript, alignment, and TimeMap;
4. load the relevant knowledge release and build a context bundle;
5. inspect the source and authorized references; never choose from filenames;
6. create a decision trace with hook/body/payoff, preset, crop, captions,
   B-roll, motion, audio, and CTA choices;
7. validate the typed plan and run direction lint;
8. resolve and verify every asset/font/motion dependency;
9. render and inspect the pilot;
10. start or resume the full production run;
11. run technical, mechanics, semantic, and playback QA;
12. record human final review for the exact artifact;
13. package and verify local delivery;
14. append feedback and propose, but do not silently activate, knowledge
    changes.

The skill must say what the system can do and the exact command for each step.
It must also list unavailable capabilities and the evidence required before an
operator can claim them.

## 18. Delivery sequence and commit boundaries

Implement in these reviewable boundaries, each on the same round branch or a
new dependent round as the repository policy requires:

1. **Control/release boundary:** W0 and W1 contracts, commands, checkpoint
   recovery, and failure tests.
2. **Knowledge boundary:** W2 release/context/trace completion and stale/hash
   propagation.
3. **Reference boundary:** W3 extraction, inspection records, style admission,
   and evaluation cases.
4. **Direction boundary:** W4 resolver, presets, lint, and decision traces.
5. **Execution boundary:** W5 motion/provider acquisition and rights binding.
6. **Render boundary:** W6 pilot/full production integration and real output
   proof.
7. **Review boundary:** W7 viewer-quality QA, playback, and review payload.
8. **Delivery boundary:** W8 cache/stale/package binding and rollback.
9. **Learning boundary:** W9 feedback, release promotion, and documentation.

Each boundary must pass targeted tests and documentation checks before the next
one begins. Do not hide all changes in one large commit or report the entire
plan complete after only the foundation boundary.

## 19. Completion criteria

The upgrade is ready for independent code and visual review only when:

- one current release and one run journal can explain the state of a complete
  production attempt;
- Codex can make a source-grounded decision using a versioned context bundle;
- the system executes only the validated typed plan;
- ready-made motion can be reused when its exact code/dependencies/licenses
  pass, while unsafe or incompatible material is rejected;
- external discovery providers are optional, bounded, rights-bound, and offline
  after acquisition;
- a crash can resume without repeating valid work or corrupting a prior package;
- all output-changing dependencies invalidate stale QA, review, cache, and
  delivery reuse;
- direction lint and four-level QA catch the previously observed sync, crop,
  caption, unrelated-B-roll, CTA, SFX, and weak-arc failures;
- a real Hero and Advanced Hero output has been decoded, watched, and reviewed;
- old artifacts and approvals remain immutable and verifiable;
- validation, schema, renderer, browser, security, and read-only mutation tests
  pass on the exact reported HEAD;
- remaining limitations are explicitly classified as external or blocked,
  rather than described as solved.

## 20. Non-goals

This plan does not authorize:

- automatic publishing or external account contact;
- a second renderer, cloud worker, database, or autonomous agent runtime;
- silent campaign-rule changes;
- unlicensed stock, fonts, SFX, or reference footage;
- “viral” scoring without campaign-specific evidence;
- treating an installed skill or Drive document as executable authority;
- declaring visual quality complete from CI alone.

