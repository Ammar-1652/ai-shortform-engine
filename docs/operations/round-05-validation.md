# Round 5 validation

Round 5 mines candidate intervals from the current transcript and the current visual analysis. The draft PR is not merged. Round 6 has not started.

## Baseline

- Required main SHA: `00402a23ceac3f7814d1a4aa0019f815cf54554c`
- Branch: `round-05-candidate-mining`
- Database schema: 4
- Migration added: none

## Dependencies

No new runtime dependency. Mining uses the standard library, Pydantic, and the existing transcript and visual contracts. No remote LLM. No network call during mining. Whisper and MediaPipe weights are not required.

## Inputs

The command accepts a source id. It requires a cleared rights record, an unchanged source file, a succeeded transcript producer, and a succeeded visual producer. The combined digest hashes the two artifact byte hashes. Cross-source pairs fail.

## Timing and windows

Boundaries are provisional. Word edges plus 250 ms padding are used when words exist. Segment edges are used otherwise. Hard duration limits are 8,000,000 µs and 65,000,000 µs. Preferred span is 18–45 seconds. The raw walk caps at 5000 and says so.

## Scores

Quality weights: 0.15, 0.20, 0.20, 0.20, 0.10, 0.05, 0.10. Edit weights: 0.25, 0.25, 0.15, 0.15, 0.10, 0.10. Missing features stay null and weights renormalize. Quality coverage below 0.70 rejects the hypothesis. There is no quality floor and no combined score. `creative_score` is `quality_score`.

## Dedupe and count

Near-duplicate: containment >= 0.80, or temporal IoU >= 0.70 and token Jaccard >= 0.70. Pre-dedupe pool: 200. Maximum selected: 25. Soft target: 15, informational. Empty output is a successful document.

## Compliance

Six deterministic rules: source rights, current transcript, current visual analysis, source range, transcript evidence, visual evidence. All must pass before `ready_for_review`. The score cannot override a failure. No platform or campaign claim.

## Artifact, cache, locks

Kind `candidate_set_json`. Job `candidate_mine`. Recipe `candidate-mining` v1. Profile fingerprint is computed from the stored profile. Lock order is prepare shared, transcribe shared, vision shared, candidate exclusive. Failures mark the new job failed or cancelled and leave the previous current artifact in place.

## Tests

Marker `candidate`. CI job `candidate` runs `pytest -m candidate` on `ubuntu-latest` with no FFmpeg install and no model download. The Python job excludes that marker.

Covered cases include empty transcript, short source, seven candidates, the 25 cap, word edges, segment-only text, missing confidence, quality ahead of edit opportunity, containment and adjacent ranges, transcript and visual invalidation, source mutation, failed upstream jobs, cross-source refusal, compliance, faces not changing quality, cache, force, locks, stale jobs, failure, cancellation, and a changed candidate file.

`uv run pytest` passed 207 tests: general 95, media 18, transcription 29, vision 34, candidate 31. `ruff`, `mypy`, `clipforge schema check`, and the four doctor commands passed. The renderer lint, typecheck, and Vitest suite passed. Transcript doctor warns that CUDA libraries and the default ASR model are absent. Vision doctor warns that the face model is not cached. Candidate mining does not need either file.

## Known limitations

- Windows are consecutive transcript segments, not a semantic topic model.
- Word times remain provisional. WhisperX is still later.
- Face tracks are not joined across scenes and are not speakers.
- The pre-dedupe pool of 200 can drop a lower-ranked distinct idea on a very dense source. The summary records that exclusion.
- Round 5 does not render the candidate.

## Round 6

Round 6 can read `candidates.json`, take each candidate’s single time-map segment, and render a cheap rough preview. It should keep the same source clock and the provisional timing label.
