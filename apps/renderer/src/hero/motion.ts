/** Deterministic motion-library v1 helpers. No randomness and no TimeMap edits. */

import type { HeroCaption, HeroMotionEvent } from "./types.js";
import { EMPHASIS_SCALE, MOTION_LIBRARY_VERSION } from "./types.js";

export function eventActive(event: HeroMotionEvent, frame: number): boolean {
  return frame >= event.output_start_frame && frame < event.output_end_frame_exclusive;
}

export function layerOpacity(events: readonly HeroMotionEvent[], frame: number): number {
  let opacity = 1;
  for (const event of events) {
    const span = event.output_end_frame_exclusive - event.output_start_frame;
    if (span <= 0) {
      continue;
    }
    if (event.component_id === "opening-fade-v1" && frame < event.output_end_frame_exclusive) {
      const progress = (frame - event.output_start_frame) / span;
      opacity *= clamp(progress);
    }
    if (event.component_id === "closing-fade-v1" && frame >= event.output_start_frame) {
      const progress = (frame - event.output_start_frame) / span;
      opacity *= clamp(1 - progress);
    }
  }
  return opacity;
}

export function emphasisScale(events: readonly HeroMotionEvent[], frame: number): number {
  const active = events.some((event) => event.component_id === "caption-emphasis-v1" && eventActive(event, frame));
  return active ? EMPHASIS_SCALE : 1;
}

export function revealedCaption(caption: HeroCaption, frame: number): string {
  if (frame < caption.output_start_frame || frame >= caption.output_end_frame_exclusive) {
    return "";
  }
  return caption.words
    .filter((word) => frame >= word.output_start_frame)
    .map((word) => word.text)
    .join("")
    .trim();
}

export function serializeMotion(events: readonly HeroMotionEvent[]): string {
  const ordered = [...events].sort((left, right) => {
    if (left.output_start_us !== right.output_start_us) {
      return left.output_start_us - right.output_start_us;
    }
    return left.event_id < right.event_id ? -1 : left.event_id > right.event_id ? 1 : 0;
  });
  return JSON.stringify({ library: MOTION_LIBRARY_VERSION, events: ordered });
}

function clamp(value: number): number {
  if (value < 0) {
    return 0;
  }
  if (value > 1) {
    return 1;
  }
  return value;
}
