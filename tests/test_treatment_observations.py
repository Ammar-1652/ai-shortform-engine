"""Relevance observations must show the footage actually selected by an edit."""

from pathlib import Path

import pytest
from PIL import Image

from clipforge.errors import MediaError
from clipforge.hero.treatment_assets import observe_registered_visual_asset
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.schemas.editorial import OutputInterval
from clipforge.storage import Database


@pytest.fixture
def visual_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    media = tmp_path / "two-scenes.mp4"
    ProcessRunner().run(
        [
            resolve_ffmpeg(),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=160x90:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=160x90:r=30:d=1",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(media),
        ],
        timeout_s=30,
    )
    # Registration/rights are covered by the asset gate suite. This test
    # isolates the actual ffprobe/ffmpeg observation and immutable publication.
    monkeypatch.setattr("clipforge.hero.treatment_assets.require_asset", lambda *_a, **_k: (None, None, media))
    return media


def _observe(root: Path, **overrides):
    return observe_registered_visual_asset(
        **{
            "database": Database(root / "unused.sqlite3"),
            "work_root": root,
            "project_id": "project-1",
            "source_asset_id": "source-1",
            "asset_id": "asset-1",
            "output_interval": OutputInterval(output_start_us=4_000_000, output_end_us=4_500_000),
            "source_in_us": 1_100_000,
            "source_evidence_ids": ["evidence-1"],
            "observed_labels": ["blue scene"],
            "relevance_score": 0.95,
            "relevance_threshold": 0.85,
            "reviewed_by": "codex-test",
            "review_note": "The selected insert is the blue second scene.",
            **overrides,
        }
    )


def test_observation_decodes_selected_inpoint_instead_of_unselected_first_scene(
    tmp_path: Path, visual_asset: Path
) -> None:
    _, observation = _observe(tmp_path)
    assert observation.analyzer_version == "ffmpeg-frame-probe-v2"
    assert len(observation.frames) == 3
    for frame in observation.frames:
        with Image.open(tmp_path / frame.relative_path) as image:
            red, _green, blue = image.convert("RGB").getpixel((80, 45))
        assert blue > 200 and red < 30, "observation sampled the unrelated first scene"
    _, before = _observe(tmp_path, source_in_us=0, observed_labels=["red scene"])
    assert before.observation_id != observation.observation_id
    with Image.open(tmp_path / before.frames[0].relative_path) as image:
        red, _green, blue = image.convert("RGB").getpixel((80, 45))
    assert red > 200 and blue < 30


def test_observation_revision_preserves_previous_evidence_and_cache_bytes(
    tmp_path: Path, visual_asset: Path
) -> None:
    path, first = _observe(tmp_path)
    original = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.parent.rglob("*") if p.is_file()}
    again_path, again = _observe(tmp_path)
    assert again_path == path and again == first
    revision_path, revision = _observe(tmp_path, relevance_score=0.9, review_note="Second independent review.")
    assert revision_path != path and revision.observation_id != first.observation_id
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == recorded for p, recorded in original.items())
    frame = tmp_path / first.frames[0].relative_path
    frame.write_bytes(b"changed evidence")
    with pytest.raises(MediaError, match="missing or stale"):
        _observe(tmp_path)
    assert frame.read_bytes() == b"changed evidence", "stale immutable evidence was silently repaired"


@pytest.mark.parametrize("source_in_us", [-1, 1.5, 1_900_000])
def test_invalid_or_overlong_observation_span_is_not_published(
    tmp_path: Path, visual_asset: Path, source_in_us
) -> None:
    with pytest.raises(MediaError, match=r"in-point|exceeds"):
        _observe(tmp_path, source_in_us=source_in_us)
    assert not list(tmp_path.glob("editorial/treatment-observations/*"))


def test_decode_failure_never_publishes_partial_observation(
    tmp_path: Path, visual_asset: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ProcessRunner.run

    def fail_decode(self, argv, **kwargs):
        if Path(argv[0]).name == "ffmpeg":
            raise MediaError("decode interrupted")
        return original(self, argv, **kwargs)

    monkeypatch.setattr(ProcessRunner, "run", fail_decode)
    with pytest.raises(MediaError, match="decode interrupted"):
        _observe(tmp_path)
    assert not list(tmp_path.glob("editorial/treatment-observations/*"))


def test_observation_at_media_endpoint_has_a_decodable_last_sample(tmp_path: Path, visual_asset: Path) -> None:
    _, observation = _observe(tmp_path, source_in_us=1_500_000)
    assert all((tmp_path / item.relative_path).is_file() for item in observation.frames)
    assert observation.source_out_us == 2_000_000
