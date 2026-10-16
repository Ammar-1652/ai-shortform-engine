import { describe, expect, it } from "vitest";

import { containRect } from "./portrait-transform.js";

describe("portrait contain transform", () => {
  it("preserves a 16:9 source inside a 1080x1920 output", () => {
    expect(containRect(1920, 1080, 1080, 1920)).toEqual({
      left: 0,
      top: 656,
      width: 1080,
      height: 608,
    });
  });

  it("centers a portrait source without stretching it", () => {
    expect(containRect(720, 1280, 1080, 1920)).toEqual({
      left: 0,
      top: 0,
      width: 1080,
      height: 1920,
    });
  });

  it("handles odd source dimensions with bounded integer pixels", () => {
    const rect = containRect(1279, 719, 1080, 1920);
    expect(rect.width).toBe(1080);
    expect(rect.height).toBe(607);
    expect(rect.left).toBe(0);
    expect(rect.top).toBe(656);
    expect(rect.top + rect.height).toBeLessThanOrEqual(1920);
  });

  it("rejects unknown or invalid dimensions instead of guessing", () => {
    expect(() => containRect(0, 1080, 1080, 1920)).toThrow(/source width/);
    expect(() => containRect(1920.5, 1080, 1080, 1920)).toThrow(/source width/);
  });
});
