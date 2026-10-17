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
  readonly campaign_overlay?: CampaignOverlaySpec;
  readonly font_identity?: string;
  readonly video_scale_permille: number;
  readonly video_offset_x_px: number;
  readonly word_highlight_mode: "off" | "reviewed";
  readonly word_timing_source: "segment-only-v1" | "transcript-word-times-v1" | "reviewed-word-times-v1";
  readonly timing_quality: "provisional";
  readonly captions: readonly RoughCaptionCue[];
  readonly source_start_us?: number;
  readonly source_end_us?: number;
  readonly proxy_sha256?: string;
  readonly staged_video_sha256?: string;
  readonly staged_audio_sha256?: string;
  readonly staged_duration_us?: number;
};

export type CampaignOverlaySpec = {
  readonly campaign_id: "tarteel";
  readonly cta_asset_id: string;
  readonly cta_asset_sha256: string;
  readonly cta_asset_name: string;
  readonly cta_background_removal: "chroma_key_v1";
  readonly cta_render_mode: "alpha_video_v1" | "alpha_png_sequence_v1";
  readonly cta_frame_prefix?: string;
  readonly cta_frame_count?: number;
  readonly cta_frame_rate: 30;
  readonly cta_position: "top_left_brand_rail_v1";
  readonly cta_left_permille: number;
  readonly cta_top_permille: number;
  readonly cta_width_permille: number;
  readonly cta_start_us: number;
  readonly cta_end_us: number;
  readonly watermark_asset_id: string;
  readonly watermark_asset_sha256: string;
  readonly watermark_asset_name: string;
  readonly watermark_mode: "alpha_v1";
  readonly watermark_position: "top_right";
  readonly watermark_width_permille: number;
  readonly first_post_caption_line: "اشترك في قناة ترتيل على اليوتيوب: @tarteelarabic";
};

export const COMPOSITION_ID = "RoughPreview" as const;
export const OUTPUT_WIDTH = 720;
export const OUTPUT_HEIGHT = 1280;
export const NEUTRAL_DARK = "#111111";
