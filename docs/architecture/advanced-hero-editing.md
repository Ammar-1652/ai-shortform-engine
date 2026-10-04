# Advanced Hero editing

Round 10 adds a separate advanced Hero artifact. It does not rewrite `hero_draft_set_json`.

## Profile

`advanced-hero-v1` is 1080×1920, 30/1, H.264, AAC, `yuv420p` (or the encoder's `yuvj420p`). Music is disallowed. B-roll and SFX must be rights-cleared local files. The maximum counts and gain limits live on the profile.

Reframing strategies are `contain`, `center_crop`, `manual_window`, `visual_safe_window`, `multi_face_safe_window`, and `saliency_window`. A face box is geometry. The largest face is not treated as the speaker. A strategy with too little evidence fails closed.

## Plan and render

`clipforge hero advanced plan` reads the current approved Hero review, forced alignment, Hero plan, visual analysis, and local assets. `clipforge hero advanced render` writes `advanced_hero_draft_set_json` through `RemotionAdvancedRenderBackend`. The CLI does not accept a test encoder. Unit tests pass `FakeAdvancedRenderBackend` explicitly. Candidates stay in Hero manifest rank order. Overlapping B-roll and overlapping typography fail planning.

Before a render job is inserted, every stored plan is checked against the current source, candidate set, rough preview, Hero artifact, Hero approval, alignment, Hero plan, visual analysis, TimeMap, asset hashes, and rights. A stale or revoked binding fails closed and does not publish a sidecar.

Asset paths are checked lexically before `Path.resolve()`. A symlink at the file or at a parent directory is rejected, including a symlink whose target has the expected hash. Absolute paths, `..`, backslashes, and file URIs outside the work root are rejected. The same check covers cache validation, staging, rendering, and media serving.

The production composition uses `contain` and the neutral-dark background `#111111`. It does not fall back to cover. Other reframing strategies fail before the job. B-roll keeps its output interval and `broll_source_in_us`. SFX gain converts with `10 ** (gain_db / 20)` inside `-24..6` dB and plays on the declared interval. Music is rejected.

## Review

`GET /api/advanced-hero-review` returns the current advanced set without filesystem paths. `GET /api/advanced-hero-review/hero/<candidate_id>` returns one candidate. `GET /media/advanced-hero/<candidate_id>` serves only that set's MP4. Decisions are append-only `ReviewDecision` rows for `approved`, `rejected`, and `changes_requested`. The page has no default selection. The newest decision on the current advanced artifact is the effective decision. Older rows stay in history. A mismatched advanced set returns the existing reload message. Text is assigned with `textContent`.

## Deferred

Envato search and download, publishing, music, full-source WhisperX, speaker attribution, face recognition, automatic approval, analytics, and republish automation.
