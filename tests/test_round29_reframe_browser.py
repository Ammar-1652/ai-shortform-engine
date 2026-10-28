"""Real Remotion smoke for contain and face_follow. A marker is geometry, not an identity."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.hero.advanced_backend import RemotionAdvancedRenderBackend
from clipforge.hero.reframe import build_face_follow
from clipforge.hero.render_authorization import authorize_render_candidate
from clipforge.hero.render_checkpoint import renderer_dependency_sha256
from clipforge.media.tools import resolve_ffmpeg, resolve_ffprobe
from clipforge.media.workspace import SourceWorkspace
from clipforge.preview.browser import resolve_browser
from clipforge.schemas.advanced import (
    AdvancedHeroRenderInput,
    AudioMixEvent,
    EmphasisEvent,
    ReframingStrategy,
    ReframingWindow,
    TypographyEvent,
    advanced_fingerprint,
)
from clipforge.schemas.editorial import BrollEvent, MotionPurpose, OutputInterval
from clipforge.schemas.time import TimelineSegment, TimeMapDocument, digest_time_map
from tests.test_round29_reframe import _track

pytestmark = [pytest.mark.preview, pytest.mark.browser]
_SHA = "a" * 64


def test_remotion_face_follow_keeps_the_marker_and_contain_keeps_bars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")
    if not (Path("apps/renderer/node_modules/@remotion/bundler")).exists():
        pytest.skip("Remotion packages are not installed")
    try:
        resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    media = tmp_path / "media"
    media.mkdir()
    source = media / "analysis.mp4"
    speech = media / "asr.flac"
    broll = media / "broll.mp4"
    effect = media / "effect.wav"
    _encode(source, "color=c=0x003366:s=320x180:r=30:d=1,drawbox=x=102:y=72:w=38:h=32:color=yellow:t=fill")
    _encode(broll, "color=c=red:s=320x180:r=30:d=1")
    _audio(speech, "flac")
    _audio(effect, "wav")
    time_map = TimeMapDocument(
        time_map_id="map-1",
        segments=[TimelineSegment(segment_id="seg-1", source_start_us=0, source_end_us=1_000_000)],
    )
    document = build_face_follow(
        samples=_track(),
        source_width=320,
        source_height=180,
        time_map=time_map,
        time_map_sha256=digest_time_map(time_map),
        source_sha256=_SHA,
        analysis_source_sha256=_SHA,
        analysis_present=True,
        producer_succeeded=True,
        visual_analysis_id="analysis-1",
        visual_analysis_sha256=_SHA,
        producer_job_id="job-visual",
        plan_id="reframe-1",
        source_asset_id="source-1",
        created_by="ada",
        tool_version="0.29.0",
        profile_fingerprint=_SHA,
        face_sample_interval_us=500_000,
    )
    assert document.trajectory is not None
    windows = []
    samples = document.trajectory.samples
    for index, sample in enumerate(samples):
        end = samples[index + 1].output_us if index + 1 < len(samples) else 1_000_000
        windows.append(
            ReframingWindow(
                window_id=f"window-{index}",
                strategy_id=ReframingStrategy(strategy_id="face_follow"),
                output_start_us=sample.output_us,
                output_end_us=end,
                source_x=sample.crop_x,
                source_y=sample.crop_y,
                source_width=sample.crop_width,
                source_height=sample.crop_height,
                frame_width=320,
                frame_height=180,
            )
        )
    followed = _render(
        tmp_path / "follow",
        source,
        speech,
        broll,
        effect,
        "face_follow",
        windows,
        trajectory_sha256=document.trajectory_sha256,
        time_map_sha256=digest_time_map(time_map),
        source_sha256=_SHA,
        output_duration_us=1_000_000,
    )
    contained = _render(
        tmp_path / "contain",
        source,
        speech,
        broll,
        effect,
        "contain",
        [
            ReframingWindow(
                window_id="window-contain",
                strategy_id=ReframingStrategy(strategy_id="contain"),
                output_start_us=0,
                output_end_us=1_000_000,
                source_x=0,
                source_y=0,
                source_width=320,
                source_height=180,
                frame_width=320,
                frame_height=180,
            )
        ],
        source_sha256=_SHA,
        output_duration_us=1_000_000,
    )
    follow_probe = _probe(followed)
    contain_probe = _probe(contained)
    assert follow_probe == ("h264", "1080", "1920", "aac")
    assert contain_probe == ("h264", "1080", "1920", "aac")
    follow_early = _rgb(followed, 0.2)
    follow_late = _rgb(followed, 0.7)
    contain_late = _rgb(contained, 0.7)
    assert _pixel(follow_late, 20, 20)[2] > 70
    assert _pixel(contain_late, 20, 20)[0] < 40
    assert _caption_plate(follow_late)
    assert _caption_plate(contain_late)
    assert _pixel(follow_early, 540, 960)[0] > 150
    assert _pixel(follow_late, 540, 400)[2] > _pixel(follow_late, 540, 400)[0]


def _render(
    root: Path,
    source: Path,
    speech: Path,
    broll: Path,
    effect: Path,
    strategy: str,
    windows: list[ReframingWindow],
    *,
    trajectory_sha256: str = "",
    time_map_sha256: str = "",
    source_sha256: str = "",
    output_duration_us: int = 0,
) -> Path:
    root.mkdir()
    staging = root / "staging"
    staging.mkdir()
    (staging / "analysis.mp4").write_bytes(source.read_bytes())
    (staging / "asr.flac").write_bytes(speech.read_bytes())
    (staging / "broll.mp4").write_bytes(broll.read_bytes())
    (staging / "effect.wav").write_bytes(effect.read_bytes())
    payload = AdvancedHeroRenderInput(
        candidate_id="cand-1",
        advanced_set_id="advanced-1",
        duration_in_frames=30,
        reframing_strategy=strategy,
        reframing_config_sha256=_SHA,
        profile_fingerprint=_SHA,
        alignment_sha256=_SHA,
        hero_plan_sha256=_SHA,
        advanced_plan_sha256=_SHA,
        typography=[
            TypographyEvent(
                event_id="type-1",
                interval=OutputInterval(output_start_us=0, output_end_us=1_000_000),
                purpose=MotionPurpose.KEY_PHRASE,
                component_id="caption",
                text="Café 説明 $12.50",
                x=72,
                y=1480,
                font_size=64,
            )
        ],
        emphasis=[
            EmphasisEvent(
                event_id="emphasis-1",
                word_id="word-1",
                text="$12.50",
                output_start_us=0,
                output_end_us=1_000_000,
                output_start_frame=0,
                output_end_frame_exclusive=30,
                purpose=MotionPurpose.NUMBER,
                rule_id="number_or_currency",
            )
        ],
        broll=[
            BrollEvent(
                event_id="broll-1",
                interval=OutputInterval(output_start_us=0, output_end_us=400_000),
                asset_id="broll-1",
                broll_source_in_us=0,
            )
        ],
        sfx=[
            AudioMixEvent(
                event_id="sfx-1",
                interval=OutputInterval(output_start_us=0, output_end_us=200_000),
                asset_id="sfx-1",
                gain_db=-6,
            )
        ],
        windows=windows,
        asset_names={"broll-1": "broll.mp4", "sfx-1": "effect.wav"},
        trajectory_sha256=trajectory_sha256,
        time_map_sha256=time_map_sha256,
        source_sha256=source_sha256,
        output_duration_us=output_duration_us,
    )
    output = root / "candidates" / "cand-1" / "advanced.mp4"
    output.parent.mkdir(parents=True)
    batch = root / "batch.json"
    batch.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "outputPath": str(output),
                        "h264Crf": 18,
                        "input_sha256": advanced_fingerprint(payload.model_dump(mode="json")),
                        "input": payload.model_dump(mode="json"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    batch_input = root / "batch-input.json"
    batch_input.write_bytes(batch.read_bytes())
    authorize_render_candidate(
        workspace=SourceWorkspace(root, "project-reframe-test", "source-1"),
        root=root,
        run_dir=root,
        render_input=payload,
        output=output,
        dependency_sha256=renderer_dependency_sha256(),
        job_id="job-reframe-test",
        parent_artifact_id="hero-reframe-test",
        actor="test",
    )
    RemotionAdvancedRenderBackend().render_batch(batch, log_path=root / "render.log")
    rendered = payload.model_dump(mode="json")
    assert rendered["reframing_strategy"] == strategy
    caption = payload.typography[0].text
    assert "Café" in caption
    assert "説明" in caption
    assert "$12.50" in caption
    return output


def _encode(path: Path, video: str) -> None:
    subprocess.run(
        [
            resolve_ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            video,
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _audio(path: Path, codec: str) -> None:
    argv = [resolve_ffmpeg(), "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=1"]
    if codec == "wav":
        argv.extend(["-c:a", "pcm_s16le"])
    else:
        argv.extend(["-c:a", "flac"])
    argv.append(str(path))
    subprocess.run(argv, check=True, capture_output=True)


def _probe(path: Path) -> tuple[str, str, str, str]:
    raw = subprocess.run(
        [
            resolve_ffprobe(),
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    payload = json.loads(raw)
    video = next(item for item in payload["streams"] if item.get("width"))
    audio = next(item for item in payload["streams"] if item.get("codec_name") == "aac")
    return video["codec_name"], str(video["width"]), str(video["height"]), audio["codec_name"]


def _rgb(path: Path, seconds: float) -> bytes:
    frame = path.parent / f"frame-{seconds}.png"
    subprocess.run(
        [resolve_ffmpeg(), "-y", "-ss", str(seconds), "-i", str(path), "-frames:v", "1", str(frame)],
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        [resolve_ffmpeg(), "-v", "error", "-i", str(frame), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
    ).stdout


def _pixel(raw: bytes, x: int, y: int) -> tuple[int, int, int]:
    offset = (y * 1080 + x) * 3
    return raw[offset], raw[offset + 1], raw[offset + 2]


def _caption_plate(raw: bytes) -> bool:
    """The production plate is white React text in the lower safe area."""
    for y in range(1400, 1860, 4):
        for x in range(64, 1016, 8):
            red, green, blue = _pixel(raw, x, y)
            if red > 200 and green > 200 and blue > 200:
                return True
    return False
