# Round 4 validation

## Baseline

Required and verified main SHA: `826dfc3af2e181a1c8b73f1b683e1f08376ae459`.

Branch: `round-04-visual-analysis`. Main was not edited directly.

## Dependencies

- PySceneDetect 0.7.1 from `scenedetect-headless` (not yanked `scenedetect-core`)
- Scene backend: PyAV (`backend="pyav"`), AdaptiveDetector, `min_scene_len` of 1 frame, library default thresholds
- MediaPipe 1.0.1, Tasks `FaceDetector`, IMAGE mode
- PyAV 18.1.0
- OpenCV distribution `opencv-contrib-python` 5.0.0.93, `cv2.__version__` 5.0.0
- `cv2` path: `.venv/lib/python3.11/site-packages/cv2/__init__.py`
- One OpenCV provider. `scenedetect-headless` metadata is overridden so `opencv-python-headless` is not installed beside the contrib wheel MediaPipe requires.

## Face model

Official file:

`https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite`

SHA-256 `b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f`, 229,746 bytes. Not committed. Download requires `--allow-model-download`. Unknown `Content-Length` fails closed.

## Scene detection

Synthetic 6 s hard cuts at 2 s and 4 s: 3 scenes, boundaries on the PTS grid within 100 ms, coverage from 0 through the canonical duration. A stable color clip is one scene. `analysis_complete` is false. `transcript_evidence` is empty.

## Frame sampling

Representative positions 20/50/80, or the midpoint under 1 s. Face cadence 500 ms. The stored detection time is the decoded PTS. VFR-style MP4 timestamps are not `frame_index / 30`.

## Visual metrics

White luma is above black. A checkerboard Laplacian variance is above a flat frame. Identical frames differ by 0. Different solids differ by more than 0.

## Face backend

CI uses a fake detector. Local smoke loaded the real model and ran it on a blank 64×64 frame: 0 detections, load 0.634 s, inference 0.005 s. The 6 s color proxy also reported 0 faces. That is not an accuracy result.

Tracking is greedy IoU 0.3 and center distance 0.2, reset at each scene. A single sample does not become a `FaceObservation`. `speaker_attribution` stays `unknown`.

## Contact sheets

Generated and hashed. A test decodes the JPEG and checks the recorded scene ordinals. Bytes are not pixel-matched.

## Cache and recovery

First run executes the backends. The second identical run is a cache hit and does not construct the face detector. Proxy SHA, scene profile, sampling profile, model SHA, and tracking profile are identity. A crash-style new sidecar with the old artifact job fails verify. Log failure and cleanup failure leave no `running` job and keep the previous analysis. `--force` writes a new run and leaves the old directory.

## Locking

Shared `prepare.lock`, then exclusive `vision.lock`. An exclusive prepare blocks vision before a job. An exclusive vision lock blocks a second vision. Vision can run while transcription holds the shared prepare lock and `transcribe.lock`.

## Schema

Database schema version 4. No migration 5. New JSON contracts are the visual document, cache record, boxes, samples, and evidence files. `clipforge schema export` wrote them.

## Tests

Local `uv run pytest`: 173 passed. 95 general, 18 media, 29 transcription, 31 vision. Ruff, format, mypy (86 files), schema check, renderer eslint/tsc/vitest (3), and `clipforge doctor` passed. `clipforge vision doctor` passes the libraries and warns when the face model is absent. `clipforge transcript doctor` still warns that CUDA libraries and `small.en` are absent. The vision CI job installs ffmpeg on ubuntu-24.04, imports `scenedetect`, `cv2`, `av`, and `mediapipe`, and does not download a model.

## Privacy

Frames stay local. No face crops, embeddings, or demographic labels are stored. MediaPipe may send its own performance metrics. Clipforge does not upload the frame for inference.

## Known limitations

- CPU only. CUDA was not changed.
- Face boxes on solid colors are not a detection-quality claim.
- Old immutable runs are not deleted automatically.
- `vision show` does not re-hash evidence. `vision verify` does.
- Semantic shot labels, OCR, pose, and object detection are not in this round.

## Round 5 prerequisites

A succeeded visual-analysis artifact and a succeeded transcript for the same source, both verified against the current proxy and ASR audio. Candidate mining is not started.
