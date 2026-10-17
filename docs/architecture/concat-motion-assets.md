# Concat motion asset integration

Clipforge reviewed `jub0t/Concat` at commit
`60ecb4a1fda62501f67afaf7e036143c95f196f8` on 2026-10-17. The upstream
repository is the AGPL-3.0-or-later Concat editor. Its effect catalogue is a
Rust crate (`src/crates/concat-effects`) whose WGSL shaders are coupled to
Concat's native wgpu compositor; its text presets are data consumed by the
Concat application. Clipforge does not copy that AGPL code, execute Concat as
a second editor, download upstream instructions at render time, or add a
runtime network dependency.

## What is bundled

Only the independently licensed font files below are copied into
`apps/renderer/assets/fonts/concat/`. The license text shipped beside each
file is the evidence for the corresponding font, and the renderer binds the
file hashes into the `concat-editorial-v1` style fingerprint.

| File | Upstream path | License | SHA-256 |
|---|---|---|---|
| `HankenGrotesk-SemiBold.ttf` | `src/crates/concat-text/fonts/HankenGrotesk-SemiBold.ttf` | SIL OFL 1.1, Hanken Grotesk Project Authors | `4f70ae1dd1c951e80603732344f18507d6a6932a3df9f7f6d8a91d4495d41e17` |
| `Anton-Regular.ttf` | `src/crates/concat-text/fonts/Anton-Regular.ttf` | SIL OFL 1.1, Anton Project Authors | `a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab` |
| `SpaceGrotesk-Bold.ttf` | `src/crates/concat-text/fonts/SpaceGrotesk-Bold.ttf` | SIL OFL 1.1, Florian Karsten | `42c2abe5fddba9a6da76fabab653246fcf48daa3ae3fc6251e61f8215fdda006` |
| `NotoSansArabicUI-Concat.ttf` | `src/crates/concat-text/fonts/NotoSansArabicUI-Concat.ttf` | SIL OFL 1.1, Noto Project Authors | `9187fa244db5f50201cfb0ede30ae7269651d090290f164c0703403fd0fab1b2` |

The selected files are used as a local font stack: Hanken Grotesk for body
captions, Anton for short Latin hook/punch display, Space Grotesk for compact
labels, and Noto Sans Arabic UI as an Arabic fallback. Arabic shaping remains
whole-run; the font choice does not make an alignment or Quran-text claim.

## What is adapted, not copied

The reviewed Concat vocabulary included the `clean`, `editorial`, `impact`,
and `lower-third` text recipes and effect manifests such as `push`,
`motion-blur`, `blur-dissolve`, and `glitch-transition`. Their visual intent
is represented by Clipforge's own allowlisted, frame-driven Remotion
components:

- `concat-editorial-v1` is a versioned `MotionStyleProfile` with numeric
  easing, travel, scale, safe region, caption mode, accent, and font hashes.
- `concat_push_v1` is a restrained deterministic push-sweep overlay at a
  reviewed TimeMap cut.
- `concat_blur_dissolve_v1` is a bounded blur/dissolve overlay at a reviewed
  TimeMap cut.
- `ConcatTransitionOverlay` is the only renderer implementation for these
  styles. It uses `useCurrentFrame`-derived progress; there are no CSS timers,
  random values, remote shaders, or arbitrary operator code.

These are clean-room Clipforge components, not copied WGSL or Rust. The
`clean_cut_v1` legacy bridge remains available for old plans. No transition is
inserted merely because a style is selected: an editorial arc must explicitly
request the transition at a real cut, and the existing campaign policy and
human review gates still apply.

## Operational contract

The renderer stages the pinned font pack into each isolated run directory and
fails closed on a missing file, symlink, or changed hash. `concat-editorial-v1`
is an opt-in direction style; existing style fingerprints and old artifacts
remain immutable. A style, font, transition, or renderer recipe change must
produce a new plan/render identity and cannot reuse old QA or final approval.

The upstream references are guidance only. They do not override Clipforge's
source-grounding, rights, no-music, no-outside-media, TimeMap, safe-area,
caption, provenance, or human-approval rules.

## Selecting it

An operator or direction brief selects the style declaratively; no JSX or
shader is supplied:

```json
{
  "style_id": "concat-editorial-v1",
  "transition_style": "concat_push_v1"
}
```

`style_id` belongs to the validated `DirectionOption`. The transition belongs
to the reviewed `EditorialArcDocument` and is applied only at its actual
TimeMap cut. Use `concat_blur_dissolve_v1` when a softer bridge is appropriate;
leave the transition as `none` when the source meaning calls for a clean cut.
The normal Hero/Advanced Hero CLI and review gates remain the execution path.

Upstream references:

- Repository: https://github.com/jub0t/Concat
- License: https://github.com/jub0t/Concat/blob/60ecb4a1fda62501f67afaf7e036143c95f196f8/LICENSE
- Third-party font notices:
  `src/crates/concat-text/fonts/LICENSE-*.txt` at the pinned commit
