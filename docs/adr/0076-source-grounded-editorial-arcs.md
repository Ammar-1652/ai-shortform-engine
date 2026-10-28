# ADR 0076: Source-grounded editorial arcs

## Status

Accepted for the next Advanced Hero cut-planning step.

## Context

Candidate mining intentionally creates one cheap contiguous source window. That
was sufficient for rough review but left no typed production input for a Hero
editor to combine separate source moments. Handwritten recuts then risked a
second clock, duplicated footage, or captions detached from speech.

## Decision

Advanced Hero accepts an optional immutable `EditorialArcDocument` supplied by
the operator. It contains an ordered TimeMap, exact forced word ids for every
segment, hook/body/punch roles, a purpose for each segment, and an explicit
allowlisted cut-transition style. The validator
requires complete-word boundaries, source containment inside the approved Hero
range, unique words, and ordered hook/body/punch semantics. Output segment
order may differ from source order. A segment that starts inside an ongoing
sentence must explicitly declare `continuation: true`; otherwise the cut is
rejected. The same map carries each segment's speech with its picture.

Planning remaps the existing forced alignment onto the arc output clock and
stores that alignment under the Advanced plan. Picture and speech staging then
consume the persisted arc TimeMap. The original Hero artifact and approval stay
immutable; the recut remains a new Advanced draft and still requires current
QA and human final review before delivery.

The arc cannot invent transcript text, add a second audio clock, or bypass
rights, alignment, direction, or approval gates. An invalid, stale, or changed
arc fails closed and changes the Advanced cache identity.

## Consequences

Codex can create a coherent multi-moment draft from source-grounded ranges while
keeping the approved Hero evidence as the parent. The current direction brief
continues to provide presentation style and optional graphics; the arc controls
only source order and speech-safe cuts. Existing one-range Advanced plans remain
readable.
