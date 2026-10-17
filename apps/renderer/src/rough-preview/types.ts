/** Facts Python already decided. The renderer does not recompute canonical time. */

export type RoughCaptionCue = {
  readonly cue_id: string;
  readonly text: string;
  readonly transcript_segment_ids: readonly string[];
  readonly transcript_word_ids: readonly string[];
  readonly source_start_us: number;
  readonly source_end_us: number;
  readonly output_start_us: number;
  readonly output_end_us: number;
  readonly output_start_frame: number;
  readonly output_end_frame_exclusive: number;
  readonly timing_quality: "provisional";
  readonly words: readonly RoughCaptionWord[];
};

export type RoughCaptionWord = {
  readonly word_id: string;
  readonly text: string;
  readonly output_start_us: number;
  readonly output_end_us: number;
  readonly output_start_frame: number;
  readonly output_end_frame_exclusive: number;
  readonly verification_status: "unverified" | "correct" | "incorrect";
};

export type RoughPreviewInput = {
  readonly composition_id: "RoughPreview";
  readonly candidate_id: string;
  readonly preview_set_id: string;
  readonly video_path: string;
  readonly audio_path: string;
  readonly media_trim_frame: number;
  readonly duration_in_frames: number;
  readonly fps_numerator: 30;
  readonly fps_denominator: 1;
  readonly width: 720;
  readonly height: 1280;
  readonly video_fit: "contain";
  readonly background: "neutral-dark-v1" | "blurred-source-v1";
  readonly font_identity?: string;
  readonly video_scale_permille: number;
  readonly video_offset_x_px: number;
  readonly word_highlight_mode: "off" | "reviewed";
  readonly timing_quality: "provisional";
  readonly captions: readonly RoughCaptionCue[];
  readonly source_start_us?: number;
  readonly source_end_us?: number;
  readonly proxy_sha256?: string;
  readonly staged_video_sha256?: string;
  readonly staged_audio_sha256?: string;
  readonly staged_duration_us?: number;
};

export const COMPOSITION_ID = "RoughPreview" as const;
export const OUTPUT_WIDTH = 720;
export const OUTPUT_HEIGHT = 1280;
export const NEUTRAL_DARK = "#111111";
