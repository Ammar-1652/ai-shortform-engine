"""Long-source preview trims. Real campaign media is not read."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.media.probe import read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.preview.backend import FakeRoughRenderBackend
from clipforge.preview.probe import probe_preview
from clipforge.preview.trim import stage_candidate_span, stage_time_map
from clipforge.schemas.time import TimelineSegment, TimeMapDocument
from tests.candidate_support import segment
from tests.preview_support import mine, ready_stack, render, short_profile

pytestmark = pytest.mark.preview


def _long_media(directory: Path, *, rate: str) -> tuple[Path, Path]:
    directory.mkdir(parents=True)
    video = directory / "long.mp4"
    audio = directory / "speech.flac"
    ffmpeg = resolve_ffmpeg()
    runner = ProcessRunner()
    runner.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=1280x720:rate={rate}:duration=20",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=20",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "48",
            "-keyint_min",
            "48",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(video),
        ],
        log_path=None,
        check=True,
    )
    runner.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=20",
            "-c:a",
            "flac",
            str(audio),
        ],
        log_path=None,
        check=True,
    )
    return video, audio


def test_candidate_trim_starts_off_zero_for_both_frame_rates(tmp_path: Path) -> None:
    for rate in ("30000/1001", "24000/1001"):
        video, audio = _long_media(tmp_path / rate.replace("/", "-"), rate=rate)
        staged = stage_candidate_span(
            video,
            audio,
            tmp_path / f"stage-{rate.replace('/', '-')}",
            stem="clip",
            start_us=8_500_000,
            end_us=12_500_000,
            frame_count=120,
            root=tmp_path,
            log_path=None,
        )
        assert staged.source_start_us == 8_500_000
        assert staged.source_end_us == 12_500_000
        assert abs(staged.duration_us - 4_000_000) <= 100_000
        assert len(staged.video_sha256) == 64
        video_path = tmp_path / f"stage-{rate.replace('/', '-')}" / "clip.mp4"
        assert not video_path.is_symlink()
        probed = read_ffprobe_json(video_path, ProcessRunner(), None)
        kinds = {
            stream.get("codec_type"): stream.get("codec_name")
            for stream in probed["streams"]
            if isinstance(stream, dict)
        }
        assert kinds.get("video") == "h264"
        audio_probe = read_ffprobe_json(staged.audio_path, ProcessRunner(), None)
        audio_kinds = {
            stream.get("codec_name")
            for stream in audio_probe["streams"]
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        }
        assert audio_kinds == {"flac"}


def test_time_map_stage_concatenates_ordered_ranges_without_repetition(tmp_path: Path) -> None:
    video, audio = _long_media(tmp_path / "jump-cut", rate="30")
    staged = stage_time_map(
        video,
        audio,
        tmp_path / "stage-jump-cut",
        stem="span",
        time_map=TimeMapDocument(
            time_map_id="jump-map",
            segments=[
                TimelineSegment(segment_id="first", source_start_us=2_000_000, source_end_us=4_000_000),
                TimelineSegment(segment_id="second", source_start_us=12_000_000, source_end_us=15_000_000),
            ],
        ),
        frame_count=150,
        root=tmp_path,
        log_path=None,
    )
    assert staged.source_ranges == ((2_000_000, 4_000_000), (12_000_000, 15_000_000))
    assert abs(staged.duration_us - 5_000_000) <= 100_000
    assert staged.video_path.is_file()
    assert staged.audio_path.is_file()
    recipe = (tmp_path / "stage-jump-cut" / "span.recipe.json").read_text(encoding="utf-8")
    assert '"source_ranges": [[2000000, 4000000], [12000000, 15000000]]' in recipe
    assert '"audio_source_ranges": [[2000000, 4000000], [12000000, 15000000]]' in recipe


def test_time_map_stage_records_identical_picture_and_speech_ranges_for_one_range(
    tmp_path: Path,
) -> None:
    """A one-shot Hero must not fall back to two independently staged clocks."""
    video, audio = _long_media(tmp_path / "single-range", rate="30")
    stage = tmp_path / "stage-single-range"
    stage_time_map(
        video,
        audio,
        stage,
        stem="span",
        time_map=TimeMapDocument(
            time_map_id="single-map",
            segments=[TimelineSegment(segment_id="only", source_start_us=3_000_000, source_end_us=7_000_000)],
        ),
        frame_count=120,
        root=tmp_path,
        log_path=None,
    )
    recipe = (stage / "span.recipe.json").read_text(encoding="utf-8")
    assert '"source_ranges": [[3000000, 7000000]]' in recipe
    assert '"audio_source_ranges": [[3000000, 7000000]]' in recipe


def test_candidate_trim_rejects_speech_duration_drift(tmp_path: Path) -> None:
    video, audio = _long_media(tmp_path / "av-drift", rate="30")
    resolve_ffmpeg_path = resolve_ffmpeg()
    ProcessRunner().run(
        [
            resolve_ffmpeg_path,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=330:sample_rate=16000:duration=1",
            "-c:a",
            "flac",
            str(audio),
        ],
        log_path=None,
        check=True,
    )
    with pytest.raises(MediaError, match=r"speech duration|AV-unsynchronized"):
        stage_candidate_span(
            video,
            audio,
            tmp_path / "stage-av-drift",
            stem="clip",
            start_us=8_500_000,
            end_us=12_500_000,
            frame_count=120,
            root=tmp_path,
            log_path=None,
        )


def test_failed_preview_does_not_promote_a_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")
    video, audio = _long_media(tmp_path / "media", rate="30000/1001")
    spoken = segment(0, 8_500_000, 12_500_000, "Point zero explains one concrete method today.")
    fixture = ready_stack(
        tmp_path / "stack",
        segments=[spoken],
        duration_us=20_000_000,
        proxy_bytes=video.read_bytes(),
        asr_bytes=audio.read_bytes(),
    )
    mined = mine(
        fixture,
        profile=short_profile(preferred_max_duration_us=5_000_000, hard_max_duration_us=6_000_000),
    )
    assert mined.selected_count == 1

    backend = FakeRoughRenderBackend()
    backend.requires_browser = True

    def fail_batch(batch_path: Path, *, log_path: Path) -> None:
        del batch_path, log_path
        raise MediaError("renderer failed before promotion")

    backend.render_batch = fail_batch  # type: ignore[method-assign]
    with pytest.raises(MediaError, match="renderer failed"):
        render(fixture, backend=backend)
    assert list(fixture.work.rglob("preview.mp4")) == []
    assert list(fixture.work.rglob("staging")) == []
    recovered = render(fixture, backend=FakeRoughRenderBackend())
    assert recovered.rendered_count == 1
    assert len(list(fixture.work.rglob("preview.mp4"))) == 1


@pytest.mark.browser
def test_real_remotion_preview_uses_the_trimmed_span(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")
    video, audio = _long_media(tmp_path / "media", rate="30000/1001")
    spoken = segment(0, 8_500_000, 12_500_000, "Point zero explains one concrete method today.")
    fixture = ready_stack(
        tmp_path / "stack",
        segments=[spoken],
        duration_us=20_000_000,
        proxy_bytes=video.read_bytes(),
        asr_bytes=audio.read_bytes(),
    )
    mine(
        fixture,
        profile=short_profile(preferred_max_duration_us=5_000_000, hard_max_duration_us=6_000_000),
    )
    before = set(Path("/tmp").glob("cfb*"))
    result = render(fixture)
    assert set(Path("/tmp").glob("cfb*")) <= before
    assert result.rendered_count == 1
    preview = next(fixture.work.rglob("preview.mp4"))
    probed = probe_preview(preview, expected_duration_us=4_000_000, log_path=None)
    assert probed.video_codec == "h264"
    assert probed.audio_codec
    rendered = (preview.parent / "render-input.json").read_text(encoding="utf-8")
    assert '"media_trim_frame": 0' in rendered
    again = render(fixture)
    assert again.cache_hit is True


def test_trim_rejects_symlink_remote_and_traversal(tmp_path: Path) -> None:
    video, audio = _long_media(tmp_path / "media", rate="30000/1001")
    linked = tmp_path / "linked.mp4"
    linked.symlink_to(video)
    with pytest.raises(MediaError, match="refusing to trim"):
        stage_candidate_span(
            linked,
            audio,
            tmp_path / "stage-link",
            stem="clip",
            start_us=1_000_000,
            end_us=2_000_000,
            frame_count=30,
            root=tmp_path,
            log_path=None,
        )
    with pytest.raises(MediaError, match="remote or traversing"):
        stage_candidate_span(
            Path("https://example.invalid/source.mp4"),
            audio,
            tmp_path / "stage-url",
            stem="clip",
            start_us=1_000_000,
            end_us=2_000_000,
            frame_count=30,
            root=tmp_path,
            log_path=None,
        )
    with pytest.raises(MediaError, match="remote or traversing"):
        stage_candidate_span(
            Path("nested/../../outside.mp4"),
            audio,
            tmp_path / "stage-dot",
            stem="clip",
            start_us=1_000_000,
            end_us=2_000_000,
            frame_count=30,
            root=tmp_path,
            log_path=None,
        )
