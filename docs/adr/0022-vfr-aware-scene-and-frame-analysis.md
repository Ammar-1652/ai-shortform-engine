# ADR 0022: VFR-aware scene and frame analysis

- Status: Accepted
- Date: 2026-10-02

## Context

Frame index divided by average FPS is wrong for variable frame rate and for timestamps that do not land on the requested sample. PySceneDetect 0.7.1 can read PTS through its PyAV backend. PyAV is already installed for transcription.

## Decision

Scene detection uses PySceneDetect 0.7.1 `AdaptiveDetector` with `backend="pyav"`. Package `scenedetect-headless` is the dependency. The yanked `scenedetect-core` 0.7.1 wheel is not used. There is no silent fallback to the OpenCV video backend.

`min_scene_len` is one frame. Adaptive threshold, window, content floor, and HSV weights stay at the library defaults. A video with no cuts is one scene from 0 to the canonical duration. Short shots are kept.

Scene edges are integer microseconds from `pts * time_base` via `Fraction`, then half-up to microseconds. The first start may clamp to 0, and the last end may clamp to the canonical duration, only inside 100 ms. A larger gap, overlap, or endpoint miss fails the job.

Sample frames come from a sequential PyAV decode. The stored time is the frame PTS. The requested target is stored beside it. Representative targets are 20%, 50%, and 80% of each scene, or the midpoint when the scene is 1 second or shorter. Face samples are every 500 ms, unioned with those frames and deduplicated on the actual PTS. Targets are half-open inside the scene: `[start, end)`.

OpenCV is `opencv-contrib-python` only. MediaPipe requires that wheel. `scenedetect-headless` metadata is overridden so `opencv-python-headless` is not installed beside it. One `cv2` package owns the namespace.

## Alternatives considered

- OpenCV scene backend. Rejected as the default. PyAV PTS is the clock this system already trusts. A failure to open PyAV is reported. It is not swapped.
- Drop scenes shorter than a fixed editorial duration. Rejected. That is a candidate decision.
- Sample every decoded frame. Rejected. Round 4 is rough evidence, and RAM is about 16 GiB with no swap.

## Consequences

A requested 5.000 s sample can be stored at 5.017 s. Detections use 5.017 s. Cache identity includes the PySceneDetect version, the detector fingerprint, the PyAV version, and the OpenCV distribution version.
