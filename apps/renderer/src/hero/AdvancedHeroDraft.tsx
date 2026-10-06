import { AbsoluteFill, Audio, OffthreadVideo, Sequence, staticFile, useCurrentFrame } from "remotion";

import { placedVideo, windowAt, type CropWindow } from "./crop.js";
import { linearVolume } from "./gain.js";

type Interval = { output_start_us?: number; output_end_us?: number };

type TypeEvent = {
  text?: string;
  interval?: Interval;
  component_id?: string;
  purpose?: string;
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
  typography?: TypeEvent[];
  diagrams?: DiagramEvent[];
  broll?: BrollEvent[];
  sfx?: SfxEvent[];
  emphasis?: EmphasisEvent[];
  asset_names?: Record<string, string>;
  windows?: CropWindow[];
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
  if (strategy !== "contain" && strategy !== "face_follow") {
    throw new Error(`advanced render does not support reframing strategy ${String(strategy)}`);
  }
  const names = input.asset_names ?? {};
  const typography = input.typography ?? [];
  const typeVisible = typography.some((item) => active(frame, item.interval));
  const typeText = typography.map((item) => item.text ?? "").join(" ");
  const diagram = (input.diagrams ?? []).find((item) => active(frame, item.interval));
  const emphasis = (input.emphasis ?? []).filter(
    (item) => frame >= frameAt(item.output_start_us) && frame < frameAt(item.output_end_us),
  );
  const speech = input.speech_name ?? "asr.flac";
  const picture = input.base_video_name ?? "analysis.mp4";
  const contained = { width: "100%", height: "100%", objectFit: "contain" as const };
  const followed = strategy === "face_follow" ? placedVideo(windowAt(frame, input.windows ?? [])) : null;
  return (
    <AbsoluteFill style={{ backgroundColor: NEUTRAL_DARK }}>
      {followed === null ? (
        <OffthreadVideo
          src={staticFile(picture)}
          durationInFrames={input.duration_in_frames}
          muted
          style={contained}
        />
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
      <Audio src={staticFile(speech)} durationInFrames={input.duration_in_frames} />
      {names.narration && /^[A-Za-z0-9._-]{1,80}$/.test(names.narration) ? (
        <Audio src={staticFile(names.narration)} />
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
                style={contained}
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
        <AbsoluteFill>
          <div style={{ position: "absolute", left: 140, top: 320, width: 280, height: 280, backgroundColor: "#ff00ff" }} />
          <div style={{ position: "absolute", left: 520, top: 320, width: 280, height: 280, backgroundColor: "#00ffff" }} />
          <div style={{ position: "absolute", left: 160, top: 340, color: "#000000", fontFamily: "sans-serif", fontSize: 36 }}>
            {diagram.payload?.left_label} {diagram.payload?.left_value}
          </div>
          <div style={{ position: "absolute", left: 540, top: 340, color: "#000000", fontFamily: "sans-serif", fontSize: 36 }}>
            {diagram.payload?.right_label} {diagram.payload?.right_value}
          </div>
        </AbsoluteFill>
      )}
      {typeVisible ? (
        <div
          style={{
            position: "absolute",
            left: 72,
            top: 1480,
            width: 936,
            height: 220,
            backgroundColor: "#ffff00",
            color: "#000000",
            fontFamily: "sans-serif",
            fontSize: 64,
            fontWeight: 700,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
          }}
        >
          {typeText}
        </div>
      ) : null}
      {emphasis.length === 0 ? null : (
        <div style={{ position: "absolute", left: 72, top: 1720, color: "#ffffff", fontFamily: "sans-serif", fontSize: 28 }}>
          {emphasis.map((item) => item.text ?? "").join(" ")}
        </div>
      )}
    </AbsoluteFill>
  );
}
