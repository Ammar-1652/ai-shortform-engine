/** Facts Python already decided for one Hero draft. This is not the rough preview. */

export type HeroWord = {
  readonly text: string;
  readonly output_start_frame: number;
  readonly output_end_frame_exclusive: number;
};

export type HeroCaption = {
  readonly cue_id: string;
  readonly text: string;
  readonly source_start_us: number;
  readonly source_end_us: number;
  readonly output_start_us: number;
  readonly output_end_us: number;
  readonly output_start_frame: number;
  readonly output_end_frame_exclusive: number;
  readonly alignment_quality: "forced";
  readonly words: readonly HeroWord[];
};

export type HeroMotionEvent = {
  readonly event_id: string;
  readonly component_id: string;
  readonly purpose: string;
  readonly output_start_us: number;
  readonly output_end_us: number;
  readonly output_start_frame: number;
  readonly output_end_frame_exclusive: number;
  readonly library: string;
};

export type HeroDraftInput = {
  readonly schema_version?: "1.0.0";
  readonly composition_id: "HeroDraft";
  readonly candidate_id: string;
  readonly hero_set_id: string;
  readonly video_path: string;
  readonly audio_path: string;
  readonly media_trim_frame: number;
  readonly duration_in_frames: number;
  readonly fps_numerator: 30;
  readonly fps_denominator: 1;
  readonly width: 1080;
  readonly height: 1920;
  readonly video_fit: "contain";
  readonly background: "neutral-dark-v1";
  readonly alignment_quality: "forced";
  readonly alignment_sha256: string;
  readonly edit_plan_sha256: string;
  readonly time_map_sha256: string;
  readonly review_id: string;
  readonly review_digest: string;
  readonly motion_library_version: "motion-library-v1";
  readonly profile_fingerprint: string;
  readonly captions: readonly HeroCaption[];
  readonly motion_events: readonly HeroMotionEvent[];
};

export const COMPOSITION_ID = "HeroDraft" as const;
export const OUTPUT_WIDTH = 1080;
export const OUTPUT_HEIGHT = 1920;
export const MOTION_LIBRARY_VERSION = "motion-library-v1" as const;
export const NEUTRAL_DARK = "#111111";
export const EMPHASIS_SCALE = 1.04;
