import { AbsoluteFill, Audio, Img, interpolate, Sequence, staticFile, useCurrentFrame, Video } from "remotion";
import type { CSSProperties } from "react";

import { CaptionPlate } from "../captions/CaptionPlate.js";
import { captionFontFamily, useCaptionFonts } from "../captions/fonts.js";
import { placedVideo, windowAt, type CropWindow } from "./crop.js";
import { linearVolume } from "./gain.js";
import { MotionGraphicCard, type MotionGraphic } from "./MotionGraphic.js";
import { ConcatTransitionOverlay, type ConcatTransitionStyle } from "./ConcatMotion.js";
import { cueWindow, frameAtOrAfter } from "./program-frames.js";
import { containRect } from "./portrait-transform.js";

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
      verification_status?: "unverified" | "correct" | "incorrect";
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

type TransitionEvent = {
  event_id?: string;
  interval?: Interval;
  style?: ConcatTransitionStyle;
};

type SourceNativeText = {
  region_id?: string;
  interval?: Interval;
  text?: string;
  visual_scene_ids?: string[];
  note?: string;
};

type MotionStyle = {
  style_id?: string;
  easing?: string;
  enter_frames?: number;
  exit_frames?: number;
  max_travel_px?: number;
  max_scale_permille?: number;
  caption_mode?: "phrase_active_word" | "phrase_whole_run";
  contrast?: string;
  font_identity?: string;
  font_sha256?: string[];
  safe_left?: number;
  safe_right?: number;
  safe_top?: number;
  safe_bottom?: number;
  max_simultaneous_emphasis?: number;
  accent?: string;
};

type CampaignOverlaySpec = {
  campaign_id: "tarteel";
  cta_asset_id: string;
  cta_asset_sha256: string;
  cta_asset_name: string;
  cta_background_removal: "chroma_key_v1";
  cta_render_mode: "alpha_video_v1" | "alpha_png_sequence_v1";
  cta_frame_prefix?: string;
  cta_frame_count?: number;
  cta_frame_rate: 30;
  cta_position: "foreground_attention_v1" | "top_left_brand_rail_v1";
  overlay_coordinate_space: "foreground_v1" | "canvas_v1";
  cta_clearance: "faces_and_captions_clear_v1";
  cta_left_permille: number;
  cta_top_permille: number;
  cta_width_permille: number;
  cta_start_us: number;
  cta_end_us: number;
  watermark_asset_id: string;
  watermark_asset_sha256: string;
  watermark_asset_name: string;
  watermark_mode: "alpha_v1";
  watermark_position: "foreground_top_right_v1" | "top_right";
  watermark_visibility: "overlay_required_v1" | "source_visible_v1";
  watermark_width_permille: number;
  first_post_caption_line: "اشترك في قناة ترتيل على اليوتيوب: @tarteelarabic";
};

export type AdvancedHeroInput = {
  renderer_recipe_version?: "advanced-hero-renderer-v1" | "advanced-hero-renderer-clean-v1" | "advanced-hero-renderer-directed-v2" | "advanced-hero-renderer-directed-v3" | "advanced-hero-renderer-directed-v4";
  duration_in_frames: number;
  style_id?:
    | "legacy-v1"
    | "editorial-clean-v1"
    | "quran-editorial-v1"
    | "concat-editorial-v1"
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
  hero_review_status?: "approved" | "pending";
  advanced_plan_sha256?: string;
  time_map_sha256?: string;
  source_sha256?: string;
  motion_style?: MotionStyle;
  reframing_strategy?: string;
  base_video_name?: string;
  speech_name?: string;
  campaign_overlay?: CampaignOverlaySpec;
  captions?: TypeEvent[];
  typography?: TypeEvent[];
  diagrams?: DiagramEvent[];
  motion_graphics?: MotionGraphic[];
  source_native_text?: SourceNativeText[];
  broll?: BrollEvent[];
  sfx?: SfxEvent[];
  emphasis?: EmphasisEvent[];
  transitions?: TransitionEvent[];
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
  const start = frameAtOrAfter(interval?.output_start_us);
  // A positive cue shorter than one output frame still owns the frame that
  // contains its start. This preserves the half-open interval while avoiding
  // an invisible one-word caption after integer frame conversion.
  const end = Math.max(start + 1, frameAtOrAfter(interval?.output_end_us));
  return frame >= start && frame < end;
}

