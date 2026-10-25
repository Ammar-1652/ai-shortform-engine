# ADR 0096: Bind Advanced browser work and caption evidence to one encoded draft

## Status

Accepted for new Advanced browser renders. Speech-completeness and viewer
acceptance remain separate gates.

## Context

An environment marker on the Remotion worker did not identify which service
input or staged media it was allowed to render. A manual batch could claim the
same marker. A successful MP4 probe also did not prove that cue-edge frames
were decoded or that the selected audio matched the caption plan. Cache lookup
checked the MP4 hash but could reuse a draft with missing evidence files.

## Decision

The Advanced service writes a canonical batch and a candidate-specific
`AdvancedRenderAuthorization` after it has checked the current plan and staged
media. The receipt binds the input, canonical batch bytes, authorized output
path, staged media hashes, source and local renderer dependency hashes. The
worker verifies those facts before loading Remotion. Each candidate retains
its receipt when shared staging advances to another candidate. The service
checks the same dependency map when issuing a receipt. This is a local
integrity boundary; it does not claim to stop the owner of the work root from
editing local files.

For a clean browser draft, the service decodes every caption cue edge and
forced-word highlight edge after final encoding. A versioned report binds
the encoded MP4 hash, render input, TimeMap, alignment, staged audio hash,
frame indexes, observations and decoded PNG hashes. The manifest references
the report. QA reloads and checks it; cache lookup checks it before reusing
the render. A changed report or decoded PNG cannot be treated as a valid
cache hit. The service follows the renderer's one-frame minimum for positive
sub-frame cues and the output clock's half-open final endpoint.

The report's `speech_coverage_status` remains `insufficient_evidence`. A
decoded frame and an ASR word list cannot establish that all audible speech,
reactions or nasheed were transcribed. Current clean QA therefore remains
insufficient until a source-bound reviewed speech inventory and visual
assessment are implemented. It cannot be upgraded by editing the report.

Clean QA also requires the separate `ViewerEvidenceBundle` contract. It binds
decoded frames/contact sheets, platform crop previews, probe and loudness
facts, font/style dependencies and an optional human watch record to the exact
artifact. A bundle without both audio and muted playback observations is not
a human watch and cannot authorize delivery.

## Consequences

- Historical documents remain readable. Missing current evidence does not
  gain approval through legacy defaults.
- Changing the worker, authorization, evidence recipe or schema changes the
  render dependency fingerprint. Changed encoded bytes invalidate the report,
  manifest and downstream QA/review bindings.
- Decoding costs additional work and storage; failed evidence generation
  leaves a resumable render without a promoted manifest.
- A passing container probe, hash check or browser fixture still does not
  certify spoken-text accuracy, legibility, placement or final approval.
