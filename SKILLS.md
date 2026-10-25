# Clipforge skills and capability routing

This file is the entry point for a new agent operating Clipforge. Read it
after `AGENTS.md`, `ARCHITECTURE.md`, the applicable ADRs, the campaign policy,
and the campaign checkpoint. Read the relevant skill before making an
editorial plan.

The main operator workflow is
`.codex/skills/clipforge-production-operator/SKILL.md`. Use
`.codex/skills/clipforge-motion-direction/SKILL.md` when selecting the visual
direction and its campaign references.

The planned extension is documented in the
[Editorial Direction Engine integration plan](docs/operations/editorial-direction-engine-integration-plan.md)
and its mandatory
[editorial knowledge-layer specification](docs/operations/editorial-knowledge-layer-plan.md).
The dependency-ordered implementation, release/checkpoint model, migration
rules, and completion gates are consolidated in the
[editorial system upgrade plan](docs/operations/editorial-system-upgrade-plan.md).
It defines how reviewed repository instructions and future authorized
reference videos become scoped guidance cards, narrative/style patterns,
evaluations, and versioned context for Codex. These documents are plans;
their proposed knowledge and provider commands are not current capabilities.

The current knowledge, motion, direction, and treatment commands are available
through the editorial doctor command, editorial knowledge list/context commands,
editorial motion list --approved-only, and the read-only `editorial direction
compare` command. For every new treatment-aware direction, inspect
`editorial treatment plan`, `editorial treatment show`, and
`editorial treatment lint` before planning Advanced Hero. Use the resulting
context bundle as an input to the direction command.
Production motion recipe ids are checked against both the Python catalog and
the renderer registry; plans naming recipes carry the catalog fingerprint.
The bundle records source facts, unknowns, selected guidance, rejected
alternatives, style cards, and motion-catalog fingerprints. Camera moves and
transitions are typed direction choices; they are not renderer defaults.
A clean Advanced plan also emits a hash-bound pilot receipt. Run
`clipforge hero advanced pilot SOURCE CANDIDATE` before `advanced render`; a
stale or missing receipt blocks encoding. Narrative presets are listed with
`clipforge editorial presets` and their recipe routes remain rights- and
catalog-bound.
A new reference video or repository pack enters through the knowledge
intake/evaluation workflow in the knowledge-layer plan; saving a file under
references does not make it active.
The shipped lifecycle is `editorial knowledge intake` → `evaluate` → `admit`;
admission creates a new release and retires the previous one without creating
an artifact approval.

Campaign execution is resumable through the system checkpoint controller. Run
`clipforge campaign checkpoint verify CHECKPOINT_ID` before relying on a prior
stage, and use `campaign resume` only when the normal evidence checks still
match. A checkpoint records progress; it cannot approve or deliver an artifact.

## Responsibility model

- **Codex operator:** decides what the short should say and show. It selects
  source moments, hook/body/punch structure, caption corrections, framing,
  graphics, B-roll, SFX, and an allowlisted style. It invokes the tools below.
- **Clipforge system:** executes typed plans and enforces rights, provenance,
  TimeMap synchronization, safe geometry, cache identity, stale evidence, QA,
  and delivery gates. It does not invent editorial choices.
- **Human reviewer:** watches the exact final MP4 with audio and muted playback
  and records final approval or rejection. Codex cannot create this approval.

The role policy is persisted in campaign and Advanced Hero documents. Candidate
and Hero editorial decisions may be recorded with `--reviewer-role
codex_operator`; final review always requires `human_reviewer`.

Temporary production default: omit `motion_graphics` from new direction briefs
and render inputs. The renderer must not add a graphic implicitly. A future
motion-graphics pass requires an explicit operator request and a campaign-policy
check; previously rendered artifacts remain immutable.

## Capability routing

