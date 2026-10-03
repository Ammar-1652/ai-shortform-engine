/** Contain math for the 720×1280 review canvas. The source picture is not cropped. */

export const VIDEO_OBJECT_FIT = "contain" as const;

export type ContainedRect = {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly fit: typeof VIDEO_OBJECT_FIT;
};

export function containedRect(
  sourceWidth: number,
  sourceHeight: number,
  canvasWidth: number,
  canvasHeight: number,
): ContainedRect {
  if (sourceWidth <= 0 || sourceHeight <= 0 || canvasWidth <= 0 || canvasHeight <= 0) {
    throw new Error("contain layout requires positive source and canvas sizes");
  }
  const scale = Math.min(canvasWidth / sourceWidth, canvasHeight / sourceHeight);
  const width = sourceWidth * scale;
  const height = sourceHeight * scale;
  return {
    x: (canvasWidth - width) / 2,
    y: (canvasHeight - height) / 2,
    width,
    height,
    fit: VIDEO_OBJECT_FIT,
  };
}
