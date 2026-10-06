# Dynamic reframing

`contain` is the default Advanced Hero picture strategy. `face_follow` is an explicit crop built from stored face-detection and face-track geometry.

## What face_follow is

The trajectory is a deterministic crop for each output frame. Output time is mapped through the candidate `TimeMap`. Word spans are not a second clock. The plan stores `time_map_sha256` and rejects a mismatched digest. Face samples use the visual analyzer's cadence. The production cadence is 500_000 us. A gap fails only when it is longer than that cadence plus the stored tolerance. The crop keeps one face box inside a 9:16 window, with a fixed headroom inset, integer smoothing, and a maximum step of 12 pixels per frame. Frame count uses the same 30/1 half-open rule as `TimeMap.output_frame_count`. The frame that starts at the exact output endpoint is excluded.

A face box is not an identity. The track id is geometry inside one analysis. `face_follow` does not run face recognition, does not name a person, and does not infer that the visible face is the speaker. `speaker_attribution` stays `unknown`.

## Eligibility

An explicit `face_follow` plan is written only when all of these hold:

- the visual-analysis artifact is present, its producer job succeeded, and its source hash matches the source;
- the selected interval contains exactly one track;
- confidence, coverage, and gaps meet the fixed thresholds;
- every crop stays inside the source and keeps the face box inside the safe inset;
- no crop center moves faster than the maximum step.

Otherwise the command fails with a specific blocker such as `face_follow_requires_one_track`, `face_track_coverage_insufficient`, `face_track_confidence_insufficient`, `face_track_gap_too_long`, `face_follow_crop_out_of_bounds`, `face_follow_motion_too_fast`, `visual_analysis_stale`, `visual_analysis_missing`, `visual_analysis_producer_failed`, or `time_map_stale`. A requested `face_follow` plan is not rewritten as `contain`. A missing plan is reported as missing, not as a successful reframe.

## Render and review

The renderer applies the stored windows. It does not detect faces again. Captions stay React text. B-roll, typography, diagrams, SFX, and emphasis keep their output times. Output stays 1080×1920, H.264, and AAC. A stale or invalid trajectory fails before render.

QA records the requested strategy, the applied strategy, the track id, the trajectory hash, the crop size, safe-area compliance, movement, coverage, confidence, and any blocker. The final-review page shows those facts. Its evidence digest includes the strategy and the trajectory hash. A changed trajectory invalidates QA, the final approval, the local package, and the campaign production cache.

`clipforge hero advanced plan SOURCE_ID CANDIDATE_ID --reframing face_follow` opts in. `clipforge hero advanced reframe doctor`, `show`, and `verify` only read.

## Deferred

Whop MCP stays deferred. External platform publishing stays deferred. Arabic and Japanese alignment stay `alignment_not_claimed` unless a real provider runs.
