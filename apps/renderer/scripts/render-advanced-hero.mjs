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
  if (input.reframing_strategy !== "contain") {
    throw new Error(
      `advanced render does not support reframing strategy ${input.reframing_strategy}`,
    );
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
