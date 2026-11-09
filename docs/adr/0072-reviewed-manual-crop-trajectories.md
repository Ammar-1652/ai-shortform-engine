# ADR 0072: Reviewed manual crop trajectories

## Status

Accepted for new Advanced Hero plans.

## Context

A single fixed portrait crop can fill the canvas but lose a speaker who moves
between camera framings inside one selected source interval. Automatic
face-follow remains fail-closed when detection coverage or continuity is not
adequate. Reverting silently to contain would preserve the subject but violate
the explicitly requested fill strategy and could reintroduce bars.

## Decision

1. `manual_window` may contain either the legacy singular crop or an ordered
   list of typed `ReframingWindow` records. The list must be gap-free,
   non-overlapping, frame-bound, in-bounds, 9:16, and cover the entire output
   duration in canonical integer microseconds.
2. The complete list participates in profile, plan, render, and downstream
   evidence fingerprints. An empty additive list is omitted from legacy profile
   digest calculation so old artifacts remain verifiable.
3. Remotion interpolates only the stored crop coordinates between validated
   windows using output frame time. It never detects a face at render time and
   never interprets a face as a speaker. Per-frame face-follow trajectories
   retain their existing behavior.
4. The operator file is parsed into the existing typed `ReframingWindow`
   contract; malformed or unsafe geometry fails before planning/rendering.
   Fixed-focus CLI usage remains supported.

## Consequences

Operators can keep a speaker framed across source camera changes without
inventing a second timebase or modifying the selected audio/TimeMap. Crop
keyframe quality remains an editorial judgment and requires decoded-frame
review. Existing one-window plans and their provenance remain immutable.
