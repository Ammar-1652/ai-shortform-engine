/** Validate service receipts before importing Remotion or opening a browser. */
import { createHash } from "node:crypto";
import { lstatSync, readFileSync } from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { fileURLToPath } from "node:url";

const SHA = /^[0-9a-f]{64}$/;

function confined(file, runDir) {
  const resolved = path.resolve(file);
  const relative = path.relative(runDir, resolved);
  if (relative.startsWith(`..${path.sep}`) || relative === ".." || path.isAbsolute(relative)) {
    throw new Error("render authorization path escapes the service run");
  }
  let current = resolved;
  for (;;) {
    try {
      if (lstatSync(current).isSymbolicLink()) throw new Error("render authorization refuses symlink paths");
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    if (current === path.dirname(current)) break;
    current = path.dirname(current);
  }
  return resolved;
}

function bytes(file, runDir) {
  const resolved = confined(file, runDir);
  if (!lstatSync(resolved).isFile()) throw new Error("render authorization input is not a regular file");
  return readFileSync(resolved);
}

export function validateRenderAuthorization(batchPath, batch) {
  const runDir = path.resolve(path.dirname(batchPath));
  confined(batchPath, runDir);
  const authorization = JSON.parse(bytes(path.join(runDir, "authorization.json"), runDir));
  if (
    authorization.schema_version !== "1.0.0" ||
    authorization.recipe !== "advanced-render-authorization-v1" ||
    !SHA.test(authorization.batch_sha256 ?? "") ||
    !SHA.test(authorization.renderer_dependency_sha256 ?? "") ||
    !Array.isArray(authorization.items) || authorization.items.length !== 1 ||
    !authorization.provenance?.source_asset_ids?.includes(authorization.source_asset_id)
  ) throw new Error("service render authorization is missing or invalid");
  const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
  const dependencies = authorization.renderer_dependency_files;
  if (!dependencies || Array.isArray(dependencies) || !Object.keys(dependencies).length) {
    throw new Error("render authorization requires local worker dependency hashes");
  }
  const current = {};
  for (const name of Object.keys(dependencies).sort()) {
    if (!name.startsWith("apps/renderer/") && !name.startsWith("src/clipforge/")) {
      throw new Error("render worker dependency path is invalid");
    }
    current[name] = createHash("sha256").update(bytes(path.join(repo, name), repo)).digest("hex");
    if (current[name] !== dependencies[name]) throw new Error("render worker dependency changed");
  }
  if (createHash("sha256").update(JSON.stringify(current)).digest("hex") !== authorization.renderer_dependency_sha256) {
    throw new Error("render worker dependency fingerprint changed");
  }
  const canonicalBytes = bytes(path.join(runDir, "batch-input.json"), runDir);
  if (createHash("sha256").update(canonicalBytes).digest("hex") !== authorization.batch_sha256) {
    throw new Error("service canonical batch hash changed");
  }
  const canonicalBatch = JSON.parse(canonicalBytes);
  if (!Array.isArray(batch?.items) || batch.items.length !== 1 || !Array.isArray(canonicalBatch?.items)) {
    throw new Error("service render batch is invalid");
  }
  const item = batch.items[0];
  const authorized = authorization.items[0];
  const canonicalMatches = canonicalBatch.items.filter((entry) => entry?.input?.candidate_id === authorized.candidate_id);
  const canonical = canonicalMatches[0];
  if (
    canonicalMatches.length !== 1 || item.input?.candidate_id !== authorized.candidate_id ||
    !SHA.test(authorized.input_sha256 ?? "") ||
    authorized.input_sha256 !== item.input_sha256 || canonical.input_sha256 !== item.input_sha256 ||
    !isDeepStrictEqual(item.input, canonical.input) || item.h264Crf !== canonical.h264Crf ||
    item.input.advanced_set_id !== authorization.advanced_set_id ||
    item.input.source_sha256 !== authorization.source_sha256
  ) throw new Error("render input changed after service authorization");
  if (
    typeof authorized.output_relative_path !== "string" ||
    authorized.output_relative_path.includes("\\") ||
    authorized.output_relative_path.split("/").some((part) => ["", ".", ".."].includes(part)) ||
    path.isAbsolute(authorized.output_relative_path)
  ) throw new Error("authorized output must be run relative");
  const finalOutput = confined(path.join(runDir, authorized.output_relative_path), runDir);
  // The canonical output is the identity of the whole composition.  Check it
  // for full renders and checkpoint units alike; otherwise a copied run could
  // reuse the canonical receipt while writing chunks under a new directory.
  if (canonical.outputPath !== finalOutput) {
    throw new Error("canonical batch was copied outside its service run");
  }
  let allowedOutput = finalOutput;
  if (item.renderMode !== undefined) {
    const [start, last] = item.frameRange ?? [];
    const count = item.input.duration_in_frames;
    if (!Number.isSafeInteger(count) || count < 1 || !Number.isSafeInteger(start) || !Number.isSafeInteger(last)) {
      throw new Error("authorized render unit range is invalid");
    }
    let name;
    if (item.renderMode === "audio" && start === 0 && last === count - 1) name = "audio.partial.wav";
    else if (item.renderMode === "video" && start >= 0 && start % 120 === 0 && last === Math.min(start + 120, count) - 1 && start <= last) {
      name = `video-${String(start / 120).padStart(6, "0")}.partial.mp4`;
    } else throw new Error("render unit does not own its authorized frame range");
    allowedOutput = path.join(path.dirname(finalOutput), "checkpoints", name);
  } else if (item.frameRange !== undefined) throw new Error("full render cannot override its frame range");
  if (confined(item.outputPath, runDir) !== allowedOutput) throw new Error("render output differs from service authorization");
  const names = new Set([item.input.base_video_name, item.input.speech_name, ...Object.values(item.input.asset_names ?? {})]);
  if (!authorized.staged_sha256 || Object.keys(authorized.staged_sha256).length !== names.size) {
    throw new Error("service staged input hash coverage is incomplete");
  }
  for (const name of names) {
    if (typeof name !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(name)) {
      throw new Error("authorized staged input must be a local file name");
    }
    const raw = bytes(path.join(runDir, "staging", name), runDir);
    if (!raw.length || createHash("sha256").update(raw).digest("hex") !== authorized.staged_sha256[name]) {
      throw new Error(`service staged input hash changed: ${name}`);
    }
  }
}
