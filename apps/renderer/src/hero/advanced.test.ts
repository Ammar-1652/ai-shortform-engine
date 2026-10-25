import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { linearVolume } from "./gain.js";
import { cameraFor } from "./AdvancedHeroDraft.js";
import { motionRecipeRoute, validateMotionRecipes } from "./motionRecipeRegistry.js";

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
    expect(source).toContain("platform-resilient-portrait-v1");
    expect(source).toContain("overlay_exclusion_sha256");
    expect(source).toContain("clean Tarteel overlays require transformed exclusion evidence");
    expect(source).toContain("clean Tarteel overlays require an accepted editorial arc review");
    expect(source).toContain("foregroundScale = frameTheme && frameLayoutId === \"platform-bleed-v1\"");
    expect(source).toContain("const maxContextLines = 2");
    expect(source).toContain("tarteel-card-olive-gold-v1");
    expect(source).toContain("auto-source-palette-v1");
    expect(source).toContain("quran_challenge");
    expect(source).toContain("palette-solid-v1");
    expect(source).toContain("platform-bleed-v1");
    expect(source).toContain("dimBlurredFrameBackdrop");
    expect(source).toContain("rgba(0,0,0,0.34)");
    expect(source).toContain("backdrop_hex");
    expect(source).toContain("review_watermark_slot");
    expect(source).toContain("review_foreground_scale_permille");
    expect(source).toContain("reviewFrameBox");
    expect(source).toContain("unsupported frame style");
    expect(source).toContain("source_native_text");
    expect(source).toContain("duplicatesNativeText");
    expect(source).toContain("complete caption style dependencies");
    expect(source).toContain("exactly one upper context line");
    expect(source).toContain("context-line-v1");
    expect(source).toContain("allowlisted emoji");
    expect(source).toContain("context line does not fit within the");
    expect(source).toContain("concat_push_v1");
    expect(source).toContain("concat_blur_dissolve_v1");
    expect(source).toContain("useCurrentFrame");
    expect(source).not.toContain("top: 1720");
    const rendererEntrypoint = readFileSync(
      resolve(dirname(fileURLToPath(import.meta.url)), "../../scripts/render-advanced-hero.mjs"),
      "utf8",
    );
    expect(rendererEntrypoint).toContain('"quran-editorial-v1"');
    expect(rendererEntrypoint).toContain("CLIPFORGE_RENDER_AUTHORITY");
    expect(rendererEntrypoint).toContain("validateRenderAuthorization");
    expect(rendererEntrypoint).toContain("canonical input digest");
    expect(rendererEntrypoint).toContain("browserSetupTimeoutMs");
    expect(rendererEntrypoint).toContain("advanced_service");
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

  it("applies bounded direction camera motion only inside its interval", () => {
    const event = {
      interval: { output_start_us: 0, output_end_us: 1_000_000 },
      path: "push_in" as const,
      target_x_permille: 250,
      target_y_permille: 750,
      scale_start_permille: 1000,
      scale_end_permille: 1060,
      travel_px: 32,
      easing: "linear" as const,
    };
    expect(cameraFor(0, [event])).toEqual({
      transform: "translate3d(0px, 0px, 0) scale(1)",
      transformOrigin: "center center",
    });
    expect(cameraFor(15, [event]).transform).toContain("scale(1.031");
    expect(cameraFor(29, [event]).transform).toContain("scale(1.06)");
    expect(cameraFor(31, [{ ...event, interval: { output_start_us: 2_000_000, output_end_us: 3_000_000 } }])).toEqual({});
  });

  it("routes only admitted motion recipes and requires a catalog fingerprint", () => {
    expect(motionRecipeRoute("motion-hook-card-v1").componentId).toBe("hook-card-v1");
    expect(() => motionRecipeRoute("operator-code")).toThrow(/unsupported production motion recipe/);
    expect(() => validateMotionRecipes(["motion-hook-card-v1"])).toThrow(/catalog fingerprint/);
    expect(() => validateMotionRecipes(["motion-hook-card-v1"], "a".repeat(64))).not.toThrow();
    const admitted = [
      "motion-caption-emphasis-v1", "motion-caption-emphasis-short-v1", "motion-caption-emphasis-payoff-v1",
      "motion-caption-emphasis-process-v1", "motion-context-reveal-v1", "motion-context-reveal-question-v1",
      "motion-context-reveal-takeaway-v1", "motion-hook-card-v1", "motion-hook-card-question-v1",
      "motion-hook-card-proof-v1", "motion-punch-card-v1", "motion-punch-card-result-v1",
      "motion-punch-card-reaction-v1", "motion-native-graphic-v1", "motion-graphic-concept-v1",
      "motion-graphic-data-v1", "motion-concat-dissolve-v1", "motion-concat-dissolve-payoff-v1",
      "motion-quran-challenge-v1", "motion-concat-push-v1", "motion-concat-push-location-v1",
    ];
    expect(() => validateMotionRecipes(admitted, "a".repeat(64))).not.toThrow();
  });
});
