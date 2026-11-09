# ADR 0111: per-beat editorial treatment orchestration

## Status

Accepted for implementation on 2026-10-25.

## Context

Advanced Hero already had typed support for B-roll, SFX, camera movement,
zooms, and transitions. A direction could still omit those layers without
recording whether the omission was a creative choice, a campaign prohibition,
or an unresolved asset decision. Preset prose did not provide a deterministic
route from a narrative beat to an asset request or a bounded treatment. The
renderer therefore had to preserve a clean edit, while Codex had no durable
contract proving why a generic edit received or omitted a treatment.

Campaign rules also differ. A generic campaign may permit relevant Envato or
Openverse editing assets, while Tarteel prohibits outside footage and added
SFX. One default cannot safely serve both cases.

## Decision

Add a treatment-aware `direction-v3` document. Each hook/body/punch beat has
one typed decision for B-roll, camera, transition, SFX, and motion graphics.
Each layer is explicitly `use`, `omit_with_reason`, `blocked_by_policy`, or
`needs_review`. `TreatmentAssetRequest` records a bounded provider query when
the selected preset prefers a cleared asset. Existing Envato/Openverse/local
asset boundaries remain responsible for discovery, license evidence,
acquisition, hashing, probing, and registration.

The deterministic treatment planner:

- derives beat intervals from forced words and the canonical output clock;
- adds bounded hook/payoff camera moves when the preset and source interval
  support them;
- adds sparse transition candidates only at discontinuous TimeMap cuts that
  start a reviewed beat;
- creates provider requests for relevant B-roll and speech-safe SFX when a
  generic preset prefers them;
- records an explicit omission when an asset is unnecessary or unavailable;
- records a policy block for restricted campaigns;
- keeps motion graphics blocked by the temporary production policy;
- hashes decisions, event references, and requests into the direction and
  Advanced Hero plan/render-input cache identity.

Remotion remains an executor of validated events. It does not search providers,
choose assets, or add a transition when a treatment-aware direction explicitly
omits one. Historical direction-v1/v2 documents retain their stored behavior
and remain immutable. New v3 plans use clean cuts when no transition decision
is selected.

## Consequences

- Codex must make a visible editorial decision for each meaningful beat.
- Generic campaigns can use the existing provider and rights pipeline for
  relevant B-roll and SFX without adding a second editor or network dependency
  to Remotion.
- A missing or uncleared preferred asset appears as `needs_review` and blocks
  clean planning until Codex selects a cleared asset or records a valid clean
  fallback through the compatibility path.
- Tarteel proves its no-outside-media/no-added-SFX rules through explicit
  policy-block decisions rather than silently inheriting generic defaults.
- Camera movement and transitions remain bounded by safe regions, complete
  words, TimeMap boundaries, and preset density limits.
- Changing a treatment, provider request, asset, license, camera/transition
  event, or audio policy changes the direction/treatment fingerprint and makes
  downstream plan, QA, approval, cache, and delivery evidence stale.
- Human playback remains the final viewer-quality decision; treatment lint and
  technical QA do not claim editorial acceptance.
