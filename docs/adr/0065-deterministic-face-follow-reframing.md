# ADR 0065: Deterministic face-follow reframing

## Status

Accepted for Round 29.

## Context

Advanced Hero rendered every picture with static `contain` framing. Face detection and tracking evidence already existed, and a face observation is required to stay `speaker_attribution = unknown`. Operators still could not keep one detected face inside a vertical crop without a second editor or a recognition model.

## Decision

`contain` remains the default. `face_follow` is an opt-in strategy. It builds an integer crop trajectory from the stored visual-analysis artifact and the candidate `TimeMap`, and persists that trajectory beside the advanced plan. Output frames are mapped with `TimeMap.output_to_source`. The renderer consumes the stored windows and the publish gate compares every window, the trajectory hash, the TimeMap hash, and the source hash. It does not sample pixels to find a face. The permitted face gap is the analyzer cadence plus one decoded-frame period of the selected source's rational frame rate. The production cadence is 500_000 us.

Eligibility fails closed. Insufficient evidence returns a named blocker and does not relabel the result as `face_follow`. The contracts reject unknown keys, non-finite numbers, bad rectangles, and unsafe text. No absolute path is stored.

QA, final review, local delivery, and the campaign production aggregate bind the applied strategy and the trajectory hash. A changed source, analysis, track, or trajectory invalidates the later gates. Human final approval stays mandatory. `ReviewDecision.automated` stays false.

This is not face recognition and not speaker attribution.

## Consequences

Portrait output can follow one stable face in landscape media when the evidence qualifies. Contain renders stay the path for every other source. Whop MCP and external publishing remain deferred. Multilingual alignment remains limited to providers that have actually run.

SQLite schema version stays 6. Contract `schema_version` stays `1.0.0`.
