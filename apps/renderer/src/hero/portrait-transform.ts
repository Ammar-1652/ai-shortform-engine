/**
 * Deterministic source-to-portrait geometry shared by Hero and Advanced Hero.
 *
 * The returned rectangle is in final 1080x1920 output pixels. Keeping the
 * rectangle explicit avoids Remotion's AbsoluteFill defaults changing the
 * intended source aspect ratio.
 */

export type PortraitRect = Readonly<{
  left: number;
  top: number;
  width: number;
  height: number;
}>;

function positiveInteger(value: number, name: string): number {
  if (!Number.isInteger(value) || value < 1) {
    throw new Error(`${name} must be a positive integer`);
  }
  return value;
}

export function containRect(
  sourceWidth: number,
  sourceHeight: number,
  outputWidth: number,
  outputHeight: number,
): PortraitRect {
  const sourceW = positiveInteger(sourceWidth, "source width");
  const sourceH = positiveInteger(sourceHeight, "source height");
  const outputW = positiveInteger(outputWidth, "output width");
  const outputH = positiveInteger(outputHeight, "output height");
  const scale = Math.min(outputW / sourceW, outputH / sourceH);
  const width = Math.max(1, Math.round(sourceW * scale));
  const height = Math.max(1, Math.round(sourceH * scale));
  if (width > outputW || height > outputH) {
    throw new Error("contained rectangle exceeds the portrait output");
  }
  return {
    left: Math.floor((outputW - width) / 2),
    top: Math.floor((outputH - height) / 2),
    width,
    height,
  };
}

