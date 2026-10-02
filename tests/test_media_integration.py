"""Synthetic ffmpeg coverage for ingest, alignment, proxies, cache, and failure."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.media import recipes
from clipforge.media.ingest import IngestResult, ingest_source
from clipforge.media.prepare import prepare_source
from clipforge.media.process import ProcessRunner
from clipforge.media.verify import verify_source
from clipforge.storage import Database, get_source_manifest, list_source_assets
from tests.media_factory import require_ffmpeg, synth_video

pytestmark = pytest.mark.media

runner = CliRunner()


@pytest.fixture(scope="module", autouse=True)
def _ffmpeg_required() -> None:
    require_ffmpeg()


@pytest.fixture(autouse=True)
def _reserve_for_synthetic_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the production default at 10 GiB. These files need only a few megabytes."""
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "1")


def test_landscape_prepare_is_cached_on_the_second_run(tmp_path: Path) -> None:
    source = synth_video(tmp_path, "landscape.mp4", size="160x90", rate="30", duration="2")
    database, project_id = _project(tmp_path)
    ingested = _ingest(database, project_id, source, tmp_path / "work")
    assert ingested.deduplicated is False
    assert ingested.storage_mode == "referenced"
    assert ingested.transcription_eligible is True
    media_runner = ProcessRunner()
    first = prepare_source(
        database=database,
        source_asset_id=ingested.source_asset_id,
        work_root=tmp_path / "work",
        runner=media_runner,
    )
    encoded = media_runner.transcode_count
    assert encoded >= 2
    assert first.proxy_from_cache is False
    assert first.audio_from_cache is False
    second = prepare_source(
        database=database,
        source_asset_id=ingested.source_asset_id,
        work_root=tmp_path / "work",
        runner=media_runner,
    )
    assert media_runner.transcode_count == encoded
    assert second.proxy_from_cache is True
    assert second.audio_from_cache is True
    report = verify_source(
        database=database,
        source_asset_id=ingested.source_asset_id,
        work_root=tmp_path / "work",
    )
    assert report.status == "PASS"
    again = _ingest(database, project_id, source, tmp_path / "work")
    assert again.deduplicated is True
    assert again.source_asset_id == ingested.source_asset_id
    with database.connect() as connection:
        assert len(list_source_assets(connection, project_id)) == 1


def test_portrait_square_and_no_audio(tmp_path: Path) -> None:
    database, project_id = _project(tmp_path)
    portrait = synth_video(tmp_path, "portrait.mp4", size="90x160", audio=True, duration="1.5")
    square = synth_video(tmp_path, "square.mp4", size="120x120", audio=False, duration="1.5")
    silent = synth_video(tmp_path, "silent.mp4", size="160x90", audio=False, duration="1.5")
    for path in (portrait, square, silent):
        ingested = _ingest(database, project_id, path, tmp_path / "work")
        prepared = prepare_source(
            database=database,
            source_asset_id=ingested.source_asset_id,
            work_root=tmp_path / "work",
        )
        assert prepared.proxy_path.is_file()
        if path is silent or path is square:
            assert ingested.transcription_eligible is False
            assert prepared.audio_path is None
            report = verify_source(
                database=database,
                source_asset_id=ingested.source_asset_id,
                work_root=tmp_path / "work",
            )
            assert report.status == "PASS"
            assert any("not expected" in line.detail for line in report.lines)


def test_proxy_duration_across_frame_rates(tmp_path: Path) -> None:
    database, project_id = _project(tmp_path)
    for rate in ("24", "25", "30", "60", "30000/1001"):
        filename = f"rate-{rate.replace('/', '-')}.mp4"
        path = synth_video(tmp_path, filename, rate=rate, audio=False, duration="1.5")
        ingested = _ingest(database, project_id, path, tmp_path / "work")
        if rate == "30000/1001":
            video = _video_from_db(database, ingested.source_asset_id)
            ratios = {
                (item.numerator, item.denominator)
                for item in (video.avg_frame_rate, video.r_frame_rate)
                if item is not None
            }
            assert (30000, 1001) in ratios
        prepare_source(
            database=database,
            source_asset_id=ingested.source_asset_id,
            work_root=tmp_path / "work",
        )


