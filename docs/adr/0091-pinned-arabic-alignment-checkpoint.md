# ADR 0091: Pinned Arabic selected-clip alignment checkpoint

## Status

Accepted for local Tarteel Advanced Hero drafts.

## Context

The Tarteel candidate is Arabic. The previous capability registry returned
`alignment_not_claimed` before WhisperX could run, even when a compatible
Arabic wav2vec2 checkpoint was available. Falling back to transcript or
proportional timings would break the forced-alignment and synchronization
rules.

## Decision

Use WhisperX's Apache-2.0 Arabic checkpoint
`jonatasgrosman/wav2vec2-large-xlsr-53-arabic` at immutable revision
`af46c2d8531b8dcbb5e23b952f739b372c2e5d2d`. Its measured model tree and
checkpoint hash are recorded in `clipforge.language.providers`. The
`selected_clip_provider_for()` scope may run this local checkpoint, while the
public `provider_for()` and full-source language registry remain
`alignment_not_claimed`. A selected clip may run with this local checkpoint and
stores `alignment_status: available_not_smoked` until a matching
speech-evidence smoke is recorded.
That status is not promoted to `verified_live`, does not claim Arabic language
capability, and does not replace the Quran canonical-text or human review
gates. No English checkpoint is ever used for Arabic.

## Consequences

- Tarteel can produce a real selected-clip draft with measured Arabic word
  boundaries when the pinned local model is present.
- Missing or stale model bytes still fail closed before alignment.
- Production verification continues to expose the evidence state rather than
  claiming Arabic support from a catalog row alone.
- Model weights stay outside Git and are acquired only through the explicit
  local model-download path.
