import { AbsoluteFill, Audio, OffthreadVideo, staticFile, useCurrentFrame } from "remotion";

import { NEUTRAL_DARK } from "./types.js";

type TextEvent = { text: string; start_frame: number; end_frame: number };
type Diagram = { left_label: string; right_label: string };

export type AdvancedHeroInput = {
  duration_in_frames: number;
  typography: TextEvent[];
  diagram: Diagram | null;
  broll_name: string | null;
};

/**
 * Advanced portrait draft. Text is a React child, never HTML.
 * Face geometry is not treated as a speaker.
 */
export function AdvancedHeroDraft({ duration_in_frames, typography, diagram, broll_name }: AdvancedHeroInput) {
  const frame = useCurrentFrame();
  const caption = typography.find((item) => frame >= item.start_frame && frame < item.end_frame);
  return (
    <AbsoluteFill style={{ backgroundColor: NEUTRAL_DARK }}>
      <OffthreadVideo src={staticFile("analysis.mp4")} durationInFrames={duration_in_frames} muted />
      <Audio src={staticFile("asr.flac")} durationInFrames={duration_in_frames} />
      {broll_name === null ? null : (
        <OffthreadVideo src={staticFile(broll_name)} durationInFrames={duration_in_frames} muted />
      )}
      {diagram === null ? null : (
        <div style={{ position: "absolute", left: 120, top: 280, color: "#ffffff", fontFamily: "sans-serif" }}>
          {diagram.left_label}
          {diagram.right_label}
        </div>
      )}
      {caption === undefined ? null : (
        <div
          style={{
            position: "absolute",
            left: 72,
            right: 72,
            bottom: 280,
            color: "#ffffff",
            fontFamily: "sans-serif",
            fontSize: 54,
            textAlign: "center",
          }}
        >
          {caption.text}
        </div>
      )}
    </AbsoluteFill>
  );
}
