/**
 * Runtime checks for one Hero render input.
 *
 * Python owns approval, forced alignment, and canonical microseconds.
 */

import {
  COMPOSITION_ID,
  MOTION_LIBRARY_VERSION,
  OUTPUT_HEIGHT,
  OUTPUT_WIDTH,
  type HeroCaption,
  type HeroDraftInput,
  type HeroMotionEvent,
  type HeroWord,
} from "./types.js";

const TOP_KEYS = new Set([
  "schema_version",
  "composition_id",
  "candidate_id",
  "hero_set_id",
  "video_path",
  "audio_path",
  "media_trim_frame",
  "duration_in_frames",
  "fps_numerator",
  "fps_denominator",
  "width",
  "height",
  "video_fit",
  "background",
  "alignment_quality",
  "alignment_sha256",
  "edit_plan_sha256",
  "time_map_sha256",
  "review_id",
  "review_digest",
  "motion_library_version",
  "profile_fingerprint",
  "captions",
  "motion_events",
]);

const CAPTION_KEYS = new Set([
  "cue_id",
  "text",
  "source_start_us",
  "source_end_us",
  "output_start_us",
  "output_end_us",
  "output_start_frame",
  "output_end_frame_exclusive",
  "alignment_quality",
  "words",
]);

const WORD_KEYS = new Set(["text", "output_start_frame", "output_end_frame_exclusive"]);

const EVENT_KEYS = new Set([
  "event_id",
  "component_id",
  "purpose",
  "output_start_us",
  "output_end_us",
  "output_start_frame",
  "output_end_frame_exclusive",
  "library",
]);

const SHA = /^[0-9a-f]{64}$/;

export function parseHeroInput(raw: unknown): HeroDraftInput {
  const record = requireRecord(raw, "hero render input");
  rejectUnknown(record, TOP_KEYS, "hero render input");
  if (record.composition_id !== COMPOSITION_ID) {
    throw new Error("hero render input composition_id must be HeroDraft");
  }
  if (record.width !== OUTPUT_WIDTH || record.height !== OUTPUT_HEIGHT) {
    throw new Error(`hero render input dimensions must be ${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}`);
  }
  if (record.fps_numerator !== 30 || record.fps_denominator !== 1) {
    throw new Error("hero render input fps must be 30/1");
  }
  if (record.video_fit !== "contain") {
    throw new Error("hero render input video_fit must be contain");
  }
  if (record.background !== "neutral-dark-v1") {
    throw new Error("hero render input background must be neutral-dark-v1");
  }
  if (record.alignment_quality !== "forced") {
    throw new Error("hero render input refuses alignment that is not forced");
  }
  if (record.motion_library_version !== MOTION_LIBRARY_VERSION) {
    throw new Error("hero render input motion library must be motion-library-v1");
  }
  const duration = requireFrameCount(record.duration_in_frames);
  requireNonNegativeInt(record.media_trim_frame, "media_trim_frame");
  requireSha(record.alignment_sha256, "alignment_sha256");
  requireSha(record.edit_plan_sha256, "edit_plan_sha256");
  requireSha(record.time_map_sha256, "time_map_sha256");
  requireSha(record.review_digest, "review_digest");
  requireSha(record.profile_fingerprint, "profile_fingerprint");
  requireText(record.candidate_id, "candidate_id");
  requireText(record.hero_set_id, "hero_set_id");
  requireText(record.review_id, "review_id");
  requireLocalPath(record.video_path, "video_path");
  requireLocalPath(record.audio_path, "audio_path");
  if (!Array.isArray(record.captions) || record.captions.length < 1) {
    throw new Error("hero render input requires at least one forced caption");
  }
  const captions = record.captions.map((item) => parseCaption(item, duration));
  if (!Array.isArray(record.motion_events)) {
    throw new Error("hero render input motion_events must be a list");
  }
  const motion = record.motion_events.map((item) => parseEvent(item, duration));
  return {
    ...(record.schema_version === undefined ? {} : { schema_version: "1.0.0" }),
    composition_id: "HeroDraft",
    candidate_id: String(record.candidate_id),
    hero_set_id: String(record.hero_set_id),
    video_path: String(record.video_path),
    audio_path: String(record.audio_path),
    media_trim_frame: Number(record.media_trim_frame),
    duration_in_frames: duration,
    fps_numerator: 30,
    fps_denominator: 1,
    width: OUTPUT_WIDTH,
    height: OUTPUT_HEIGHT,
    video_fit: "contain",
    background: "neutral-dark-v1",
    alignment_quality: "forced",
    alignment_sha256: String(record.alignment_sha256),
    edit_plan_sha256: String(record.edit_plan_sha256),
    time_map_sha256: String(record.time_map_sha256),
    review_id: String(record.review_id),
    review_digest: String(record.review_digest),
    motion_library_version: MOTION_LIBRARY_VERSION,
    profile_fingerprint: String(record.profile_fingerprint),
    captions,
    motion_events: motion,
  };
}

