import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { activeCaption } from "./captions.js";
import { containedRect, VIDEO_OBJECT_FIT } from "./layout.js";
import type { RoughCaptionCue, RoughPreviewInput } from "./types.js";
import { compositionFacts, parseRenderInput } from "./validation.js";

const here = dirname(fileURLToPath(import.meta.url));

function cue(overrides: Partial<RoughCaptionCue> = {}): RoughCaptionCue {
  return {
    cue_id: "cue-1",
    text: "Hello world.",
    transcript_segment_ids: ["seg-0"],
    transcript_word_ids: ["w-0"],
    source_start_us: 0,
    source_end_us: 1_000_000,
    output_start_us: 0,
    output_end_us: 1_000_000,
    output_start_frame: 0,
    output_end_frame_exclusive: 30,
    timing_quality: "provisional",
    words: [],
    ...overrides,
  };
}

function input(overrides: Partial<RoughPreviewInput> = {}): RoughPreviewInput {
  return {
    composition_id: "RoughPreview",
    candidate_id: "cand-1",
    preview_set_id: "set-1",
    video_path: "/work/staging/analysis.mp4",
    audio_path: "/work/staging/asr.flac",
    media_trim_frame: 12,
    duration_in_frames: 90,
    fps_numerator: 30,
    fps_denominator: 1,
    width: 720,
    height: 1280,
    video_fit: "contain",
    background: "neutral-dark-v1",
    video_scale_permille: 1000,
    video_offset_x_px: 0,
    word_highlight_mode: "off",
    word_timing_source: "segment-only-v1",
    timing_quality: "provisional",
    captions: [cue()],
    ...overrides,
  };
}

describe("rough preview render input", () => {
  it("parses a valid payload and keeps Python's duration", () => {
    const parsed = parseRenderInput(input());
    expect(parsed.duration_in_frames).toBe(90);
    expect(parsed.captions[0]?.text).toBe("Hello world.");
    expect(compositionFacts(input({ duration_in_frames: 48 })).durationInFrames).toBe(48);
  });

  it("rejects dimensions other than 720x1280", () => {
    expect(() => parseRenderInput({ ...input(), width: 1080 })).toThrow(/720x1280/);
  });

  it("rejects a non-positive duration", () => {
    expect(() => parseRenderInput({ ...input(), duration_in_frames: 0 })).toThrow(/duration_in_frames/);
    expect(() => parseRenderInput({ ...input(), duration_in_frames: 1.5 })).toThrow(/duration_in_frames/);
  });

  it("rejects a caption whose frame interval is not half-open", () => {
    expect(() =>
      parseRenderInput(input({ captions: [cue({ output_start_frame: 10, output_end_frame_exclusive: 10 })] })),
    ).toThrow(/half-open/);
  });

  it("rejects a caption that extends past the composition", () => {
    expect(() =>
      parseRenderInput(input({ captions: [cue({ output_end_frame_exclusive: 91 })] })),
    ).toThrow(/outside duration_in_frames/);
  });

  it("rejects a remote media URL", () => {
    expect(() => parseRenderInput(input({ video_path: "https://example.com/a.mp4" }))).toThrow(/http/);
    expect(() => parseRenderInput(input({ audio_path: "http://example.com/a.flac" }))).toThrow(/http/);
  });

  it("rejects unexpected and dangerous fields", () => {
    expect(() => parseRenderInput({ ...input(), dangerouslySetInnerHTML: { __html: "<b>" } })).toThrow(/rejected/);
    expect(() => parseRenderInput({ ...input(), eval: "alert(1)" })).toThrow(/rejected|unexpected/);
  });

  it("renders with zero captions and keeps Unicode text", () => {
    expect(parseRenderInput(input({ captions: [] })).captions).toEqual([]);
    const text = "café 日本語 42";
    const parsed = parseRenderInput(input({ captions: [cue({ text })] }));
    expect(parsed.captions[0]?.text).toBe(text);
  });

  it("accepts only bounded uniform scale and explicit review highlighting", () => {
    expect(parseRenderInput(input({ video_scale_permille: 1150, video_offset_x_px: 54, word_highlight_mode: "reviewed" })).video_offset_x_px).toBe(54);
    expect(() => parseRenderInput(input({ video_scale_permille: 1300 }))).toThrow(/video_scale_permille/);
    expect(() => parseRenderInput(input({ video_offset_x_px: 121 }))).toThrow(/video_offset_x_px/);
    expect(() => parseRenderInput(input({ word_highlight_mode: "forced" as never }))).toThrow(/word_highlight_mode/);
  });

  it("accepts the explicit source-blur background variant", () => {
    expect(parseRenderInput(input({ background: "blurred-source-v1" })).background).toBe("blurred-source-v1");
    expect(parseRenderInput(input({ word_highlight_mode: "reviewed", word_timing_source: "reviewed-word-times-v1", captions: [cue({ words: [{ word_id: "w-0", text: "Hello", output_start_us: 0, output_end_us: 500_000, output_start_frame: 0, output_end_frame_exclusive: 15, verification_status: "unverified" }] })] })).word_timing_source).toBe("reviewed-word-times-v1");
  });

  it("rejects reviewed words without a declared timing source", () => {
    const word = { word_id: "w-0", text: "Hello", output_start_us: 0, output_end_us: 500_000, output_start_frame: 0, output_end_frame_exclusive: 15, verification_status: "unverified" as const };
    expect(() => parseRenderInput(input({ word_highlight_mode: "reviewed", captions: [cue({ words: [word] })] }))).toThrow(/timing source/);
  });

  it("accepts a source-bound Tarteel CTA and alpha watermark overlay", () => {
    const overlay = {
      schema_version: "1.0.0",
      campaign_id: "tarteel",
      cta_asset_id: "cta-asset",
      cta_asset_sha256: "a".repeat(64),
      cta_asset_name: "tarteel-cta-alpha.webm",
      cta_background_removal: "chroma_key_v1",
      cta_render_mode: "alpha_png_sequence_v1",
      cta_frame_prefix: "tarteel-cta-alpha",
      cta_frame_count: 60,
      cta_frame_rate: 30,
      cta_start_us: 1_000_000,
      cta_end_us: 3_000_000,
      watermark_asset_id: "watermark-asset",
      watermark_asset_sha256: "b".repeat(64),
      watermark_asset_name: "tarteel-watermark-alpha.png",
      watermark_mode: "alpha_v1",
      watermark_position: "top_right",
      watermark_width_permille: 170,
      first_post_caption_line: "اشترك في قناة ترتيل على اليوتيوب: @tarteelarabic",
    } as const;
    expect(parseRenderInput(input({ campaign_overlay: overlay })).campaign_overlay?.cta_asset_name).toBe(
      "tarteel-cta-alpha.webm",
    );
  });

  it("keeps legacy inputs compatible when the optional overlay is null", () => {
    expect(parseRenderInput({ ...input(), campaign_overlay: null }).campaign_overlay).toBeUndefined();
  });

  it("rejects an opaque CTA contract", () => {
    const overlay = {
      schema_version: "1.0.0",
      campaign_id: "tarteel",
      cta_asset_id: "cta-asset",
      cta_asset_sha256: "a".repeat(64),
      cta_asset_name: "cta.mp4",
      cta_background_removal: "none",
      cta_render_mode: "alpha_png_sequence_v1",
      cta_frame_prefix: "cta",
      cta_frame_count: 60,
      cta_frame_rate: 30,
      cta_start_us: 1_000_000,
      cta_end_us: 3_000_000,
      watermark_asset_id: "watermark-asset",
      watermark_asset_sha256: "b".repeat(64),
      watermark_asset_name: "watermark.png",
      watermark_mode: "alpha_v1",
      watermark_position: "top_right",
      watermark_width_permille: 170,
      first_post_caption_line: "اشترك في قناة ترتيل على اليوتيوب: @tarteelarabic",
    };
    expect(() => parseRenderInput(input({ campaign_overlay: overlay as never }))).toThrow(/overlay/);
  });
});

