import { AbsoluteFill, Audio, OffthreadVideo, staticFile, useCurrentFrame } from "remotion";

import { emphasisScale, layerOpacity, revealedCaption } from "./motion.js";
import { NEUTRAL_DARK, type HeroDraftInput } from "./types.js";
import { parseHeroInput } from "./validation.js";

/**
 * One approved candidate in a portrait Hero frame.
 *
 * The picture is contained. Caption text is a React text node revealed from
 * forced word frames. Motion is a short fade plus a small emphasis scale.
 */
function stagedName(filePath: string): string {
  const slash = Math.max(filePath.lastIndexOf("/"), filePath.lastIndexOf("\\"));
  const name = slash >= 0 ? filePath.slice(slash + 1) : filePath;
  if (!/^[A-Za-z0-9._-]{1,80}$/.test(name) || name.includes("..")) {
    throw new Error("staged media name is not safe");
  }
  return name;
}

export function HeroDraft(raw: HeroDraftInput) {
  const input = parseHeroInput(raw);
  const frame = useCurrentFrame();
  const opacity = layerOpacity(input.motion_events, frame);
  const scale = emphasisScale(input.motion_events, frame);
  const caption = input.captions
    .map((item) => revealedCaption(item, frame))
    .find((text) => text.length > 0);
  return (
    <AbsoluteFill style={{ backgroundColor: NEUTRAL_DARK, opacity }}>
      <AbsoluteFill>
        <OffthreadVideo
          src={staticFile(stagedName(input.video_path))}
          trimBefore={input.media_trim_frame}
          durationInFrames={input.duration_in_frames}
          muted
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
        />
        <Audio
          src={staticFile(stagedName(input.audio_path))}
          trimBefore={input.media_trim_frame}
          durationInFrames={input.duration_in_frames}
        />
      </AbsoluteFill>
      {caption === undefined ? null : (
        <div
          style={{
            position: "absolute",
            left: 72,
            right: 72,
            bottom: 280,
            display: "flex",
            justifyContent: "center",
            transform: `scale(${scale})`,
          }}
        >
          <div
            style={{
              color: "#ffffff",
              fontFamily: "sans-serif",
              fontWeight: 700,
              fontSize: 54,
              lineHeight: 1.25,
              textAlign: "center",
              textShadow: "0 2px 8px rgba(0,0,0,0.85)",
              backgroundColor: "rgba(0,0,0,0.45)",
              padding: "16px 20px",
              maxWidth: "100%",
              whiteSpace: "pre-wrap",
            }}
          >
            {caption}
          </div>
        </div>
      )}
    </AbsoluteFill>
  );
}
