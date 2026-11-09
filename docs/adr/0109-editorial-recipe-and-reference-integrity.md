# ADR 0109: Hash-bound editorial recipe and reference execution

**Status:** Accepted  
**Date:** 2026-10-25

## Decision

Editorial direction may name only recipes from the local motion catalog. The
catalog persists a digest for every recipe and a captured digest for every
local renderer reference. The loader verifies both before a direction can be
planned or rendered. The renderer has a second allowlist registry and requires
the catalog fingerprint whenever a production plan names a recipe.

Reference-video analyses use the captured source digest and evidence files.
Loading an analysis verifies that the authorized source and evidence still
exist under the work root and that their bytes have not changed. Proposed style
cards store the analysis id and digest, so changing an analysis cannot silently
keep an old style decision active.

Camera and transition choices are remapped through the editorial TimeMap for
recuts. The Advanced plan, render input, viewer evidence, QA, and final review
refer to the same effective events and recipe fingerprint.

Clean Advanced plans also publish a pilot preflight receipt containing the
plan, direction, event, and dependency hashes. Browser encoding and viewer QA
require that receipt to remain current. Narrative presets are separate typed
catalog records whose recipe routes are checked against the same motion catalog.

Legacy direction-v1 and Hero artifacts remain readable. New direction-v2
production records carry the catalog fingerprint and fail closed when it is
stale.

