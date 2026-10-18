/**
 * Bundle AdvancedHeroDraft once, then render each batch item in order.
 *
 * Python writes the batch. This process does not read SQLite, approve
 * candidates, or accept an http(s) media URL. Staged analysis.mp4 and
 * asr.flac are served from this run's staging directory.
 */

import { mkdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stageCaptionFonts } from "./caption-fonts.mjs";

const isolationDir = process.argv[4];
if (typeof isolationDir === "string" && isolationDir.length > 0) {
  mkdirSync(isolationDir, { recursive: true });
  process.env.TMPDIR = isolationDir;
  process.env.TMP = isolationDir;
  process.env.TEMP = isolationDir;
}
const { bundle } = await import("@remotion/bundler");
const { renderMedia, selectComposition } = await import("@remotion/renderer");

const here = path.dirname(fileURLToPath(import.meta.url));
const entryPoint = path.resolve(here, "../src/hero/index.tsx");

const batchPath = process.argv[2];
const browserExecutable = process.argv[3];
if (!batchPath || !browserExecutable) {
  throw new Error("usage: node render-hero.mjs BATCH_JSON BROWSER_EXECUTABLE");
}

const batch = JSON.parse(readFileSync(batchPath, "utf8"));
if (!batch || !Array.isArray(batch.items) || batch.items.length !== 1) {
  throw new Error("hero render batch must contain exactly one item");
}

const runDir = path.resolve(path.dirname(batchPath));
const stagingDir = path.join(runDir, "staging");
const chromiumOptions = { gl: "swangle" };

function contained(filePath, root) {
  const resolved = path.resolve(filePath);
  const prefix = root.endsWith(path.sep) ? root : `${root}${path.sep}`;
  if (resolved !== root && !resolved.startsWith(prefix)) {
    throw new Error(`refusing to write outside the hero run: ${resolved}`);
  }
  return resolved;
}

