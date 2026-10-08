import { AbsoluteFill, Audio, interpolate, OffthreadVideo, Sequence, staticFile, useCurrentFrame } from "remotion";
import type { CSSProperties } from "react";

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
  x?: number;
  y?: number;
  font_size?: number;
  color?: string;
  words?: readonly {
    word_id?: string;
    text?: string;
    output_start_us?: number;
    output_end_us?: number;
    output_start_frame?: number;
    output_end_frame_exclusive?: number;
  }[];
};

type DiagramEvent = {
  event_id?: string;
  component_id?: string;
  interval?: Interval;
  kind?: string;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: {
    kind?: string;
    left_label?: string;
    right_label?: string;
    left_value?: number;
    right_value?: number;
    left_display?: string;
    right_display?: string;
  };
};

type BrollEvent = {
  asset_id?: string;
  interval?: Interval;
  broll_source_in_us?: number;
  source_evidence_ids?: string[];
  relevance_note?: string;
};

type SfxEvent = {
  asset_id?: string;
  interval?: Interval;
  gain_db?: number;
  fade_in_us?: number;
  fade_out_us?: number;
  sfx_source_in_us?: number;
  role?: string;
  source_evidence_ids?: string[];
  purpose?: string;
  relevance_note?: string;
};

type EmphasisEvent = { text?: string; output_start_us?: number; output_end_us?: number };

type MotionStyle = {
  style_id?: string;
  easing?: string;
  enter_frames?: number;
  exit_frames?: number;
  max_travel_px?: number;
  max_scale_permille?: number;
  caption_mode?: "phrase_active_word" | "phrase_whole_run";
  contrast?: string;
  accent?: string;
};

export type AdvancedHeroInput = {
  duration_in_frames: number;
  style_id?:
    | "legacy-v1"
    | "editorial-clean-v1"
    | "kinetic-caption-v1"
    | "documentary-broll-v1"
    | "data-explainer-v1"
    | "paper-explainer-v1"
    | "premium-minimal-v1";
  style_fingerprint?: string;
  direction_id?: string;
  direction_sha256?: string;
  profile_fingerprint?: string;
  alignment_sha256?: string;
  hero_plan_sha256?: string;
  advanced_plan_sha256?: string;
  time_map_sha256?: string;
  source_sha256?: string;
  motion_style?: MotionStyle;
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
  // A positive cue shorter than one output frame still owns the frame that
  // contains its start. This preserves the half-open interval while avoiding
  // an invisible one-word caption after integer frame conversion.
  const end = Math.max(start + 1, frameAt(interval?.output_end_us));
  return frame >= start && frame < end;
}

function span(interval: Interval | undefined): { from: number; duration: number } {
  const from = frameAt(interval?.output_start_us);
  const end = frameAt(interval?.output_end_us);
  return { from, duration: Math.max(1, end - from) };
}

function eased(value: number, easing: string | undefined): number {
  const clamped = Math.max(0, Math.min(1, value));
  if (easing === "ease_in_out_cubic") {
    return clamped < 0.5 ? 4 * clamped * clamped * clamped : 1 - Math.pow(-2 * clamped + 2, 3) / 2;
  }
  if (easing === "ease_out_cubic") {
    return 1 - Math.pow(1 - clamped, 3);
  }
  return clamped;
}

function motionFor(frame: number, interval: Interval | undefined, style: MotionStyle | undefined): CSSProperties {
  if (!style || style.style_id === "legacy-v1") {
    return {};
  }
  const start = frameAt(interval?.output_start_us);
  const end = Math.max(start + 1, frameAt(interval?.output_end_us));
  const duration = end - start;
  const enter = Math.min(Math.max(0, style.enter_frames ?? 0), Math.floor(duration / 3));
  const exit = Math.min(Math.max(0, style.exit_frames ?? 0), Math.floor(duration / 3));
  const enterProgress = enter === 0 ? 1 : eased((frame - start) / enter, style.easing);
  const exitProgress = exit === 0 ? 1 : eased((end - frame) / exit, style.easing);
  // Captions must be readable on their first/last owned frame. Motion never
  // turns a short forced cue into an invisible fade.
  const opacity = 0.85 + 0.15 * Math.min(1, enterProgress, exitProgress);
  const travel = Math.max(0, style.max_travel_px ?? 0);
  const entranceOffset = (1 - enterProgress) * travel;
  const exitOffset = (1 - exitProgress) * -travel * 0.5;
  const scaleMax = Math.max(1000, style.max_scale_permille ?? 1000) / 1000;
  const scale = 1 + (scaleMax - 1) * enterProgress * (1 - exitProgress);
  return {
    opacity,
    transform: `translate3d(0, ${entranceOffset + exitOffset}px, 0) scale(${scale})`,
    transformOrigin: "center center",
  };
}

