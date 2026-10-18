/**
 * Bundle RoughPreview once, then render each batch item in order.
 *
 * Python writes the batch. This process does not read SQLite, rank
 * candidates, or accept an http(s) media URL. Staged analysis.mp4 and
 * asr.flac are served from this run's staging directory.
 */

import { mkdirSync } from "node:fs";
import { readFileSync } from "node:fs";
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
const entryPoint = path.resolve(here, "../src/rough-preview/index.tsx");

const batchPath = process.argv[2];
const browserExecutable = process.argv[3];
if (!batchPath || !browserExecutable) {
  throw new Error("usage: node render-rough.mjs BATCH_JSON BROWSER_EXECUTABLE");
}

const batch = JSON.parse(readFileSync(batchPath, "utf8"));
if (!batch || !Array.isArray(batch.items)) {
  throw new Error("render batch is missing items");
}

const runDir = path.resolve(path.dirname(batchPath));
const stagingDir = path.join(runDir, "staging");
const chromiumOptions = { gl: "swangle" };

function stagedBasename(value) {
  if (typeof value !== "string" || value.includes("..")) {
    throw new Error("staged media name is not safe");
  }
  const name = path.basename(value);
  if (!/^[A-Za-z0-9._-]{1,80}$/.test(name)) {
    throw new Error("staged media name is not safe");
  }
  return name;
}

function memoryReport() {
  const usage = process.memoryUsage();
  let availableKb = null;
  try {
    const text = readFileSync("/proc/meminfo", "utf8");
    const line = text.split("\n").find((item) => item.startsWith("MemAvailable:"));
    availableKb = line ? Number(line.split(/\s+/)[1]) : null;
  } catch {
    availableKb = null;
  }
  return { rss: usage.rss, heapUsed: usage.heapUsed, memAvailableKb: availableKb };
}

function contained(filePath, root) {
  const resolved = path.resolve(filePath);
  const prefix = root.endsWith(path.sep) ? root : `${root}${path.sep}`;
  if (resolved !== root && !resolved.startsWith(prefix)) {
    throw new Error(`refusing to write outside the preview run: ${resolved}`);
  }
  return resolved;
}

for (const item of batch.items) {
  if (!item || typeof item !== "object") {
    throw new Error("render batch item was not an object");
  }
  contained(item.outputPath, runDir);
  const input = item.input;
  if (!input || typeof input !== "object") {
    throw new Error("render batch item is missing input");
  }
  for (const key of ["video_path", "audio_path"]) {
    const value = input[key];
    if (typeof value !== "string") {
      throw new Error(`render batch ${key} is missing`);
    }
    const lower = value.toLowerCase();
    if (lower.startsWith("http://") || lower.startsWith("https://")) {
      throw new Error(`refusing remote media URL in ${key}`);
    }
  }
  const videoName = stagedBasename(input.video_path);
  const audioName = stagedBasename(input.audio_path);
  contained(path.join(stagingDir, videoName), stagingDir);
  contained(path.join(stagingDir, audioName), stagingDir);
  if (input.campaign_overlay) {
    const overlay = input.campaign_overlay;
    for (const key of ["watermark_asset_name"]) {
      const value = overlay[key];
      if (typeof value !== "string" || stagedBasename(value) !== value) {
        throw new Error(`campaign overlay ${key} is not a safe staged name`);
      }
      contained(path.join(stagingDir, value), stagingDir);
    }
    if (overlay.cta_background_removal !== "chroma_key_v1" || (overlay.cta_render_mode !== "alpha_video_v1" && overlay.cta_render_mode !== "alpha_png_sequence_v1") || overlay.cta_frame_rate !== 30 || overlay.watermark_mode !== "alpha_v1" || overlay.cta_position !== "foreground_attention_v1" || overlay.overlay_coordinate_space !== "foreground_v1" || (overlay.watermark_position !== "foreground_top_right_v1" && overlay.watermark_position !== "top_right") || !Number.isInteger(overlay.cta_width_permille) || overlay.cta_width_permille < 320 || overlay.cta_width_permille > 600) {
      throw new Error("unsupported campaign overlay contract");
    }
    if (overlay.cta_render_mode === "alpha_video_v1") {
      if (typeof overlay.cta_asset_name !== "string" || stagedBasename(overlay.cta_asset_name) !== overlay.cta_asset_name) {
        throw new Error("campaign overlay CTA alpha video name is invalid");
      }
      contained(path.join(stagingDir, overlay.cta_asset_name), stagingDir);
    } else {
      if (typeof overlay.cta_frame_prefix !== "string" || !/^[A-Za-z0-9._-]{1,80}$/.test(overlay.cta_frame_prefix) || !Number.isInteger(overlay.cta_frame_count) || overlay.cta_frame_count < 1 || overlay.cta_frame_count > 600) {
        throw new Error("campaign overlay CTA frame sequence is invalid");
      }
      for (let index = 1; index <= overlay.cta_frame_count; index += 1) {
        contained(path.join(stagingDir, `${overlay.cta_frame_prefix}-${String(index).padStart(4, "0")}.png`), stagingDir);
      }
    }
  }
  if (!Number.isInteger(item.h264Crf) || item.h264Crf < 0 || item.h264Crf > 51) {
    throw new Error("render batch h264Crf must be an integer from 0 to 51");
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
  const frames = Number(item.input.duration_in_frames);
  const timeoutInMilliseconds = Math.min(90_000, Math.max(20_000, frames * 80));
  process.stderr.write(
    `${JSON.stringify({
      event: "rough-preview-watch",
      phase: "start",
      candidate_id: item.watch?.candidate_id ?? item.input.candidate_id,
      source_id: item.watch?.source_id ?? "",
      duration_in_frames: frames,
      staged_duration_us: item.watch?.staged_duration_us ?? null,
      memory: memoryReport(),
      timeout_ms: timeoutInMilliseconds,
    })}\n`,
  );
  const composition = await selectComposition({
    serveUrl,
    id: "RoughPreview",
    inputProps: item.input,
    browserExecutable,
    chromiumOptions,
  });
  if (composition.durationInFrames !== item.input.duration_in_frames) {
    throw new Error(
      `composition duration ${composition.durationInFrames} does not match Python duration_in_frames ${item.input.duration_in_frames}`,
    );
  }
  if (composition.width !== 720 || composition.height !== 1280) {
    throw new Error(`composition size ${composition.width}x${composition.height} is not 720x1280`);
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
    frameRange: item.frameRange,
    timeoutInMilliseconds,
  });
  renderSeconds += (Date.now() - started) / 1000;
  process.stderr.write(
    `${JSON.stringify({
      event: "rough-preview-watch",
      phase: "promoted-by-python-after-process",
      candidate_id: item.watch?.candidate_id ?? item.input.candidate_id,
      elapsed_ms: Date.now() - started,
      memory: memoryReport(),
      node_exit: 0,
    })}\n`,
  );
}

process.stderr.write(
  `${JSON.stringify({
    event: "rough-preview-timing",
    bundleSeconds,
    renderSeconds,
    candidateCount: batch.items.length,
  })}\n`,
);