for (const item of batch.items) {
  if (!item || typeof item !== "object") {
    throw new Error("hero render batch item was not an object");
  }
  contained(item.outputPath, runDir);
  if (item.renderMode !== undefined && !["video", "audio"].includes(item.renderMode)) {
    throw new Error("unsupported render unit mode");
  }
  const input = item.input;
  if (!input || typeof input !== "object") {
    throw new Error("hero render batch item is missing input");
  }
  if (item.frameRange !== undefined && (
    !Array.isArray(item.frameRange) || item.frameRange.length !== 2 ||
    !item.frameRange.every(Number.isSafeInteger) || item.frameRange[0] < 0 ||
    item.frameRange[1] < item.frameRange[0] || item.frameRange[1] >= input.duration_in_frames
  )) throw new Error("render unit frame range is invalid");
  if (input.composition_id !== "AdvancedHeroDraft") {
    throw new Error("advanced render refuses a composition other than AdvancedHeroDraft");
  }
  if (input.renderer_recipe_version === "advanced-hero-renderer-directed-v4") {
    stageCaptionFonts(stagingDir, input.motion_style?.font_sha256);
  }
  if (input.debug_overlays === true) {
    throw new Error("production advanced render rejects debug overlays");
  }
  if (input.campaign_overlay) {
    const overlay = input.campaign_overlay;
    if (
      overlay.campaign_id !== "tarteel" ||
      input.style_id !== "quran-editorial-v1" ||
      typeof input.quran_review_id !== "string" ||
      !/^[0-9a-f]{64}$/.test(input.quran_review_sha256 ?? "") ||
      overlay.cta_background_removal !== "chroma_key_v1" ||
      (overlay.cta_render_mode !== "alpha_video_v1" && overlay.cta_render_mode !== "alpha_png_sequence_v1") ||
      overlay.cta_frame_rate !== 30 ||
      overlay.cta_position !== "foreground_attention_v1" ||
      overlay.overlay_coordinate_space !== "foreground_v1" ||
      overlay.cta_clearance !== "faces_and_captions_clear_v1" ||
      overlay.sizing_method !== "source_frame_scan_v1" ||
      !/^[0-9a-f]{64}$/.test(overlay.sizing_measurement_sha256 ?? "") ||
      !Number.isInteger(overlay.cta_width_permille) || overlay.cta_width_permille < 80 || overlay.cta_width_permille > 600 ||
      overlay.watermark_mode !== "alpha_v1" ||
      overlay.watermark_position !== "foreground_top_right_v1" && overlay.watermark_position !== "top_right" ||
      typeof overlay.cta_asset_name !== "string" ||
      typeof overlay.watermark_asset_name !== "string" ||
      !/^[A-Za-z0-9._-]{1,80}$/.test(overlay.cta_asset_name) ||
      !/^[A-Za-z0-9._-]{1,80}$/.test(overlay.watermark_asset_name) ||
      !/^[0-9a-f]{64}$/.test(overlay.cta_asset_sha256) ||
      !/^[0-9a-f]{64}$/.test(overlay.watermark_asset_sha256) ||
      overlay.cta_end_us <= overlay.cta_start_us ||
      overlay.cta_end_us > input.output_duration_us
    ) {
      throw new Error("invalid Tarteel campaign overlay contract");
    }
    const names = new Set(Object.values(input.asset_names ?? {}));
    const ctaName = overlay.cta_render_mode === "alpha_video_v1" ? overlay.cta_asset_name : overlay.cta_frame_prefix;
    if (!names.has(ctaName) || !names.has(overlay.watermark_asset_name)) {
      throw new Error("campaign overlay files are not staged");
    }
    if (overlay.cta_render_mode === "alpha_png_sequence_v1" && (!/^[A-Za-z0-9._-]{1,80}$/.test(overlay.cta_frame_prefix) || !Number.isInteger(overlay.cta_frame_count) || overlay.cta_frame_count < 1 || overlay.cta_frame_count > 600)) {
      throw new Error("campaign overlay CTA frame sequence is invalid");
    }
  }
  const productionStyles = new Set([
    "editorial-clean-v1",
    "concat-editorial-v1",
    "kinetic-caption-v1",
    "documentary-broll-v1",
    "data-explainer-v1",
    "paper-explainer-v1",
    "premium-minimal-v1",
  ]);
  if (input.style_id !== undefined && input.style_id !== "legacy-v1" && !productionStyles.has(input.style_id)) {
    throw new Error(`unsupported motion style ${input.style_id}`);
  }
  if (input.style_id !== undefined && input.style_id !== "legacy-v1") {
    if (typeof input.style_fingerprint !== "string" || !/^[0-9a-f]{64}$/.test(input.style_fingerprint)) {
      throw new Error(`motion style ${input.style_id} requires a fingerprint`);
    }
    if (input.motion_style && input.motion_style.style_id !== input.style_id) {
      throw new Error("motion style payload does not match style_id");
    }
    const sha = /^[0-9a-f]{64}$/;
    for (const key of [
      "profile_fingerprint",
      "alignment_sha256",
      "hero_plan_sha256",
      "advanced_plan_sha256",
      "time_map_sha256",
      "source_sha256",
    ]) {
      if (typeof input[key] !== "string" || !sha.test(input[key])) {
        throw new Error(`production advanced render requires ${key}`);
      }
    }
    if (
      typeof input.direction_id !== "string" ||
      input.direction_id.length === 0 ||
      typeof input.direction_sha256 !== "string" ||
      !sha.test(input.direction_sha256)
    ) {
      throw new Error("production advanced render requires a persisted direction binding");
    }
  }
  for (const event of [...(input.typography ?? []), ...(input.captions ?? []), ...(input.diagrams ?? [])]) {
    const component = typeof event?.component_id === "string" ? event.component_id.toLowerCase() : "";
    if (component.includes("debug") || component.includes("fixture") || component.includes("marker")) {
      throw new Error("production advanced render rejects diagnostic-only events");
    }
  }
  for (const diagram of input.diagrams ?? []) {
    const kind = diagram?.payload?.kind ?? "number_comparison";
    if (kind !== "number_comparison") {
      throw new Error(`unsupported production diagram kind ${kind}`);
    }
    const x = diagram.x ?? 120;
    const y = diagram.y ?? 280;
    const width = diagram.width ?? 840;
    const height = diagram.height ?? 360;
    if (x < 48 || y < 48 || width < 80 || height < 80 || x + width > 1032 || y + height > 1872) {
      throw new Error("diagram geometry is outside the production safe area");
    }
  }
  const motionGraphicTemplates = new Set([
    "credit_card",
    "travel_postcard",
    "business_identity",
    "business_spotlight",
  ]);
  for (const graphic of input.motion_graphics ?? []) {
    if (!graphic || !motionGraphicTemplates.has(graphic.template)) {
      throw new Error(`unsupported production motion graphic ${String(graphic?.template)}`);
    }
    if (
      !Array.isArray(graphic.source_evidence_ids) ||
      graphic.source_evidence_ids.length === 0 ||
      !graphic.source_evidence_ids.every((item) => typeof item === "string" && item.length > 0) ||
      typeof graphic.display_text !== "string" ||
      graphic.display_text.trim().length === 0
    ) {
      throw new Error("production motion graphic requires source evidence and source text");
    }
    const { x, y, width, height } = graphic;
    if (
      !Number.isInteger(x) ||
      !Number.isInteger(y) ||
      !Number.isInteger(width) ||
      !Number.isInteger(height) ||
      x < 48 ||
      y < 120 ||
      width < 220 ||
      height < 180 ||
      x + width > 1032 ||
      y + height > 1480
    ) {
      throw new Error("motion graphic geometry is outside the production graphic region");
    }
  }
  if (
    input.reframing_strategy !== "contain" &&
    input.reframing_strategy !== "center_crop" &&
    input.reframing_strategy !== "face_follow" &&
    input.reframing_strategy !== "manual_window"
  ) {
    throw new Error(
      `advanced render does not support reframing strategy ${input.reframing_strategy}`,
    );
  }
  if (input.reframing_strategy === "face_follow") {
    assertFaceFollow(input);
  }
  if (input.reframing_strategy === "manual_window") {
    const windows = input.windows ?? [];
    let cursorUs = 0;
    if (windows.length === 0) {
      throw new Error("manual_window requires reviewed crop windows");
    }
    for (const window of windows) {
      if (
        window.output_start_us !== cursorUs ||
        window.output_end_us <= window.output_start_us ||
        window.strategy_id?.strategy_id !== "manual_window" ||
        window.frame_width !== windows[0].frame_width ||
        window.frame_height !== windows[0].frame_height ||
        window.source_width * 16 !== window.source_height * 9 ||
        window.source_x < 0 ||
        window.source_y < 0 ||
        window.source_width < 1 ||
        window.source_height < 1 ||
        window.source_x + window.source_width > window.frame_width ||
        window.source_y + window.source_height > window.frame_height
      ) {
        throw new Error("manual_window trajectory must be ordered, contiguous, and safe 9:16 crops");
      }
      cursorUs = window.output_end_us;
    }
    if (cursorUs !== input.output_duration_us) {
      throw new Error("manual_window trajectory must cover the complete output duration");
    }
  }
  for (const event of input.sfx ?? []) {
    if (event && event.role && event.role !== "sfx") {
      throw new Error("advanced render rejects music");
    }
    if (
      event &&
      typeof event.gain_db === "number" &&
      (event.gain_db < -24 || event.gain_db > 6)
    ) {
      throw new Error("SFX gain_db must be between -24 and 6");
    }
    if (input.style_id !== "legacy-v1") {
      if (!Array.isArray(event?.source_evidence_ids) || event.source_evidence_ids.length === 0) {
        throw new Error("production SFX requires source evidence");
      }
      if (typeof event?.relevance_note !== "string" || event.relevance_note.trim().length === 0) {
        throw new Error("production SFX requires a relevance note");
      }
      if (typeof event?.purpose !== "string" || event.purpose.length === 0) {
        throw new Error("production SFX requires a motion purpose");
      }
    }
  }
  for (const event of input.broll ?? []) {
    if (input.style_id !== "legacy-v1") {
      if (!Array.isArray(event?.source_evidence_ids) || event.source_evidence_ids.length === 0) {
        throw new Error("production B-roll requires source evidence");
      }
      if (typeof event?.relevance_note !== "string" || event.relevance_note.trim().length === 0) {
        throw new Error("production B-roll requires a relevance note");
      }
    }
  }
  const raw = JSON.stringify(input);
  if (raw.includes("http://") || raw.includes("https://")) {
    throw new Error("refusing remote media URL in the advanced render input");
  }
  for (const name of [input.base_video_name, input.speech_name]) {
    if (typeof name !== "string" || name.includes("..") || name.includes("/")) {
      throw new Error("advanced staged media name is not a file name");
    }
    contained(path.join(stagingDir, name), stagingDir);
  }
  const names = input.asset_names ?? {};
  for (const name of Object.values(names)) {
    if (typeof name !== "string" || name.includes("..") || name.includes("/")) {
      throw new Error("advanced asset name is not a staging file name");
    }
    contained(path.join(stagingDir, name), stagingDir);
  }
  if (!Number.isInteger(item.h264Crf) || item.h264Crf < 0 || item.h264Crf > 51) {
    throw new Error("hero render batch h264Crf must be an integer from 0 to 51");
  }
}

