/**
 * Round 1 scaffold. This module does not register a Remotion composition
 * and it does not render frames.
 */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { Codec } from "remotion";

/** Present so `tsc` loads Remotion's public types. No composition is registered. */
export type DeferredCodec = Codec;

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));

export const JSON_SCHEMA_INDEX = resolve(here, "../../../schemas/generated/index.json");

export const RENDERER_STATUS = "scaffold" as const;

export type RendererScaffold = {
  readonly status: typeof RENDERER_STATUS;
  readonly rendersVideo: false;
};

export function scaffold(): RendererScaffold {
  return { status: RENDERER_STATUS, rendersVideo: false };
}

export function schemaIndexVersion(): string {
  const parsed: unknown = JSON.parse(readFileSync(JSON_SCHEMA_INDEX, "utf8"));
  if (!isRecord(parsed) || typeof parsed.schema_version !== "string") {
    throw new Error(`${JSON_SCHEMA_INDEX} has no string schema_version. Export schemas before typecheck tests.`);
  }
  return parsed.schema_version;
}

export function remotionPackageVersion(): string {
  const parsed: unknown = require("remotion/package.json");
  if (!isRecord(parsed) || typeof parsed.version !== "string" || parsed.version.length === 0) {
    throw new Error("remotion/package.json has no version. The renderer dependency is not installed.");
  }
  return parsed.version;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
