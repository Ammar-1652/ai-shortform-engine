import { describe, expect, it } from "vitest";

import { faceInSafe, frameStartUs, placedVideo, windowAt, windowInsideSource, type CropWindow } from "./crop.js";

const frame = (index: number, x: number): CropWindow => ({
  output_start_us: frameStartUs(index),
  output_end_us: frameStartUs(index + 1),
  source_x: x,
  source_y: 0,
  source_width: 101,
  source_height: 180,
  frame_width: 320,
  frame_height: 180,
});

describe("face-follow crop", () => {
  it("keeps contain geometry free of a crop offset", () => {
    const window = frame(0, 40);
    expect(windowInsideSource(window)).toBe(true);
    const placed = placedVideo(window);
    expect(placed.width).toBeGreaterThan(1080);
    expect(placed.left).toBeCloseTo(-40 * (1080 / 101));
  });

  it("moves the crop and stays inside the source", () => {
    const windows = [frame(0, 40), frame(1, 48), frame(2, 56)];
    const first = placedVideo(windowAt(0, windows));
    const later = placedVideo(windowAt(2, windows));
    expect(later.left).toBeLessThan(first.left);
    for (const item of windows) {
      expect(windowInsideSource(item)).toBe(true);
    }
  });

  it("keeps the face inside the safe region and does not drift frames", () => {
    const window = frame(3, 80);
    expect(frameStartUs(3)).toBe(Math.floor((3 * 1_000_000) / 30));
    expect(windowAt(3, [frame(0, 40), frame(1, 48), frame(2, 56), window]).output_start_us).toBe(frameStartUs(3));
    expect(
      faceInSafe({ x: 100, y: 40, width: 30, height: 40 }, window),
    ).toBe(true);
    expect(() => windowAt(4, [window])).toThrow(/drifted/);
  });
});