describe("provisional caption frames", () => {
  const captions = [
    cue({ cue_id: "early", output_start_frame: 2, output_end_frame_exclusive: 5, text: "early" }),
    cue({ cue_id: "later", output_start_frame: 5, output_end_frame_exclusive: 8, text: "later" }),
  ];

  it("selects the same cue for the same frame", () => {
    expect(activeCaption(captions, 3)?.cue_id).toBe("early");
    expect(activeCaption(captions, 3)?.cue_id).toBe(activeCaption(captions, 3)?.cue_id);
  });

  it("does not show a caption before its start frame", () => {
    expect(activeCaption(captions, 0)).toBeNull();
    expect(activeCaption(captions, 1)).toBeNull();
    expect(activeCaption(captions, 2)?.text).toBe("early");
  });

  it("ends at the exclusive end frame", () => {
    expect(activeCaption(captions, 4)?.cue_id).toBe("early");
    expect(activeCaption(captions, 5)?.cue_id).toBe("later");
  });
});

describe("contain layout", () => {
  it("letterboxes landscape footage", () => {
    const rect = containedRect(1920, 1080, 720, 1280);
    expect(rect.fit).toBe(VIDEO_OBJECT_FIT);
    expect(rect.width).toBeCloseTo(720);
    expect(rect.height).toBeLessThan(1280);
    expect(rect.y).toBeGreaterThan(0);
  });

  it("keeps portrait footage fully visible", () => {
    const rect = containedRect(1080, 1920, 720, 1280);
    expect(rect.height).toBeCloseTo(1280);
    expect(rect.width).toBeLessThanOrEqual(720);
    expect(rect.x).toBeGreaterThanOrEqual(0);
  });
});

describe("composition source", () => {
  it("does not inject transcript HTML", () => {
    const picture = readFileSync(resolve(here, "RoughPreview.tsx"), "utf8");
    const overlay = readFileSync(resolve(here, "captions.ts"), "utf8");
    expect(picture).not.toContain("dangerouslySetInnerHTML");
    expect(overlay).not.toContain("dangerouslySetInnerHTML");
    expect(picture).toContain("caption.text");
  });
});
