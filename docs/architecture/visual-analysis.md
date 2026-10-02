# Visual analysis

Round 4 records visual facts from the Round 2 analysis proxy. It does not choose clips, name speakers, or recognize people.

## Input

`clipforge vision analyze SOURCE_ID` resolves the source, checks rights, and refuses a mutated file. The decoded file is `proxy/analysis.mp4` (`analysis-proxy` v1) from a succeeded `media_prepare` job. A missing proxy is an error that names `clipforge media prepare`. The command does not prepare media itself.

Proxy time 0 is canonical source time 0. Timestamps are integer microseconds. Frame PTS is the clock. `frame_index / average_fps` is not.

## Scenes

A `Scene` here is a shot-like interval from PySceneDetect `AdaptiveDetector` on the PyAV backend. It is not a labeled story scene. Ranges cover `[0, canonical_duration_us)` with no gaps or overlaps. No detected cuts means one scene. `visual_evidence` points at a `SceneVisualEvidence` id. `transcript_evidence` stays empty. `analysis_complete` stays false until a later round has both.

## Samples

Representative frames are at 20%, 50%, and 80% of the scene, or the midpoint when the scene is one second or shorter. Face detection also runs every 500 ms. The union is deduplicated on the actual decoded PTS. Each stored frame keeps the requested target and the PTS. Detections use the PTS.

Metrics on those samples are mean luma, luma standard deviation, Laplacian variance, and mean absolute difference from the previous sample in the same scene. The difference uses a 64×64 luma thumbnail. None of these is a quality score.

Representative frames are JPEGs at quality 85, long edge at most 640, never upscaled. Contact sheets are review images with a scene ordinal and a timestamp. They are not a clock. Face crops are not written.

## Faces

MediaPipe Tasks `FaceDetector` runs in image mode on CPU. Boxes are normalized to the displayed proxy. A track id such as `scene-0004-face-track-0002` is geometric continuity inside that scene only. Tracking resets at the cut. One detection does not grow into a `FaceObservation`. Two or more timestamps do. `speaker_attribution` remains `unknown`.

The detector does not store age, gender, ethnicity, emotion, or an embedding. A face count is not a people count.

The model is the official BlazeFace short-range file. It downloads only with `--allow-model-download`. Unknown download size fails closed. The weights are not in git.

MediaPipe Tasks processes the frame on device and does not send that frame to Google for inference. MediaPipe may still send its own performance metrics. Clipforge does not add a call that uploads frames.

## Cache, locks, and checks

The run directory is immutable: `vision/runs/<analysis_id>/`. The sidecar is `metadata/visual-analysis.recipe.json`. The artifact kind is `visual_analysis_json`. Identity includes the source SHA, proxy SHA, scene detector, sample profile, MediaPipe version, model SHA, and tracking profile. It does not include the transcript.

Lock order is shared `prepare.lock`, then exclusive `vision.lock`. Transcription may hold the shared prepare lock at the same time. See ADR 0025.

`vision verify` checks the proxy, the job binding, the JSON, and every evidence hash. It does not load the face model. A missing model is a warning. `vision show` only reads the stored document and rejects a mismatched project or source.

## Round 5

Candidate mining can read this document plus the transcript. It should not treat a face track as a speaker or as a person who continues into the next shot.
