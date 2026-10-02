import { describe, expect, it } from "vitest";

import { RENDERER_STATUS, remotionPackageVersion, scaffold, schemaIndexVersion } from "./index.js";

describe("renderer scaffold", () => {
  it("does not claim to render video", () => {
    expect(RENDERER_STATUS).toBe("scaffold");
    expect(scaffold()).toEqual({ status: "scaffold", rendersVideo: false });
  });

  it("reads the exported contract index", () => {
    expect(schemaIndexVersion()).toBe("1.0.0");
  });

  it("sees an installed remotion package version", () => {
    expect(remotionPackageVersion()).toMatch(/^\d+\.\d+\.\d+/);
  });
});
