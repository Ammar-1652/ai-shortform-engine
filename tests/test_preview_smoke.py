"""One real Remotion render. This is the only preview test that launches a browser."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg, resolve_ffprobe
from clipforge.preview.probe import probe_preview
from clipforge.preview.show import load_preview_document
from clipforge.preview.verify import verify_preview
from tests.candidate_support import SOURCE_ID, segment
from tests.preview_support import mine, ready_stack, render, short_profile

pytestmark = [pytest.mark.preview, pytest.mark.browser]


def test_real_remotion_preview_is_vertical_and_contained(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")
    landscape, speech = _synthetic_media(tmp_path / "source-media")
    spoken = segment(0, 0, 2_000_000, "Café numbers 42 stay visible here.")
    fixture = ready_stack(
        tmp_path / "stack",
        segments=[spoken],
        duration_us=3_000_000,
        proxy_bytes=landscape.read_bytes(),
        asr_bytes=speech.read_bytes(),
    )
    mined = mine(
        fixture,
        profile=short_profile(
            preferred_max_duration_us=2_000_000,
            hard_max_duration_us=2_500_000,
        ),
    )
    assert mined.selected_count == 1
    result = render(fixture)
    assert result.cache_hit is False
    assert result.rendered_count == 1
    document = load_preview_document(fixture.database, SOURCE_ID, fixture.work)
    preview = document.previews[0]
    video = result.manifest_path.parent / preview.preview_relative_path
    probed = probe_preview(video, expected_duration_us=preview.output_duration_us, log_path=None)
    assert probed.video_codec == "h264"
    assert probed.pixel_format in {"yuv420p", "yuvj420p"}
    assert probed.audio_codec
    assert abs(probed.duration_error_us) <= 100_000
    rendered = (video.parent / "render-input.json").read_text(encoding="utf-8")
    assert "Café" in rendered
    report = verify_preview(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work)
    assert report.status == "PASS"
    _assert_contained_frame(video, tmp_path / "frame.png")


def _synthetic_media(directory: Path) -> tuple[Path, Path]:
    directory.mkdir()
    landscape = directory / "landscape.mp4"
    speech = directory / "speech.flac"
    ffmpeg = resolve_ffmpeg()
    runner = ProcessRunner()
    runner.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=1280x720:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(landscape),
        ],
        check=True,
    )
    runner.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:d=2",
            "-c:a",
            "flac",
            str(speech),
        ],
        check=True,
    )
    return landscape, speech


def _assert_contained_frame(video: Path, frame: Path) -> None:
    ffmpeg = resolve_ffmpeg()
    subprocess.run(
        [ffmpeg, "-y", "-ss", "0.4", "-i", str(video), "-frames:v", "1", str(frame)],
        check=True,
        capture_output=True,
    )
    raw = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(frame), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
    ).stdout
    width, height = 720, 1280
    assert len(raw) == width * height * 3
    probe = subprocess.run(
        [
            resolve_ffprobe(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(frame),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "720,1280"

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        offset = (y * width + x) * 3
        return raw[offset], raw[offset + 1], raw[offset + 2]

    top = pixel(360, 8)
    assert max(top) < 40
    middle = pixel(360, 640)
    assert middle[0] > 120 and middle[0] > middle[1] and middle[0] > middle[2]
    bright = False
    for y in range(980, 1120):
        for x in range(80, 640, 4):
            red, green, blue = pixel(x, y)
            if red > 200 and green > 200 and blue > 200:
                bright = True
                break
        if bright:
            break
    assert bright, "caption text was not visible in the lower safe area"
