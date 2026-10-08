"""Decode program frames across many non-frame-aligned editorial cuts."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.preview.trim import stage_time_map
from clipforge.schemas.time import TimelineSegment, TimeMapDocument
from clipforge.timeline import FrameRate
from clipforge.timeline.framerate import frame_start_us

pytestmark = pytest.mark.preview


def _decode_gray(video: Path) -> bytes:
    result = subprocess.run(
        [
            resolve_ffmpeg(),
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            "scale=1:1",
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return result.stdout


def test_many_off_grid_cuts_preserve_each_segment_on_the_program_clock(tmp_path: Path) -> None:
    """Equal total durations do not prove sync: inspect the middle of every cut."""
    video = tmp_path / "source.mp4"
    audio = tmp_path / "source.flac"
    runner = ProcessRunner()
    runner.run(
        [
            resolve_ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "nullsrc=size=64x64:rate=30:duration=20,geq=lum='16+floor(N/30)*10':cb=128:cr=128",
            "-c:v",
            "libx264",
            "-crf",
            "0",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    runner.run(
        [
            resolve_ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=20",
            "-c:a",
            "flac",
            str(audio),
        ],
        check=True,
    )
    document = TimeMapDocument(
        time_map_id="many-off-grid-cuts",
        segments=[
            TimelineSegment(
                segment_id=f"segment-{index}",
                source_start_us=index * 1_000_000 + 110_000,
                source_end_us=index * 1_000_000 + 247_000,
            )
            for index in range(20)
        ],
    )
    mapper = document.to_time_map()
    rate = FrameRate(30, 1)
    staged = stage_time_map(
        video,
        audio,
        tmp_path / "staging",
        stem="span",
        time_map=document,
        frame_count=mapper.output_frame_count(rate),
        root=tmp_path,
        log_path=None,
    )
    source_frames = _decode_gray(video)
    output_frames = _decode_gray(staged.video_path)
    assert len(output_frames) == mapper.output_frame_count(rate)
    checked: set[str] = set()
    for frame, value in enumerate(output_frames):
        output_us = frame_start_us(frame, rate)
        segment = next(
            item for item in mapper.segments if item.output_start_us <= output_us < item.output_end_us
        )
        # Exclude a single frame around a cut. Decode evidence must have only
        # bounded grid rounding, never an accumulated segment-length error.
        if min(output_us - segment.output_start_us, segment.output_end_us - output_us) < 35_000:
            continue
        source_us = mapper.output_to_source(output_us)
        source_frame = (source_us * 30) // 1_000_000
        assert abs(value - source_frames[source_frame]) <= 2, (
            f"frame {frame} at {output_us} us is not from {segment.segment_id}: "
            f"gray {value}, expected {source_frames[source_frame]}"
        )
        checked.add(segment.segment_id)
    assert len(checked) == 20
