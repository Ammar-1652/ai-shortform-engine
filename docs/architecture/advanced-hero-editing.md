# Advanced Hero editing

Round 10 adds a separate advanced Hero artifact. It does not rewrite `hero_draft_set_json`.

## Profile

`advanced-hero-v1` is 1080×1920, 30/1, H.264, AAC, `yuv420p` (or the encoder's `yuvj420p`). Music is disallowed. B-roll and SFX must be rights-cleared local files. The maximum counts and gain limits live on the profile.

Reframing strategies are `contain`, `center_crop`, `manual_window`, `visual_safe_window`, `multi_face_safe_window`, and `saliency_window`. A face box is geometry. The largest face is not treated as the speaker. A strategy with too little evidence fails closed.

## Plan and render

`clipforge hero advanced plan` reads the current approved Hero review, forced alignment, Hero plan, visual analysis, and local assets. `clipforge hero advanced render` writes `advanced_hero_draft_set_json`. Candidates stay in Hero manifest rank order. Overlapping B-roll and overlapping typography fail planning.

The deterministic test encoder is ffmpeg. The Remotion composition is `AdvancedHeroDraft`. Text is a React child. Partial outputs are not promoted. A failed sidecar leaves the previous advanced set current.

## Review

`GET /api/advanced-hero-review` returns the current advanced set without filesystem paths. `GET /media/advanced-hero/<candidate_id>` serves only that set's MP4. Decisions remain append-only `ReviewDecision` rows.

## Deferred

Envato search and download, publishing, music, full-source WhisperX, speaker attribution, face recognition, automatic approval, analytics, and republish automation.
