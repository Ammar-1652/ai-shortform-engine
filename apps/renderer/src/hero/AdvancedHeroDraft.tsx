import { AbsoluteFill, Audio, OffthreadVideo, Sequence, staticFile, useCurrentFrame } from "remotion";

import { CaptionPlate } from "../captions/CaptionPlate.js";
import { placedVideo, windowAt, type CropWindow } from "./crop.js";
import { linearVolume } from "./gain.js";

type Interval = { output_start_us?: number; output_end_us?: number };

type TypeEvent = {
  event_id?: string;
  text?: string;
  interval?: Interval;
  component_id?: string;
  purpose?: string;
  language?: string;
};

type DiagramEvent = {
  component_id?: string;
  interval?: Interval;
  payload?: {
    left_label?: string;
    right_label?: string;
    left_value?: number;
    right_value?: number;
  };
};

type BrollEvent = {
  asset_id?: string;
  interval?: Interval;
  broll_source_in_us?: number;
};

type SfxEvent = {
  asset_id?: string;
  interval?: Interval;
  gain_db?: number;
  role?: string;
};

type EmphasisEvent = { text?: string; output_start_us?: number; output_end_us?: number };

export type AdvancedHeroInput = {
  duration_in_frames: number;
  reframing_strategy?: string;
  base_video_name?: string;
  speech_name?: string;
  captions?: TypeEvent[];
  typography?: TypeEvent[];
  diagrams?: DiagramEvent[];
  broll?: BrollEvent[];
  sfx?: SfxEvent[];
  emphasis?: EmphasisEvent[];
  asset_names?: Record<string, string>;
  windows?: CropWindow[];
  language?: string;
  source_gain_db?: number;
  narration_gain_db?: number;
  audio_loudness_lufs?: number;
  audio_true_peak_dbfs?: number;
  audio_lra_lu?: number;
  audio_mix_version?: string;
  debug_overlays?: boolean;
};

const FPS = 30;
const NEUTRAL_DARK = "#111111";

function frameAt(microseconds: number | undefined): number {
  if (typeof microseconds !== "number") {
    return 0;
  }
  return Math.floor((microseconds * FPS) / 1_000_000);
}

function active(frame: number, interval: Interval | undefined): boolean {
  const start = frameAt(interval?.output_start_us);
  const end = frameAt(interval?.output_end_us);
  return frame >= start && frame < end;
}

function span(interval: Interval | undefined): { from: number; duration: number } {
  const from = frameAt(interval?.output_start_us);
  const end = frameAt(interval?.output_end_us);
  return { from, duration: Math.max(1, end - from) };
}

/**
 * Advanced portrait draft. Contain keeps the whole source picture.
 * Text nodes are React children. A face box is not a speaker. Music is not a layer.
 */
