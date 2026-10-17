import { AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, staticFile, useCurrentFrame, Video } from "remotion";

import { activeCaption } from "./captions.js";
import { VIDEO_OBJECT_FIT } from "./layout.js";
import { NEUTRAL_DARK, type RoughCaptionCue, type RoughPreviewInput } from "./types.js";
import { parseRenderInput } from "./validation.js";
import { captionFontFamily, useCaptionFonts } from "../captions/fonts.js";
import { nextCaptionWord } from "../captions/word-matching.js";

/**
 * One candidate, contained in a vertical review frame.
 *
 * Video and speech share `media_trim_frame` on the 30/1 preview grid.
 * Provisional ASR captions are phrase-only by default. The explicit reviewed
 * word mode is a visual review aid and is never a substitute for alignment
 * evidence in a Hero approval.
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
  const fontsReady = useCaptionFonts(
    input.font_identity === "amiri-quran-local-v1" || input.font_identity === "concat-editorial-local-v1",
    input.font_identity,
  );
  if (!fontsReady) return null;
  return (
    <AbsoluteFill style={{ backgroundColor: NEUTRAL_DARK, overflow: "hidden" }}>
      <AbsoluteFill style={{ overflow: "hidden" }}>
        {input.background === "blurred-source-v1" ? (
          <OffthreadVideo
            src={staticFile(stagedName(input.video_path))}
            trimBefore={input.media_trim_frame}
            durationInFrames={input.duration_in_frames}
            muted
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              objectFit: "cover",
              filter: "blur(24px)",
              transform: "scale(1.08)",
              opacity: 0.72,
            }}
          />
        ) : null}
        <OffthreadVideo
          src={staticFile(stagedName(input.video_path))}
          trimBefore={input.media_trim_frame}
          durationInFrames={input.duration_in_frames}
          muted
          style={{ width: "100%", height: "100%", objectFit: VIDEO_OBJECT_FIT, transform: `translateX(${input.video_offset_x_px}px) scale(${input.video_scale_permille / 1000})` }}
        />
        <Audio
          src={staticFile(stagedName(input.audio_path))}
          trimBefore={input.media_trim_frame}
          durationInFrames={input.duration_in_frames}
        />
      </AbsoluteFill>
      {input.campaign_overlay ? (
        <>
          <Img
            src={staticFile(input.campaign_overlay.watermark_asset_name)}
            style={{
              position: "absolute",
              top: 34,
              right: 34,
              width: `${input.campaign_overlay.watermark_width_permille / 10}%`,
              height: "auto",
              objectFit: "contain",
              filter: "drop-shadow(0 3px 6px rgba(0,0,0,.55))",
            }}
          />
          <Sequence
            from={Math.floor((input.campaign_overlay.cta_start_us * 30) / 1_000_000)}
            durationInFrames={Math.max(
              1,
              Math.ceil(((input.campaign_overlay.cta_end_us - input.campaign_overlay.cta_start_us) * 30) / 1_000_000),
            )}
          >
            <CampaignCta overlay={input.campaign_overlay} localFrame={frame - Math.floor((input.campaign_overlay.cta_start_us * 30) / 1_000_000)} />
          </Sequence>
        </>
      ) : null}
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
              fontFamily: captionFontFamily(input.font_identity),
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
          {input.word_highlight_mode === "reviewed" && caption.words.length > 0 ? (
            <CaptionWords cue={caption} frame={frame} />
          ) : caption.text}
          </div>
        </div>
      )}
    </AbsoluteFill>
  );
}

function CampaignCta({
  overlay,
  localFrame,
}: {
  overlay: NonNullable<RoughPreviewInput["campaign_overlay"]>;
  localFrame: number;
}) {
  const placement = {
    position: "absolute" as const,
    left: `${overlay.cta_left_permille / 10}%`,
    top: `${overlay.cta_top_permille / 10}%`,
    width: `${overlay.cta_width_permille / 10}%`,
    height: "auto",
    objectFit: "contain" as const,
    zIndex: 12,
  };
  if (overlay.cta_render_mode === "alpha_video_v1") {
    const durationInFrames = Math.max(
      1,
      Math.ceil(((overlay.cta_end_us - overlay.cta_start_us) * 30) / 1_000_000),
    );
    return (
      <Video
        src={staticFile(overlay.cta_asset_name)}
        trimBefore={0}
        durationInFrames={durationInFrames}
        muted
        style={placement}
      />
    );
  }
  if (overlay.cta_frame_prefix === undefined || overlay.cta_frame_count === undefined) {
    throw new Error("PNG CTA overlay is missing its frame sequence");
  }
  const index = Math.min(overlay.cta_frame_count - 1, Math.max(0, localFrame));
  const name = `${overlay.cta_frame_prefix}-${String(index + 1).padStart(4, "0")}.png`;
  return (
    <Img
      src={staticFile(name)}
      style={{
        ...placement,
      }}
    />
  );
}

function CaptionWords({ cue, frame }: { cue: RoughCaptionCue; frame: number }) {
  let cursor = 0;
  return (
    <>
      {cue.text.split(/(\s+)/).map((part, index) => {
        if (/^\s+$/u.test(part)) return <span key={`${part}-${index}`}>{part}</span>;
        const matched = nextCaptionWord(part, cue.words, cursor);
        cursor = matched.nextCursor;
        const word = matched.word;
        const active = word !== undefined && frame >= word.output_start_frame && frame < word.output_end_frame_exclusive;
        const color = word?.verification_status === "incorrect"
          ? "#ff4d5f"
          : word?.verification_status === "correct" && active
            ? "#42d487"
            : active
              ? "#ffcf4a"
              : "#ffffff";
        return <span key={`${part}-${index}`} style={{ color }}>{part}</span>;
      })}
    </>
  );
}
