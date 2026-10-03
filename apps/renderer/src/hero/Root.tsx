import { Composition } from "remotion";

import { AdvancedHeroDraft } from "./AdvancedHeroDraft.js";
import { HeroDraft } from "./HeroDraft.js";
import type { HeroDraftInput } from "./types.js";
import { compositionFacts, parseHeroInput } from "./validation.js";

const placeholder: HeroDraftInput = {
  composition_id: "HeroDraft",
  candidate_id: "placeholder",
  hero_set_id: "placeholder",
  video_path: "/work/staging/analysis.mp4",
  audio_path: "/work/staging/asr.flac",
  media_trim_frame: 0,
  duration_in_frames: 30,
  fps_numerator: 30,
  fps_denominator: 1,
  width: 1080,
  height: 1920,
  video_fit: "contain",
  background: "neutral-dark-v1",
  alignment_quality: "forced",
  alignment_sha256: "a".repeat(64),
  edit_plan_sha256: "b".repeat(64),
  time_map_sha256: "c".repeat(64),
  review_id: "review-placeholder",
  review_digest: "d".repeat(64),
  motion_library_version: "motion-library-v1",
  profile_fingerprint: "e".repeat(64),
  captions: [
    {
      cue_id: "cue-placeholder",
      text: "Placeholder.",
      source_start_us: 0,
      source_end_us: 1_000_000,
      output_start_us: 0,
      output_end_us: 1_000_000,
      output_start_frame: 0,
      output_end_frame_exclusive: 30,
      alignment_quality: "forced",
      words: [{ text: "Placeholder.", output_start_frame: 0, output_end_frame_exclusive: 30 }],
    },
  ],
  motion_events: [],
};

const advancedPlaceholder = {
  duration_in_frames: 30,
  typography: [{ text: "Café $12.50", start_frame: 0, end_frame: 30 }],
  diagram: { left_label: "Café", right_label: "$12.50" },
  broll_name: null,
};

export function HeroRoot() {
  return (
    <>
    <Composition
      id="AdvancedHeroDraft"
      component={AdvancedHeroDraft}
      durationInFrames={30}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={advancedPlaceholder}
      calculateMetadata={({ props }) => ({
        durationInFrames: props.duration_in_frames,
        fps: 30,
        width: 1080,
        height: 1920,
        props,
      })}
    />
    <Composition
      id="HeroDraft"
      component={HeroDraft}
      durationInFrames={placeholder.duration_in_frames}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={placeholder}
      calculateMetadata={({ props }) => {
        const facts = compositionFacts(props);
        return {
          durationInFrames: facts.durationInFrames,
          fps: facts.fps,
          width: facts.width,
          height: facts.height,
          props: parseHeroInput(props),
        };
      }}
    />
    </>
  );
}
