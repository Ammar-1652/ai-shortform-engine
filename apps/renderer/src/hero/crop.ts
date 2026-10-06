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

export function windowAt(frame: number, windows: CropWindow[]): CropWindow {
  const time = frameStartUs(frame);
  const found = windows.find((item) => time >= item.output_start_us && time < item.output_end_us);
  if (found === undefined) {
    throw new Error("face_follow frame index drifted");
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
