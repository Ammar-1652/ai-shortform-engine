# ADR 0023: Face detection without identity or speaker attribution

- Status: Accepted
- Date: 2026-10-02

## Context

`FaceObservation.speaker_attribution` is fixed to `unknown`. A box is not a speaker, and a track is not a person. Round 4 needs geometry for later framing, not recognition.

## Decision

The production detector is MediaPipe Tasks `FaceDetector` 1.0.1 in `IMAGE` mode. `LIVE_STREAM` is not used. The model file is the official short-range BlazeFace asset:

`https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite`

It is stored under `CLIPFORGE_MODEL_ROOT/vision/face-detector/` and is not committed. Download happens only from `clipforge vision model fetch face-detector --allow-model-download` or `vision analyze --allow-model-download`. The size comes from `Content-Length`. Unknown size fails closed before the GET. A symlinked model root is refused before any write.

Boxes are normalized to the displayed proxy frame. Overflow of at most 2 pixels is clipped and marked `clamped`. Negative size, NaN, infinity, and a box fully outside the frame are dropped. Optional keypoints are left eye, right eye, nose, and mouth center. They are not used for tracking and are not age, gender, emotion, or identity.

Tracking is greedy IoU plus center distance inside one scene. The thresholds are IoU 0.3, center distance 0.2, and a gap of 1 second. Track ids look like `scene-0004-face-track-0002`. They reset at every scene boundary. A track with one timestamp stays a `FaceDetectionSample`. A track with two or more timestamps becomes a `FaceObservation` whose confidence is the mean detector score and whose speaker attribution stays `unknown`. No speaker score field is added.

Representative JPEGs and contact sheets are stored. Cropped face images are not.

## Alternatives considered

- Legacy `mp.solutions.face_detection`. Rejected. The Tasks API loads and runs on this machine.
- Face embeddings or a recognizer. Rejected. Out of scope and the wrong data to store.
- Hungarian matching via SciPy. Rejected. The scene sample count does not need it.
- Treat the largest face as the speaker. Rejected by the existing schema.

## Consequences

CI imports MediaPipe and does not download the model. Tests use `FakeFaceDetectionBackend`. A missing model after a successful analysis is a verify warning. The artifact bytes remain valid. `vision doctor` and `vision verify` do not create the model root and do not load the detector.
