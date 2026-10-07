import { AbsoluteFill, Audio, interpolate, OffthreadVideo, Sequence, staticFile, useCurrentFrame } from "remotion";

import { CaptionPlate, type CaptionVariant } from "../captions/CaptionPlate.js";
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
  style_id?: "legacy-v1" | "editorial-clean-v1";
  style_fingerprint?: string;
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

function captionVariant(index: number, count: number): CaptionVariant {
  if (index === 0) return "hook";
  if (index === count - 1) return "punch";
  return "body";
}

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
  const style = input.style_id ?? "legacy-v1";
  if (style !== "legacy-v1" && style !== "editorial-clean-v1") {
    throw new Error(`unsupported motion style ${String(style)}`);
  }
  if (style === "editorial-clean-v1" && !/^[0-9a-f]{64}$/.test(input.style_fingerprint ?? "")) {
    throw new Error("editorial-clean-v1 requires a style fingerprint");
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
  const activeDesignedCard = typography.find(
    (item) =>
      active(frame, item.interval) &&
      (item.component_id === "hook-card-v1" || item.component_id === "punch-card-v1"),
  );
  const hasDesignedHook = typography.some((item) => item.component_id === "hook-card-v1");
  const cardText = activeDesignedCard?.text?.replace(/\s+/g, " ").trim().toLowerCase();
  const visibleCaptions = captions.filter((item) => {
    if (!active(frame, item.interval) || (item.text ?? "").trim().length === 0) return false;
    if (!cardText) return true;
    const captionText = (item.text ?? "").replace(/\s+/g, " ").trim().toLowerCase();
    return !captionText.includes(cardText);
  });
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
        return (
          <Sequence key={`sfx-${name}-${window.from}`} from={window.from} durationInFrames={window.duration}>
            <Audio src={staticFile(name)} volume={linearVolume(item.gain_db ?? 0)} />
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
          const index = captions.indexOf(item);
          const activeWord =
            style === "editorial-clean-v1" &&
            !language.startsWith("ar") &&
            !language.startsWith("ja")
              ? item.words?.find(
                  (word) =>
                    frame >= Number(word.output_start_frame ?? frameAt(word.output_start_us)) &&
                    frame < Number(word.output_end_frame_exclusive ?? frameAt(word.output_end_us)),
                )?.text
              : undefined;
          return (
            <CaptionPlate
              key={`${item.component_id ?? "caption"}-${item.event_id ?? ""}-${item.text}`}
              text={(item.text ?? "").trim()}
              language={item.language || language}
              variant={style === "editorial-clean-v1" ? (hasDesignedHook && index === 0 ? "body" : captionVariant(index, captions.length)) : "body"}
              emphasisText={activeWord ?? (style === "editorial-clean-v1" ? activeEmphasis : undefined)}
            />
          );
        })()
      ))}
      {visibleType.map((item) => (
        <CaptionPlate
          key={`${item.component_id ?? "type"}-${item.text}`}
          text={item.text ?? ""}
          language={item.language || language}
          variant={style === "editorial-clean-v1" && item.component_id === "hook-card-v1" ? "hook" : style === "editorial-clean-v1" && item.component_id === "punch-card-v1" ? "punch" : "typography"}
          emphasisText={style === "editorial-clean-v1" ? activeEmphasis : undefined}
          x={item.x}
          y={item.y}
          fontSize={item.font_size}
        />
      ))}
      {style === "editorial-clean-v1" ? <AbsoluteFill style={{ pointerEvents: "none" }}>
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
            background: "linear-gradient(90deg, #ffcf4a, #3ddbd6, #ffcf4a)",
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
            background: "linear-gradient(90deg, #3ddbd6, #ffcf4a)",
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