function assertFaceFollow(input) {
  const sha = /^[0-9a-f]{64}$/;
  for (const key of ["trajectory_sha256", "time_map_sha256", "source_sha256", "profile_fingerprint"]) {
    if (typeof input[key] !== "string" || !sha.test(input[key])) {
      throw new Error(`face_follow ${key} is missing`);
    }
  }
  if (!Number.isInteger(input.output_duration_us) || input.output_duration_us < 1) {
    throw new Error("face_follow output duration is missing");
  }
  if (!Number.isInteger(input.duration_in_frames) || input.duration_in_frames < 1) {
    throw new Error("face_follow duration_in_frames is missing");
  }
  const windows = input.windows;
  if (!Array.isArray(windows) || windows.length !== input.duration_in_frames) {
    throw new Error("face_follow trajectory is missing");
  }
  let frameWidth = null;
  let frameHeight = null;
  let cursor = 0;
  windows.forEach((item, index) => {
    if (!item || typeof item !== "object") {
      throw new Error("face_follow window is missing");
    }
    if (item.output_start_us !== cursor || item.output_end_us <= item.output_start_us) {
      throw new Error("face_follow frame index drifted");
    }
    const strategy = item.strategy_id && item.strategy_id.strategy_id;
    if (strategy !== "face_follow") {
      throw new Error("face_follow strategy id does not match");
    }
    if (frameWidth === null) {
      frameWidth = item.frame_width;
      frameHeight = item.frame_height;
    }
    if (item.frame_width !== frameWidth || item.frame_height !== frameHeight) {
      throw new Error("face_follow frame dimensions changed");
    }
    if (
      item.source_x < 0 ||
      item.source_y < 0 ||
      item.source_width < 1 ||
      item.source_height < 1 ||
      item.source_x + item.source_width > item.frame_width ||
      item.source_y + item.source_height > item.frame_height
    ) {
      throw new Error("face_follow_crop_out_of_bounds");
    }
    const expectedStart = Math.floor((index * 1_000_000) / 30);
    if (item.output_start_us !== expectedStart) {
      throw new Error("face_follow sample is not on a 30/1 frame start");
    }
    cursor = item.output_end_us;
  });
  if (windows[0].output_start_us !== 0 || cursor !== input.output_duration_us) {
    throw new Error("face_follow final endpoint does not match the duration");
  }
}

