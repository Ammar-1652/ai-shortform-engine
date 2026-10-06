"""Local delivery export. External platform publishing is not implemented."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.main import app
from clipforge.hero.advanced_assets import binding_for, load_catalog
from clipforge.hero.advanced_service import JOB_ADVANCED, KIND_ADVANCED
from clipforge.hero.probe import probe_hero
from clipforge.media.clock import seconds_text_to_us
from clipforge.media.hashing import sha256_file
from clipforge.media.probe import read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.media.workspace import SourceWorkspace
from clipforge.publish.errors import EXTERNAL_PUBLISHING, PublishError
from clipforge.publish.preflight import preflight_delivery
from clipforge.publish.service import (
    export_delivery,
    list_deliveries,
    plan_delivery,
    recover_delivery,
    resume_delivery,
    show_delivery,
    verify_delivery,
)
from clipforge.qa.service import KIND_QA
from clipforge.schemas.advanced import (
    AdvancedHeroCacheRecord,
    AdvancedHeroDraftOutput,
    AdvancedHeroDraftSetDocument,
    AdvancedHeroPlanDocument,
    AdvancedHeroProfile,
    AudioMixEvent,
    ReframingStrategy,
    TypographyEvent,
)
from clipforge.schemas.editorial import BrollEvent, MotionPurpose, OutputInterval
from clipforge.schemas.governance import AssetReference, ReviewDecision
from clipforge.schemas.ingest import SourceIngestManifest
from clipforge.schemas.jobs import JobRecord, JobStatus, QACheck, QAKind, QAResult, QAStatus
from clipforge.schemas.media import SourceAsset
from clipforge.schemas.project import Project
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.publish import (
    PublishCacheRecord,
    PublishExportInput,
    PublishFile,
    PublishPackageDocument,
    PublishProfile,
    PublishReadinessReport,
)
from clipforge.schemas.qa import PolicyDigest, QACacheRecord, QASetDocument
from clipforge.schemas.registry import CONTRACT_MODELS
from clipforge.storage import (
    Database,
    get_job,
    insert_artifact,
    insert_asset_license_record,
    insert_job,
    insert_project,
    insert_review,
    insert_source_asset,
    insert_source_manifest,
)
from clipforge.voice.provider import FakeVoiceProvider
from clipforge.voice.service import generate_narration
from tests.helpers import license_record, provenance, stamp
from tests.media_factory import synth_video
from tests.test_media_unit import _probe
from tests.test_round15 import _narration

pytestmark = [pytest.mark.benchmark, pytest.mark.filterwarnings("ignore::DeprecationWarning")]
runner = CliRunner()
_SEED = Path("/tmp/clipforge-round16-seed.mp4")
_VIDEO: tuple[bytes, int] | None = None


@dataclass
class World:
    database: Database
    work: Path
    workspace: SourceWorkspace
    video: Path
    source_path: Path
    broll: Path
    sfx: Path
    manifest: Path
    duration_us: int
    advanced_sha: str


def test_publish_contracts_are_registered() -> None:
    for model in (
        PublishProfile,
        PublishFile,
        PublishPackageDocument,
        PublishReadinessReport,
        PublishExportInput,
        PublishCacheRecord,
    ):
        assert model in CONTRACT_MODELS
    profile = PublishProfile()
    assert profile.profile_id == "local-delivery-v1"
    assert len(profile.fingerprint()) == 64


def test_export_copies_bytes_and_verifies_with_ffprobe(tmp_path: Path) -> None:
    world = _world(tmp_path)
    result = export_delivery(world.database, world.work, "source-1", "cand-1", created_by="ada")
    package = world.work / result.relative_package
    exported = package / "candidates" / "cand-1" / "video.mp4"
    assert result.status == "succeeded"
    assert exported.read_bytes() == world.video.read_bytes()
    assert sha256_file(exported) == result.video_sha256
    assert exported.stat().st_size == result.video_size
    probed = probe_hero(exported, expected_duration_us=world.duration_us)
    assert (probed.video_codec, probed.audio_codec, probed.fps_numerator, probed.fps_denominator) == (
        "h264",
        "aac",
        30,
        1,
    )
    manifest = (package / "manifest.json").read_text(encoding="utf-8")
    metadata = (package / "candidates" / "cand-1" / "metadata.json").read_text(encoding="utf-8")
    checksums = (package / "checksums.sha256").read_text(encoding="utf-8")
    assert "Café 説明" in metadata
    assert "caption_mode" in metadata
    assert "embedded_or_unavailable" in metadata
    for blob in (manifest, metadata, checksums):
        assert "/home/" not in blob
        assert "/tmp/" not in blob
        assert "://" not in blob
        assert "\\" not in blob
    _assert_checksums(package)
    assert "PASS delivery" in verify_delivery(world.database, world.work, "source-1", result.delivery_id)


def test_repeat_export_is_a_cache_hit_without_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(tmp_path)
    first = export_delivery(world.database, world.work, "source-1", "cand-1")
    jobs = _publish_jobs(world.database)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("cache hit called ffmpeg or copied a file")

    monkeypatch.setattr("clipforge.publish.preflight.probe_hero", fail)
    monkeypatch.setattr("clipforge.publish.service.shutil.copyfile", fail)
    second = export_delivery(world.database, world.work, "source-1", "cand-1")
    assert second.status == "cache_hit"
    assert second.delivery_id == first.delivery_id
    assert second.job_id == first.job_id
    assert _publish_jobs(world.database) == jobs


def test_force_keeps_the_previous_package(tmp_path: Path) -> None:
    world = _world(tmp_path)
    first = export_delivery(world.database, world.work, "source-1", "cand-1")
    second = export_delivery(world.database, world.work, "source-1", "cand-1", force=True)
    assert second.delivery_id != first.delivery_id
    assert second.status == "succeeded"
    old = world.work / "deliveries" / first.delivery_id / "manifest.json"
    new = world.work / "deliveries" / second.delivery_id / "manifest.json"
    assert old.is_file() and new.is_file()
    assert sha256_file(old) == first.manifest_sha256


def test_preflight_failures_insert_no_job(tmp_path: Path) -> None:
    world = _world(tmp_path)
    _set_decision(world, "rejected")
    with pytest.raises(PublishError, match="rejected") as rejected:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert rejected.value.category == "approval_rejected"
    _set_decision(world, "changes_requested")
    with pytest.raises(PublishError, match="changes_requested") as requested:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert requested.value.category == "approval_changes_requested"
    with world.database.transaction() as connection:
        connection.execute("DELETE FROM reviews WHERE review_id = 'review-hero'")
    with pytest.raises(PublishError, match="missing") as missing:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert missing.value.category == "approval_missing"
    assert _publish_jobs(world.database) == 0


def test_stale_approval_blocks_export(tmp_path: Path) -> None:
    world = _world(tmp_path)
    _insert_artifact(world, "art-old", world.manifest)
    with world.database.transaction() as connection:
        connection.execute("UPDATE reviews SET artifact_id = 'art-old' WHERE review_id = 'review-hero'")
    with pytest.raises(PublishError, match="older") as exc:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert exc.value.category == "approval_stale"
    assert _publish_jobs(world.database) == 0


def test_qa_gates_block_export(tmp_path: Path) -> None:
    world = _world(tmp_path)
    with world.database.transaction() as connection:
        connection.execute("DELETE FROM artifacts WHERE artifact_id = 'art-qa'")
    with pytest.raises(PublishError) as missing:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert missing.value.category == "qa_missing"
    world = _world(tmp_path / "failed")
    _rewrite_qa(world, status="fail")
    with pytest.raises(PublishError, match="fail") as failed:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert failed.value.category == "qa_failed"
    world = _world(tmp_path / "stale")
    _rewrite_qa(world, target="art-old")
    with pytest.raises(PublishError, match="bound") as stale:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert stale.value.category == "qa_stale"


def test_changed_hashes_and_rights_block_export(tmp_path: Path) -> None:
    world = _world(tmp_path)
    world.source_path.write_bytes(world.source_path.read_bytes() + b"x")
    with pytest.raises(PublishError) as source:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert source.value.category == "source_changed"
    world = _world(tmp_path / "hero")
    world.video.write_bytes(world.video.read_bytes() + b"x")
    with pytest.raises(PublishError) as hero:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert hero.value.category == "artifact_changed"
    world = _world(tmp_path / "broll")
    world.broll.write_bytes(world.broll.read_bytes() + b"x")
    with pytest.raises(PublishError) as broll:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert broll.value.category == "artifact_changed"
    world = _world(tmp_path / "sfx")
    world.sfx.write_bytes(world.sfx.read_bytes() + b"x")
    with pytest.raises(PublishError) as sfx:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert sfx.value.category == "artifact_changed"
    world = _world(tmp_path / "unknown")
    _set_rights(world, "lic-source", "unknown")
    with pytest.raises(PublishError) as unknown:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert unknown.value.category == "rights_blocked"
    world = _world(tmp_path / "prohibited")
    _set_rights(world, "lic-broll", "prohibited")
    with pytest.raises(PublishError) as prohibited:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert prohibited.value.category == "rights_blocked"


def test_narration_rights_and_hash(tmp_path: Path) -> None:
    world = _world(tmp_path)
    request = _narration("Hello from the booth")
    audio = generate_narration(world.database, world.work, request, FakeVoiceProvider())
    result = export_delivery(
        world.database,
        world.work,
        "source-1",
        "cand-1",
        include_narration=True,
        narration_artifact_id=audio.artifact_id,
    )
    copied = world.work / result.relative_package / "candidates" / "cand-1" / "narration.wav"
    assert sha256_file(copied) == audio.audio_sha256
    world = _world(tmp_path / "changed")
    audio = generate_narration(world.database, world.work, request, FakeVoiceProvider())
    wav = world.work / "voice" / "audio" / f"{audio.artifact_id}.wav"
    wav.write_bytes(wav.read_bytes() + b"x")
    with pytest.raises(PublishError) as changed:
        export_delivery(
            world.database,
            world.work,
            "source-1",
            "cand-1",
            include_narration=True,
            narration_artifact_id=audio.artifact_id,
        )
    assert changed.value.category == "artifact_changed"
    world = _world(tmp_path / "nc")
    audio = generate_narration(world.database, world.work, request, FakeVoiceProvider())
    sidecar = world.work / "voice" / "audio" / f"{audio.artifact_id}.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["model_license"] = "cc_by_nc"
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PublishError) as blocked:
        export_delivery(
            world.database,
            world.work,
            "source-1",
            "cand-1",
            include_narration=True,
            narration_artifact_id=audio.artifact_id,
        )
    assert blocked.value.category == "rights_blocked"


def test_symlinks_traversal_and_remote_urls_fail(tmp_path: Path) -> None:
    world = _world(tmp_path)
    real = world.video.read_bytes()
    world.video.unlink()
    target = world.work / "linked.mp4"
    target.write_bytes(real)
    world.video.symlink_to(target)
    with pytest.raises(PublishError) as mp4:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert mp4.value.category == "unsafe_path"
    world = _world(tmp_path / "asset")
    payload = world.broll.read_bytes()
    world.broll.unlink()
    outside = world.work / "broll-real.bin"
    outside.write_bytes(payload)
    world.broll.symlink_to(outside)
    with pytest.raises(PublishError) as asset:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert asset.value.category == "unsafe_path"
    world = _world(tmp_path / "dest")
    mirror = tmp_path / "mirror-deliveries"
    mirror.mkdir()
    (world.work / "deliveries").symlink_to(mirror, target_is_directory=True)
    with pytest.raises(PublishError) as destination:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert destination.value.category == "unsafe_path"
    assert _publish_jobs(world.database) == 0
    world = _world(tmp_path / "parent")
    (world.work / "deliveries").mkdir()
    current = world.work / "deliveries" / "current"
    current.symlink_to(mirror, target_is_directory=True)
    with pytest.raises(PublishError) as parent:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert parent.value.category == "unsafe_path"
    world = _world(tmp_path / "remote")
    _set_evidence(world, "lic-source", "https://example.invalid/license")
    with pytest.raises(PublishError) as remote:
        preflight_delivery(world.database, world.work, "source-1", "cand-1", probe=False)
    assert remote.value.category == "rights_blocked"
    world = _world(tmp_path / "outside")
    _set_evidence(world, "lic-source", "file:///tmp/clipforge-outside-license.txt")
    with pytest.raises(PublishError) as escaped:
        preflight_delivery(world.database, world.work, "source-1", "cand-1", probe=False)
    assert escaped.value.category == "unsafe_path"
    world = _world(tmp_path / "slash")
    _set_evidence(world, "lic-broll", "licenses\\owned.txt")
    with pytest.raises(PublishError) as slash:
        preflight_delivery(world.database, world.work, "source-1", "cand-1", probe=False)
    assert slash.value.category == "unsafe_path"
    world = _world(tmp_path / "dot")
    _set_evidence(world, "lic-broll", "../outside.txt")
    with pytest.raises(PublishError) as traversal:
        preflight_delivery(world.database, world.work, "source-1", "cand-1", probe=False)
    assert traversal.value.category == "unsafe_path"


def test_absolute_metadata_corruption_and_recovery(tmp_path: Path) -> None:
    world = _world(tmp_path)
    _retitle(world, "/home/ada/secret")
    with pytest.raises(PublishError) as absolute:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert absolute.value.category == "unsafe_path"
    assert not (world.work / "deliveries" / "current" / "source-1.json").exists()
    world = _world(tmp_path / "ok")
    first = export_delivery(world.database, world.work, "source-1", "cand-1")
    video = world.work / first.relative_package / "candidates" / "cand-1" / "video.mp4"
    video.write_bytes(video.read_bytes() + b"x")
    with pytest.raises(PublishError):
        verify_delivery(world.database, world.work, "source-1", first.delivery_id)
    again = export_delivery(world.database, world.work, "source-1", "cand-1")
    assert again.status == "succeeded"
    assert again.delivery_id != first.delivery_id
    assert (world.work / "deliveries" / first.delivery_id).is_dir()

    def interrupt() -> None:
        raise RuntimeError("staging interrupted")

    with pytest.raises(PublishError, match="interrupted"):
        export_delivery(world.database, world.work, "source-1", "cand-1", force=True, copy_hook=interrupt)
    sidecar = (world.work / "deliveries" / "current" / "source-1.json").read_text(encoding="utf-8")
    assert again.delivery_id in sidecar

    def cancel() -> None:
        raise PublishError("delivery export was cancelled", category="cancelled")

    with pytest.raises(PublishError, match="cancelled"):
        export_delivery(world.database, world.work, "source-1", "cand-1", force=True, copy_hook=cancel)
    with world.database.connect() as connection:
        cancelled = connection.execute(
            "SELECT status FROM jobs WHERE kind = 'publish_export' AND status = 'cancelled'"
        ).fetchone()
    assert cancelled is not None
    assert again.delivery_id in (world.work / "deliveries" / "current" / "source-1.json").read_text(
        encoding="utf-8"
    )


def test_sidecar_and_database_failure_restore_the_previous_package(tmp_path: Path) -> None:
    world = _world(tmp_path)
    first = export_delivery(world.database, world.work, "source-1", "cand-1")
    previous = (world.work / "deliveries" / "current" / "source-1.json").read_bytes()

    def fail() -> None:
        raise RuntimeError("sidecar failed")

    with pytest.raises(PublishError, match="previous"):
        export_delivery(world.database, world.work, "source-1", "cand-1", force=True, sidecar_hook=fail)
    assert (world.work / "deliveries" / "current" / "source-1.json").read_bytes() == previous
    assert (world.work / "deliveries" / first.delivery_id / "manifest.json").is_file()
    with pytest.raises(PublishError, match="previous"):
        export_delivery(world.database, world.work, "source-1", "cand-1", force=True, commit_hook=fail)
    assert (world.work / "deliveries" / "current" / "source-1.json").read_bytes() == previous
    fresh = _world(tmp_path / "first")
    with pytest.raises(PublishError):
        export_delivery(fresh.database, fresh.work, "source-1", "cand-1", sidecar_hook=fail)
    assert not (fresh.work / "deliveries" / "current" / "source-1.json").exists()


def test_stale_recovery_does_not_promote(tmp_path: Path) -> None:
    world = _world(tmp_path)
    first = export_delivery(world.database, world.work, "source-1", "cand-1")
    moment = datetime.now(UTC) - timedelta(hours=2)
    job = JobRecord(
        job_id="job-stale",
        project_id="project-1",
        kind="publish_export",
        status=JobStatus.RUNNING,
        created_at=moment,
        updated_at=moment,
        payload={
            "source_asset_id": "source-1",
            "source_sha256": "ab" * 32,
            "candidate_id": "cand-1",
            "delivery_id": "stale-delivery",
            "destination": "local",
        },
    )
    with world.database.transaction() as connection:
        insert_job(connection, job)
    partial = world.work / "deliveries" / ".partial-stale-delivery"
    partial.mkdir(parents=True)
    (partial / "video.mp4").write_bytes(b"partial")
    text = recover_delivery(world.database, world.work, "source-1", "stale-delivery")
    assert "job-stale" in text
    with world.database.connect() as connection:
        stored = get_job(connection, "job-stale")
    assert stored.status is JobStatus.FAILED
    assert stored.error_message is not None
    assert "not marked succeeded" in stored.error_message
    assert not partial.exists()
    assert (world.work / "deliveries" / first.delivery_id / "manifest.json").is_file()


def test_resume_refuses_success_and_retries_failure(tmp_path: Path) -> None:
    world = _world(tmp_path)
    first = export_delivery(world.database, world.work, "source-1", "cand-1")
    with pytest.raises(PublishError, match="verified success"):
        resume_delivery(world.database, world.work, "source-1", first.delivery_id)

    def cancel() -> None:
        raise PublishError("delivery export was cancelled", category="cancelled")

    with pytest.raises(PublishError):
        export_delivery(world.database, world.work, "source-1", "cand-1", force=True, copy_hook=cancel)
    with world.database.connect() as connection:
        row = connection.execute(
            "SELECT payload_json FROM jobs WHERE kind = 'publish_export' AND status = 'cancelled'"
        ).fetchone()
    assert row is not None
    delivery_id = json.loads(row[0])["delivery_id"]
    resumed = resume_delivery(world.database, world.work, "source-1", delivery_id)
    assert resumed.status == "succeeded"
    assert resumed.delivery_id != delivery_id
    assert resumed.delivery_id != first.delivery_id


def test_verify_list_and_show_are_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(tmp_path)
    result = export_delivery(world.database, world.work, "source-1", "cand-1")
    before_db = world.database.path.read_bytes()
    before_video = (world.work / result.relative_package / "candidates" / "cand-1" / "video.mp4").read_bytes()

    def forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("read-only command opened a write transaction")

    monkeypatch.setattr(world.database, "transaction", forbid)
    assert "PASS delivery" in verify_delivery(world.database, world.work, "source-1", result.delivery_id)
    assert result.delivery_id in list_deliveries(world.database, world.work, "source-1")
    shown = show_delivery(world.database, world.work, "source-1", result.delivery_id)
    assert "://" not in shown
    plan = plan_delivery(world.database, world.work, "source-1", "cand-1")
    assert "local-delivery-v1" not in plan or "profile_fingerprint" in plan
    monkeypatch.undo()
    assert world.database.path.read_bytes() == before_db
    assert (
        world.work / result.relative_package / "candidates" / "cand-1" / "video.mp4"
    ).read_bytes() == before_video


def test_external_destination_is_rejected(tmp_path: Path) -> None:
    world = _world(tmp_path)
    with pytest.raises(PublishError, match=EXTERNAL_PUBLISHING) as exc:
        export_delivery(world.database, world.work, "source-1", "cand-1", destination="tiktok")
    assert exc.value.category == "unsupported_destination"
    assert _publish_jobs(world.database) == 0
    cli = runner.invoke(
        app,
        [
            "publish",
            "export",
            "source-1",
            "cand-1",
            "--destination",
            "youtube",
            "--db",
            str(world.database.path),
            "--work-dir",
            str(world.work),
        ],
    )
    assert cli.exit_code != 0
    assert EXTERNAL_PUBLISHING in cli.stderr
    doctor = runner.invoke(app, ["publish", "doctor"])
    assert doctor.exit_code == 0
    assert "not_implemented" in doctor.stdout
    assert "ffprobe" in doctor.stdout


def test_cli_export_plan_and_verify(tmp_path: Path) -> None:
    world = _world(tmp_path)
    planned = runner.invoke(
        app,
        [
            "publish",
            "plan",
            "source-1",
            "cand-1",
            "--db",
            str(world.database.path),
            "--work-dir",
            str(world.work),
        ],
    )
    assert planned.exit_code == 0
    assert _publish_jobs(world.database) == 0
    exported = runner.invoke(
        app,
        [
            "publish",
            "export",
            "source-1",
            "cand-1",
            "--db",
            str(world.database.path),
            "--work-dir",
            str(world.work),
        ],
    )
    assert exported.exit_code == 0
    assert "status: succeeded" in exported.stdout
    delivery_id = _field(exported.stdout, "delivery_id")
    verified = runner.invoke(
        app,
        [
            "publish",
            "verify",
            "source-1",
            delivery_id,
            "--db",
            str(world.database.path),
            "--work-dir",
            str(world.work),
        ],
    )
    assert verified.exit_code == 0
    assert verified.stdout.startswith("PASS delivery")
    listed = runner.invoke(
        app,
        ["publish", "list", "source-1", "--db", str(world.database.path), "--work-dir", str(world.work)],
    )
    assert listed.exit_code == 0
    assert delivery_id in listed.stdout


def _field(text: str, name: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{name}:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(name)


def _publish_jobs(database: Database) -> int:
    with database.connect() as connection:
        row = connection.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'publish_export'").fetchone()
    assert row is not None
    return int(row[0])


def _assert_checksums(package: Path) -> None:
    document = PublishPackageDocument.model_validate_json(
        (package / "manifest.json").read_text(encoding="utf-8")
    )
    lines = []
    entries = [("manifest.json", sha256_file(package / "manifest.json"))]
    prefix = f"deliveries/{document.delivery_id}/"
    for item in document.files:
        relative = item.relative_path[len(prefix) :]
        entries.append((relative, sha256_file(package / relative)))
    lines.extend(f"{digest}  {relative}\n" for relative, digest in sorted(entries))
    assert (package / "checksums.sha256").read_text(encoding="utf-8") == "".join(lines)


def _video_bytes() -> tuple[bytes, int]:
    global _VIDEO
    if _VIDEO is None:
        _SEED.parent.mkdir(parents=True, exist_ok=True)
        if not _SEED.is_file():
            synth_video(_SEED.parent, _SEED.name, size="1080x1920", rate="30", duration="1")
        payload = read_ffprobe_json(_SEED, ProcessRunner(), None)
        fmt = payload.get("format")
        raw = fmt.get("duration") if isinstance(fmt, dict) else None
        duration = seconds_text_to_us(raw)
        if duration is None:
            raise RuntimeError("seed video has no duration")
        _VIDEO = (_SEED.read_bytes(), duration)
    return _VIDEO


def _world(tmp_path: Path) -> World:
    video_bytes, duration = _video_bytes()
    tmp_path.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    work.mkdir()
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    workspace = SourceWorkspace(work, "project-1", "source-1")
    workspace.ensure()
    source_path = work / "projects" / "project-1" / "sources" / "source-1" / "original.bin"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes("source-bytes-café".encode())
    evidence = workspace.metadata_file("license.txt")
    evidence.write_text("owned by the project\n", encoding="utf-8")
    evidence_uri = evidence.resolve().as_uri()
    broll = workspace.advanced_asset_file("broll-1")
    sfx = workspace.advanced_asset_file("sfx-1")
    broll.parent.mkdir(parents=True, exist_ok=True)
    sfx.parent.mkdir(parents=True, exist_ok=True)
    broll.write_bytes(b"broll-bytes")
    sfx.write_bytes(b"sfx-bytes")
    _catalog(workspace, work, evidence_uri, broll, sfx)
    candidate = workspace.candidate_run_dir("cand-set") / "manifest.json"
    visual = workspace.metadata_file("visual.json")
    hero = workspace.hero_run_dir("hero-set-1") / "manifest.json"
    rough = workspace.preview_run_dir("preview-set") / "manifest.json"
    alignment = workspace.hero_alignment_file("cand-1")
    hero_plan = workspace.hero_plan_file("cand-1")
    for path, payload in (
        (candidate, {"candidates": [{"candidate_id": "cand-1"}]}),
        (visual, {"visual_analysis_id": "art-visual"}),
        (hero, {"hero_set_id": "hero-set-1"}),
        (rough, {"preview_set_id": "preview-set"}),
        (alignment, {"alignment_id": "align-1", "candidate_id": "cand-1"}),
        (hero_plan, {"hero_plan_id": "hero-plan-1"}),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    hashes = {path: sha256_file(path) for path in (candidate, visual, hero, rough, alignment, hero_plan)}
    video = workspace.advanced_run_dir("set-1") / "candidates" / "cand-1" / "advanced.mp4"
    workspace.prepare_advanced_file(video)
    video.write_bytes(video_bytes)
    video_sha = sha256_file(video)
    profile = AdvancedHeroProfile(reframing=ReframingStrategy(strategy_id="contain"))
    fingerprint = profile.fingerprint()
    config_sha = hashlib.sha256(b"contain").hexdigest()
    advanced_input = hashlib.sha256(b"advanced-input").hexdigest()
    review_digest = hashlib.sha256(b"review").hexdigest()
    plan_path = workspace.advanced_plan_file("cand-1")
    workspace.prepare_advanced_file(plan_path)
    plan = _plan(
        profile_fingerprint=fingerprint,
        source_sha=sha256_file(source_path),
        candidate_sha=hashes[candidate],
        visual_sha=hashes[visual],
        hero_sha=hashes[hero],
        rough_sha=hashes[rough],
        alignment_sha=hashes[alignment],
        hero_plan_sha=hashes[hero_plan],
        config_sha=config_sha,
        review_digest=review_digest,
        workspace=workspace,
    )
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
    plan_sha = sha256_file(plan_path)
    manifest = workspace.advanced_run_dir("set-1") / "manifest.json"
    document = _advanced_document(
        profile=profile,
        fingerprint=fingerprint,
        source_sha=sha256_file(source_path),
        candidate_sha=hashes[candidate],
        visual_sha=hashes[visual],
        hero_sha=hashes[hero],
        rough_sha=hashes[rough],
        alignment_sha=hashes[alignment],
        hero_plan_sha=hashes[hero_plan],
        plan_sha=plan_sha,
        config_sha=config_sha,
        advanced_input=advanced_input,
        review_digest=review_digest,
        video_sha=video_sha,
        video_size=video.stat().st_size,
        duration_us=duration,
    )
    manifest.write_text(document.model_dump_json(), encoding="utf-8")
    manifest_sha = sha256_file(manifest)
    record = AdvancedHeroCacheRecord(
        project_id="project-1",
        source_asset_id="source-1",
        advanced_set_id="set-1",
        job_id="job-advanced",
        source_sha256=sha256_file(source_path),
        candidate_set_artifact_id="art-cand",
        candidate_set_sha256=hashes[candidate],
        rough_preview_artifact_id="art-preview",
        rough_manifest_sha256=hashes[rough],
        hero_artifact_id="art-hero",
        hero_set_id="hero-set-1",
        hero_manifest_sha256=hashes[hero],
        visual_analysis_id="art-visual",
        visual_analysis_sha256=hashes[visual],
        profile_fingerprint=fingerprint,
        reframing_strategy="contain",
        reframing_config_sha256=config_sha,
        advanced_input_sha256=advanced_input,
        manifest_sha256=manifest_sha,
        manifest_size_bytes=manifest.stat().st_size,
        rendered_count=1,
        validation_status="passed",
        created_at=stamp(),
    )
    workspace.advanced_sidecar().write_text(record.model_dump_json(), encoding="utf-8")
    now = datetime.now(UTC)
    source_sha = sha256_file(source_path)
    stat = source_path.stat()
    project = Project(project_id="project-1", name="Delivery", created_at=now, provenance=provenance())
    source = SourceAsset(
        source_asset_id="source-1",
        project_id="project-1",
        uri=source_path.resolve().as_uri(),
        license_record_id="lic-source",
        provenance=provenance(["source-1"]),
    )
    manifest_row = SourceIngestManifest(
        source_asset_id="source-1",
        project_id="project-1",
        content_sha256=source_sha,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        original_filename=source_path.name,
        transcription_eligible=False,
        video_stream_index=0,
        audio_stream_index=None,
        canonical_duration_us=2_000_000,
        video_origin_us=0,
        ingested_at=now,
        probe=_probe(),
    )
    qa_path = workspace.qa_run_dir("qa-set-1") / "manifest.json"
    workspace.prepare_qa_file(qa_path)
    qa = _qa_document(manifest_sha)
    qa_path.write_text(qa.model_dump_json(), encoding="utf-8")
    qa_sha = sha256_file(qa_path)
    qa_record = QACacheRecord(
        project_id="project-1",
        source_asset_id="source-1",
        qa_set_id="qa-set-1",
        artifact_id="art-qa",
        target_artifact_id="art-advanced",
        target_artifact_kind=KIND_ADVANCED,
        target_manifest_sha256=manifest_sha,
        profile_id="advanced-hero-v1",
        profile_sha256=fingerprint,
        manifest_sha256=qa_sha,
        manifest_size_bytes=qa_path.stat().st_size,
        status=QAStatus.PASS,
        created_at=stamp(),
    )
    workspace.qa_sidecar().write_text(qa_record.model_dump_json(), encoding="utf-8")
    with database.transaction() as connection:
        insert_project(connection, project)
        insert_asset_license_record(
            connection, license_record("source-1", "lic-source", evidence_uri=evidence_uri)
        )
        insert_asset_license_record(
            connection, license_record("broll-1", "lic-broll", evidence_uri=evidence_uri)
        )
        insert_asset_license_record(connection, license_record("sfx-1", "lic-sfx", evidence_uri=evidence_uri))
        insert_source_asset(connection, source)
        insert_source_manifest(connection, manifest_row)
        insert_job(connection, _job("job-evidence", "media_prepare", source_sha))
        insert_job(connection, _job("job-advanced", JOB_ADVANCED, source_sha))
        insert_job(connection, _job("job-qa", "qa_run", source_sha))
        _store(connection, "art-cand", "job-evidence", "candidate_set_json", candidate)
        _store(connection, "art-visual", "job-evidence", "visual_analysis_json", visual)
        _store(connection, "art-hero", "job-evidence", "hero_draft_set_json", hero)
        _store(connection, "art-preview", "job-evidence", "rough_preview_set_json", rough)
        _store(connection, "art-plan", "job-evidence", "advanced_hero_plan_json", plan_path)
        _store(connection, "art-advanced", "job-advanced", KIND_ADVANCED, manifest)
        _store(connection, "art-qa", "job-qa", KIND_QA, qa_path)
        insert_review(connection, _review("approved"))
        insert_review(connection, _candidate_review())
    from clipforge.review.final_gate import capture_final_decision

    capture_final_decision(
        database,
        work,
        "source-1",
        "cand-1",
        decision="approved",
        reviewer_id="ada",
        notes="final",
    )
    return World(database, work, workspace, video, source_path, broll, sfx, manifest, duration, manifest_sha)


def _catalog(workspace: SourceWorkspace, work: Path, evidence_uri: str, broll: Path, sfx: Path) -> None:
    del evidence_uri
    assets = []
    for path, asset_id, kind in ((broll, "broll-1", "graphic"), (sfx, "sfx-1", "audio")):
        reference = AssetReference(
            asset_id=asset_id,
            project_id="project-1",
            uri=path.resolve().as_uri(),
            kind=kind,  # type: ignore[arg-type]
            license_record_id="lic-broll" if asset_id == "broll-1" else "lic-sfx",
            provenance=provenance(["source-1"]),
        )
        body = reference.model_dump(mode="json")
        body["relative_path"] = path.resolve().relative_to(work.resolve()).as_posix()
        body["file_sha256"] = sha256_file(path)
        assets.append(body)
    workspace.advanced_asset_catalog().write_text(json.dumps({"assets": assets}), encoding="utf-8")


def _plan(**kwargs: object) -> AdvancedHeroPlanDocument:
    workspace = kwargs["workspace"]
    assert isinstance(workspace, SourceWorkspace)
    interval = OutputInterval(output_start_us=0, output_end_us=400_000)
    bindings = []
    for entry in load_catalog(workspace):
        license_id = entry.reference.license_record_id
        record = license_record(entry.reference.asset_id, license_id, evidence_uri="file:///unused")
        bindings.append(binding_for(entry, record))
    source_sha = str(kwargs["source_sha"])
    return AdvancedHeroPlanDocument(
        plan_id="plan-1",
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="cand-1",
        source_sha256=source_sha,
        candidate_set_artifact_id="art-cand",
        candidate_set_sha256=str(kwargs["candidate_sha"]),
        rough_preview_artifact_id="art-preview",
        rough_manifest_sha256=str(kwargs["rough_sha"]),
        hero_artifact_id="art-hero",
        hero_set_id="hero-set-1",
        hero_manifest_sha256=str(kwargs["hero_sha"]),
        hero_review_id="review-hero",
        hero_review_digest=str(kwargs["review_digest"]),
        alignment_id="align-1",
        alignment_sha256=str(kwargs["alignment_sha"]),
        hero_plan_id="hero-plan-1",
        hero_plan_sha256=str(kwargs["hero_plan_sha"]),
        visual_analysis_id="art-visual",
        visual_analysis_sha256=str(kwargs["visual_sha"]),
        time_map_sha256=hashlib.sha256(b"time-map").hexdigest(),
        profile_fingerprint=str(kwargs["profile_fingerprint"]),
        reframing_strategy="contain",
        reframing_config_sha256=str(kwargs["config_sha"]),
        typography=[
            TypographyEvent(
                event_id="type-1",
                interval=interval,
                purpose=MotionPurpose.KEY_PHRASE,
                component_id="label",
                text="Café 説明",
                x=120,
                y=120,
                font_size=48,
            )
        ],
        broll=[BrollEvent(event_id="broll-event", interval=interval, asset_id="broll-1", broll_source_in_us=0)],
        sfx=[AudioMixEvent(event_id="sfx-event", interval=interval, asset_id="sfx-1", gain_db=0)],
        assets=bindings,
        qa_requirements=["technical"],
        provenance=provenance(["source-1"]),
    )


def _advanced_document(**kwargs: object) -> AdvancedHeroDraftSetDocument:
    profile = kwargs["profile"]
    assert isinstance(profile, AdvancedHeroProfile)
    duration = int(str(kwargs["duration_us"]))
    return AdvancedHeroDraftSetDocument(
        advanced_set_id="set-1",
        project_id="project-1",
        source_asset_id="source-1",
        source_sha256=str(kwargs["source_sha"]),
        candidate_set_artifact_id="art-cand",
        candidate_set_sha256=str(kwargs["candidate_sha"]),
        rough_preview_artifact_id="art-preview",
        rough_manifest_sha256=str(kwargs["rough_sha"]),
        hero_artifact_id="art-hero",
        hero_set_id="hero-set-1",
        hero_manifest_sha256=str(kwargs["hero_sha"]),
        visual_analysis_id="art-visual",
        visual_analysis_sha256=str(kwargs["visual_sha"]),
        profile=profile,
        profile_fingerprint=str(kwargs["fingerprint"]),
        reframing_strategy="contain",
        reframing_config_sha256=str(kwargs["config_sha"]),
        advanced_input_sha256=str(kwargs["advanced_input"]),
        drafts=[
            AdvancedHeroDraftOutput(
                candidate_id="cand-1",
                rank=1,
                hero_review_id="review-hero",
                hero_review_digest=str(kwargs["review_digest"]),
                alignment_id="align-1",
                alignment_sha256=str(kwargs["alignment_sha"]),
                hero_plan_id="hero-plan-1",
                hero_plan_sha256=str(kwargs["hero_plan_sha"]),
                advanced_plan_sha256=str(kwargs["plan_sha"]),
                render_input_sha256=hashlib.sha256(b"render-input").hexdigest(),
                preview_relative_path="candidates/cand-1/advanced.mp4",
                preview_sha256=str(kwargs["video_sha"]),
                preview_size_bytes=int(str(kwargs["video_size"])),
                output_duration_us=duration,
                detected_video_codec="h264",
                detected_pixel_format="yuv420p",
                detected_audio_codec="aac",
                detected_audio_sample_rate=48000,
                detected_duration_us=duration,
                duration_error_us=0,
            )
        ],
        provenance=_lineage("job-advanced", str(kwargs["advanced_input"])),
    )


def _qa_document(manifest_sha: str) -> QASetDocument:
    technical = _result("qa-technical", QAKind.TECHNICAL)
    campaign = _result("qa-campaign", QAKind.CAMPAIGN_COMPLIANCE)
    return QASetDocument(
        qa_set_id="qa-set-1",
        project_id="project-1",
        source_asset_id="source-1",
        target_artifact_id="art-advanced",
        target_artifact_kind=KIND_ADVANCED,
        target_manifest_sha256=manifest_sha,
        profile_id="advanced-hero-v1",
        profile_sha256=hashlib.sha256(b"qa-profile").hexdigest(),
        policies=[PolicyDigest(policy_id="source-rights", sha256=hashlib.sha256(b"policy").hexdigest())],
        technical=technical,
        campaign=campaign,
        status=QAStatus.PASS,
        provenance=_lineage("job-qa", None, ["art-advanced", "art-plan"]),
    )


def _result(qa_id: str, kind: QAKind) -> QAResult:
    return QAResult(
        qa_id=qa_id,
        project_id="project-1",
        artifact_id="art-advanced",
        kind=kind,
        status=QAStatus.PASS,
        checks=[QACheck(name="bound", status=QAStatus.PASS, evidence="matches the current advanced artifact")],
        provenance=_lineage("job-qa", None, ["art-advanced"]),
    )


def _lineage(job_id: str, inputs: str | None, parents: list[str] | None = None) -> ArtifactProvenance:
    return ArtifactProvenance(
        created_at=stamp(),
        created_by="tester",
        tool="pytest",
        tool_version="0.1.0",
        source_asset_ids=["source-1"],
        parent_artifact_ids=parents or [],
        job_id=job_id,
        inputs_sha256=inputs,
    )


def _job(job_id: str, kind: str, source_sha: str) -> JobRecord:
    now = datetime.now(UTC)
    return JobRecord(
        job_id=job_id,
        project_id="project-1",
        kind=kind,
        status=JobStatus.SUCCEEDED,
        created_at=now,
        updated_at=now,
        payload={"source_asset_id": "source-1", "source_sha256": source_sha},
    )


def _store(connection: object, artifact_id: str, job_id: str, kind: str, path: Path) -> None:
    insert_artifact(
        connection,  # type: ignore[arg-type]
        artifact_id=artifact_id,
        project_id="project-1",
        job_id=job_id,
        source_asset_id="source-1",
        kind=kind,
        uri=path.resolve().as_uri(),
        provenance=_lineage(job_id, None),
    )


def _candidate_review() -> ReviewDecision:
    return ReviewDecision(
        review_id="review-candidate-current",
        project_id="project-1",
        artifact_id="art-preview",
        candidate_id="cand-1",
        subject_kind="candidate",
        decision="approved",
        reviewer_id="ada",
        created_at=stamp(),
        notes="kept",
        automated=False,
    )


def _review(decision: str) -> ReviewDecision:
    return ReviewDecision(
        review_id="review-hero",
        project_id="project-1",
        artifact_id="art-advanced",
        candidate_id="cand-1",
        subject_kind="hero",
        decision=decision,  # type: ignore[arg-type]
        reviewer_id="ada",
        created_at=stamp(),
        notes="kept",
        automated=False,
    )


def _set_decision(world: World, decision: str) -> None:
    with world.database.transaction() as connection:
        connection.execute("UPDATE reviews SET decision = ? WHERE review_id = 'review-hero'", (decision,))


def _set_rights(world: World, license_id: str, status: str) -> None:
    with world.database.transaction() as connection:
        connection.execute(
            "UPDATE asset_license_records SET status = ? WHERE license_record_id = ?",
            (status, license_id),
        )


def _set_evidence(world: World, license_id: str, uri: str) -> None:
    with world.database.transaction() as connection:
        connection.execute(
            "UPDATE asset_license_records SET evidence_uri = ? WHERE license_record_id = ?",
            (uri, license_id),
        )


def _insert_artifact(world: World, artifact_id: str, path: Path) -> None:
    with world.database.transaction() as connection:
        _store(connection, artifact_id, "job-evidence", "note_json", path)


def _rewrite_qa(world: World, *, status: str = "pass", target: str = "art-advanced") -> None:
    path = world.workspace.qa_run_dir("qa-set-1") / "manifest.json"
    document = QASetDocument.model_validate_json(path.read_text(encoding="utf-8"))
    qa_status = QAStatus.FAIL if status == "fail" else QAStatus.PASS
    technical = document.technical.model_copy(
        update={
            "artifact_id": target,
            "status": qa_status,
            "checks": [QACheck(name="bound", status=qa_status, evidence="qa evidence")],
        }
    )
    campaign = document.campaign.model_copy(update={"artifact_id": target})
    if target != "art-advanced":
        _insert_artifact(world, target, world.manifest)
    rewritten = document.model_copy(
        update={
            "status": QAStatus.FAIL if status == "fail" else document.status,
            "technical": technical,
            "campaign": campaign,
            "target_artifact_id": target,
            "provenance": _lineage("job-qa", None, [target, "art-plan"]),
        }
    )
    path.write_text(rewritten.model_dump_json(), encoding="utf-8")
    record = QACacheRecord.model_validate_json(world.workspace.qa_sidecar().read_text(encoding="utf-8"))
    updated = record.model_copy(
        update={
            "manifest_sha256": sha256_file(path),
            "manifest_size_bytes": path.stat().st_size,
            "status": rewritten.status,
            "target_artifact_id": rewritten.target_artifact_id,
            "target_manifest_sha256": rewritten.target_manifest_sha256,
        }
    )
    world.workspace.qa_sidecar().write_text(updated.model_dump_json(), encoding="utf-8")


def _retitle(world: World, text: str) -> None:
    path = world.workspace.advanced_plan_file("cand-1")
    plan = AdvancedHeroPlanDocument.model_validate_json(path.read_text(encoding="utf-8"))
    event = plan.typography[0].model_copy(update={"text": text})
    rewritten = plan.model_copy(update={"typography": [event]})
    path.write_text(rewritten.model_dump_json(), encoding="utf-8")
    digest = sha256_file(path)
    manifest = AdvancedHeroDraftSetDocument.model_validate_json(world.manifest.read_text(encoding="utf-8"))
    draft = manifest.drafts[0].model_copy(update={"advanced_plan_sha256": digest})
    manifest = manifest.model_copy(update={"drafts": [draft]})
    world.manifest.write_text(manifest.model_dump_json(), encoding="utf-8")
    record = AdvancedHeroCacheRecord.model_validate_json(
        world.workspace.advanced_sidecar().read_text(encoding="utf-8")
    )
    record = record.model_copy(
        update={
            "manifest_sha256": sha256_file(world.manifest),
            "manifest_size_bytes": world.manifest.stat().st_size,
        }
    )
    world.workspace.advanced_sidecar().write_text(record.model_dump_json(), encoding="utf-8")
    qa_path = world.workspace.qa_run_dir("qa-set-1") / "manifest.json"
    qa = QASetDocument.model_validate_json(qa_path.read_text(encoding="utf-8"))
    qa = qa.model_copy(update={"target_manifest_sha256": record.manifest_sha256})
    qa_path.write_text(qa.model_dump_json(), encoding="utf-8")
    qa_record = QACacheRecord.model_validate_json(world.workspace.qa_sidecar().read_text(encoding="utf-8"))
    qa_record = qa_record.model_copy(
        update={
            "target_manifest_sha256": record.manifest_sha256,
            "manifest_sha256": sha256_file(qa_path),
            "manifest_size_bytes": qa_path.stat().st_size,
        }
    )
    world.workspace.qa_sidecar().write_text(qa_record.model_dump_json(), encoding="utf-8")
