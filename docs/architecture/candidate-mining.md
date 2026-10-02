# Candidate mining

Round 5 turns the current transcript and the current visual analysis into one candidate-set document. It does not render, crop, caption, or publish. Round 6 can render each selected candidate from its single source range.

```text
source manifest
    -> current transcript.json
    -> current analysis.json
    -> combined input digest
    -> windows, scores, dedupe
    -> candidates/runs/<mining_id>/candidates.json
    -> Round 6 rough preview (not this round)
```

## Inputs

`clipforge candidate mine SOURCE_ID` does not take a file path. It loads the source, the cleared rights record, the ingest manifest, the current `transcript_json` artifact, and the current `visual_analysis_json` artifact. Integrity reuses `document_sidecar_problems` and `producer_binding_problems` for the transcript, and `visual_problems` for the visual analysis. Those checks hash `audio/asr.flac` and `proxy/analysis.mp4`. They do not decode them and they do not load model weights.

The combined digest is SHA-256 of:

```json
{"transcript_sha256":"...","visual_analysis_sha256":"..."}
```

Keys are sorted and the encoding is compact. It is stored as `candidate_input_sha256` and as `ArtifactProvenance.inputs_sha256` on the document, each candidate, and the artifact row.

The transcript and the visual document must name the same project and source. Their canonical durations must equal the manifest duration. Pairing source A’s transcript with source B’s visual analysis fails.

## Ranges

A candidate is one half-open interval `[start_us, end_us)` on the canonical source clock. The time map has exactly one segment, so the output duration equals the source duration of that interval. Round 5 does not speed, slow, jump-cut, or reorder.

When the included segments have word times, the start is the first word’s `start_us` minus 250 ms and the end is the last word’s `end_us` plus 250 ms. Both ends clamp to `[0, canonical_duration_us]`. If padding would land inside another known word, the boundary snaps to that word’s edge. Segments without words use the segment start and end. No word time is invented. `boundary_timing_quality` stays `provisional`.

Windows walk consecutive transcript segments and stop once a start would pass the 65 second hard maximum. Endpoints near 8 seconds, 18 seconds, 30 seconds, 45 seconds, and 65 seconds are kept, plus a window whose observed text already ends with punctuation. Identical ranges are kept once. The walk stops at 5000 raw windows and records `raw_hypothesis_cap_reached`.

## Scores

`quality_score` asks whether the interval looks like a coherent short-form idea. It is copied to `CandidateClip.creative_score`. It is not a probability of views, virality, compliance, truth, or approval.

| Feature | Weight | What it measures |
| --- | --- | --- |
| duration_fit | 0.15 | 1 from 18 s through 45 s, linear down to 0 at 8 s and at 65 s |
| speech_coverage | 0.20 | Union of included transcript time divided by the candidate duration |
| boundary_completeness | 0.20 | Alignment with the word or segment edge, no cut inside a known word, observed closing punctuation |
| transcript_reliability | 0.20 | Word confidence, or else segment avg_logprob, no_speech_prob, and compression_ratio |
| information_density | 0.10 | Words per spoken second, plateau 1.5–3.5 |
| opening_structure | 0.05 | Observed question mark, number, or short opening clause. No topic keywords |
| visual_evidence_coverage | 0.10 | Overlapping scenes and representative frames inside the interval. Not faces |

A null feature is omitted and the remaining weights are renormalized. Coverage below 0.70 rejects the hypothesis. There is no other quality floor.

`edit_opportunity_score` is separate. Weights: scene change 0.25, stored `difference_from_previous_sample` 0.25, face-layout variation 0.15, numeric tokens 0.15, emphasis punctuation 0.10, more than one scene 0.10. Scene-change reward caps at 0.2 cuts per second. Missing edit features are omitted. They do not reject the candidate and they do not change rank.

Face evidence is detection count, samples inside the interval, area, and scene-local track ids. It is not a speaker, host, guest, or identity. Zero faces is valid.

## Dedupe and count

A pair is a near-duplicate when the shorter range is at least 80 percent inside the longer one, or when temporal IoU and token Jaccard are both at least 0.70. Empty token sets have Jaccard 0. The winner is higher quality, then higher coverage, then higher boundary completeness, then earlier start, then shorter duration, then the stable hypothesis id.

Scored hypotheses enter a pool of 200 before that comparison, ranked the same way, so the opening of a long source is not preferred just because it was generated first. The pool size is in the profile fingerprint. After dedupe the list is capped at 25. The soft target of 15 does not create extra candidates. `below_soft_target` is informational.

## Compliance

These rules are recorded on every selected candidate and must pass:

- `candidate_source_rights`
- `candidate_current_transcript`
- `candidate_current_visual`
- `candidate_source_range_valid`
- `candidate_transcript_evidence_present`
- `candidate_visual_evidence_present`

A failing rule cannot be `ready_for_review`. The score cannot override it. Round 5 does not claim a platform or campaign policy result. No `CampaignProfile` is required.

## Artifact, cache, and locks

The artifact kind is `candidate_set_json`. The run directory is `candidates/runs/<mining_id>/`. The sidecar is `metadata/candidate-mining.recipe.json`. Schema version stays 4.

Lock order: shared `prepare.lock`, shared `transcribe.lock`, shared `vision.lock`, exclusive `candidate.lock`. A busy lock fails before a job row. After the locks are held, stale `running` candidate jobs for that source are marked failed, and the upstream pair is validated again. See ADR 0030 and ADR 0029.

`clipforge candidate verify` is read-only. `list` and `show` only check that the stored document names the requested source. `show` states that word timing remains provisional. `doctor` reports the recipe, profile fingerprint, limits, and disk. It does not load a model.
