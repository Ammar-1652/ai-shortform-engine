"""Installed visual-analysis libraries. Importing them does not load a face model."""

from __future__ import annotations

import importlib.metadata

from clipforge.errors import MediaError


def installed_versions() -> tuple[str, str, str, str]:
    """Return PySceneDetect, PyAV, OpenCV distribution, and MediaPipe versions."""
    import scenedetect

    scene = getattr(scenedetect, "__version__", None)
    if not isinstance(scene, str) or not scene:
        raise MediaError("PySceneDetect did not report a version")
    return (
        scene,
        _dist("av"),
        _dist("opencv-contrib-python"),
        _dist("mediapipe"),
    )


def cv2_file() -> str:
    import cv2

    return str(getattr(cv2, "__file__", ""))


def _dist(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise MediaError(f"{name} is not installed. Run uv sync.") from exc
