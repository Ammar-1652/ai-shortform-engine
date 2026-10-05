"""One real Hero Remotion render. This is the only Hero test that launches a browser."""

from __future__ import annotations

import subprocess
from pathlib import Path
from time import perf_counter

import pytest

from clipforge.errors import MediaError
from clipforge.hero.alignment import FakeForcedAlignment
from clipforge.hero.probe import probe_hero
from clipforge.hero.service import render_hero_drafts
from clipforge.hero.show import load_current_hero
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg, resolve_ffprobe
from clipforge.paths import find_repo_root
from clipforge.preview.backend import FakeRoughRenderBackend
from clipforge.preview.browser import resolve_browser
from clipforge.review.service import DecisionContext, record_decision, review_board
from tests.candidate_support import PROJECT_ID, SOURCE_ID, segment
from tests.preview_support import mine, ready_stack, render, short_profile

pytestmark = [pytest.mark.hero, pytest.mark.browser]


def test_real_hero_render_is_portrait_and_captioned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")
    try:
        resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    bundler = find_repo_root() / "apps" / "renderer" / "node_modules" / "@remotion" / "bundler"
    if not bundler.is_dir():
        pytest.skip("renderer dependencies are not installed, so the Hero smoke render was not started")
    landscape, speech = _synthetic_media(tmp_path / "source-media")
    spoken = segment(0, 0, 2_000_000, "Point 0 説明 costs $12.50 today.")
    fixture = ready_stack(
        tmp_path / "stack",
        segments=[spoken],
        duration_us=3_000_000,
        proxy_bytes=landscape.read_bytes(),
        asr_bytes=speech.read_bytes(),
    )
    mined = mine(
        fixture,
        profile=short_profile(preferred_max_duration_us=2_000_000, hard_max_duration_us=2_500_000),
    )
    assert mined.selected_count == 1
    render(fixture, FakeRoughRenderBackend())
    board = review_board(fixture.database, SOURCE_ID, fixture.work)
    cards = board["candidates"]
    assert isinstance(cards, list)
    card = cards[0]
    assert isinstance(card, dict)
    record_decision(
        database=fixture.database,
        work_root=fixture.work,
        context=DecisionContext(
            source_asset_id=SOURCE_ID,
            project_id=PROJECT_ID,
            artifact_id=str(board["artifact_id"]),
            preview_set_id=str(board["preview_set_id"]),
            manifest_sha256=str(board["manifest_sha256"]),
            candidate_id=str(card["candidate_id"]),
        ),
        decision="approved",
        reviewer_id="ada",
        notes="",
    )
    started = perf_counter()
    result = render_hero_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        alignment_backend=FakeForcedAlignment(),
    )
    elapsed = perf_counter() - started
    assert result.status == "rendered"
    assert result.rendered_count == 1
    assert result.manifest_path is not None
    current = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    draft = current.document.drafts[0]
    video = result.manifest_path.parent / draft.preview_relative_path
    probed = probe_hero(video, expected_duration_us=draft.output_duration_us)
    assert probed.video_codec == "h264"
    assert probed.pixel_format in {"yuv420p", "yuvj420p"}
    assert probed.audio_codec == "aac"
    rendered = (video.parent / "render-input.json").read_text(encoding="utf-8")
    assert "説明" in rendered
    assert "$12.50" in rendered
    assert current.document.profile_fingerprint
    print(
        f"hero_smoke_seconds {elapsed:.3f} "
        f"fingerprint {current.document.profile_fingerprint} "
        f"motion {current.document.motion_library_version}"
    )
    _assert_portrait_frame(video, tmp_path / "early.png", tmp_path / "caption.png")


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
            "color=c=red:s=1280x720:r=30:d=3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=3",
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
            "sine=frequency=440:sample_rate=16000:d=3",
            "-c:a",
            "flac",
            str(speech),
        ],
        check=True,
    )
    return landscape, speech


def _assert_portrait_frame(video: Path, early: Path, caption: Path) -> None:
    ffmpeg = resolve_ffmpeg()
    subprocess.run(
        [ffmpeg, "-y", "-ss", "0", "-i", str(video), "-frames:v", "1", str(early)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [ffmpeg, "-y", "-ss", "0.5", "-i", str(video), "-frames:v", "1", str(caption)],
        check=True,
        capture_output=True,
    )
    raw = _rgb(caption)
    width, height = 1080, 1920
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
            str(caption),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "1080,1920"

    def pixel(buf: bytes, x: int, y: int) -> tuple[int, int, int]:
        offset = (y * width + x) * 3
        return buf[offset], buf[offset + 1], buf[offset + 2]

    top = pixel(raw, 540, 8)
    assert max(top) < 40
    middle = pixel(raw, 540, 960)
    assert middle[0] > 120 and middle[0] > middle[1] and middle[0] > middle[2]
    bright = False
    for y in range(1500, 1750):
        for x in range(120, 960, 4):
            red, green, blue = pixel(raw, x, y)
            if red > 200 and green > 200 and blue > 200:
                bright = True
                break
        if bright:
            break
    assert bright, "caption text was not visible in the lower safe area"
    early_raw = _rgb(early)
    assert _mean(early_raw) < _mean(raw)


def _rgb(path: Path) -> bytes:
    return subprocess.run(
        [resolve_ffmpeg(), "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
    ).stdout


def _mean(raw: bytes) -> float:
    if not raw:
        return 0
    return sum(raw[::64]) / max(1, len(raw[::64]))
