# ADR 0069: Source-grounded motion direction presets

## Status

Accepted for implementation on `feature/motion-craft-production-quality`.

## Context

Advanced Hero needs repeatable editorial presentation without allowing an
operator or model to inject arbitrary Remotion code. A style suggestion that is
not bound to the promoted candidate, forced alignment, and canonical TimeMap
can produce attractive but false captions, duplicated beats, or stale approved
packages.

## Decision

Add a typed `DirectionDocument` between the approved Hero candidate and the
Advanced Hero plan. A direction contains exactly three source-grounded
hook/body/punch alternatives, evidence ids and copied source text, a
deterministically selected option, and one of seven pinned production styles:

`editorial-clean-v1`, `kinetic-caption-v1`, `documentary-broll-v1`,
`data-explainer-v1`, `paper-explainer-v1`, and `premium-minimal-v1`.

The project-local motion-direction skill creates declarative JSON only. The
`clipforge hero advanced direction plan` command validates its source, Hero
plan, and TimeMap hashes, binds the selected style fingerprint, and stores an
immutable direction artifact. Advanced Hero planning reads that artifact; the
render input carries its id/hash, safe-region id, and strict numeric style
contract. Any changed direction, style, font dependency, source, alignment,
TimeMap, rights evidence, or plan invalidates downstream render/cache/review
evidence through the existing hashes and stale checks.

Remotion remains the sole renderer. It accepts only the seven style ids (plus
legacy compatibility for old artifacts), derives animation from
`useCurrentFrame`, and never receives JavaScript, JSX, CSS, HTML, or shell code
from an operator. The universal `portrait-safe-v1` region remains the sole
platform rectangle. Direction does not change candidate selection or invent
copy; an option can omit optional graphics and B-roll.

## Consequences

The operator must create and validate a brief before a newly directed
Advanced Hero plan. Existing plans without a direction remain readable and
retain their recorded legacy/clean behavior. Direction artifacts are not
approvals: human Hero and final-review decisions remain append-only and are
required for delivery.
