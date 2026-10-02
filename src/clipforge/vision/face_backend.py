"""MediaPipe Tasks FaceDetector. IMAGE mode, synchronous, no live stream.

The backend returns normalized geometry. MediaPipe objects do not leave this
module. No recognition, embedding, age, gender, or emotion model is loaded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clipforge.errors import MediaError
from clipforge.vision.constants import FACE_ENGINE, MIN_DETECTION_CONFIDENCE, MIN_SUPPRESSION_THRESHOLD
from clipforge.vision.geometry import NormalizedFace, normalize_box, with_score

_KEYPOINTS = ("right_eye", "left_eye", "nose", "mouth_center")
_STORED = {"left_eye": "left_eye", "right_eye": "right_eye", "nose": "nose", "mouth_center": "mouth_center"}


class MediaPipeFaceDetectionBackend:
    engine = FACE_ENGINE

    def __init__(
        self,
        model_path: Path,
        *,
        min_detection_confidence: float = MIN_DETECTION_CONFIDENCE,
        min_suppression_threshold: float = MIN_SUPPRESSION_THRESHOLD,
    ) -> None:
        self.calls = 0
        self._detector = _open_detector(
            model_path,
            min_detection_confidence=min_detection_confidence,
            min_suppression_threshold=min_suppression_threshold,
        )
        self._image_type: Any = None

    def detect(self, rgb: Any, timestamp_us: int) -> list[NormalizedFace]:
        del timestamp_us
        self.calls += 1
        import mediapipe as mp

        height, width = rgb.shape[:2]
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        try:
            result = self._detector.detect(image)
        except Exception as exc:
            raise MediaError(f"MediaPipe face detection failed: {exc}") from exc
        faces: list[NormalizedFace] = []
        for detection in result.detections or []:
            box = getattr(detection, "bounding_box", None)
            if box is None:
                continue
            normalized = normalize_box(
                float(box.origin_x),
                float(box.origin_y),
                float(box.width),
                float(box.height),
                frame_width=int(width),
                frame_height=int(height),
            )
            if normalized is None:
                continue
            score = _category_score(detection)
            if score is None:
                continue
            scored = with_score(normalized, score, _keypoints(getattr(detection, "keypoints", None)))
            if scored is not None:
                faces.append(scored)
        return faces

    def close(self) -> None:
        closer = getattr(self._detector, "close", None)
        if closer is not None:
            closer()


def _open_detector(
    model_path: Path,
    *,
    min_detection_confidence: float,
    min_suppression_threshold: float,
) -> Any:
    if not model_path.is_file() or model_path.is_symlink():
        raise MediaError(f"face detector model is missing at {model_path}")
    try:
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import FaceDetector, FaceDetectorOptions, RunningMode
    except ImportError as exc:
        raise MediaError("MediaPipe is not installed. Run uv sync. The face model was not loaded.") from exc
    options = FaceDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(model_path)),
        running_mode=RunningMode.IMAGE,
        min_detection_confidence=min_detection_confidence,
        min_suppression_threshold=min_suppression_threshold,
    )
    try:
        return FaceDetector.create_from_options(options)
    except Exception as exc:
        raise MediaError(f"could not load the MediaPipe face detector: {exc}") from exc


def _category_score(detection: Any) -> float | None:
    """Return the detector confidence, or None when MediaPipe did not provide one.

    Face evidence requires a real detector score. Missing/invalid confidence is
    not replaced with a fabricated zero.
    """
    categories = getattr(detection, "categories", None) or []
    if not categories:
        return None
    raw_score = getattr(categories[0], "score", None)
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        return None
    return float(raw_score)


def _keypoints(points: Any) -> tuple[tuple[str, float, float], ...]:
    if not points:
        return ()
    kept: list[tuple[str, float, float]] = []
    for index, point in enumerate(points):
        if index >= len(_KEYPOINTS):
            break
        name = _STORED.get(_KEYPOINTS[index])
        if name is None:
            continue
        x = getattr(point, "x", None)
        y = getattr(point, "y", None)
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            kept.append((name, float(x), float(y)))
    return tuple(kept)
