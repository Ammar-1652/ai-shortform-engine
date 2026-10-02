"""PySceneDetect adapter. Tests can supply a fake with the same methods.

The production backend is AdaptiveDetector on PySceneDetect's PyAV reader.
``min_scene_len`` is one frame so a short cut is kept. Thresholds are the
library defaults, not values tuned to one fixture. There is no silent
fallback to the OpenCV video backend.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

from clipforge.errors import MediaError
from clipforge.vision.constants import (
    ADAPTIVE_THRESHOLD,
    MIN_CONTENT_VAL,
    MIN_SCENE_LEN_FRAMES,
    SCENE_BACKEND,
    SCENE_DETECTOR,
    WINDOW_WIDTH,
)
from clipforge.vision.timeutil import rational_to_us


class PySceneDetectBackend:
    engine = "pyscenedetect"
    detector = SCENE_DETECTOR
    backend = SCENE_BACKEND

    def __init__(self) -> None:
        self.calls = 0
        self.version = _version()

    def detect(self, path: Path, duration_us: int) -> list[tuple[int, int]]:
        del duration_us
        self.calls += 1
        try:
            from scenedetect import SceneManager, open_video
            from scenedetect.detectors import AdaptiveDetector
            from scenedetect.detectors.content_detector import ContentDetector
        except ImportError as exc:
            raise MediaError("PySceneDetect is not installed. Run uv sync. No scene detection ran.") from exc
        weights = ContentDetector.Components(
            delta_hue=1.0,
            delta_sat=1.0,
            delta_lum=1.0,
            delta_edges=0.0,
        )
        try:
            video = open_video(str(path), backend=SCENE_BACKEND)
        except Exception as exc:
            raise MediaError(
                f"PySceneDetect could not open {path.name} with the PyAV backend: {exc}. "
                "The OpenCV backend was not substituted."
            ) from exc
        manager = SceneManager()
        manager.add_detector(
            AdaptiveDetector(
                adaptive_threshold=ADAPTIVE_THRESHOLD,
                min_scene_len=MIN_SCENE_LEN_FRAMES,
                window_width=WINDOW_WIDTH,
                min_content_val=MIN_CONTENT_VAL,
                weights=weights,
                luma_only=False,
            )
        )
        try:
            manager.detect_scenes(video, show_progress=False)
            scenes = manager.get_scene_list()
        except Exception as exc:
            raise MediaError(f"PySceneDetect failed on {path.name}: {exc}") from exc
        return [(_timecode_us(start), _timecode_us(end)) for start, end in scenes]


def _timecode_us(timecode: Any) -> int:
    pts = getattr(timecode, "pts", None)
    base = getattr(timecode, "time_base", None)
    if isinstance(pts, bool) or not isinstance(pts, int) or base is None:
        raise MediaError("PySceneDetect returned a scene boundary without a presentation timestamp")
    return rational_to_us(Fraction(pts) * Fraction(base))


def _version() -> str:
    import scenedetect

    version = getattr(scenedetect, "__version__", None)
    if not isinstance(version, str) or not version:
        raise MediaError("PySceneDetect did not report a version. No scene detection ran.")
    return version
