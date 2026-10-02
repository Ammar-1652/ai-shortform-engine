"""Deterministic stand-ins for scene detection, decoding, and face detection."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from clipforge.vision.geometry import NormalizedFace
from clipforge.vision.types import DecodedFrame


class FakeSceneBackend:
    def __init__(self, spans: list[tuple[int, int]]) -> None:
        self.spans = list(spans)
        self.calls = 0
        self.engine = "fake"
        self.version = "fake-scene-1"
        self.detector = "FakeDetector"
        self.backend = "fake"

    def detect(self, path: Path, duration_us: int) -> list[tuple[int, int]]:
        del path, duration_us
        self.calls += 1
        return list(self.spans)


class FakeFrameReader:
    def __init__(self, frames: list[DecodedFrame]) -> None:
        self._frames = list(frames)
        self.calls = 0

    def frames(self, path: Path) -> Iterator[DecodedFrame]:
        del path
        self.calls += 1
        yield from self._frames


class FakeFaceBackend:
    def __init__(self, script: dict[int, list[NormalizedFace]]) -> None:
        self.script = script
        self.calls = 0
        self.engine = "fake"

    def detect(self, rgb: object, timestamp_us: int) -> list[NormalizedFace]:
        del rgb
        self.calls += 1
        return list(self.script.get(timestamp_us, []))


def solid_frame(timestamp_us: int, color: tuple[int, int, int] = (0, 0, 0), size: int = 16) -> DecodedFrame:
    import numpy as np

    rgb = np.zeros((size, size, 3), dtype=np.uint8)
    rgb[..., 0] = color[0]
    rgb[..., 1] = color[1]
    rgb[..., 2] = color[2]
    return DecodedFrame(timestamp_us=timestamp_us, width=size, height=size, rgb=rgb)


def face_at(x: float, *, confidence: float = 0.9) -> NormalizedFace:
    return NormalizedFace(
        confidence=confidence,
        x=x,
        y=0.2,
        width=0.2,
        height=0.2,
        clamped=False,
        keypoints=(),
    )
