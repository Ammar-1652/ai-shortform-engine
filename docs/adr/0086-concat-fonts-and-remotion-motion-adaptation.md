# ADR 0086: Concat font provenance and Remotion motion adaptation

- Status: accepted
- Date: 2026-10-17
- Decision owners: Clipforge maintainers

## Context

Concat (`jub0t/Concat`) has a useful short-form vocabulary of title presets
and effects, but its application and effect crate are AGPL-3.0-or-later Rust
code coupled to a native wgpu compositor. Clipforge has one deterministic
Remotion production renderer, typed render inputs, and existing rights/cache
bindings. Copying Concat's Rust/WGSL packages or invoking Concat as a second
editor would create a conflicting production core and a license boundary that
has not been approved.

## Decision

1. Pin the inspected upstream commit in
   `docs/architecture/concat-motion-assets.md` and ship only the individually
   licensed font files selected from Concat's font directory, with their
   license notices and SHA-256 hashes.
2. Add an opt-in `concat-editorial-v1` declarative motion style. Its font
   identity and hashes are part of the style fingerprint, staged locally, and
   required by the existing Remotion production gate.
3. Reimplement only restrained, frame-derived transition intent as native
   Remotion components: `concat_push_v1` and `concat_blur_dissolve_v1`. They
   can be requested only by a reviewed editorial arc at a real TimeMap cut.
4. Keep `clean_cut_v1`, all prior style ids, old artifacts, rights checks,
   source grounding, safe regions, no-music policy, and human review gates
   unchanged.

## Consequences

- Existing plans and renders remain reproducible because no old style profile
  is changed. The new style creates new fingerprints and cache identities.
- The renderer gains local Hanken Grotesk, Anton, Space Grotesk, and Noto Sans
  Arabic UI coverage without a CDN or runtime network request.
- The visual behavior is compatible with Remotion and can be frame-tested;
  it is not a claim that Concat's native shaders were imported.
- Future additions must pass the same license review. AGPL Concat source,
  effect shaders, or runtime dependencies must not be copied into Clipforge
  without a separate licensing and architecture decision.