export function compositionFacts(raw: unknown): { durationInFrames: number; fps: number; width: number; height: number } {
  const input = parseHeroInput(raw);
  return {
    durationInFrames: input.duration_in_frames,
    fps: 30,
    width: OUTPUT_WIDTH,
    height: OUTPUT_HEIGHT,
  };
}

function parseCaption(raw: unknown, duration: number): HeroCaption {
  const record = requireRecord(raw, "hero caption");
  rejectUnknown(record, CAPTION_KEYS, "hero caption");
  if (record.alignment_quality !== "forced") {
    throw new Error("hero caption refuses alignment that is not forced");
  }
  requireText(record.cue_id, "cue_id");
  requireText(record.text, "text");
  const start = requireFrame(record.output_start_frame, "output_start_frame");
  const end = requireFrame(record.output_end_frame_exclusive, "output_end_frame_exclusive");
  if (end <= start) {
    throw new Error("hero caption frame interval must be positive and half-open");
  }
  if (end > duration) {
    throw new Error("hero caption frame interval is outside duration_in_frames");
  }
  if (!Array.isArray(record.words) || record.words.length < 1) {
    throw new Error("hero caption requires forced words");
  }
  return {
    cue_id: String(record.cue_id),
    text: String(record.text),
    source_start_us: requireNonNegativeInt(record.source_start_us, "source_start_us"),
    source_end_us: requireNonNegativeInt(record.source_end_us, "source_end_us"),
    output_start_us: requireNonNegativeInt(record.output_start_us, "output_start_us"),
    output_end_us: requireNonNegativeInt(record.output_end_us, "output_end_us"),
    output_start_frame: start,
    output_end_frame_exclusive: end,
    alignment_quality: "forced",
    words: record.words.map((word) => parseWord(word, duration)),
  };
}

function parseWord(raw: unknown, duration: number): HeroWord {
  const record = requireRecord(raw, "hero word");
  rejectUnknown(record, WORD_KEYS, "hero word");
  requireText(record.text, "text");
  const start = requireFrame(record.output_start_frame, "output_start_frame");
  const end = requireFrame(record.output_end_frame_exclusive, "output_end_frame_exclusive");
  if (end <= start || end > duration) {
    throw new Error("hero word frame interval must be half-open and inside the composition");
  }
  return {
    text: String(record.text),
    output_start_frame: start,
    output_end_frame_exclusive: end,
  };
}

function parseEvent(raw: unknown, duration: number): HeroMotionEvent {
  const record = requireRecord(raw, "hero motion event");
  rejectUnknown(record, EVENT_KEYS, "hero motion event");
  requireText(record.event_id, "event_id");
  requireText(record.component_id, "component_id");
  requireText(record.purpose, "purpose");
  if (record.library !== MOTION_LIBRARY_VERSION) {
    throw new Error("hero motion event library must be motion-library-v1");
  }
  const start = requireFrame(record.output_start_frame, "output_start_frame");
  const end = requireFrame(record.output_end_frame_exclusive, "output_end_frame_exclusive");
  if (end <= start || end > duration) {
    throw new Error("hero motion frame interval must be half-open and inside the composition");
  }
  return {
    event_id: String(record.event_id),
    component_id: String(record.component_id),
    purpose: String(record.purpose),
    output_start_us: requireNonNegativeInt(record.output_start_us, "output_start_us"),
    output_end_us: requireNonNegativeInt(record.output_end_us, "output_end_us"),
    output_start_frame: start,
    output_end_frame_exclusive: end,
    library: MOTION_LIBRARY_VERSION,
  };
}

function requireRecord(raw: unknown, label: string): Record<string, unknown> {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new Error(`${label} must be an object`);
  }
  return raw as Record<string, unknown>;
}

function rejectUnknown(record: Record<string, unknown>, allowed: Set<string>, label: string): void {
  for (const key of Object.keys(record)) {
    if (!allowed.has(key)) {
      throw new Error(`${label} has unknown field ${key}`);
    }
  }
}

function requireText(value: unknown, label: string): void {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${label} must be non-blank text`);
  }
}

function requireSha(value: unknown, label: string): void {
  if (typeof value !== "string" || !SHA.test(value)) {
    throw new Error(`${label} must be a sha256 hex digest`);
  }
}

function requireFrameCount(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    throw new Error("duration_in_frames must be a positive integer");
  }
  return value;
}

function requireFrame(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`${label} must be a non-negative integer`);
  }
  return value;
}

function requireNonNegativeInt(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`${label} must be a non-negative integer`);
  }
  return value;
}

function requireLocalPath(value: unknown, label: string): void {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be a local path`);
  }
  const lower = value.toLowerCase();
  if (lower.startsWith("http://") || lower.startsWith("https://")) {
    throw new Error(`${label} must be a local file, not an http URL`);
  }
  if (value.includes("..") || value.includes("\u0000")) {
    throw new Error(`${label} must not contain a parent segment`);
  }
}
