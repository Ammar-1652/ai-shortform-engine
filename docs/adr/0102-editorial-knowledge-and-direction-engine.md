# ADR 0102: Editorial knowledge and direction engine

**Status:** accepted for staged implementation

## Context

Clipforge has deterministic media and review machinery, but editorial direction
must remain explicit and repeatable. Repository skills and reference videos
should teach Codex how to choose a hook, story arc, caption treatment, motion,
B-roll, sound, and ending. A folder of copied prompts or an effect list would
not record applicability, counterexamples, source evidence, or which guidance
influenced a render.

## Decision

Add a versioned local knowledge layer in the AI decision plane. It stores pinned
sources, reference observations, guidance cards, narrative patterns, style
cards, evaluation cases, conflicts, releases, direction contexts, decision
traces, and append-only feedback. The current implementation provides strict
Pydantic contracts, a validated local library, deterministic tag-based
retrieval, hash-bound context bundles, CLI inspection/context commands, and
direction-plan binding.

Codex reads the context and chooses the editorial plan. The system validates
the plan and executes it. A guidance record never grants rights, changes a
TimeMap, executes code, or creates an approval. A reference video may be
analyzed only with explicit permission; analysis permission does not grant
footage reuse. Craft observations remain separate from performance evidence.

Knowledge releases are immutable inputs to plans. Updating a source or card
creates a new release/context/plan identity. Historical plans retain their
recorded guidance. Conflicts and unknowns are surfaced rather than silently
discarded.

## Consequences

* New agents can discover the same direction vocabulary and tool routes.
* Guidance has scope, evidence, limits, failure examples, and evaluation cases.
* Reference videos can be admitted as reusable knowledge without becoming
  unverified templates or automatic claims about virality.
* Knowledge retrieval is local and deterministic; no vector database or network
  call is required for production.
* Future implementation work must add the reference-analysis evaluation loop,
  complete decision-trace persistence, and broader motion/style catalogs before
  claiming the full direction engine is complete.
