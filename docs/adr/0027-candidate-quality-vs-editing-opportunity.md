# ADR 0027: Candidate quality versus editing opportunity

- Status: Accepted
- Date: 2026-10-02

## Context

`CandidateClip.creative_score` already exists and is not a compliance weight. Round 5 needs a transparent rank for "does this interval look like a usable short?" and a separate note for "does the interval contain structure a later edit could use?" Adding those numbers would let a busy mediocre interval outrank a clearer one.

## Decision

`quality_score` is the editorial ranking heuristic. It is stored on the score breakdown and copied to `creative_score`. Weights are duration fit 0.15, speech coverage 0.20, boundary completeness 0.20, transcript reliability 0.20, information density 0.10, opening structure 0.05, and visual evidence coverage 0.10.

`edit_opportunity_score` uses scene-change 0.25, stored visual difference 0.25, face-layout variation 0.15, numeric tokens 0.15, punctuation emphasis 0.10, and multi-scene 0.10. It is not added to quality and does not break ties.

A missing feature stays null. The weight is renormalized over the features that exist. `quality_weight_coverage` below 0.70 rejects the hypothesis. Sparse edit evidence does not. There is no quality floor and no virality threshold. Faces do not raise quality. Face layout is an edit signal only, and it is not a speaker change.

Transcript reliability uses word confidence when words have it, otherwise segment `avg_logprob`, `no_speech_prob`, and `compression_ratio`. It is not a truth score. Information density is words per spoken second.

## Alternatives considered

- One blended score. Rejected. The two questions are different.
- Substitute 0.5 for missing confidence. Rejected. That invents evidence.
- A hard cutoff at 0.5. Rejected. The band is for humans to review, not a scientific boundary.

## Consequences

Ordering is quality, then coverage, then boundary completeness, then earlier start, then shorter duration, then the stable id. Commands print the unit score. They do not print a percent chance.