/**
 * Advanced portrait draft. Contain keeps the whole source picture.
 * Text nodes are React children. A face box is not a speaker. Music is not a layer.
 */
export function AdvancedHeroDraft(input: AdvancedHeroInput) {
  const frame = useCurrentFrame();
  const strategy = input.reframing_strategy ?? "contain";
  const style = input.style_id ?? "legacy-v1";
  const productionStyles = new Set([
    "editorial-clean-v1",
    "kinetic-caption-v1",
    "documentary-broll-v1",
    "data-explainer-v1",
    "paper-explainer-v1",
    "premium-minimal-v1",
  ]);
  if (style !== "legacy-v1" && !productionStyles.has(style)) {
    throw new Error(`unsupported motion style ${String(style)}`);
  }
  if (style !== "legacy-v1" && !/^[0-9a-f]{64}$/.test(input.style_fingerprint ?? "")) {
    throw new Error(`${style} requires a style fingerprint`);
  }
  if (style !== "legacy-v1") {
    for (const [key, value] of Object.entries({
      profile_fingerprint: input.profile_fingerprint,
      alignment_sha256: input.alignment_sha256,
      hero_plan_sha256: input.hero_plan_sha256,
      advanced_plan_sha256: input.advanced_plan_sha256,
      time_map_sha256: input.time_map_sha256,
      source_sha256: input.source_sha256,
    })) {
      if (!/^[0-9a-f]{64}$/.test(value ?? "")) {
        throw new Error(`production advanced render requires ${key}`);
      }
    }
    if (!input.direction_id || !/^[0-9a-f]{64}$/.test(input.direction_sha256 ?? "")) {
      throw new Error("production advanced render requires a persisted direction binding");
    }
    for (const event of input.broll ?? []) {
      if (!event.source_evidence_ids?.length || !event.relevance_note?.trim()) {
        throw new Error("production B-roll requires source evidence and relevance");
      }
    }
    for (const event of input.sfx ?? []) {
      if (!event.source_evidence_ids?.length || !event.relevance_note?.trim() || !event.purpose) {
        throw new Error("production SFX requires source evidence, purpose, and relevance");
      }
    }
  }
  if (input.motion_style && input.motion_style.style_id !== style) {
    throw new Error("motion style payload does not match style_id");
  }
  if (input.debug_overlays === true) {
    throw new Error("production advanced renders reject debug overlays");
  }
  if (strategy !== "contain" && strategy !== "center_crop" && strategy !== "face_follow") {
    throw new Error(`advanced render does not support reframing strategy ${String(strategy)}`);
  }
  const names = input.asset_names ?? {};
  const captions = input.captions ?? [];
  const typography = input.typography ?? [];
  const visibleCaptions = captions.filter(
    (item) => active(frame, item.interval) && (item.text ?? "").trim().length > 0,
  );
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
  const motionStyle = input.motion_style;
  const diagram = (input.diagrams ?? []).find((item) => active(frame, item.interval));
  if (diagram && (diagram.payload?.kind ?? "number_comparison") !== "number_comparison") {
    throw new Error(`unsupported production diagram kind ${String(diagram.payload?.kind)}`);
  }
  if (diagram) {
    const x = diagram.x ?? 120;
    const y = diagram.y ?? 280;
    const width = diagram.width ?? 840;
    const height = diagram.height ?? 360;
    if (x < 48 || y < 48 || width < 80 || height < 80 || x + width > 1032 || y + height > 1872) {
      throw new Error("diagram geometry is outside the production safe area");
    }
  }
  const emphasis = (input.emphasis ?? []).filter(
    (item) => frame >= frameAt(item.output_start_us) && frame < frameAt(item.output_end_us),
  );
  const activeEmphasis = emphasis[0]?.text?.replace(/\s+/g, " ").trim();
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
        const fadeIn = Math.max(0, Math.round((item.fade_in_us ?? 20_000) * FPS / 1_000_000));
        const fadeOut = Math.max(0, Math.round((item.fade_out_us ?? 60_000) * FPS / 1_000_000));
        const baseGain = linearVolume(item.gain_db ?? -18);
        return (
          <Sequence key={`sfx-${name}-${window.from}`} from={window.from} durationInFrames={window.duration}>
            <Audio
              src={staticFile(name)}
              trimBefore={frameAt(item.sfx_source_in_us)}
              volume={(localFrame) => {
                const remaining = window.duration - localFrame;
                const inScale = fadeIn > 0 ? Math.min(1, (localFrame + 1) / fadeIn) : 1;
                const outScale = fadeOut > 0 ? Math.min(1, Math.max(0, remaining / fadeOut)) : 1;
                return baseGain * Math.min(inScale, outScale);
              }}
            />
          </Sequence>
        );
      })}
      {diagram === undefined ? null : (
        <AbsoluteFill style={{ left: diagram.x ?? 120, top: diagram.y ?? 280, width: diagram.width ?? 840, height: diagram.height ?? 360, display: "flex", justifyContent: "center" }}>
          <div
            style={{
              width: "100%",
              height: "100%",
              borderRadius: 28,
              background: "linear-gradient(135deg, rgba(8,14,28,0.95), rgba(21,48,59,0.9))",
              border: "2px solid rgba(255,207,74,0.78)",
              color: "#ffffff",
              fontFamily: "'Arial Black', 'Liberation Sans Narrow', 'DejaVu Sans', sans-serif",
              fontSize: 36,
              fontWeight: 800,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-evenly",
              textAlign: "center",
              boxShadow: "0 16px 40px rgba(0,0,0,0.4)",
            }}
          >
            <div>
              <div>{diagram.payload?.left_label}</div>
              <strong>{diagram.payload?.left_display ?? diagram.payload?.left_value}</strong>
            </div>
            <div style={{ opacity: 0.6 }}>vs</div>
            <div>
              <div>{diagram.payload?.right_label}</div>
              <strong>{diagram.payload?.right_display ?? diagram.payload?.right_value}</strong>
            </div>
          </div>
        </AbsoluteFill>
      )}
      {visibleCaptions.map((item) => (
        (() => {
          const activeWord =
            style !== "legacy-v1" &&
            motionStyle?.caption_mode === "phrase_active_word" &&
            !language.startsWith("ar") &&
            !language.startsWith("ja")
              ? item.words?.find(
                  (word) =>
                    frame >= Number(word.output_start_frame ?? frameAt(word.output_start_us)) &&
                    frame < Number(word.output_end_frame_exclusive ?? frameAt(word.output_end_us)),
                )?.text
              : undefined;
          return (
            <AbsoluteFill
              key={`${item.component_id ?? "caption"}-${item.event_id ?? ""}-${item.text}`}
              style={{ pointerEvents: "none", ...motionFor(frame, item.interval, motionStyle) }}
            >
              <CaptionPlate
                text={(item.text ?? "").trim()}
                language={item.language || language}
                variant="body"
                emphasisText={activeWord ?? (style !== "legacy-v1" ? activeEmphasis : undefined)}
              />
            </AbsoluteFill>
          );
        })()
      ))}
      {visibleType.map((item) => (
        <AbsoluteFill
          key={`${item.component_id ?? "type"}-${item.text}`}
          style={{ pointerEvents: "none", ...motionFor(frame, item.interval, motionStyle) }}
        >
          <CaptionPlate
            text={item.text ?? ""}
            language={item.language || language}
            variant={style !== "legacy-v1" && item.component_id === "hook-card-v1" ? "hook" : style !== "legacy-v1" && item.component_id === "punch-card-v1" ? "punch" : "typography"}
            emphasisText={style !== "legacy-v1" ? activeEmphasis : undefined}
            x={item.x}
            y={item.y}
            fontSize={item.font_size}
          />
        </AbsoluteFill>
      ))}
      {style !== "legacy-v1" ? <AbsoluteFill style={{ pointerEvents: "none" }}>
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "linear-gradient(115deg, rgba(255,207,74,0.18), transparent 24%, transparent 76%, rgba(61,219,214,0.16))",
            opacity: interpolate(frame, [0, 10, 24], [0.9, 0.22, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          }}
        />
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: 12,
            background: `linear-gradient(90deg, ${motionStyle?.accent ?? "#ffcf4a"}, #3ddbd6, ${motionStyle?.accent ?? "#ffcf4a"})`,
            opacity: interpolate(frame, [0, 8, 18], [1, 0.7, 0.18], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
          }}
        />
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: 10,
            background: `linear-gradient(90deg, #3ddbd6, ${motionStyle?.accent ?? "#ffcf4a"})`,
            opacity: interpolate(
              frame,
              [Math.max(0, input.duration_in_frames - 18), Math.max(1, input.duration_in_frames - 6), input.duration_in_frames - 1],
              [0.12, 0.6, 1],
              { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
            ),
          }}
        />
      </AbsoluteFill> : null}
    </AbsoluteFill>
  );
}
