/**
 * Runtime checks for one render-input object.
 *
 * Python owns candidate selection and canonical microseconds. This module
 * rejects a payload the composition must not draw. It does not derive a new
 * duration from floating seconds.
 */

import {
  COMPOSITION_ID,
  OUTPUT_HEIGHT,
  OUTPUT_WIDTH,
  type RoughCaptionWord,
  type RoughCaptionCue,
  type RoughPreviewInput,
} from "./types.js";

const TOP_KEYS = new Set([
  "schema_version",
  "composition_id",
  "candidate_id",
  "preview_set_id",
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
  "font_identity",
  "video_scale_permille",
  "video_offset_x_px",
  "word_highlight_mode",
  "timing_quality",
  "captions",
  "source_start_us",
  "source_end_us",
  "proxy_sha256",
  "staged_video_sha256",
  "staged_audio_sha256",
  "staged_duration_us",
]);

const CUE_KEYS = new Set([
  "schema_version",
  "cue_id",
  "text",
  "transcript_segment_ids",
  "transcript_word_ids",
  "source_start_us",
  "source_end_us",
  "output_start_us",
  "output_end_us",
  "output_start_frame",
  "output_end_frame_exclusive",
  "timing_quality",
  "words",
]);
const WORD_KEYS = new Set([
  "schema_version",
  "word_id",
  "text",
  "output_start_us",
  "output_end_us",
  "output_start_frame",
  "output_end_frame_exclusive",
  "verification_status",
]);

const DANGEROUS = new Set([
  "dangerouslySetInnerHTML",
  "__html",
  "html",
  "script",
  "eval",
  "__proto__",
  "constructor",
  "prototype",
]);

export function parseRenderInput(raw: unknown): RoughPreviewInput {
  const record = requireRecord(raw, "render input");
  rejectDangerousKeys(record, "render input");
  rejectUnknown(record, TOP_KEYS, "render input");
  if (record.composition_id !== COMPOSITION_ID) {
    throw new Error("render input composition_id must be RoughPreview");
  }
  if (record.width !== OUTPUT_WIDTH || record.height !== OUTPUT_HEIGHT) {
    throw new Error(`render input dimensions must be ${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}`);
  }
  if (record.fps_numerator !== 30 || record.fps_denominator !== 1) {
    throw new Error("render input fps must be 30/1");
  }
  if (record.video_fit !== "contain") {
    throw new Error("render input video_fit must be contain");
  }
  if (record.background !== "neutral-dark-v1") {
    throw new Error("render input background must be neutral-dark-v1");
  }
  const videoScale = record.video_scale_permille === undefined ? 1000 : requireIntegerInRange(record.video_scale_permille, 1000, 1250, "video_scale_permille");
  const videoOffsetX = record.video_offset_x_px === undefined ? 0 : requireIntegerInRange(record.video_offset_x_px, -120, 120, "video_offset_x_px");
  if (record.word_highlight_mode !== undefined && record.word_highlight_mode !== "off" && record.word_highlight_mode !== "reviewed") {
    throw new Error("render input word_highlight_mode must be off or reviewed");
  }
  if (record.timing_quality !== "provisional") {
    throw new Error("render input timing_quality must be provisional");
  }
  const duration = requireFrameCount(record.duration_in_frames);
  const trim = requireNonNegativeInt(record.media_trim_frame, "media_trim_frame");
  const video = requireLocalPath(record.video_path, "video_path");
  const audio = requireLocalPath(record.audio_path, "audio_path");
  const captions = parseCaptions(record.captions, duration);
  return {
    composition_id: COMPOSITION_ID,
    candidate_id: requireId(record.candidate_id, "candidate_id"),
    preview_set_id: requireId(record.preview_set_id, "preview_set_id"),
    video_path: video,
    audio_path: audio,
    media_trim_frame: trim,
    duration_in_frames: duration,
    fps_numerator: 30,
    fps_denominator: 1,
    width: OUTPUT_WIDTH,
    height: OUTPUT_HEIGHT,
    video_fit: "contain",
    background: "neutral-dark-v1",
    ...(typeof record.font_identity === "string" ? { font_identity: record.font_identity } : {}),
    video_scale_permille: videoScale,
    video_offset_x_px: videoOffsetX,
    word_highlight_mode: record.word_highlight_mode === "reviewed" ? "reviewed" : "off",
    timing_quality: "provisional",
    captions,
  };
}

/** Duration frames come from the payload. They are not recomputed from seconds. */
export function compositionFacts(raw: unknown): {
  durationInFrames: number;
  width: number;
  height: number;
  fps: number;
} {
  const input = parseRenderInput(raw);
  return {
    durationInFrames: input.duration_in_frames,
    width: input.width,
    height: input.height,
    fps: input.fps_numerator / input.fps_denominator,
  };
}

function parseCaptions(raw: unknown, duration: number): RoughCaptionCue[] {
  if (!Array.isArray(raw)) {
    throw new Error("render input captions must be a list");
  }
  return raw.map((item, index) => parseCue(item, index, duration));
}

