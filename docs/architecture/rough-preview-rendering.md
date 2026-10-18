# Rough preview rendering

Round 6 turns the current candidate set into short vertical review files. A person can watch them and decide which candidates deserve a Hero edit. The files are not finished social videos.

## Inputs

`clipforge preview render SOURCE_ID` resolves the source from the database and the work root. It does not accept a video path, a transcript path, or a candidate JSON path.

Before a job row is inserted, the command requires:

- the source, its manifest, and cleared rights
- the referenced original still matches the ingest fingerprint
- a succeeded `media_prepare` job, a valid analysis proxy, and a valid ASR FLAC
- a succeeded transcript, a succeeded visual analysis, and a succeeded candidate set
- the candidate set bound to that transcript and visual analysis
- every selected candidate `ready_for_review`, still passing Round 5 compliance, with exactly one TimeMap segment inside the canonical duration

Missing upstream artifacts are not rebuilt. The error names `media prepare`, `transcript run`, `vision analyze`, or `candidate mine`.

## Picture, speech, and time

The picture is `proxy/analysis.mp4`. The speech is `audio/asr.flac`. Both already start at canonical t=0. The candidate TimeMap is the range. Output duration is `TimeMap.total_output_duration()` in microseconds. Python converts that duration to `duration_in_frames` at 30/1 with the existing rational frame math. The renderer receives the integer. It does not derive it from a float.

The preview trim is the 30/1 frame that contains the candidate start. Video and audio share that frame. Canonical bounds stored on the manifest stay exact. Quantization error is recorded as `duration_error_us` and must stay inside 100 ms.

The canvas is 720×1280. The whole source frame is contained. The default review background is
`neutral-dark-v1` (`#111111`). An explicit comparison render may select
`blurred-source-v1`: it draws the same staged source behind the contained foreground,
cover-fills it, applies a bounded 24px blur and 0.72 opacity, and never stretches the
foreground. The background choice is part of the render input and therefore the cache
identity. There is no face crop and no speaker inference. A review-only variant may also
use a bounded uniform `video_scale_permille` (1000–1250) and `video_offset_x_px`
(-120–120); these are composition comparisons, not final portrait reframing.
The Tarteel profile selects a bounded foreground rectangle and mild zoom on the
contained source while keeping campaign overlays in that same foreground coordinate
space. Its CTA start and face-safe position are deterministic and recorded in the
render input.

## Captions

`provisional-caption-v1` copies transcript text. Word mode chunks real word times: 8 words, 42 code points, 3 seconds, and a gap over 1.25 seconds, preferring a break after observed punctuation. Segment mode uses one cue per untimed segment and does not invent word times. Cues store source microseconds, output microseconds, and derived half-open frames. `timing_quality` is `provisional`; the renderer shows the grouped phrase only and never paints a moving word highlight from provisional ASR. Forced word motion belongs to the approved Hero/Advanced alignment path. Overlapping cues fail the plan.

The overlay is bold system sans-serif, white on a dark plate, centered above the bottom safe area. Changes between cues are hard cuts. Text is a React text node. `word_highlight_mode=reviewed` is an explicit visual review aid: it uses stored word intervals and review statuses (green correct, red incorrect, gold unverified); it does not upgrade provisional ASR to forced alignment or approval evidence. A reviewed word payload must declare `word_timing_source` (`transcript-word-times-v1` or `reviewed-word-times-v1`); segment-only payloads cannot paint word highlights. Operators must use the transcript/alignment word intervals, never distribute words evenly across a subtitle phrase.

## Render

Remotion 4.0.532 composites one `RoughPreview`. Python writes `candidates/<id>/render-input.json` and one batch file. Node bundles once per set and renders in order at concurrency 1. Staged media is a hard link of the proxy and the FLAC under the run directory, served to Remotion from that directory, then removed. For a Tarteel run, the validated alpha CTA and watermark are retained under the run's `staging/` directory because `preview verify` checks those exact evidence files; they remain inside the gitignored work root. The original source is not copied.

Each MP4 is written to a partial path, probed, hashed, and renamed to `preview.mp4`. The manifest is published only after every candidate validates. The current artifact kind is `rough_preview_set_json`. The sidecar is `metadata/rough-preview.recipe.json`.

## Cache, locks, and failure

Cache identity is the source hash, the candidate set id and hash, the transcript id and hash, the visual analysis id and hash, the proxy hash, the ASR hash, the profile fingerprint, the renderer recipe, and the caption algorithm, plus the manifest and every preview file. A hit returns the existing succeeded job and does not start Node. `--force` creates a new run and keeps the old one.

Lock order is shared prepare, shared transcribe, shared vision, shared candidate, then exclusive preview. A busy lock fails before the job insert. `preview verify` only reads.

A failed or cancelled run does not replace the previous current set. A first-run sidecar failure deletes the new artifact row so the source has no current preview.

## What this round does not do

No WhisperX, karaoke, B-roll, music, sound effects, dynamic zoom, jump cut, diarization, face recognition, or Hero motion. Scores on the manifest are copies for display. They do not change the picture.
