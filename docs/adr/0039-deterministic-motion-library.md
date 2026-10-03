# ADR 0039: Deterministic motion library v1

- Status: Accepted
- Date: 2026-10-03

## Context

Hero drafts need a place for purposeful motion without turning Round 8 into a visual-effects system. Random animation, face tracking, B-roll, music, and sound effects would change the picture without a reviewed reason.

## Decision

Motion library `motion-library-v1` emits `MotionEvent` values on the output clock. The first components are:

- caption reveal from forced word frames
- caption emphasis for a word that ends in observed punctuation or contains a digit
- an opening fade and a closing fade of 266666 microseconds
- a 1.04 scale while an emphasis event is active

Event ids are UUID version 5 of the candidate, component, index, and interval. The same inputs serialize to the same events. Motion does not edit the TimeMap, infer a speaker, or reframe the picture. The Hero profile uses a static `contain` fit on a 1080×1920, 30/1 frame. The rough preview stays 720×1280.

## Alternatives considered

- A procedural animation seed. Rejected. A cache hit would not be reproducible.
- Dynamic face-aware reframing in this round. Rejected. That is later Hero work.

## Consequences

The Hero renderer can test each component without a model. Later rounds can add components by versioning the library instead of changing these event ids.