def test_stream_overrides_and_invalid_indexes(tmp_path: Path) -> None:
    database, project_id = _project(tmp_path)
    path = synth_video(tmp_path, "multi.mp4", extra_audio=True, duration="1.5")
    automatic = _ingest(database, project_id, path, tmp_path / "work")
    assert automatic.audio_stream_index is not None
    other = 1 if automatic.audio_stream_index != 1 else 2
    # A second project so the same bytes are not deduplicated before the override is applied.
    other_project = _second_project(database)
    chosen = ingest_source(
        database=database,
        project_id=other_project,
        source=str(path),
        rights_status="licensed",
        rights_evidence=_evidence(tmp_path),
        rights_name="Licensed fixture",
        confirm_rights=True,
        work_root=tmp_path / "work",
        audio_stream=other,
    )
    assert chosen.audio_stream_index == other
    assert chosen.source_asset_id != automatic.source_asset_id
    with pytest.raises(MediaError, match="did not fall back"):
        ingest_source(
            database=database,
            project_id=other_project,
            source=str(path),
            rights_status="licensed",
            rights_evidence=_evidence(tmp_path),
            rights_name="Licensed fixture",
            confirm_rights=True,
            work_root=tmp_path / "work",
            video_stream=99,
        )
    with pytest.raises(MediaError, match="audio stream"):
        ingest_source(
            database=database,
            project_id=other_project,
            source=str(synth_video(tmp_path, "one.mp4", duration="1")),
            rights_status="licensed",
            rights_evidence=_evidence(tmp_path),
            rights_name="Licensed fixture",
            confirm_rights=True,
            work_root=tmp_path / "work",
            audio_stream=40,
        )


def test_delayed_audio_has_leading_silence(tmp_path: Path) -> None:
    path = synth_video(tmp_path, "delayed.mp4", duration="3", audio_offset="0.5")
    database, project_id = _project(tmp_path)
    ingested = _ingest(database, project_id, path, tmp_path / "work")
    assert ingested.audio_offset_us is not None
    assert ingested.audio_offset_us > 400_000
    prepared = prepare_source(
        database=database,
        source_asset_id=ingested.source_asset_id,
        work_root=tmp_path / "work",
    )
    assert prepared.audio_path is not None
    early = _mean_volume(prepared.audio_path, "0", "0.35")
    later = _mean_volume(prepared.audio_path, "0.70", "0.40")
    assert early < -45
    assert later > -35


def test_early_audio_is_trimmed_to_video_time(tmp_path: Path) -> None:
    path = synth_video(tmp_path, "early.mp4", duration="2", video_offset="0.5", early_tone=True, audio=False)
    database, project_id = _project(tmp_path)
    ingested = _ingest(database, project_id, path, tmp_path / "work")
    assert ingested.audio_offset_us is not None
    assert ingested.audio_offset_us < -300_000
    prepared = prepare_source(
        database=database,
        source_asset_id=ingested.source_asset_id,
        work_root=tmp_path / "work",
    )
    assert prepared.audio_path is not None
    low = _band_volume(prepared.audio_path, 200)
    high = _band_volume(prepared.audio_path, 2000)
    assert high > low + 8


def test_rotation_proxy_uses_display_dimensions(tmp_path: Path) -> None:
    path = synth_video(tmp_path, "rotated.mp4", size="160x90", rotate="90", audio=False, duration="1.2")
    database, project_id = _project(tmp_path)
    ingested = _ingest(database, project_id, path, tmp_path / "work")
    video = _video_from_db(database, ingested.source_asset_id)
    if video.rotation.degrees not in {90, -270}:
        pytest.fail(f"fixture did not expose rotation metadata, got {video.rotation.degrees}")
    assert (video.display_width, video.display_height) == (90, 160)
    prepared = prepare_source(
        database=database,
        source_asset_id=ingested.source_asset_id,
        work_root=tmp_path / "work",
    )
    probed = _ffprobe_wh(prepared.proxy_path)
    assert probed == (90, 160)


