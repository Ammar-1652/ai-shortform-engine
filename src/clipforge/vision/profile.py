"""Fingerprints for the material visual-analysis settings.

``created_at`` is not included. The same function builds the fingerprint at
publication and at validation, from the stored numbers rather than from a
second hidden copy.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from clipforge.vision.constants import (
    ADAPTIVE_THRESHOLD,
    CONTACT_COLUMNS,
    CONTACT_ROWS,
    DIFFERENCE_EDGE,
    FACE_SAMPLE_INTERVAL_US,
    JPEG_LONG_EDGE,
    JPEG_QUALITY,
    METRICS_VERSION,
    MIN_CONTENT_VAL,
    MIN_DETECTION_CONFIDENCE,
    MIN_SCENE_LEN_FRAMES,
    MIN_SUPPRESSION_THRESHOLD,
    REPRESENTATIVE_FRACTIONS,
    SCENE_BACKEND,
    SCENE_DETECTOR,
    SHORT_SCENE_US,
    TRACKING_ALGORITHM,
    TRACKING_CENTER_DISTANCE,
    TRACKING_IOU_THRESHOLD,
    TRACKING_MAX_GAP_US,
    WINDOW_WIDTH,
)


def scene_fingerprint(
    *,
    detector: str = SCENE_DETECTOR,
    backend: str = SCENE_BACKEND,
    adaptive_threshold: float = ADAPTIVE_THRESHOLD,
    min_content_val: float = MIN_CONTENT_VAL,
    window_width: int = WINDOW_WIDTH,
    min_scene_len_frames: int = MIN_SCENE_LEN_FRAMES,
) -> str:
    return _fingerprint(
        {
            "adaptive_threshold": _num(adaptive_threshold),
            "backend": backend,
            "delta_edges": _num(0.0),
            "delta_hue": _num(1.0),
            "delta_lum": _num(1.0),
            "delta_sat": _num(1.0),
            "detector": detector,
            "luma_only": False,
            "min_content_val": _num(min_content_val),
            "min_scene_len_frames": min_scene_len_frames,
            "window_width": window_width,
        }
    )


def sampling_fingerprint(
    *,
    fractions: tuple[str, ...] | list[str] = REPRESENTATIVE_FRACTIONS,
    short_scene_us: int = SHORT_SCENE_US,
    face_sample_interval_us: int = FACE_SAMPLE_INTERVAL_US,
    jpeg_quality: int = JPEG_QUALITY,
    jpeg_long_edge: int = JPEG_LONG_EDGE,
) -> str:
    return _fingerprint(
        {
            "contact_columns": CONTACT_COLUMNS,
            "contact_rows": CONTACT_ROWS,
            "difference_edge": DIFFERENCE_EDGE,
            "face_sample_interval_us": face_sample_interval_us,
            "jpeg_long_edge": jpeg_long_edge,
            "jpeg_quality": jpeg_quality,
            "metrics_version": METRICS_VERSION,
            "representative_fractions": list(fractions),
            "short_scene_us": short_scene_us,
        }
    )


def face_fingerprint(
    *,
    min_detection_confidence: float = MIN_DETECTION_CONFIDENCE,
    min_suppression_threshold: float = MIN_SUPPRESSION_THRESHOLD,
) -> str:
    return _fingerprint(
        {
            "min_detection_confidence": _num(min_detection_confidence),
            "min_suppression_threshold": _num(min_suppression_threshold),
            "running_mode": "IMAGE",
        }
    )


def tracking_fingerprint(
    *,
    iou_threshold: float = TRACKING_IOU_THRESHOLD,
    center_distance_threshold: float = TRACKING_CENTER_DISTANCE,
    max_gap_us: int = TRACKING_MAX_GAP_US,
) -> str:
    return _fingerprint(
        {
            "algorithm": TRACKING_ALGORITHM,
            "center_distance_threshold": _num(center_distance_threshold),
            "iou_threshold": _num(iou_threshold),
            "max_gap_us": max_gap_us,
        }
    )


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _num(value: float) -> str:
    return format(value, "f")