| Codex decision | System tool or contract | Output |
|---|---|---|
| Inspect source, duration, streams, scenes, faces | `source inspect`, `media prepare`, visual analysis, ffprobe | Source and visual evidence |
| Extract speech and subtitles | transcript service, `hero align`, `clipforge.campaign.speech` | Forced alignment and typed speech inventory |
| Find candidate moments | `candidate mine` | Candidate set with transcript and visual evidence |
| Choose an editorial direction | `clipforge-motion-direction` skill, `editorial direction compare`, and `direction plan` | Declarative `DirectionDocument` with camera and transition choices |
| Decide treatment per beat | `editorial treatment plan/show/lint` after direction selection | Hash-bound use, omission, policy-block, or review decision for B-roll, SFX, camera, transitions, and graphics |
| Bind a cleared treatment asset | Existing provider search/acquire/register tools, then `editorial treatment bind-asset` | Request-bound placement with provider, selection, license, acquisition, and asset hashes |
| Choose hook/body/punch cuts | typed `EditorialArcDocument` and `advanced plan --editorial-arc-file` | Ordered TimeMap and arc evidence |
| Frame faces and important source content | `advanced plan --reframing` and typed crop windows | Hash-bound portrait transform |
| Add captions | shared caption builders and Remotion `CaptionPlate` | Word-timed caption events |
| Add B-roll, images, fonts, or SFX | asset registration, license records, typed direction placements | Rights-cleared asset bindings |
| Add illustrations and motion graphics | **Disabled by default**; only an explicit operator request may select an allowlisted Remotion event after policy review | Source-grounded graphics |
| Add camera movement and transitions | typed `camera_motion` and `transitions` in the selected direction option | Bounded output-space camera events and word-safe transition events |
| Encode and resume | `hero advanced render`, `--resume` | Checkpointed MP4 and manifest |
| Prove the result | `qa run`, decoded viewer evidence, ffprobe/ebur128 | Technical and viewer evidence |
| Request final approval | `final review watch-target`, `final review decide` | Human playback review and final decision |
| Deliver locally | `publish export` | Verified local package only |

Skills and external adapters are advisory input producers. They must return
typed declarative data, cite source evidence, preserve the campaign policy, and
leave executable code out of plans. MCP belongs only at an approved external
service boundary. A new repository or asset pack belongs under the asset or
motion-library boundary with license and provenance records. A new skill
belongs under `.codex/skills/` with a pinned provenance note when it imports
third-party guidance.

## Editorial direction presets

Choose one after reading the source and policy. Omission is valid when the
source does not support a treatment.

- `editorial-clean-v1`: restrained phrase captions, clear subject, minimal
  motion, and clean cuts.
- `quran-readable-v2`: large centered readable Quran/dialogue captions with
  forced-word active coloring and a reviewed upper context line.
- `kinetic-caption-v1`: bounded phrase movement and active-word emphasis when
  shaping and timing support it.
- `documentary-broll-v1`: relevant source-bound or licensed B-roll that
  explains the spoken phrase, never decorative filler.
- `data-explainer-v1`: proportional diagrams only when exact source facts,
  units, labels, and provenance exist.
- `paper-explainer-v1`: restrained card-like explanation for a source-grounded
  concept, with no invented claim.
- `premium-minimal-v1`: quiet typography and deliberate pacing when the source
  already carries the visual interest.

Do not force a hook, chart, zoom, transition, B-roll, SFX, or headline onto a
clip. The source meaning and campaign policy decide which preset is eligible.

## Required operator sequence

1. Read the campaign rules, rights, checkpoint, source metadata, transcript,
   visual analysis, existing artifacts, and relevant skill.
2. Inspect source audio and picture. Do not trust raw ASR or old captions
   blindly; retain observed text and source hashes.
3. Build the candidate and forced alignment, then choose a coherent
   hook/body/punch arc with speech-safe boundaries.
4. Choose a preset and typed direction. Register every supporting asset and
   verify its license and source relevance.
5. Plan the crop, captions, graphics, B-roll, SFX, and overlays in output
   coordinates. Run the deterministic Advanced Hero service.
6. Decode frames and audio, inspect cue edges, cuts, platform crops, loudness,
   and the complete story. Fix the plan or renderer when evidence fails.
7. Run QA and stale/cache verification. Generate the exact human playback
   target. Stop for human final review before delivery.