def test_vfr_like_source_is_not_rejected(tmp_path: Path) -> None:
    path = synth_video(tmp_path, "vfr.mp4", vfr=True, audio=False, duration="1.5")
    database, project_id = _project(tmp_path)
    ingested = _ingest(database, project_id, path, tmp_path / "work")
    assert ingested.frame_timing in {"cfr_likely", "vfr_possible", "unknown"}
    prepare_source(database=database, source_asset_id=ingested.source_asset_id, work_root=tmp_path / "work")


def test_hdr_tag_blocks_proxy_generation(tmp_path: Path) -> None:
    path = synth_video(tmp_path, "hdr.mp4", color_trc="smpte2084", audio=False, duration="1")
    database, project_id = _project(tmp_path)
    ingested = _ingest(database, project_id, path, tmp_path / "work")
    assert ingested.hdr == "pq"
    media_runner = ProcessRunner()
    with pytest.raises(MediaError, match="HDR"):
        prepare_source(
            database=database,
            source_asset_id=ingested.source_asset_id,
            work_root=tmp_path / "work",
            runner=media_runner,
        )
    assert media_runner.transcode_count == 0
    proxy = (
        tmp_path
        / "work"
        / "projects"
        / project_id
        / "sources"
        / ingested.source_asset_id
        / "proxy"
        / "analysis.mp4"
    )
    assert not proxy.exists()


def test_corrupt_text_and_remote_inputs(tmp_path: Path) -> None:
    database, project_id = _project(tmp_path)
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(os.urandom(64))
    text = tmp_path / "notes.mp4"
    text.write_text("this is not media")
    for path in (corrupt, text):
        with pytest.raises(MediaError):
            _ingest(database, project_id, path, tmp_path / "work")
    invoked = runner.invoke(
        app,
        [
            "source",
            "ingest",
            project_id,
            "https://example.com/a.mp4",
            "--rights-status",
            "owned",
            "--rights-evidence",
            _evidence(tmp_path),
            "--rights-name",
            "Owned",
            "--confirm-rights",
            "--db",
            str(tmp_path / "clipforge.sqlite3"),
            "--work-dir",
            str(tmp_path / "work"),
        ],
    )
    assert invoked.exit_code != 0
    assert "local file" in invoked.stderr.lower() or "Rejected" in invoked.stderr
    missing_confirm = runner.invoke(
        app,
        [
            "source",
            "ingest",
            project_id,
            str(text),
            "--rights-status",
            "owned",
            "--rights-evidence",
            _evidence(tmp_path),
            "--rights-name",
            "Owned",
            "--db",
            str(tmp_path / "clipforge.sqlite3"),
            "--work-dir",
            str(tmp_path / "work"),
        ],
    )
    assert missing_confirm.exit_code != 0
    assert "confirm-rights" in missing_confirm.stderr


def test_source_mutation_blocks_prepare(tmp_path: Path) -> None:
    path = synth_video(tmp_path, "mutate.mp4", audio=False, duration="1.2")
    database, project_id = _project(tmp_path)
    ingested = _ingest(database, project_id, path, tmp_path / "work")
    original = path.read_bytes()
    path.write_bytes(original + b"mutated")
    with pytest.raises(MediaError, match="changed since ingest"):
        prepare_source(
            database=database,
            source_asset_id=ingested.source_asset_id,
            work_root=tmp_path / "work",
        )
    with database.connect() as connection:
        stored = get_source_manifest(connection, ingested.source_asset_id)
    assert stored.content_sha256 == ingested.content_sha256


