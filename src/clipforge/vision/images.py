"""Representative JPEGs and contact sheets. Face crops are not written.

JPEG quality is 85 and 4:2:0 is the OpenCV default. The long edge is capped
at ``JPEG_LONG_EDGE`` and frames are never upscaled. Contact-sheet text is a
scene ordinal and a timestamp. It is not timing authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clipforge.errors import MediaError
from clipforge.vision.constants import CONTACT_COLUMNS, CONTACT_ROWS, JPEG_LONG_EDGE, JPEG_QUALITY


def write_jpeg(
    path: Path,
    rgb: Any,
    *,
    long_edge: int = JPEG_LONG_EDGE,
    quality: int = JPEG_QUALITY,
) -> tuple[int, int]:
    """Write one JPEG. Returns the stored width and height."""
    import cv2

    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    height, width = bgr.shape[:2]
    scale = min(1.0, long_edge / max(height, width))
    if scale < 1:
        resized_w = max(1, round(width * scale))
        resized_h = max(1, round(height * scale))
        bgr = cv2.resize(bgr, (resized_w, resized_h), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise MediaError(f"could not encode {path.name}")
    path.write_bytes(encoded.tobytes())
    stored_h, stored_w = bgr.shape[:2]
    return int(stored_w), int(stored_h)


def write_contact_sheet(
    path: Path,
    tiles: list[tuple[Path, int, int]],
    *,
    columns: int = CONTACT_COLUMNS,
    rows: int = CONTACT_ROWS,
) -> tuple[int, int]:
    """Lay representative frames into one sheet. ``tiles`` are path, ordinal, timestamp."""
    import cv2
    import numpy as np

    if not tiles:
        raise MediaError("a contact sheet requires at least one representative frame")
    if len(tiles) > columns * rows:
        raise MediaError("contact sheet tile count exceeds the page")
    cell_w = 160
    cell_h = 120
    label_h = 22
    sheet_w = columns * cell_w
    sheet_h = rows * (cell_h + label_h)
    canvas = np.full((sheet_h, sheet_w, 3), 255, dtype=np.uint8)
    for index, (image_path, ordinal, timestamp_us) in enumerate(tiles):
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise MediaError(f"could not read evidence image {image_path.name} for a contact sheet")
        fitted = _fit(image, cell_w, cell_h, cv2)
        column = index % columns
        row = index // columns
        origin_x = column * cell_w
        origin_y = row * (cell_h + label_h)
        canvas[origin_y : origin_y + fitted.shape[0], origin_x : origin_x + fitted.shape[1]] = fitted
        label = f"s{ordinal:04d} {timestamp_us / 1_000_000:.3f}s"
        cv2.putText(
            canvas,
            label,
            (origin_x + 4, origin_y + cell_h + 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
    ok, encoded = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    if not ok:
        raise MediaError(f"could not encode {path.name}")
    path.write_bytes(encoded.tobytes())
    return sheet_w, sheet_h


def _fit(image: Any, width: int, height: int, cv2: Any) -> Any:
    scale = min(width / image.shape[1], height / image.shape[0], 1.0)
    resized_w = max(1, round(image.shape[1] * scale))
    resized_h = max(1, round(image.shape[0] * scale))
    if resized_w == image.shape[1] and resized_h == image.shape[0]:
        return image
    return cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_AREA)