function normalizedCaptionTokens(value: string): string[] {
  return value
    .toLocaleLowerCase()
    .replace(/you're/g, "you are")
    .replace(/\u2019re/g, " you are")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
}

function nativeCaptionDuplicate(caption: TypeEvent, native: SourceNativeText): boolean {
  const captionStart = caption.interval?.output_start_us ?? 0;
  const captionEnd = caption.interval?.output_end_us ?? captionStart;
  const nativeStart = native.interval?.output_start_us ?? 0;
  const nativeEnd = native.interval?.output_end_us ?? nativeStart;
  if (captionEnd <= nativeStart || nativeEnd <= captionStart) return false;
  const captionTokens = normalizedCaptionTokens(caption.text ?? "");
  const nativeTokens = new Set(normalizedCaptionTokens(native.text ?? ""));
  return captionTokens.length >= 4 && captionTokens.every((token) => nativeTokens.has(token));
}

function span(interval: Interval | undefined): { from: number; duration: number } {
  return cueWindow(interval?.output_start_us, interval?.output_end_us);
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
  const start = frameAtOrAfter(interval?.output_start_us);
  const end = Math.max(start + 1, frameAtOrAfter(interval?.output_end_us));
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
  const modernLayout = input.renderer_recipe_version === "advanced-hero-renderer-directed-v4";
  const motionStyle = input.motion_style;
  const fontsReady = useCaptionFonts(modernLayout, motionStyle?.font_identity);
  const strategy = input.reframing_strategy ?? "contain";
  const style = input.style_id ?? "legacy-v1";
  const productionStyles = new Set([
    "editorial-clean-v1",
    "concat-editorial-v1",
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
    const motionStyle = input.motion_style;
    if (modernLayout && (
      !motionStyle ||
      typeof motionStyle.font_identity !== "string" ||
      motionStyle.font_identity.trim().length === 0 ||
      !Array.isArray(motionStyle.font_sha256) ||
      motionStyle.font_sha256.some((digest) => !/^[0-9a-f]{64}$/.test(digest)) ||
      ![motionStyle.safe_left, motionStyle.safe_right, motionStyle.safe_top, motionStyle.safe_bottom].every(
        (value) => typeof value === "number" && Number.isInteger(value) && value >= 0,
      )
    )) {
      throw new Error("production advanced render requires complete caption style dependencies");
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
  if (
    strategy !== "contain" &&
    strategy !== "center_crop" &&
    strategy !== "face_follow" &&
    strategy !== "manual_window"
  ) {
    throw new Error(`advanced render does not support reframing strategy ${String(strategy)}`);
  }
  const names = input.asset_names ?? {};
  if (input.campaign_overlay) {
    if (
      input.campaign_overlay.campaign_id !== "tarteel" ||
      input.campaign_overlay.cta_background_removal !== "chroma_key_v1" ||
      (input.campaign_overlay.cta_render_mode !== "alpha_video_v1" && input.campaign_overlay.cta_render_mode !== "alpha_png_sequence_v1") ||
      (input.campaign_overlay.cta_position !== "foreground_attention_v1" && input.campaign_overlay.cta_position !== "top_left_brand_rail_v1") ||
      input.campaign_overlay.overlay_coordinate_space !== "foreground_v1" ||
      input.campaign_overlay.watermark_mode !== "alpha_v1" ||
      (input.campaign_overlay.watermark_position !== "foreground_top_right_v1" && input.campaign_overlay.watermark_position !== "top_right") ||
      names[input.campaign_overlay.cta_asset_id] !== (input.campaign_overlay.cta_render_mode === "alpha_video_v1" ? input.campaign_overlay.cta_asset_name : input.campaign_overlay.cta_frame_prefix) ||
      names[input.campaign_overlay.watermark_asset_id] !== input.campaign_overlay.watermark_asset_name
    ) {
      throw new Error("invalid Tarteel campaign overlay binding");
    }
  }
  const captions = input.captions ?? [];
  const typography = input.typography ?? [];
  const visibleType = typography.filter(
    (item) => active(frame, item.interval) && (item.text ?? "").trim().length > 0,
  );
  const visibleNativeText = (input.source_native_text ?? []).filter(
    (item) => active(frame, item.interval) && (item.text ?? "").trim().length > 0,
  );
  const visibleCaptions = captions.filter(
    (item) =>
      active(frame, item.interval) &&
      (item.text ?? "").trim().length > 0 &&
      !visibleNativeText.some((native) => nativeCaptionDuplicate(item, native)),
  );
  const rawLanguage = input.language?.trim();
  // Legacy/offline fixtures may omit locale evidence. Keep the layout
  // deterministic without treating the sentinel as a supported locale claim.
  const language = !rawLanguage || rawLanguage === "missing" ? "en-US" : rawLanguage;
  const diagram = (input.diagrams ?? []).find((item) => active(frame, item.interval));
  const motionGraphics = (input.motion_graphics ?? []).filter((item) => active(frame, item.interval));
  const transitions = (input.transitions ?? []).filter((item) => active(frame, item.interval));
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
    (item) => frame >= frameAtOrAfter(item.output_start_us) && frame < frameAtOrAfter(item.output_end_us),
  );
  const activeEmphasis = emphasis[0]?.text?.replace(/\s+/g, " ").trim();
  const speech = input.speech_name ?? "asr.flac";
  const picture = input.base_video_name ?? "analysis.mp4";
  const contained = { width: "100%", height: "100%", objectFit: "contain" as const };
  const sourceWindow = input.windows?.[0];
  const legacyGeometry = input.renderer_recipe_version !== "advanced-hero-renderer-directed-v4";
  if (!legacyGeometry && !sourceWindow) {
    throw new Error("portrait transform requires source dimensions in a reframing window");
  }
  const containBox = sourceWindow
    ? containRect(sourceWindow.frame_width, sourceWindow.frame_height, 1080, 1920)
    : containRect(1080, 1920, 1080, 1920);
  const campaignForegroundTransform = input.campaign_overlay
    ? { transform: "scale(1.08)", transformOrigin: "center center" }
    : {};
  const followed =
    strategy === "face_follow" || strategy === "center_crop" || strategy === "manual_window"
      ? placedVideo(windowAt(frame, input.windows ?? []))
      : null;
  if (!fontsReady) return null;
  return (
      <AbsoluteFill style={{ backgroundColor: NEUTRAL_DARK }}>
      {followed === null ? (
        <AbsoluteFill style={{ overflow: "hidden" }}>
          <Video
            src={staticFile(picture)}
            durationInFrames={input.duration_in_frames}
            muted
            style={{ ...contained, objectFit: "cover", filter: "blur(24px)", transform: "scale(1.08)", opacity: 0.72 }}
          />
          {legacyGeometry ? (
            <AbsoluteFill style={sourceWindow ? { width: "100%", aspectRatio: `${sourceWindow.frame_width} / ${sourceWindow.frame_height}`, top: "50%", transform: "translateY(-50%)" } : { inset: 0 }}>
              <Video src={staticFile(picture)} durationInFrames={input.duration_in_frames} muted style={{ width: "100%", height: "100%", objectFit: "fill" }} />
            </AbsoluteFill>
          ) : <div style={{ position: "absolute", ...containBox, ...campaignForegroundTransform }}>
            <Video
              src={staticFile(picture)}
              durationInFrames={input.duration_in_frames}
              muted
              style={{ width: "100%", height: "100%", objectFit: "contain" }}
            />
          </div>}
        </AbsoluteFill>
      ) : (
        <AbsoluteFill style={{ overflow: "hidden" }}>
          <Video
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
      {input.campaign_overlay ? (
        <div
          style={
            followed === null && !legacyGeometry
              ? { position: "absolute", ...containBox, ...campaignForegroundTransform, overflow: "hidden" }
              : { position: "absolute", inset: 0, overflow: "hidden" }
          }
        >
          {input.campaign_overlay.watermark_visibility === "source_visible_v1" ? null : (
            <Img
              src={staticFile(input.campaign_overlay.watermark_asset_name)}
              style={{
                position: "absolute",
                top: 18,
                right: 18,
                width: `${input.campaign_overlay.watermark_width_permille / 10}%`,
                height: "auto",
                objectFit: "contain",
                filter: "drop-shadow(0 4px 9px rgba(0,0,0,.6))",
              }}
            />
          )}
          <Sequence
            from={frameAt(input.campaign_overlay.cta_start_us)}
            durationInFrames={Math.max(
              1,
              Math.ceil(((input.campaign_overlay.cta_end_us - input.campaign_overlay.cta_start_us) * 30) / 1_000_000),
            )}
          >
            <CampaignCta
              overlay={input.campaign_overlay}
              localFrame={frame - frameAt(input.campaign_overlay.cta_start_us)}
            />
          </Sequence>
        </div>
      ) : null}
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
              <Video
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
      {motionGraphics.map((graphic) => {
        if (
          graphic.template !== "credit_card" &&
          graphic.template !== "travel_postcard" &&
          graphic.template !== "business_identity" &&
          graphic.template !== "business_spotlight"
        ) {
          throw new Error(`unsupported production motion graphic ${String(graphic.template)}`);
        }
        if (!graphic.source_evidence_ids?.length || !(graphic.display_text ?? "").trim()) {
          throw new Error("production motion graphic requires source evidence and source text");
        }
        const x = graphic.x ?? 72;
        const y = graphic.y ?? 760;
        const width = graphic.width ?? 420;
        const height = graphic.height ?? 300;
        if (x < 48 || y < 120 || width < 220 || height < 180 || x + width > 1032 || y + height > 1480) {
          throw new Error("motion graphic geometry is outside the production graphic region");
        }
        const graphicText = (graphic.display_text ?? "").replace(/\s+/g, " ").trim().toLowerCase();
        const duplicateCaption = visibleCaptions.some((caption) => {
          const captionText = (caption.text ?? "").replace(/\s+/g, " ").trim().toLowerCase();
          return Boolean(graphicText) && (captionText.includes(graphicText) || graphicText.includes(captionText));
        });
        return (
          <MotionGraphicCard
            key={graphic.event_id ?? `${graphic.template}-${graphic.display_text}`}
            graphic={graphic}
            accent={motionStyle?.accent ?? "#64d8ff"}
            fontFamily={captionFontFamily(motionStyle?.font_identity, "typography")}
            showLabel={!duplicateCaption}
          />
        );
      })}
      {transitions.map((transition) => {
        if (
          transition.style !== undefined &&
          transition.style !== "clean_cut_v1" &&
          transition.style !== "concat_push_v1" &&
          transition.style !== "concat_blur_dissolve_v1"
        ) {
          throw new Error(`unsupported production transition ${String(transition.style)}`);
        }
        const start = frameAtOrAfter(transition.interval?.output_start_us);
        const local = Math.max(0, frame - start);
        const duration = Math.max(1, frameAtOrAfter(transition.interval?.output_end_us) - start);
        const progress = Math.min(1, local / duration);
        return (
          <ConcatTransitionOverlay
            key={`transition-${transition.event_id ?? start}`}
            style={transition.style ?? "clean_cut_v1"}
            progress={eased(progress, motionStyle?.easing)}
            accent={motionStyle?.accent ?? "#ffcf4a"}
          />
        );
      })}
      {visibleCaptions.map((item) => (
        (() => {
          const activeWord =
            style !== "legacy-v1" &&
            motionStyle?.caption_mode === "phrase_active_word" &&
            (item.words?.some((word) => word.verification_status === "correct" || word.verification_status === "incorrect") ||
              (!language.startsWith("ar") && !language.startsWith("ja")))
              ? item.words?.find(
                  (word) =>
                    frame >= Number(word.output_start_frame ?? frameAtOrAfter(word.output_start_us)) &&
                    frame < Number(word.output_end_frame_exclusive ?? frameAtOrAfter(word.output_end_us)),
                )?.text
              : undefined;
          const activeWordRecord =
            style !== "legacy-v1" &&
            motionStyle?.caption_mode === "phrase_active_word" &&
            (item.words?.some((word) => word.verification_status === "correct" || word.verification_status === "incorrect") ||
              (!language.startsWith("ar") && !language.startsWith("ja")))
              ? item.words?.find(
                  (word) =>
                    frame >= Number(word.output_start_frame ?? frameAtOrAfter(word.output_start_us)) &&
                    frame < Number(word.output_end_frame_exclusive ?? frameAtOrAfter(word.output_end_us)),
                )
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
                emphasisStatus={activeWordRecord?.verification_status}
                wordStatuses={item.words}
                style={modernLayout ? motionStyle : undefined}
                layoutVersion={modernLayout ? "caption-layout-v2" : "caption-layout-v1"}
              />
            </AbsoluteFill>
          );
        })()
      ))}
      {visibleType.map((item) => {
        const text = (item.text ?? "").replace(/\s+/g, " ").trim().toLowerCase();
        const duplicatesCaption = visibleCaptions.some((caption) =>
          (() => {
            const captionText = caption.text?.replace(/\s+/g, " ").trim().toLowerCase() ?? "";
            return captionText.includes(text) || text.includes(captionText);
          })(),
        );
        const duplicatesNativeText = visibleNativeText.some((native) =>
          nativeCaptionDuplicate(item, native),
        );
        const isHook = item.component_id === "hook-card-v1";
        const isPunch = item.component_id === "punch-card-v1";
        const left = item.x ?? 72;
        const top = item.y ?? (isHook ? 220 : isPunch ? 1450 : 360);
        const accent = motionStyle?.accent ?? "#ffcf4a";
        return (
          <AbsoluteFill
            key={`${item.component_id ?? "type"}-${item.event_id ?? ""}-${item.text}`}
            style={{ pointerEvents: "none", ...motionFor(frame, item.interval, motionStyle) }}
          >
            {duplicatesCaption || duplicatesNativeText ? (
              <div
                style={{
                  position: "absolute",
                  left,
                  top: top + (isPunch ? -34 : 68),
                  width: isPunch ? 760 : isHook ? 620 : 520,
                  height: 14,
                  borderRadius: 7,
                  background: `linear-gradient(90deg, ${accent}, #3ddbd6 72%, transparent)`,
                  boxShadow: `0 4px 18px ${accent}55`,
                }}
              >
                <div
                  style={{
                    position: "absolute",
                    right: -2,
                    top: -5,
                    width: 24,
                    height: 24,
                    borderRadius: "50%",
                    border: `3px solid ${accent}`,
                    background: "rgba(11,18,32,0.9)",
                  }}
                />
              </div>
            ) : null}
            {!duplicatesCaption && !duplicatesNativeText ? (
              <CaptionPlate
                text={item.text ?? ""}
                language={item.language || language}
                variant={style !== "legacy-v1" && isHook ? "hook" : style !== "legacy-v1" && isPunch ? "punch" : "typography"}
                emphasisText={style !== "legacy-v1" ? activeEmphasis : undefined}
                x={item.x}
                y={item.y}
                fontSize={item.font_size}
                style={modernLayout ? motionStyle : undefined}
                layoutVersion={modernLayout ? "caption-layout-v2" : "caption-layout-v1"}
              />
            ) : null}
          </AbsoluteFill>
        );
      })}
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

function CampaignCta({
  overlay,
  localFrame,
}: {
  overlay: NonNullable<AdvancedHeroInput["campaign_overlay"]>;
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