def test_corrupt_proxy_and_recipe_change_regenerate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = synth_video(tmp_path, "cache.mp4", audio=True, duration="1.2")
    database, project_id = _project(tmp_path)
    ingested = _ingest(database, project_id, path, tmp_path / "work")
    media_runner = ProcessRunner()
    first = prepare_source(
        database=database,
        source_asset_id=ingested.source_asset_id,
        work_root=tmp_path / "work",
        runner=media_runner,
    )
    baseline = media_runner.transcode_count
    data = first.proxy_path.read_bytes()
    first.proxy_path.write_bytes(data[:80] + bytes([data[80] ^ 0x5A]) + data[81:])
    prepare_source(
        database=database,
        source_asset_id=ingested.source_asset_id,
        work_root=tmp_path / "work",
        runner=media_runner,
    )
    assert media_runner.transcode_count > baseline
    after_corrupt = media_runner.transcode_count
    first.proxy_path.unlink()
    prepare_source(
        database=database,
        source_asset_id=ingested.source_asset_id,
        work_root=tmp_path / "work",
        runner=media_runner,
    )
    assert media_runner.transcode_count > after_corrupt
    monkeypatch.setattr(recipes, "ANALYSIS_PROXY_VERSION", "2")
    before_recipe = media_runner.transcode_count
    prepare_source(
        database=database,
        source_asset_id=ingested.source_asset_id,
        work_root=tmp_path / "work",
        runner=media_runner,
    )
    assert media_runner.transcode_count > before_recipe


def test_names_with_spaces_and_unicode(tmp_path: Path) -> None:
    database, project_id = _project(tmp_path)
    spaced = synth_video(tmp_path, "my video.mp4", audio=False, duration="1")
    unicode_name = synth_video(tmp_path, "视频_é.mp4", audio=False, duration="1.2", size="120x80")
    for path in (spaced, unicode_name):
        ingested = _ingest(database, project_id, path, tmp_path / "work")
        assert ingested.original_filename == path.name
        prepare_source(database=database, source_asset_id=ingested.source_asset_id, work_root=tmp_path / "work")


def test_same_bytes_are_not_deduplicated_across_projects(tmp_path: Path) -> None:
    path = synth_video(tmp_path, "shared.mp4", audio=False, duration="1")
    database, project_id = _project(tmp_path)
    first = _ingest(database, project_id, path, tmp_path / "work")
    second_project = _second_project(database)
    second = _ingest(database, second_project, path, tmp_path / "work")
    assert first.source_asset_id != second.source_asset_id
    assert first.content_sha256 == second.content_sha256


def _project(tmp_path: Path) -> tuple[Database, str]:
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    created = runner.invoke(app, ["project", "create", "Media", "--db", str(database.path)])
    assert created.exit_code == 0, created.stderr
    return database, created.stdout.strip()


def _second_project(database: Database) -> str:
    created = runner.invoke(app, ["project", "create", "Other", "--db", str(database.path)])
    assert created.exit_code == 0, created.stderr
    return created.stdout.strip()


def _evidence(tmp_path: Path) -> str:
    path = tmp_path / "evidence.txt"
    if not path.exists():
        path.write_text("campaign brief fixture")
    return str(path)


def _ingest(database: Database, project_id: str, source: Path, work: Path) -> IngestResult:
    result = ingest_source(
        database=database,
        project_id=project_id,
        source=str(source),
        rights_status="campaign_provided",
        rights_evidence=_evidence(source.parent),
        rights_name="Campaign provided footage",
        confirm_rights=True,
        work_root=work,
    )
    return result


def _video_from_db(database: Database, source_id: str) -> object:
    with database.connect() as connection:
        manifest = get_source_manifest(connection, source_id)
    for stream in manifest.probe.video_streams:
        if stream.index == manifest.video_stream_index:
            return stream
    raise AssertionError("selected video missing")


def _mean_volume(path: Path, start: str, duration: str) -> float:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-ss",
            start,
            "-t",
            duration,
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    text = completed.stderr
    if "max_volume: -inf" in text:
        return -120.0
    for line in text.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:", 1)[1].strip().split()[0])
    raise AssertionError(text[-500:])


def _band_volume(path: Path, frequency: int) -> float:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-t",
            "0.25",
            "-i",
            str(path),
            "-af",
            f"bandpass=f={frequency}:width_type=h:w=100,volumedetect",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    text = completed.stderr
    if "max_volume: -inf" in text:
        return -120.0
    for line in text.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:", 1)[1].strip().split()[0])
    raise AssertionError(text[-500:])


def _ffprobe_wh(path: Path) -> tuple[int, int]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    width, height = completed.stdout.strip().split(",")
    return int(width), int(height)
