# ADR 0090: Canonical Quran display evidence without pronunciation claims

## Status

Accepted for Tarteel Advanced Hero drafts.

## Context

The Arabic first-pass transcript can spell Quran words incorrectly while its
selected-clip alignment remains the available timing evidence. Replacing those
words directly in a render input would lose provenance, and marking them
correct would falsely claim pronunciation review. Fetching Quran text during a
render would also make cache identity and reproducibility unstable.

## Decision

Tarteel stores a typed sidecar containing the source and transcript hashes,
source-to-ayah intervals, and a hashed Quran.com Uthmani API snapshot under the
ignored work root. `canonical_match_verified` means only that the observed ASR
word sequence matches the pinned canonical sequence using deterministic Arabic
normalization and bounded one-to-three-word matching. The matcher carries the
observed source word ids and timing span into a canonical display word; it does
not modify audio, TimeMap, or the persisted forced alignment. Canonicalized
display words remain `unverified`. A human pronunciation review is the only
path to a `correct` status and green styling.

Advanced planning verifies the snapshot, source hash, transcript hash, and
sidecar hash before binding the Quran evidence. No network request is made by
production rendering. Any mismatch blocks planning and invalidates dependent
render, QA, approval, and delivery evidence through the existing plan hash.

## Consequences

- ASR spelling errors such as merged/split Arabic words cannot leak into
  Quran captions when the reviewed source mapping is complete.
- Display-text correction is auditable and deterministic, but it never claims
  pronunciation or Arabic alignment capability; Arabic alignment remains
  `alignment_not_claimed` outside the selected-clip production path.
- Existing artifacts remain immutable. A changed snapshot or mapping creates a
  new sidecar hash and therefore a new Advanced plan/render identity.
