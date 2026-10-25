"""Deterministic, source-bound palette selection for rounded portrait frames.

The palette is intentionally a small routing decision, not unrestricted colour
generation.  We sample the already-authorized analysis proxy, record the
dominant colour evidence, and map its hue/value to one of three reviewed frame
families.  The resulting values are persisted in the Advanced Hero plan so a
changed source or analyzer cannot silently reuse an old frame treatment.
"""

from __future__ import annotations

import colorsys
from collections import Counter
from pathlib import Path
from typing import Literal

from clipforge.errors import MediaError
from clipforge.schemas.advanced import FramePaletteSpec

_ANALYZER_VERSION: Literal["source-frame-palette-v1"] = "source-frame-palette-v1"
_SAMPLE_FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)


def analyze_frame_palette(
    proxy_path: Path,
    *,
    source_sha256: str,
    duration_us: int,
) -> FramePaletteSpec:
    """Read five deterministic proxy frames and choose a reviewed palette.

    OpenCV is already a required local vision dependency.  No network or
    additional model is used.  The frame itself is not stored in the plan;
    only the source-bound colour evidence and selected allowlisted family are.
    """

    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - environment foundation failure
        raise MediaError(
            "source frame palette analysis requires the installed OpenCV vision dependency"
        ) from exc

    capture = cv2.VideoCapture(str(proxy_path))
    if not capture.isOpened():
        raise MediaError(f"source frame palette analysis could not open proxy: {proxy_path}")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count < 1:
            raise MediaError("source frame palette analysis found no proxy frames")
        pixels: list[tuple[int, int, int]] = []
        sample_times_us: list[int] = []
        for fraction in _SAMPLE_FRACTIONS:
            frame_index = min(frame_count - 1, round((frame_count - 1) * fraction))
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok or frame is None:
                raise MediaError(f"source frame palette analysis could not decode proxy frame {frame_index}")
            small = cv2.resize(frame, (64, 64), interpolation=cv2.INTER_AREA)
            rgb = small[:, :, ::-1].reshape(-1, 3)
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).reshape(-1, 3)
            # Avoid black rails and blown-out white UI/source text dominating
            # the frame family decision. Keep a deterministic fallback below.
            mask = (hsv[:, 1] >= 20) & (hsv[:, 2] >= 25) & (hsv[:, 2] <= 245)
            selected = rgb[mask] if mask.any() else rgb
            for red, green, blue in selected[::2]:
                pixels.append((int(red), int(green), int(blue)))
            sample_times_us.append(round(duration_us * fraction))
    finally:
        capture.release()

    if not pixels:
        raise MediaError("source frame palette analysis produced no usable pixels")
    quantized = [tuple((channel // 16) * 16 for channel in pixel) for pixel in pixels]
    dominant = Counter(quantized).most_common(1)[0][0]
    red, green, blue = (channel / 255 for channel in dominant)
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    if value < 0.22 or saturation < 0.12:
        family: Literal["olive", "sage", "charcoal"] = "charcoal"
    elif 0.10 <= hue <= 0.34:
        family = "sage"
    else:
        family = "olive"

    # Reviewed campaign-safe values. The measured source colour is retained as
    # evidence; the rendered border/background are deliberately restrained so
    # a bright source cannot produce an unreadable frame.
    themes = {
        "olive": ("#d2aa45", "#8f752f", "#2b2418", "#141a17"),
        "sage": ("#a7ad72", "#d2aa45", "#2e3a2c", "#161e1a"),
        "charcoal": ("#171d1b", "#d2aa45", "#212623", "#101412"),
    }
    primary_hex, accent_hex, backdrop_hex, backdrop_alt_hex = themes[family]
    dominant_hex = "#" + "".join(f"{channel:02x}" for channel in dominant)
    return FramePaletteSpec(
        analyzer_version=_ANALYZER_VERSION,
        source_sha256=source_sha256,
        family=family,
        dominant_hex=dominant_hex,
        primary_hex=primary_hex,
        accent_hex=accent_hex,
        backdrop_hex=backdrop_hex,
        backdrop_alt_hex=backdrop_alt_hex,
        sample_times_us=sample_times_us,
    )
