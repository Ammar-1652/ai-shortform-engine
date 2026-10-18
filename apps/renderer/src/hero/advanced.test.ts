import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { linearVolume } from "./gain.js";

const source = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "AdvancedHeroDraft.tsx"), "utf8");

describe("advanced hero composition", () => {
  it("keeps text as React children and stays local", () => {
    expect(source).not.toContain("innerHTML");
    expect(source).not.toContain("dangerouslySetInnerHTML");
    expect(source).not.toContain("eval(");
    expect(source).not.toContain("http://");
    expect(source).not.toContain("https://");
    expect(source).toContain('objectFit: "cover"');
    expect(source).toContain('objectFit: "contain"');
    expect(source).toContain("containRect");
    expect(source).toContain("broll_source_in_us");
    expect(source).toContain("linearVolume");
    expect(source).toContain("CaptionPlate");
    expect(source).not.toContain("{typeText}");
    expect(source).not.toContain(".join(\" \")");
    expect(source).toContain("diagram.payload?.left_label");
    expect(source).toContain("staticFile(name)");
    expect(source).toContain("names.narration");
    expect(source).toContain("hook-card-v1");
    expect(source).toContain("punch-card-v1");
    expect(source).toContain("activeEmphasis");
    expect(source).toContain("editorial-clean-v1");
    expect(source).toContain("quran-editorial-v1");
    expect(source).toContain("concat-editorial-v1");
    expect(source).toContain("output_start_frame");
    expect(source).toContain("unsupported production diagram kind");
    expect(source).toContain("motionFor");
    expect(source).toContain("max_travel_px");
    expect(source).toContain("max_scale_permille");
    expect(source).toContain("font_identity");
    expect(source).toContain("safe_left");
    expect(source).toContain("safe_bottom");
    expect(source).toContain("source_native_text");
    expect(source).toContain("duplicatesNativeText");
    expect(source).toContain("complete caption style dependencies");
    expect(source).toContain("exactly one upper context line");
    expect(source).toContain("context-line-v1");
    expect(source).toContain("allowlisted emoji");
    expect(source).toContain("does not fit on one line");
    expect(source).toContain("concat_push_v1");
    expect(source).toContain("concat_blur_dissolve_v1");
    expect(source).toContain("useCurrentFrame");
    expect(source).not.toContain("top: 1720");
    const rendererEntrypoint = readFileSync(
      resolve(dirname(fileURLToPath(import.meta.url)), "../../scripts/render-advanced-hero.mjs"),
      "utf8",
    );
    expect(rendererEntrypoint).toContain('"quran-editorial-v1"');
    const captionPlate = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../captions/CaptionPlate.tsx"), "utf8");
    expect(captionPlate).toContain("hook || punch || typography");
    expect(captionPlate).toContain("whole shaped runs");
  });

  it("converts SFX gain from dB and rejects music-range values", () => {
    expect(linearVolume(0)).toBeCloseTo(1);
    expect(linearVolume(-6)).toBeCloseTo(10 ** (-6 / 20));
    expect(linearVolume(6)).toBeCloseTo(10 ** (6 / 20));
    expect(linearVolume(-24)).toBeCloseTo(10 ** (-24 / 20));
    expect(() => linearVolume(7)).toThrow(/-24 and 6/);
    expect(() => linearVolume(-25)).toThrow(/-24 and 6/);
  });
});
