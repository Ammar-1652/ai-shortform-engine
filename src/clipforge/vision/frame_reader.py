"""Sequential PyAV decode. The frame PTS is the clock, not frame index / FPS."""

from __future__ import annotations

from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.vision.constants import SCENE_ENDPOINT_TOLERANCE_US
from clipforge.vision.timeutil import rational_to_us
from clipforge.vision.types import DecodedFrame


class PyAVFrameReader:
    def __init__(self, *, duration_us: int | None = None) -> None:
        self.calls = 0
        self.duration_us = duration_us

    def frames(self, path: Path) -> Iterator[DecodedFrame]:
        self.calls += 1
        try:
            import av
        except ImportError as exc:
            raise MediaError("PyAV is not installed. Run uv sync. No frames were decoded.") from exc
        try:
            container = av.open(str(path))
        except Exception as exc:
            raise MediaError(f"could not open analysis proxy {path.name}: {exc}") from exc
        previous = -1
        try:
            stream = container.streams.video[0]
            if stream.time_base is None:
                raise MediaError(f"{path.name} video stream has no time base")
            for frame in container.decode(stream):
                if frame.pts is None:
                    raise MediaError(f"{path.name} has a video frame with no presentation timestamp")
                timestamp = rational_to_us(Fraction(frame.pts) * Fraction(stream.time_base))
                if timestamp < previous:
                    raise MediaError("analysis proxy frame timestamps are not monotonic")
                if timestamp == previous:
                    continue
                if self.duration_us is not None and timestamp > self.duration_us + SCENE_ENDPOINT_TOLERANCE_US:
                    raise MediaError(
                        f"frame at {timestamp} us is more than {SCENE_ENDPOINT_TOLERANCE_US} us "
                        f"past the canonical duration {self.duration_us} us"
                    )
                if self.duration_us is not None and timestamp >= self.duration_us:
                    continue
                array = frame.to_ndarray(format="rgb24")
                height, width = array.shape[:2]
                yield DecodedFrame(timestamp_us=timestamp, width=int(width), height=int(height), rgb=array)
                previous = timestamp
        finally:
            container.close()
