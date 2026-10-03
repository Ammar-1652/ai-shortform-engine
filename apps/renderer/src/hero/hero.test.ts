import { describe, expect, it } from "vitest";

import { emphasisScale, layerOpacity, revealedCaption, serializeMotion } from "./motion.js";
import { EMPHASIS_SCALE, OUTPUT_HEIGHT, OUTPUT_WIDTH, type HeroCaption, type HeroDraftInput, type HeroMotionEvent } from "./types.js";
import { parseHeroInput } from "./validation.js";

const sha = "a".repeat(64);

function word(text: string, start: number, end: number) {
  return { text, output_start_frame: start, output_end_frame_exclusive: end };
}

function caption(overrides: Partial<HeroCaption> = {}): HeroCaption {
  return {
    cue_id: "cue-1",
    text: "説明 12.",
    source_start_us: 0,
    source_end_us: 1_000_000,
    output_start_us: 0,
    output_end_us: 1_000_000,
    output_start_frame: 0,
    output_end_frame_exclusive: 30,
    alignment_quality: "forced",
    words: [word("説明 ", 0, 15), word("12.", 15, 30)],
    ...overrides,
  };
}

function event(overrides: Partial<HeroMotionEvent> = {}): HeroMotionEvent {
  return {
    event_id: "event-1",
    component_id: "opening-fade-v1",
    purpose: "visual_reveal",
    output_start_us: 0,
    output_end_us: 266_666,
    output_start_frame: 0,
    output_end_frame_exclusive: 8,
    library: "motion-library-v1",
    ...overrides,
  };
}

function input(overrides: Partial<HeroDraftInput> = {}): HeroDraftInput {
  return {
    composition_id: "HeroDraft",
    candidate_id: "cand-1",
    hero_set_id: "hero-1",
    video_path: "/work/staging/analysis.mp4",
    audio_path: "/work/staging/asr.flac",
    media_trim_frame: 0,
    duration_in_frames: 36,
    fps_numerator: 30,
    fps_denominator: 1,
    width: 1080,
    height: 1920,
    video_fit: "contain",
    background: "neutral-dark-v1",
    alignment_quality: "forced",
    alignment_sha256: sha,
    edit_plan_sha256: sha,
    time_map_sha256: sha,
    review_id: "review-1",
    review_digest: sha,
    motion_library_version: "motion-library-v1",
    profile_fingerprint: sha,
    captions: [caption()],
    motion_events: [event()],
    ...overrides,
  };
}

describe("hero draft render input", () => {
  it("keeps forced unicode captions and the portrait profile", () => {
    const parsed = parseHeroInput(input());
    expect(parsed.width).toBe(OUTPUT_WIDTH);
    expect(parsed.height).toBe(OUTPUT_HEIGHT);
    expect(parsed.captions[0]?.text).toBe("説明 12.");
    expect(parsed.alignment_quality).toBe("forced");
  });

  it("rejects rough dimensions, remote media, and provisional alignment", () => {
    expect(() => parseHeroInput({ ...input(), width: 720, height: 1280 })).toThrow(/1080x1920/);
    expect(() => parseHeroInput({ ...input(), video_path: "https://example.com/a.mp4" })).toThrow(/http/);
    const provisional: unknown = { ...input(), alignment_quality: "provisional" };
    expect(() => parseHeroInput(provisional)).toThrow(/forced/);
  });
});

describe("hero motion library v1", () => {
  it("reveals caption words on forced frames and emphasizes only marked cues", () => {
    const cue = caption();
    expect(revealedCaption(cue, 0)).toBe("説明");
    expect(revealedCaption(cue, 15)).toBe("説明 12.");
    expect(revealedCaption(cue, 30)).toBe("");
    const events = [
      event(),
      event({
        event_id: "event-2",
        component_id: "caption-emphasis-v1",
        output_start_frame: 15,
        output_end_frame_exclusive: 30,
      }),
    ];
    expect(layerOpacity(events, 0)).toBe(0);
    expect(layerOpacity(events, 8)).toBe(1);
    expect(emphasisScale(events, 14)).toBe(1);
    expect(emphasisScale(events, 15)).toBe(EMPHASIS_SCALE);
  });

  it("serializes the same events to the same text", () => {
    const events = [
      event({ event_id: "b", output_start_us: 20 }),
      event({ event_id: "a", output_start_us: 10 }),
    ];
    expect(serializeMotion(events)).toBe(serializeMotion([...events].reverse()));
    expect(serializeMotion(events)).toContain("motion-library-v1");
  });
});
