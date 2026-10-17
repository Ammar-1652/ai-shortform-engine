import { Composition } from "remotion";

import { RoughPreview } from "./RoughPreview.js";
import type { RoughPreviewInput } from "./types.js";
import { compositionFacts, parseRenderInput } from "./validation.js";

const placeholder: RoughPreviewInput = {
  composition_id: "RoughPreview",
  candidate_id: "placeholder",
  preview_set_id: "placeholder",
  video_path: "/work/staging/analysis.mp4",
  audio_path: "/work/staging/asr.flac",
  media_trim_frame: 0,
  duration_in_frames: 30,
  fps_numerator: 30,
  fps_denominator: 1,
  width: 720,
  height: 1280,
  video_fit: "contain",
  background: "neutral-dark-v1",
      video_scale_permille: 1000,
      video_offset_x_px: 0,
      word_highlight_mode: "off",
  timing_quality: "provisional",
  captions: [],
};

export function RemotionRoot() {
  return (
    <Composition
      id="RoughPreview"
      component={RoughPreview}
      durationInFrames={placeholder.duration_in_frames}
      fps={30}
      width={720}
      height={1280}
      defaultProps={placeholder}
      calculateMetadata={({ props }) => {
        const facts = compositionFacts(props);
        return {
          durationInFrames: facts.durationInFrames,
          fps: facts.fps,
          width: facts.width,
          height: facts.height,
          props: parseRenderInput(props),
        };
      }}
    />
  );
}
