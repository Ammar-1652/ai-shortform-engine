"""Rough preview rendering with a fake encoder. Chromium is not started."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_to_file_uri
from clipforge.preview.backend import FakeRoughRenderBackend
from clipforge.preview.constants import KIND_PREVIEW
from clipforge.preview.inputs import load_preview_inputs, preview_input_digest
from clipforge.preview.integrity import preview_problems
from clipforge.preview.service import default_profile
from clipforge.preview.show import format_preview, format_preview_list, load_preview_document
from clipforge.preview.verify import verify_preview
from clipforge.schemas.jobs import JobStatus
from clipforge.storage import find_artifact, get_job, list_jobs
from tests.candidate_support import PROJECT_ID, SOURCE_ID
from tests.preview_support import PreviewFixture, isolated_segments, mine, ready_stack, render, short_profile

pytestmark = pytest.mark.preview
runner = CliRunner()


@pytest.fixture(autouse=True)
def _reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")


def _jobs(database) -> list:
    with database.connect() as connection:
        return [job for job in list_jobs(connection, PROJECT_ID) if job.kind == "rough_preview_render"]


def _mined(tmp_path: Path, count: int = 1) -> tuple[PreviewFixture, FakeRoughRenderBackend]:
    pieces, duration = isolated_segments(count)
    fixture = ready_stack(tmp_path, segments=pieces, duration_us=duration)
    mined = mine(fixture, profile=short_profile(max_candidates=max(count, 1)))
    assert mined.selected_count == count
    return fixture, FakeRoughRenderBackend()


def test_root_help_hides_preview_subcommands() -> None:
    top = runner.invoke(app, ["--help"])
    assert top.exit_code == 0
    assert "preview" in top.stdout
    for absent in ("publish", "transcribe", "render"):
        assert absent not in top.stdout
    group = runner.invoke(app, ["preview", "--help"])
    assert group.exit_code == 0
    assert "doctor" in group.stdout
    assert "list" in group.stdout
    assert "show" in group.stdout
    assert "verify" in group.stdout


def test_full_set_preserves_order_hashes_and_digest(tmp_path: Path) -> None:
    fixture, backend = _mined(tmp_path, 3)
    result = render(fixture, backend)
    assert result.cache_hit is False
    assert result.rendered_count == 3
    assert backend.calls == 1
    document = load_preview_document(fixture.database, SOURCE_ID, fixture.work)
    mined_ids = [item.candidate_id for item in document.previews]
    assert [item.rank for item in document.previews] == [1, 2, 3]
    assert document.summary.rendered_count == document.summary.selected_candidate_count == 3
    assert document.summary.total_output_duration_us == sum(
        item.output_duration_us for item in document.previews
    )
    assert document.summary.total_preview_bytes == sum(item.preview_size_bytes for item in document.previews)
    digest = preview_input_digest(
        source_sha256=document.source_sha256,
        candidate_set_sha256=document.candidate_set_sha256,
        transcript_sha256=document.transcript_sha256,
        visual_analysis_sha256=document.visual_analysis_sha256,
        analysis_proxy_sha256=document.analysis_proxy_sha256,
        asr_audio_sha256=document.asr_audio_sha256,
        profile_fingerprint=document.profile_fingerprint,
    )
    assert document.preview_input_sha256 == digest
    assert document.provenance.inputs_sha256 == digest
    with fixture.database.connect() as connection:
        job = get_job(connection, result.job_id)
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_PREVIEW)
    assert job.status is JobStatus.SUCCEEDED
    assert job.payload["preview_input_sha256"] == digest
    assert job.payload["preview_set_id"] == document.preview_set_id
    assert job.payload["profile_fingerprint"] == document.profile_fingerprint
    assert row is not None and row.job_id == job.job_id
    assert row.provenance.job_id == job.job_id
    run = result.manifest_path.parent
    for preview in document.previews:
        video = run / preview.preview_relative_path
        rendered = run / "candidates" / preview.candidate_id / "render-input.json"
        assert sha256_file(video) == preview.preview_sha256
        assert sha256_file(rendered) == preview.render_input_sha256
        payload = rendered.read_text(encoding="utf-8")
        assert "quality_score" not in payload
        assert "virality" not in payload
        assert preview.width == 720 and preview.height == 1280
        assert preview.detected_video_codec == "h264"
        assert preview.detected_pixel_format == "yuv420p"
        assert preview.detected_audio_codec == "aac"
        assert abs(preview.duration_error_us) <= 100_000
        assert preview.timing_quality == "provisional"
        assert len(preview.time_map_sha256) == 64
    assert "provisional" in format_preview(document, mined_ids[0])
    listed = format_preview_list(document)
    assert mined_ids[0] in listed
    assert preview.preview_sha256[:12] in listed
    report = verify_preview(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work)
    assert report.status == "PASS"
    doctor = runner.invoke(app, ["preview", "doctor", "--work-dir", str(fixture.work)])
    assert doctor.exit_code == 0
    assert "720x1280" in doctor.stdout
    assert "provisional-caption-v1" in doctor.stdout
    assert "schema_version: 4" in doctor.stdout
    shown = runner.invoke(
        app,
        [
            "preview",
            "show",
            SOURCE_ID,
            mined_ids[0],
            "--db",
            str(fixture.database.path),
            "--work-dir",
            str(fixture.work),
        ],
    )
    assert shown.exit_code == 0
    assert "provisional" in shown.stdout


def test_seven_and_twenty_five_keep_their_counts(tmp_path: Path) -> None:
    for count in (7, 25):
        directory = tmp_path / str(count)
        directory.mkdir()
        fixture, backend = _mined(directory, count)
        result = render(fixture, backend)
        assert result.rendered_count == count
        assert result.candidate_count == count
        document = load_preview_document(fixture.database, SOURCE_ID, fixture.work)
        assert len(document.previews) == count


def test_zero_candidates_skip_the_renderer(tmp_path: Path) -> None:
    fixture = ready_stack(tmp_path, segments=[], duration_us=30_000_000)
    mined = mine(fixture, profile=short_profile())
    assert mined.selected_count == 0
    backend = FakeRoughRenderBackend()
    result = render(fixture, backend)
    assert result.rendered_count == 0
    assert backend.calls == 0
    document = load_preview_document(fixture.database, SOURCE_ID, fixture.work)
    assert document.previews == []
    assert document.summary.total_output_duration_us == 0
    assert document.summary.total_preview_bytes == 0
    assert (
        verify_preview(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work).status
        == "PASS"
    )


def test_cache_hit_skips_the_renderer_and_force_keeps_the_old_run(tmp_path: Path) -> None:
    fixture, backend = _mined(tmp_path, 1)
    first = render(fixture, backend)
    second = render(fixture, backend)
    assert second.cache_hit is True
    assert second.job_id == first.job_id
    assert second.preview_set_id == first.preview_set_id
    assert backend.calls == 1
    forced = render(fixture, backend, force=True)
    assert forced.cache_hit is False
    assert forced.preview_set_id != first.preview_set_id
    assert first.manifest_path.is_file()
    assert forced.manifest_path.is_file()
    assert backend.calls == 2


def test_corrupt_or_missing_preview_is_a_miss(tmp_path: Path) -> None:
    fixture, backend = _mined(tmp_path, 1)
    first = render(fixture, backend)
    video = (
        first.manifest_path.parent
        / load_preview_document(fixture.database, SOURCE_ID, fixture.work).previews[0].preview_relative_path
    )
    original = video.read_bytes()
    mutated = bytearray(original)
    mutated[20] ^= 0xFF
    video.write_bytes(mutated)
    again = render(fixture, backend)
    assert again.cache_hit is False
    assert again.preview_set_id != first.preview_set_id
    assert video.read_bytes() != original
    missing = (
        again.manifest_path.parent
        / load_preview_document(fixture.database, SOURCE_ID, fixture.work).previews[0].preview_relative_path
    )
    missing.unlink()
    third = render(fixture, backend)
    assert third.cache_hit is False
    assert third.preview_set_id != again.preview_set_id
    assert backend.calls == 3


def test_profile_and_candidate_changes_miss(tmp_path: Path) -> None:
    fixture, backend = _mined(tmp_path, 1)
    first = render(fixture, backend)
    changed = default_profile().model_copy(update={"h264_crf": 30})
    second = render(fixture, backend, profile=changed)
    assert second.cache_hit is False
    assert second.preview_set_id != first.preview_set_id
    mine(fixture, profile=short_profile(), force=True)
    third = render(fixture, backend, profile=changed)
    assert third.cache_hit is False
    assert third.mining_id != second.mining_id


def test_transcript_and_visual_changes_block_until_restored(tmp_path: Path) -> None:
    fixture, backend = _mined(tmp_path, 1)
    first = render(fixture, backend)
    transcript = fixture.workspace.transcript_file()
    original = transcript.read_text(encoding="utf-8")
    transcript.write_text(original.replace("Point", "Topic"), encoding="utf-8")
    assert (
        verify_preview(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work).status
        == "FAIL"
    )
    with pytest.raises(MediaError, match="transcript"):
        render(fixture, backend)
    transcript.write_text(original, encoding="utf-8")
    assert render(fixture, backend).cache_hit is True
    visual = fixture.workspace.vision_run_dir("analysis-1") / "analysis.json"
    visual_bytes = visual.read_bytes()
    visual.write_bytes(visual_bytes + b" ")
    with pytest.raises(MediaError, match="visual"):
        render(fixture, backend)
    visual.write_bytes(visual_bytes)
    assert render(fixture, backend).cache_hit is True
    assert first.manifest_path.is_file()


def test_upstream_gates_insert_no_preview_job(tmp_path: Path) -> None:
    fixture, backend = _mined(tmp_path, 1)
    with fixture.database.transaction() as connection:
        connection.execute("DELETE FROM artifacts WHERE kind = 'candidate_set_json'")
    with pytest.raises(MediaError, match="candidate mine"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []

    fixture, backend = _mined(tmp_path / "transcript", 1)
    with fixture.database.transaction() as connection:
        connection.execute("DELETE FROM artifacts WHERE kind = 'transcript_json'")
    with pytest.raises(MediaError, match="transcript run"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []

    fixture, backend = _mined(tmp_path / "visual", 1)
    with fixture.database.transaction() as connection:
        connection.execute("DELETE FROM artifacts WHERE kind = 'visual_analysis_json'")
    with pytest.raises(MediaError, match="vision analyze"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []

    fixture, backend = _mined(tmp_path / "proxy", 1)
    fixture.workspace.proxy_file("analysis.mp4").unlink()
    with pytest.raises(MediaError, match="media prepare"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []

    fixture, backend = _mined(tmp_path / "asr", 1)
    fixture.workspace.audio_file("asr.flac").unlink()
    with pytest.raises(MediaError, match="media prepare"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []


def test_mutation_rights_and_failed_producers_block(tmp_path: Path) -> None:
    fixture, backend = _mined(tmp_path, 1)
    fixture.source_path.write_bytes(b"mutated-source")
    with pytest.raises(MediaError, match=r"hash|changed|mutation|source"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []

    fixture, backend = _mined(tmp_path / "rights", 1)
    with fixture.database.transaction() as connection:
        connection.execute(
            "UPDATE asset_license_records SET status = 'unknown' WHERE license_record_id = 'lic-1'"
        )
    with pytest.raises(MediaError, match="rights"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []

    fixture, backend = _mined(tmp_path / "candidate-job", 1)
    mined_jobs = _kind(fixture, "candidate_mine")
    _mark_failed(fixture, mined_jobs[0].job_id, "candidate failed")
    with pytest.raises(MediaError, match="candidate"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []

    fixture, backend = _mined(tmp_path / "transcript-job", 1)
    _mark_failed(fixture, "job-transcript", "transcript failed")
    with pytest.raises(MediaError, match="transcript"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []

    fixture, backend = _mined(tmp_path / "visual-job", 1)
    _mark_failed(fixture, "job-visual", "visual failed")
    with pytest.raises(MediaError, match="visual"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []


def test_byte_mutations_block(tmp_path: Path) -> None:
    fixture, backend = _mined(tmp_path, 1)
    document_path = _candidate_path(fixture)
    document_path.write_bytes(document_path.read_bytes() + b"\n")
    with pytest.raises(MediaError, match="candidate"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []

    fixture, backend = _mined(tmp_path / "proxy", 1)
    proxy = fixture.workspace.proxy_file("analysis.mp4")
    proxy.write_bytes(proxy.read_bytes() + b"x")
    with pytest.raises(MediaError, match=r"proxy|analysis"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []

    fixture, backend = _mined(tmp_path / "asr", 1)
    audio = fixture.workspace.audio_file("asr.flac")
    audio.write_bytes(audio.read_bytes() + b"x")
    with pytest.raises(MediaError, match=r"ASR|audio"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []


def test_cross_project_and_producer_binding(tmp_path: Path) -> None:
    fixture, backend = _mined(tmp_path, 1)
    result = render(fixture, backend)
    document = load_preview_document(fixture.database, SOURCE_ID, fixture.work)
    foreign = document.model_copy(update={"project_id": "other-project"})
    inputs = load_preview_inputs(
        fixture.database,
        SOURCE_ID,
        fixture.work,
        profile_fingerprint=document.profile_fingerprint,
        create_workspace=False,
    )
    with fixture.database.connect() as connection:
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_PREVIEW)
        job = get_job(connection, result.job_id)
    assert row is not None
    problems = preview_problems(
        foreign,
        _sidecar(fixture),
        manifest_path=result.manifest_path,
        work_root=fixture.work,
        workspace=fixture.workspace,
        inputs=inputs,
        artifact_job_id=row.job_id,
        artifact_uri=row.uri,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
    )
    assert any("another project" in item for item in problems)
    payload = dict(job.payload)
    payload["preview_input_sha256"] = "b" * 64
    from clipforge.storage import update_job

    with fixture.database.transaction() as connection:
        update_job(connection, job.model_copy(update={"payload": payload}))
    report = verify_preview(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work)
    assert report.status == "FAIL"
    assert any("preview_input_sha256" in line.detail for line in report.lines)


def test_verify_is_read_only(tmp_path: Path) -> None:
    fixture, backend = _mined(tmp_path, 1)
    render(fixture, backend)
    before_files = _tree(fixture.work)
    before_rows = _rows(fixture.database)
    report = verify_preview(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work)
    assert report.status == "PASS"
    assert _tree(fixture.work) == before_files
    assert _rows(fixture.database) == before_rows
    listed = runner.invoke(
        app,
        ["preview", "list", SOURCE_ID, "--db", str(fixture.database.path), "--work-dir", str(fixture.work)],
    )
    assert listed.exit_code == 0
    assert _tree(fixture.work) == before_files


def test_artifact_paths_are_confined_before_preview_reads(tmp_path: Path) -> None:
    fixture, backend = _mined(tmp_path, 1)
    outside_candidate = tmp_path / "outside-candidate.json"
    outside_candidate.write_text("{not-json", encoding="utf-8")
    with fixture.database.transaction() as connection:
        connection.execute(
            "UPDATE artifacts SET uri = ? WHERE project_id = ? AND source_asset_id = ? AND kind = ?",
            (
                path_to_file_uri(outside_candidate),
                PROJECT_ID,
                SOURCE_ID,
                "candidate_set_json",
            ),
        )
    with pytest.raises(MediaError, match="outside the work root"):
        render(fixture, backend)
    assert _jobs(fixture.database) == []

    fixture, backend = _mined(tmp_path / "preview", 1)
    render(fixture, backend)
    outside_preview = tmp_path / "outside-preview.json"
    outside_preview.write_text("{not-json", encoding="utf-8")
    with fixture.database.transaction() as connection:
        connection.execute(
            "UPDATE artifacts SET uri = ? WHERE project_id = ? AND source_asset_id = ? AND kind = ?",
            (
                path_to_file_uri(outside_preview),
                PROJECT_ID,
                SOURCE_ID,
                KIND_PREVIEW,
            ),
        )
    report = verify_preview(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work)
    assert report.status == "FAIL"
    assert any("outside the work root" in line.detail for line in report.lines)


def test_candidate_ids_cannot_escape(tmp_path: Path) -> None:
    fixture = ready_stack(tmp_path)
    with pytest.raises(MediaError, match="refusing"):
        fixture.workspace.preview_candidate_dir("preview-set", "..")
    with pytest.raises(MediaError, match="refusing"):
        fixture.workspace.preview_candidate_dir("preview-set", "a/b")
    outside = tmp_path / "outside"
    outside.mkdir()
    assert not any(outside.iterdir())


def test_sidecar_field_and_bad_picture_fail_closed(tmp_path: Path) -> None:
    fixture, backend = _mined(tmp_path, 1)
    result = render(fixture, backend)
    sidecar_path = fixture.workspace.preview_sidecar()
    from clipforge.schemas.preview import RoughPreviewCacheRecord
    from clipforge.transcription.io import dump_json

    record = RoughPreviewCacheRecord.model_validate_json(sidecar_path.read_text(encoding="utf-8"))
    other = record.model_copy(update={"mining_id": "mining-other"})
    sidecar_path.write_text(dump_json(other), encoding="utf-8")
    report = verify_preview(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work)
    assert report.status == "FAIL"
    assert any("mining id" in line.detail for line in report.lines)
    sidecar_path.write_text(dump_json(record), encoding="utf-8")

    document = load_preview_document(fixture.database, SOURCE_ID, fixture.work)
    video = result.manifest_path.parent / document.previews[0].preview_relative_path
    from clipforge.media.process import ProcessRunner
    from clipforge.media.tools import resolve_ffmpeg

    ProcessRunner().run(
        [
            resolve_ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=16x16:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(video),
        ],
        check=True,
    )
    updated = document.previews[0].model_copy(
        update={"preview_sha256": sha256_file(video), "preview_size_bytes": video.stat().st_size}
    )
    rewritten = document.model_copy(
        update={
            "previews": [updated],
            "summary": document.summary.model_copy(update={"total_preview_bytes": updated.preview_size_bytes}),
        }
    )
    from clipforge.schemas.preview import RoughPreviewSetDocument

    stored = RoughPreviewSetDocument.model_validate(rewritten.model_dump(mode="json"))
    result.manifest_path.write_text(dump_json(stored), encoding="utf-8")
    refreshed = record.model_copy(
        update={
            "manifest_sha256": sha256_file(result.manifest_path),
            "manifest_size_bytes": result.manifest_path.stat().st_size,
        }
    )
    sidecar_path.write_text(dump_json(refreshed), encoding="utf-8")
    checked = verify_preview(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work)
    assert checked.status == "FAIL"
    assert any("720" in line.detail or "16x16" in line.detail for line in checked.lines)


def test_renderer_sources_do_not_use_a_shell() -> None:
    root = Path(__file__).resolve().parents[1]
    texts = []
    for path in (root / "src" / "clipforge" / "preview").rglob("*.py"):
        texts.append(path.read_text(encoding="utf-8"))
    for path in (root / "apps" / "renderer" / "src" / "rough-preview").rglob("*"):
        if path.suffix == ".tsx":
            texts.append(path.read_text(encoding="utf-8"))
    script = (root / "apps" / "renderer" / "scripts" / "render-rough.mjs").read_text(encoding="utf-8")
    texts.append(script)
    combined = "\n".join(texts)
    assert "shell=True" not in combined
    assert "dangerouslySetInnerHTML" not in combined
    assert "eval(" not in combined


def _mark_failed(fixture: PreviewFixture, job_id: str, message: str) -> None:
    from clipforge.storage import update_job

    with fixture.database.connect() as connection:
        job = get_job(connection, job_id)
    failed = job.model_copy(
        update={"status": JobStatus.FAILED, "error_message": message, "updated_at": job.updated_at}
    )
    with fixture.database.transaction() as connection:
        update_job(connection, failed)


def _kind(fixture: PreviewFixture, kind: str) -> list:
    with fixture.database.connect() as connection:
        return [job for job in list_jobs(connection, PROJECT_ID) if job.kind == kind]


def _candidate_path(fixture: PreviewFixture) -> Path:
    with fixture.database.connect() as connection:
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, "candidate_set_json")
    assert row is not None
    from clipforge.media.local_file import path_from_file_uri

    return path_from_file_uri(row.uri)


def _sidecar(fixture: PreviewFixture):
    from clipforge.schemas.preview import RoughPreviewCacheRecord

    return RoughPreviewCacheRecord.model_validate_json(
        fixture.workspace.preview_sidecar().read_text(encoding="utf-8")
    )


def _tree(root: Path) -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append((str(path.relative_to(root)), path.stat().st_size, digest))
    return rows


def _rows(database) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    with database.connect() as connection:
        jobs = connection.execute(
            "SELECT job_id, kind, status, payload_json, error_message FROM jobs ORDER BY job_id"
        ).fetchall()
        artifacts = connection.execute(
            "SELECT artifact_id, kind, uri, job_id FROM artifacts ORDER BY artifact_id"
        ).fetchall()
    return [tuple(row) for row in jobs], [tuple(row) for row in artifacts]
