/** Deterministic crop placement. The stored window is the crop. Pixels are not re-detected. */

export const OUTPUT_WIDTH = 1080;
export const OUTPUT_HEIGHT = 1920;
export const FPS = 30;

export type CropWindow = {
  output_start_us: number;
  output_end_us: number;
  source_x: number;
  source_y: number;
  source_width: number;
  source_height: number;
  frame_width: number;
  frame_height: number;
};

export type FaceBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export function frameStartUs(frame: number): number {
  return Math.floor((frame * 1_000_000) / FPS);
}

/** Frames that start strictly before durationUs. Matches TimeMap.output_frame_count at 30/1. */
export function outputFrameCount(durationUs: number): number {
  if (durationUs <= 0) {
    return 0;
  }
  let count = Math.floor((durationUs * FPS) / 1_000_000);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (count > 0 && frameStartUs(count - 1) >= durationUs) {
      count -= 1;
      continue;
    }
    if (frameStartUs(count) < durationUs) {
      count += 1;
      continue;
    }
    return count;
  }
  throw new Error("could not count output frames");
}

export function windowAt(frame: number, windows: CropWindow[]): CropWindow {
  const time = frameStartUs(frame);
  const index = windows.findIndex((item) => time >= item.output_start_us && time < item.output_end_us);
  if (index < 0) {
    throw new Error("face_follow frame index drifted");
  }
  const found = windows[index];
  const next = windows[index + 1];
  if (found === undefined) {
    throw new Error("face_follow frame index drifted");
  }
  // Reviewed manual windows are trajectory keyframes: move deterministically
  // toward the next crop over this interval. Face-follow windows are already
  // frame-quantized, so this leaves their per-frame path unchanged.
  if (next !== undefined && found.output_end_us - found.output_start_us > 2 * Math.ceil(1_000_000 / FPS)) {
    const progress = Math.max(
      0,
      Math.min(1, (time - found.output_start_us) / (found.output_end_us - found.output_start_us)),
    );
    return {
      ...found,
      source_x: Math.round(found.source_x + (next.source_x - found.source_x) * progress),
      source_y: Math.round(found.source_y + (next.source_y - found.source_y) * progress),
    };
  }
  return found;
}

export function windowInsideSource(window: CropWindow): boolean {
  return (
    window.source_x >= 0 &&
    window.source_y >= 0 &&
    window.source_width >= 1 &&
    window.source_height >= 1 &&
    window.source_x + window.source_width <= window.frame_width &&
    window.source_y + window.source_height <= window.frame_height
  );
}

export function placedVideo(window: CropWindow): { left: number; top: number; width: number; height: number } {
  if (!windowInsideSource(window)) {
    throw new Error("face_follow_crop_out_of_bounds");
  }
  const scaleX = OUTPUT_WIDTH / window.source_width;
  const scaleY = OUTPUT_HEIGHT / window.source_height;
  return {
    left: -window.source_x * scaleX,
    top: -window.source_y * scaleY,
    width: window.frame_width * scaleX,
    height: window.frame_height * scaleY,
  };
}

export function faceInSafe(face: FaceBox, window: CropWindow, headroomPermille = 120): boolean {
  const marginX = Math.floor((window.source_width * headroomPermille) / 1000);
  const marginY = Math.floor((window.source_height * headroomPermille) / 1000);
  const left = window.source_x + marginX;
  const top = window.source_y + marginY;
  const right = window.source_x + window.source_width - marginX;
  const bottom = window.source_y + window.source_height - marginY;
  return face.x >= left && face.y >= top && face.x + face.width <= right && face.y + face.height <= bottom;
}
