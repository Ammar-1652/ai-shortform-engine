# ADR 0071: Cut-boundary audio envelopes and reviewed asset content binding

## Status

Accepted for new Hero and Advanced Hero production artifacts.

## Context

Review of the credit-piggybacking and Envato experiments found three chain
failures rather than a problem in one finished MP4. A Hero render staged its
picture and speech with two independent trim recipes. An Advanced Hero
TimeMap could begin or end inside a forced word, which could remove a word
onset (for example, `How` becoming `ow`). Finally, selected stock media had no
machine-checkable relationship to the source phrase, and SFX had no production
envelope or conservative level cap.

## Decision

1. Browser Hero renders use the exact picture/audio pair produced by the same
   candidate-span staging transaction. Any fallback trim path must use a
   relative duration (`end - start`) and validate its measured audio duration.
2. Advanced alignment rejects a TimeMap boundary that falls inside an aligned
   word and rejects forced-word intervals shorter than 5 ms. A new edit must
   be selected at a complete-word boundary; caption grouping cannot repair a
   phonetic cut.
3. Advanced jump-cut staging cuts picture and speech from the identical
   ordered TimeMap. Speech receives a deterministic 8 ms fade-in/out only at a
   discontinuity. It does not overlap, loop, stretch, or introduce a second
   clock. The staging recipe is hashable and records this policy.
4. A reviewed local/Envato asset carries operator-confirmed content tags.
   Every clean B-roll placement copies the exact tags and its relevance note
   must name at least one tag. Missing or mismatched tags fail before render.
   The rule is a relevance gate, not an automated claim that replaces human
   review.
5. Clean production SFX defaults to -18 dB gain, is capped at -18 dB by the
   profile, and uses a 20 ms entrance / 60 ms exit envelope. Legacy recipes
   retain their recorded behavior and are not reinterpreted.

## Consequences

Old artifacts remain immutable and may continue to show the defects recorded
in their evidence. Recreating the same edit through the current production
path either produces a single-clock, boundary-safe result or fails with an
actionable error before a misleading package is made. Tags, audio policy,
staging recipe, alignment and TimeMap digests participate in fingerprints and
stale-evidence checks. A direction may omit stock and SFX entirely when no
source-grounded use survives review.
