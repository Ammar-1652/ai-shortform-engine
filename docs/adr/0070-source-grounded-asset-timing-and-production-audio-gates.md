# ADR 0070: Source-grounded asset timing and production audio gates

## Status

Accepted for the next Advanced Hero production artifacts.

## Context

Decoded review outputs exposed two unsafe defaults. The Advanced Hero builder
placed every supplied B-roll file in evenly spaced slots and every SFX file at
200 ms plus 100 ms per item. Clean renders also derived hook/punch cards from
word-position heuristics when no direction brief existed. Those paths produced
unrelated Envato inserts, annoying sound effects, duplicate or missing text,
and clips whose visual structure was not tied to the source. One manually
assembled output measured -33.9 LUFS because loudness was not a delivery gate.

The canonical TimeMap and forced alignment already provide the clocks needed to
make these decisions safely. The missing contract was the reviewed relation
between an asset, a source phrase/scene, and an output interval.

## Decision

1. Clean production Advanced Hero renders require a persisted, source-grounded
   direction document. The legacy recipe remains available only when explicitly
   selected for compatibility and A/B comparison. Clean production never
   invents hook/body/punch text from word positions or character classes.
2. A selected direction may contain `DirectionAssetPlacement` records. Each
   placement names the local asset, kind, integer-microsecond output interval,
   asset in-point, source evidence ids, motion purpose, and a relevance note.
   The selected option's placements are the only production B-roll/SFX timing
   authority. The builder rejects a mismatch between supplied ids and those
   placements.
3. Old plans remain readable. Their legacy evenly-spaced events are marked with
   an explicit `legacy_auto_spacing` note and empty evidence; the Remotion
   production gate and technical QA reject them for a clean render instead of
   silently presenting them as reviewed work.
4. Production audio is measured with ffmpeg `ebur128=peak=true` after the
   deterministic loudnorm pass. Integrated loudness must be within 1.5 LU of
   the profile target (-16 LUFS by default), true peak must not exceed the
   profile limit (-1.5 dBFS by default), and near-silent output fails.
5. Existing `stage_time_map` remains the only picture/speech staging path. It
   trims both streams from the identical ordered source ranges and validates
   their duration and zero start before Remotion receives them.

## Consequences

An operator must review direction and relevance before a clean render. A
direction can intentionally omit B-roll/SFX; restraint is valid. Existing
legacy artifacts are immutable and verifiable, but they cannot receive a new
clean approval or delivery. Direction, placement, style, font, audio policy,
and plan hashes remain part of cache and stale-evidence checks.
