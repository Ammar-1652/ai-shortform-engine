import { AbsoluteFill, Audio, OffthreadVideo, staticFile, useCurrentFrame } from "remotion";

import { CaptionPlate } from "../captions/CaptionPlate.js";
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
  const active = input.captions.find((item) => revealedCaption(item, frame).length > 0);
  const caption = active === undefined ? undefined : revealedCaption(active, frame);
  const language = active?.language || input.language;
  if (caption !== undefined && !language) {
    throw new Error("hero caption is missing a locale");
  }
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
        <AbsoluteFill style={{ transform: `scale(${scale})`, transformOrigin: "center center" }}>
          <CaptionPlate text={caption} language={language ?? ""} />
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
}
