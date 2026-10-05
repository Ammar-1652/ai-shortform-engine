import { AbsoluteFill, Audio, OffthreadVideo, staticFile, useCurrentFrame } from "remotion";

import { activeCaption } from "./captions.js";
import { VIDEO_OBJECT_FIT } from "./layout.js";
import { NEUTRAL_DARK, type RoughPreviewInput } from "./types.js";
import { parseRenderInput } from "./validation.js";

/**
 * One candidate, contained in a vertical review frame.
 *
 * Video and speech share `media_trim_frame` on the 30/1 preview grid.
 * Caption text is a React text node. There is no word highlight.
 */
function stagedName(filePath: string): string {
  const slash = Math.max(filePath.lastIndexOf("/"), filePath.lastIndexOf("\\"));
  const name = slash >= 0 ? filePath.slice(slash + 1) : filePath;
  if (!/^[A-Za-z0-9._-]{1,80}$/.test(name) || name.includes("..")) {
    throw new Error("staged media name is not safe");
  }
  return name;
}

export function RoughPreview(raw: RoughPreviewInput) {
  const input = parseRenderInput(raw);
  const frame = useCurrentFrame();
  const caption = activeCaption(input.captions, frame);
  return (
    <AbsoluteFill style={{ backgroundColor: NEUTRAL_DARK }}>
      <AbsoluteFill>
        <OffthreadVideo
          src={staticFile(stagedName(input.video_path))}
          trimBefore={input.media_trim_frame}
          durationInFrames={input.duration_in_frames}
          muted
          style={{ width: "100%", height: "100%", objectFit: VIDEO_OBJECT_FIT }}
        />
        <Audio
          src={staticFile(stagedName(input.audio_path))}
          trimBefore={input.media_trim_frame}
          durationInFrames={input.duration_in_frames}
        />
      </AbsoluteFill>
      {caption === null ? null : (
        <div
          style={{
            position: "absolute",
            left: 48,
            right: 48,
            bottom: 220,
            display: "flex",
            justifyContent: "center",
          }}
        >
          <div
            style={{
              color: "#ffffff",
              fontFamily: "sans-serif",
              fontWeight: 700,
              fontSize: 42,
              lineHeight: 1.25,
              textAlign: "center",
              textShadow: "0 2px 8px rgba(0,0,0,0.85)",
              backgroundColor: "rgba(0,0,0,0.45)",
              padding: "12px 16px",
              maxWidth: "100%",
              whiteSpace: "pre-wrap",
            }}
          >
            {caption.text}
          </div>
        </div>
      )}
    </AbsoluteFill>
  );
}
