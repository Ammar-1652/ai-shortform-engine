# ADR 0006: Two-stage editing

- Status: Accepted
- Date: 2026-10-02

## Context

A long source can contain many plausible shorts. Spending Hero effort (graphics, B-roll, SFX, forced alignment) on every idea wastes time and makes review impossible. A single "export the top 5" rule also throws away a sixth clip that is the one a reviewer wanted.

## Decision

Stage 1 is candidate mining and a light rough edit: many moments, cheap previews, enough to reject weak ideas.

Stage 2 is the Hero edit: motion graphics, typography, annotations, diagrams, B-roll, SFX, punch-ins, and precise captions. Only clips that pass the compliance gate and a human promotion enter this stage.

`EditPlan.stage` is `rough` or `hero`. `CandidateStatus` does not contain a fixed rank. No constant named top-5 exists. Promotion is a `ReviewDecision`, and the number promoted is whatever passed review.

Rough and Hero plans use the same time-map type and the same renderer. They differ by which events are filled in and by how expensive the render is allowed to be.

## Alternatives considered

- One stage that fully edits every detected moment. Rejected on cost.
- A hard-coded top 5. Rejected because distinctness, campaign fit, and human taste are not a fixed integer.
- Separate codebases for rough cuts and Hero cuts. Rejected. The core stays shared (the project goal's first principle).

## Consequences

- Later scoring can sort and filter, but it cannot publish and it cannot skip the review record.
- Schema and CLI must not grow a `--top 5` default.
- Rough renders are allowed to be ugly. They are not allowed to use a different clock.
