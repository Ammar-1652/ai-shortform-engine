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
  const input = item.input;
  if (!input || typeof input !== "object") {
    throw new Error("hero render batch item is missing input");
  }
  if (input.composition_id !== "AdvancedHeroDraft") {
    throw new Error("advanced render refuses a composition other than AdvancedHeroDraft");
  }
  if (input.debug_overlays === true) {
    throw new Error("production advanced render rejects debug overlays");
  }
  if (input.style_id !== undefined && input.style_id !== "legacy-v1" && input.style_id !== "editorial-clean-v1") {
    throw new Error(`unsupported motion style ${input.style_id}`);
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
  if (
    input.reframing_strategy !== "contain" &&
    input.reframing_strategy !== "center_crop" &&
    input.reframing_strategy !== "face_follow"
  ) {
    throw new Error(
      `advanced render does not support reframing strategy ${input.reframing_strategy}`,
    );
  }
  if (input.reframing_strategy === "face_follow") {
    assertFaceFollow(input);
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
  await renderMedia({
    composition,
    serveUrl,
    codec: "h264",
    outputLocation: path.resolve(item.outputPath),
    inputProps: item.input,
    browserExecutable,
    chromiumOptions,
    concurrency: 1,
    crf: item.h264Crf,
    pixelFormat: "yuv420p",
    audioCodec: "aac",
    overwrite: true,
    muted: false,
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
