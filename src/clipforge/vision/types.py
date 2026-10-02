"""In-memory frames and sample plans. RGB buffers are not stored in the document."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DecodedFrame:
    timestamp_us: int
    width: int
    height: int
    rgb: Any


@dataclass(frozen=True, slots=True)
class SampleRequest:
    scene_ordinal: int
    scene_start_us: int
    scene_end_us: int
    requested_us: int
    label: str | None
    face: bool


@dataclass(frozen=True, slots=True)
class AssignedSample:
    scene_ordinal: int
    scene_start_us: int
    scene_end_us: int
    requested_us: int
    matched_requests_us: tuple[int, ...]
    labels: tuple[str, ...]
    face: bool
    frame: DecodedFrame


class FrameReader(Protocol):
    calls: int

    def frames(self, path: Any) -> Any:
        """Yield ``DecodedFrame`` values in presentation order."""


class SceneDetectionBackend(Protocol):
    calls: int
    engine: str
    version: str
    detector: str
    backend: str

    def detect(self, path: Any, duration_us: int) -> list[tuple[int, int]]:
        """Return raw inclusive-start scene spans in canonical microseconds."""


class FaceDetectionBackend(Protocol):
    calls: int
    engine: str

    def detect(self, rgb: Any, timestamp_us: int) -> list[Any]:
        """Return ``NormalizedFace`` values for one RGB frame."""