export function AdvancedHeroDraft(input: AdvancedHeroInput) {
  const frame = useCurrentFrame();
  const strategy = input.reframing_strategy ?? "contain";
  if (input.debug_overlays === true) {
    throw new Error("production advanced renders reject debug overlays");
  }
  if (strategy !== "contain" && strategy !== "center_crop" && strategy !== "face_follow") {
    throw new Error(`advanced render does not support reframing strategy ${String(strategy)}`);
  }
  const names = input.asset_names ?? {};
  const captions = input.captions ?? [];
  const typography = input.typography ?? [];
  const visibleCaptions = captions.filter((item) => active(frame, item.interval) && (item.text ?? "").trim().length > 0);
  const visibleType = typography.filter((item) => {
    if (!active(frame, item.interval) || (item.text ?? "").trim().length === 0) {
      return false;
    }
    const text = (item.text ?? "").replace(/\s+/g, " ").trim().toLowerCase();
    // A typography event copied from the transcript must not be painted over
    // the grouped caption that already carries the same words.
    return !visibleCaptions.some((caption) =>
      caption.text?.replace(/\s+/g, " ").toLowerCase().includes(text),
    );
  });
  const rawLanguage = input.language?.trim();
  // Legacy/offline fixtures may omit locale evidence. Keep the layout
  // deterministic without treating the sentinel as a supported locale claim.
  const language = !rawLanguage || rawLanguage === "missing" ? "en-US" : rawLanguage;
  const diagram = (input.diagrams ?? []).find((item) => active(frame, item.interval));
  const emphasis = (input.emphasis ?? []).filter(
    (item) => frame >= frameAt(item.output_start_us) && frame < frameAt(item.output_end_us),
  );
  const speech = input.speech_name ?? "asr.flac";
  const picture = input.base_video_name ?? "analysis.mp4";
  const contained = { width: "100%", height: "100%", objectFit: "contain" as const };
  const sourceWindow = input.windows?.[0];
  const containBox = sourceWindow
    ? {
        position: "absolute" as const,
        width: "100%",
        aspectRatio: `${sourceWindow.frame_width} / ${sourceWindow.frame_height}`,
        top: "50%",
        transform: "translateY(-50%)",
      }
    : { position: "absolute" as const, inset: 0 };
  const followed = strategy === "face_follow" || strategy === "center_crop" ? placedVideo(windowAt(frame, input.windows ?? [])) : null;
  return (
    <AbsoluteFill style={{ backgroundColor: NEUTRAL_DARK }}>
      {followed === null ? (
        <AbsoluteFill style={{ overflow: "hidden" }}>
          <OffthreadVideo
            src={staticFile(picture)}
            durationInFrames={input.duration_in_frames}
            muted
            style={{ ...contained, objectFit: "cover", filter: "blur(24px)", transform: "scale(1.08)", opacity: 0.72 }}
          />
          <AbsoluteFill style={containBox}>
            <OffthreadVideo
              src={staticFile(picture)}
              durationInFrames={input.duration_in_frames}
              muted
              style={{ width: "100%", height: "100%", objectFit: "fill" }}
            />
          </AbsoluteFill>
        </AbsoluteFill>
      ) : (
        <AbsoluteFill style={{ overflow: "hidden" }}>
          <OffthreadVideo
            src={staticFile(picture)}
            durationInFrames={input.duration_in_frames}
            muted
            style={{ position: "absolute", ...followed }}
          />
        </AbsoluteFill>
      )}
      <Audio
        src={staticFile(speech)}
        durationInFrames={input.duration_in_frames}
        volume={linearVolume(input.source_gain_db ?? 0)}
      />
      {names.narration && /^[A-Za-z0-9._-]{1,80}$/.test(names.narration) ? (
        <Audio
          src={staticFile(names.narration)}
          durationInFrames={input.duration_in_frames}
          volume={linearVolume(input.narration_gain_db ?? 0)}
        />
      ) : null}
      {(input.broll ?? []).map((item) => {
        const name = item.asset_id ? names[item.asset_id] : undefined;
        if (!name) {
          return null;
        }
        const window = span(item.interval);
        return (
          <Sequence key={`broll-${name}-${window.from}`} from={window.from} durationInFrames={window.duration}>
            <AbsoluteFill>
              <OffthreadVideo
                src={staticFile(name)}
                trimBefore={frameAt(item.broll_source_in_us)}
                durationInFrames={window.duration}
                muted
                style={{ ...contained, objectFit: "cover" }}
              />
            </AbsoluteFill>
          </Sequence>
        );
      })}
      {(input.sfx ?? []).map((item) => {
        const name = item.asset_id ? names[item.asset_id] : undefined;
        if (!name || item.role === "music") {
          return null;
        }
        const window = span(item.interval);
        return (
          <Sequence key={`sfx-${name}-${window.from}`} from={window.from} durationInFrames={window.duration}>
            <Audio src={staticFile(name)} volume={linearVolume(item.gain_db ?? 0)} />
          </Sequence>
        );
      })}
      {diagram === undefined ? null : (
        <AbsoluteFill style={{ left: 72, right: 72, top: 280, height: 360, display: "flex", justifyContent: "center" }}>
          <div
            style={{
              width: 840,
              height: 360,
              borderRadius: 28,
              backgroundColor: "rgba(17,17,17,0.88)",
              border: "2px solid rgba(255,255,255,0.22)",
              color: "#ffffff",
              fontFamily: "sans-serif",
              fontSize: 36,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-evenly",
              textAlign: "center",
            }}
          >
            <div>
              <div>{diagram.payload?.left_label}</div>
              <strong>{diagram.payload?.left_value}</strong>
            </div>
            <div style={{ opacity: 0.6 }}>vs</div>
            <div>
              <div>{diagram.payload?.right_label}</div>
              <strong>{diagram.payload?.right_value}</strong>
            </div>
          </div>
        </AbsoluteFill>
      )}
      {visibleCaptions.map((item) => (
        <CaptionPlate
          key={`${item.component_id ?? "caption"}-${item.event_id ?? ""}-${item.text}`}
          text={(item.text ?? "").trim()}
          language={item.language || language}
        />
      ))}
      {visibleType.map((item) => (
        <CaptionPlate
          key={`${item.component_id ?? "type"}-${item.text}`}
          text={item.text ?? ""}
          language={item.language || language}
        />
      ))}
      {emphasis.map((item) => (
        <div
          key={`emphasis-${item.text ?? ""}-${item.output_start_us ?? 0}`}
          style={{ position: "absolute", left: 72, top: 1720, color: "#ffffff", fontFamily: "sans-serif", fontSize: 28 }}
        >
          {item.text ?? ""}
        </div>
      ))}
    </AbsoluteFill>
  );
}
