import { AbsoluteFill, Audio, staticFile, useCurrentFrame, Video } from "remotion";

import { CaptionPlate } from "../captions/CaptionPlate.js";
import { useCaptionFonts } from "../captions/fonts.js";
import { emphasisScale, layerOpacity, revealedCaption } from "./motion.js";
import { containRect } from "./portrait-transform.js";
import { NEUTRAL_DARK, type HeroDraftInput } from "./types.js";
import { parseHeroInput } from "./validation.js";

/**
 * One approved candidate in a portrait Hero frame.
 *
 * The picture stays legible in a contained foreground over a blurred full-frame
 * treatment. Captions are grouped by cue; forced word frames remain timing
 * evidence for emphasis. Motion is a short fade plus a small emphasis scale.
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
  const foreground = containRect(input.source_width, input.source_height, input.width, input.height);
  const legacy = input.renderer_recipe_version !== "hero-draft-renderer-v2";
  const fontsReady = useCaptionFonts(!legacy);
  if (caption !== undefined && !language) {
    throw new Error("hero caption is missing a locale");
  }
  if (!fontsReady) return null;
  return (
    <AbsoluteFill style={{ backgroundColor: NEUTRAL_DARK, opacity }}>
      <AbsoluteFill>
        <AbsoluteFill style={{ overflow: "hidden" }}>
          <Video
            src={staticFile(stagedName(input.video_path))}
            trimBefore={input.media_trim_frame}
            durationInFrames={input.duration_in_frames}
            muted
            style={{ width: "100%", height: "100%", objectFit: "cover", filter: "blur(24px)", transform: "scale(1.08)", opacity: 0.72 }}
          />
          {legacy ? (
            <AbsoluteFill style={{ width: "100%", aspectRatio: `${input.source_width} / ${input.source_height}`, top: "50%", transform: "translateY(-50%)" }}>
              <Video src={staticFile(stagedName(input.video_path))} trimBefore={input.media_trim_frame} durationInFrames={input.duration_in_frames} muted style={{ width: "100%", height: "100%", objectFit: "fill" }} />
            </AbsoluteFill>
          ) : <div style={{
              position: "absolute",
              left: foreground.left,
              top: foreground.top,
              width: foreground.width,
              height: foreground.height,
            }}
          >
            <Video
              src={staticFile(stagedName(input.video_path))}
              trimBefore={input.media_trim_frame}
              durationInFrames={input.duration_in_frames}
              muted
              style={{ width: "100%", height: "100%", objectFit: "contain" }}
            />
          </div>}
        </AbsoluteFill>
        <Audio
          src={staticFile(stagedName(input.audio_path))}
          trimBefore={input.media_trim_frame}
          durationInFrames={input.duration_in_frames}
        />
      </AbsoluteFill>
      {caption === undefined ? null : (
        <AbsoluteFill style={{ transform: `scale(${scale})`, transformOrigin: "center center" }}>
          <CaptionPlate text={caption} language={language ?? ""} layoutVersion={legacy ? "caption-layout-v1" : "caption-layout-v2"} />
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
}
