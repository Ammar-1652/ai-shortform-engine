import { describe, expect, it } from "vitest";
import { cueWindow, frameAtOrAfter } from "./program-frames.js";

describe("canonical program cue frames", () => {
  it("owns the next frame at an off-grid cut instead of captioning the outgoing picture", () => {
    expect(frameAtOrAfter(2_001_000)).toBe(61);
    expect(cueWindow(0, 2_001_000)).toEqual({ from: 0, duration: 61 });
    expect(cueWindow(2_001_000, 5_443_000)).toEqual({ from: 61, duration: 103 });
  });
  it("uses exact truncated frame starts, half-open endpoints and positive short cues", () => {
    expect(frameAtOrAfter(33_333)).toBe(1);
    expect(frameAtOrAfter(33_334)).toBe(2);
    expect(cueWindow(100_000, 133_333)).toEqual({ from: 3, duration: 1 });
    expect(cueWindow(100_001, 100_002)).toEqual({ from: 4, duration: 1 });
  });
  it("rejects floating or unsafe canonical cue time", () => {
    expect(() => frameAtOrAfter(1.5)).toThrow(/integer microseconds/);
    expect(() => frameAtOrAfter(-1)).toThrow(/integer microseconds/);
  });
});