function parseCue(raw: unknown, index: number, duration: number): RoughCaptionCue {
  const record = requireRecord(raw, `caption ${index}`);
  rejectDangerousKeys(record, `caption ${index}`);
  rejectUnknown(record, CUE_KEYS, `caption ${index}`);
  const text = record.text;
  if (typeof text !== "string" || text.length === 0 || text.length > 300) {
    throw new Error(`caption ${index} text must be 1 to 300 characters`);
  }
  if (record.timing_quality !== "provisional") {
    throw new Error(`caption ${index} timing_quality must be provisional`);
  }
  const sourceStart = requireNonNegativeInt(record.source_start_us, `caption ${index} source_start_us`);
  const sourceEnd = requireNonNegativeInt(record.source_end_us, `caption ${index} source_end_us`);
  const outputStart = requireNonNegativeInt(record.output_start_us, `caption ${index} output_start_us`);
  const outputEnd = requireNonNegativeInt(record.output_end_us, `caption ${index} output_end_us`);
  const frameStart = requireNonNegativeInt(record.output_start_frame, `caption ${index} output_start_frame`);
  const frameEnd = requireNonNegativeInt(
    record.output_end_frame_exclusive,
    `caption ${index} output_end_frame_exclusive`,
  );
  if (sourceEnd <= sourceStart || outputEnd <= outputStart) {
    throw new Error(`caption ${index} intervals must be positive and half-open`);
  }
  if (frameEnd <= frameStart) {
    throw new Error(`caption ${index} frame interval must be positive and half-open`);
  }
  if (frameEnd > duration || frameStart >= duration) {
    throw new Error(`caption ${index} falls outside duration_in_frames`);
  }
  return {
    cue_id: requireId(record.cue_id, `caption ${index} cue_id`),
    text,
    transcript_segment_ids: requireIds(record.transcript_segment_ids, `caption ${index} segments`, 1),
    transcript_word_ids: requireIds(record.transcript_word_ids, `caption ${index} words`, 0),
    source_start_us: sourceStart,
    source_end_us: sourceEnd,
    output_start_us: outputStart,
    output_end_us: outputEnd,
    output_start_frame: frameStart,
    output_end_frame_exclusive: frameEnd,
    timing_quality: "provisional",
    words: parseWords(record.words, duration),
  };
}

function parseWords(raw: unknown, duration: number): RoughCaptionWord[] {
  if (raw === undefined) return [];
  if (!Array.isArray(raw)) throw new Error("caption words must be a list");
  return raw.map((item, index) => {
    const record = requireRecord(item, `caption word ${index}`);
    rejectUnknown(record, WORD_KEYS, `caption word ${index}`);
    const start = requireNonNegativeInt(record.output_start_frame, `caption word ${index} start`);
    const end = requireNonNegativeInt(record.output_end_frame_exclusive, `caption word ${index} end`);
    if (end <= start || end > duration) throw new Error(`caption word ${index} frame interval is invalid`);
    if (record.verification_status !== "unverified" && record.verification_status !== "correct" && record.verification_status !== "incorrect") {
      throw new Error(`caption word ${index} verification status is invalid`);
    }
    return {
      word_id: requireId(record.word_id, `caption word ${index} id`),
      text: requireText(record.text, `caption word ${index} text`),
      output_start_us: requireNonNegativeInt(record.output_start_us, `caption word ${index} start_us`),
      output_end_us: requireNonNegativeInt(record.output_end_us, `caption word ${index} end_us`),
      output_start_frame: start,
      output_end_frame_exclusive: end,
      verification_status: record.verification_status,
    };
  });
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
      throw new Error(`${label} contains unexpected field ${key}`);
    }
  }
}

function rejectDangerousKeys(record: Record<string, unknown>, label: string): void {
  for (const key of Object.keys(record)) {
    if (DANGEROUS.has(key)) {
      throw new Error(`${label} contains a rejected field ${key}`);
    }
  }
}

function requireFrameCount(value: unknown): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    throw new Error("duration_in_frames must be a positive integer");
  }
  return value;
}

function requireNonNegativeInt(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`${label} must be a non-negative integer`);
  }
  return value;
}

function requireId(value: unknown, label: string): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value)) {
    throw new Error(`${label} is not a safe id`);
  }
  return value;
}

function requireIntegerInRange(value: unknown, minimum: number, maximum: number, label: string): number {
  if (!Number.isInteger(value) || Number(value) < minimum || Number(value) > maximum) {
    throw new Error(`${label} must be an integer from ${minimum} to ${maximum}`);
  }
  return Number(value);
}

function requireText(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0 || value.length > 300) {
    throw new Error(`${label} must be non-empty text`);
  }
  return value;
}

function requireIds(value: unknown, label: string, minimum: number): string[] {
  if (!Array.isArray(value) || value.length < minimum) {
    throw new Error(`${label} must be a list`);
  }
  return value.map((item, index) => requireId(item, `${label} ${index}`));
}

function requireLocalPath(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0 || value.length > 4096) {
    throw new Error(`${label} must be a local path`);
  }
  const lower = value.toLowerCase();
  if (lower.startsWith("http://") || lower.startsWith("https://")) {
    throw new Error(`${label} must be a local file, not an http URL`);
  }
  if (value.includes("..") || value.includes("\0")) {
    throw new Error(`${label} must not contain a parent segment`);
  }
  return value;
}
