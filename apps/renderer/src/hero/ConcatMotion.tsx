import { AbsoluteFill, interpolate } from "remotion";

export type ConcatTransitionStyle = "clean_cut_v1" | "concat_push_v1" | "concat_blur_dissolve_v1";

type Props = {
  style: ConcatTransitionStyle;
  progress: number;
  accent: string;
};

/**
 * Deterministic Remotion-native adaptations of the reviewed Concat motion
 * vocabulary. Concat's AGPL Rust/WGSL effects are not copied or executed here;
 * these small overlays preserve the editorial intent while remaining inside
 * Clipforge's frame-driven renderer and its allowlisted contracts.
 */
export function ConcatTransitionOverlay({ style, progress, accent }: Props) {
  const t = Math.max(0, Math.min(1, progress));
  if (style === "concat_push_v1") {
    return (
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          transform: `translate3d(${interpolate(t, [0, 1], [0, 110])}%, 0, 0)`,
          background: `linear-gradient(100deg, ${accent} 0%, ${accent}dd 66%, #ffffff 68%, ${accent}66 72%, transparent 100%)`,
          boxShadow: `-18px 0 44px ${accent}88`,
        }}
      />
    );
  }
  if (style === "concat_blur_dissolve_v1") {
    return (
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          opacity: interpolate(t, [0, 0.55, 1], [0.7, 0.34, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          background: `radial-gradient(circle at 50% 46%, ${accent}55, #08111ddd 72%)`,
          filter: `blur(${interpolate(t, [0, 1], [10, 0])}px)`,
        }}
      />
    );
  }
  return (
    <AbsoluteFill
      style={{
        pointerEvents: "none",
        opacity: interpolate(t, [0, 1], [0.56, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
        background: `linear-gradient(112deg, transparent 0%, ${accent} 47%, #ffffff 50%, #3ddbd6 53%, transparent 100%)`,
        mixBlendMode: "screen",
      }}
    />
  );
}