const bundleStarted = Date.now();
const serveUrl = await bundle({
  entryPoint,
  webpackOverride: (config) => {
    config.resolve = config.resolve ?? {};
    config.resolve.extensionAlias = {
      ".js": [".ts", ".tsx", ".js"],
    };
    return config;
  },
  publicDir: stagingDir,
  symlinkPublicDir: true,
  enableCaching: false,
});
const bundleSeconds = (Date.now() - bundleStarted) / 1000;

let renderSeconds = 0;
for (const item of batch.items) {
  const started = Date.now();
  const composition = await selectComposition({
    serveUrl,
    id: "AdvancedHeroDraft",
    inputProps: item.input,
    browserExecutable,
    chromiumOptions,
  });
  if (composition.durationInFrames !== item.input.duration_in_frames) {
    throw new Error(
      `composition duration ${composition.durationInFrames} does not match Python duration_in_frames ${item.input.duration_in_frames}`,
    );
  }
  if (composition.width !== 1080 || composition.height !== 1920) {
    throw new Error(`composition size ${composition.width}x${composition.height} is not 1080x1920`);
  }
  const audioOnly = item.renderMode === "audio";
  await renderMedia({
    composition,
    serveUrl,
    codec: audioOnly ? "wav" : "h264",
    outputLocation: path.resolve(item.outputPath),
    inputProps: item.input,
    browserExecutable,
    chromiumOptions,
    concurrency: 1,
    crf: audioOnly ? undefined : item.h264Crf,
    pixelFormat: audioOnly ? undefined : "yuv420p",
    audioCodec: audioOnly ? "pcm-16" : "aac",
    sampleRate: 48000,
    frameRange: item.frameRange,
    overwrite: true,
    muted: item.renderMode === "video",
  });
  renderSeconds += (Date.now() - started) / 1000;
}

process.stderr.write(
  `${JSON.stringify({
    event: "hero-draft-timing",
    bundleSeconds,
    renderSeconds,
    candidateCount: batch.items.length,
  })}\n`,
);
