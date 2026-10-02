"""Deterministic frame measurements. None of these is a quality score."""

from __future__ import annotations

from typing import Any

from clipforge.errors import MediaError
from clipforge.schemas.vision import FrameVisualMetrics
from clipforge.vision.constants import DIFFERENCE_EDGE

_LUMA = (0.299, 0.587, 0.114)


def measure_frame(rgb: Any, previous_rgb: Any | None) -> FrameVisualMetrics:
    """Luma, Laplacian variance, and mean absolute change from the previous sample.

    The difference uses a ``DIFFERENCE_EDGE`` luma thumbnail. It resets when
    ``previous_rgb`` is None, which the caller does at each scene boundary.
    """
    array = _require_rgb(rgb)
    luma = array[..., 0] * _LUMA[0] + array[..., 1] * _LUMA[1] + array[..., 2] * _LUMA[2]
    mean = float(luma.mean())
    spread = float(luma.std())
    sharp = _sharpness(array)
    difference = None if previous_rgb is None else _difference(previous_rgb, array)
    return FrameVisualMetrics(
        mean_luma=mean,
        luma_stddev=spread,
        sharpness_laplacian_variance=sharp,
        difference_from_previous_sample=difference,
    )


def _sharpness(rgb: Any) -> float:
    import cv2

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    value = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if value < 0:
        raise MediaError("Laplacian variance was negative")
    return value


def _difference(previous: Any, rgb: Any) -> float:
    import cv2
    import numpy as np

    left = _thumbnail(_require_rgb(previous), cv2, np)
    right = _thumbnail(rgb, cv2, np)
    delta = np.abs(left.astype(np.float64) - right.astype(np.float64)).mean() / 255.0
    return float(delta)


def _thumbnail(rgb: Any, cv2: Any, np: Any) -> Any:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    resized = cv2.resize(gray, (DIFFERENCE_EDGE, DIFFERENCE_EDGE), interpolation=cv2.INTER_AREA)
    return np.asarray(resized)


def _require_rgb(rgb: Any) -> Any:
    shape = getattr(rgb, "shape", None)
    if shape is None or len(shape) != 3 or shape[2] != 3 or shape[0] <= 0 or shape[1] <= 0:
        raise MediaError("frame metrics require an HxWx3 RGB array")
    return rgb
