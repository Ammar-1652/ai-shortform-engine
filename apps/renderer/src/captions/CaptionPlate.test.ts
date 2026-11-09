import { describe, expect, it } from "vitest";

import { captionWordColor } from "./CaptionPlate.js";

describe("caption word verification colors", () => {
  it("shows a verified word green only while it is active", () => {
    expect(captionWordColor("correct", true)).toBe("#42d487");
    expect(captionWordColor("correct", false)).toBeUndefined();
  });

  it("keeps an incorrect word red after its active interval", () => {
    expect(captionWordColor("incorrect", true)).toBe("#ff4d5f");
    expect(captionWordColor("incorrect", false)).toBe("#ff4d5f");
  });

  it("does not claim correctness for an unverified word", () => {
    expect(captionWordColor("unverified", true, "#64d8ff")).toBe("#64d8ff");
    expect(captionWordColor("unverified", false, "#64d8ff")).toBeUndefined();
  });
});
