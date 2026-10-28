# ADR 0103: Motion catalog and Openverse discovery boundary

**Status:** accepted for staged implementation

## Context

Reviewed motion repositories contain useful recipes and sometimes usable
components. Open-source status does not clear bundled fonts, media, or
dependencies, and Openverse metadata is not independent license proof.
Clipforge must be able to use compatible ready-made components while retaining
Remotion, TimeMap, rights, and cache guarantees.

## Decision

Maintain a local, pinned motion catalog. Each recipe records its source,
permission, license, component id, fallback, purpose, duration, language/profile
compatibility, parameter bounds, readability risk, and recipe hash. Only
approved recipes whose component ids are in the local Remotion registry may
enter a direction context. Compatible ready-made components may be used
directly after per-file license and deterministic-render checks. A repository
license does not automatically clear its fonts, media, or dependencies.

Openverse is an optional, bounded discovery provider. Search is disabled by
default, never scrapes, never downloads all results, and never treats a result
license field as final clearance. Normalized records keep landing URL, direct
URL, license metadata, attribution, response hash, and provider facts.
Selection remains pending until independent evidence is supplied; unknown,
non-commercial, no-derivatives, share-alike-without-policy, missing, or
conflicting rights are blocked. Acquisition must enter through the existing
asset license and confinement path in a later implementation stage.

## Consequences

* Motion guidance and compatible ready-made code can influence real direction
  plans without adding a second editor.
* The renderer remains deterministic and offline-capable after approved assets
  are present.
* Openverse live access is opt-in and not required by CI.
* Selection and discovery do not authorize a render; a future acquisition stage
  must hash, probe, decode, license, and atomically promote bytes.
