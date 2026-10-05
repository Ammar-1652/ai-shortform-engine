"""Fail-closed campaign integrity. A green manifest is not evidence by itself."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clipforge.campaign.production import resume_campaign, run_campaign, verify_campaign_run
from clipforge.campaign.providers import CampaignError
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.storage import insert_job
from tests.helpers import stamp
from tests.test_round20_campaign import _refresh_checksum, _world

_VIDEO = "deliveries/{delivery}/candidates/{candidate}/video.mp4"


def test_corrupt_delivery_fails_verify_and_is_not_a_cache_hit(tmp_path: Path) -> None:
    world = _world(tmp_path)
    first = run_campaign(world.database, world.work)
    video = _video(world.work, "before")
    video.write_bytes(b"")
    with pytest.raises(CampaignError) as empty:
        verify_campaign_run(world.database, world.work, first.campaign_run_id)
    assert empty.value.code == "zero_byte_video"
    video.write_bytes(b"tampered")
    with pytest.raises(CampaignError) as changed:
        verify_campaign_run(world.database, world.work, first.campaign_run_id)
    assert changed.value.code == "delivery_changed"
    video.write_bytes(b"video-bytes-extra")
    with pytest.raises(CampaignError) as sized:
        verify_campaign_run(world.database, world.work, first.campaign_run_id)
    assert sized.value.code == "delivery_changed"
    video.unlink()
    with pytest.raises(CampaignError) as missing:
        verify_campaign_run(world.database, world.work, first.campaign_run_id)
    assert missing.value.code == "delivery_missing"
    again = run_campaign(world.database, world.work)
    assert again.campaign_run_id != first.campaign_run_id
    by_id = {item.source_id: item for item in again.sources}
    assert by_id["src-before-famous"].status == "blocked"
    assert by_id["src-american-secret"].status == "succeeded"
    stored_path = world.work / "campaigns" / "runs" / first.campaign_run_id / "manifest.json"
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    assert stored["status"] != "succeeded"


def test_checksum_and_package_symlink_fail_closed(tmp_path: Path) -> None:
    world = _world(tmp_path)
    document = run_campaign(world.database, world.work)
    package = world.work / "deliveries" / "delivery-before"
    checksum = package / "checksums.sha256"
    checksum.unlink()
    with pytest.raises(CampaignError) as missing:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert missing.value.code == "checksum_missing"
    checksum.write_text("not-a-checksum\n", encoding="utf-8")
    with pytest.raises(CampaignError) as changed:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert changed.value.code == "checksum_changed"
    _refresh_checksum(package / "manifest.json")
    video = _video(world.work, "before")
    target = video.read_bytes()
    video.unlink()
    other = tmp_path / "elsewhere.mp4"
    other.write_bytes(target)
    video.symlink_to(other)
    with pytest.raises(CampaignError) as linked:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert linked.value.code == "symlink"


def test_symlinked_package_directory_is_rejected(tmp_path: Path) -> None:
    world = _world(tmp_path)
    document = run_campaign(world.database, world.work)
    package = world.work / "deliveries" / "delivery-before"
    outside = tmp_path / "outside-package"
    package.rename(outside)
    package.symlink_to(outside)
    with pytest.raises(CampaignError) as exc:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert exc.value.code == "symlink"


def test_producer_lineage_failures(tmp_path: Path) -> None:
    world = _world(tmp_path)
    document = run_campaign(world.database, world.work)
    with world.database.transaction() as connection:
        connection.execute(
            "UPDATE jobs SET status = 'failed', error_message = 'encoder' WHERE job_id = 'job-before'"
        )
    with pytest.raises(CampaignError) as failed:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert failed.value.code == "producer_failed"
    with world.database.transaction() as connection:
        connection.execute(
            "UPDATE jobs SET status = 'succeeded', error_message = NULL WHERE job_id = 'job-before'"
        )
        connection.execute("UPDATE artifacts SET job_id = NULL WHERE artifact_id = 'publish-before'")
    with pytest.raises(CampaignError) as missing:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert missing.value.code == "producer_missing"


def test_package_identity_is_bound_to_the_source(tmp_path: Path) -> None:
    world = _world(tmp_path)
    document = run_campaign(world.database, world.work)
    manifest = world.work / "deliveries" / "delivery-before" / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["source_asset_id"] = "asset-secret"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_checksum(manifest)
    with pytest.raises(CampaignError) as source:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert source.value.code == "cross_source"
    payload["source_asset_id"] = "asset-before"
    payload["project_id"] = "project-2"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_checksum(manifest)
    with pytest.raises(CampaignError) as project:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert project.value.code == "cross_project"


def test_review_bindings_fail_closed(tmp_path: Path) -> None:
    world = _world(tmp_path)
    document = run_campaign(world.database, world.work)
    _set_review(world, "review-before", "candidate_id", "candidate-secret")
    with pytest.raises(CampaignError) as other_candidate:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert other_candidate.value.code == "review_missing"
    _set_review(world, "review-before", "candidate_id", "candidate-before")
    _set_review(world, "review-before", "artifact_id", "rough_preview_set_json-secret")
    with pytest.raises(CampaignError) as other_source:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert other_source.value.code == "cross_source"
    _set_review(world, "review-before", "artifact_id", "rough_preview_set_json-before")
    _set_review(world, "review-before", "subject_kind", "hero")
    with pytest.raises(CampaignError) as subject:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert subject.value.code == "review_subject"
    _set_review(world, "review-before", "subject_kind", "candidate")
    _set_review(world, "review-before", "decision", "rejected")
    with pytest.raises(CampaignError) as rejected:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert rejected.value.code == "review_rejected"
    _set_review(world, "review-before", "decision", "changes_requested")
    with pytest.raises(CampaignError) as changes:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert changes.value.code == "review_changes_requested"
    _set_review(world, "review-before", "decision", "approved")
    _set_review(world, "hero-review-before", "artifact_id", "qa-before")
    with pytest.raises(CampaignError) as older_hero:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert older_hero.value.code == "stale_review"
    _set_review(world, "hero-review-before", "artifact_id", "hero_draft_set_json-before")
    with world.database.transaction() as connection:
        connection.execute("DELETE FROM reviews WHERE review_id = 'review-before'")
    with pytest.raises(CampaignError) as missing:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert missing.value.code == "review_missing"


def test_resume_does_not_skip_corrupt_evidence(tmp_path: Path) -> None:
    world = _world(tmp_path)
    document = run_campaign(world.database, world.work)
    _video(world.work, "before").write_bytes(b"broken-video")
    resumed = resume_campaign(world.database, world.work, document.campaign_run_id)
    by_id = {item.source_id: item for item in resumed.sources}
    assert resumed.campaign_run_id == document.campaign_run_id
    assert by_id["src-before-famous"].status != "succeeded"
    assert by_id["src-american-secret"].status == "succeeded"
    _video(world.work, "before").write_bytes(b"video-bytes")
    _refresh_checksum(world.work / "deliveries" / "delivery-before" / "manifest.json")
    world.sources["src-before-famous"].qa.write_bytes(b"qa-changed")
    again = resume_campaign(world.database, world.work, document.campaign_run_id)
    assert {item.source_id: item.status for item in again.sources}["src-before-famous"] != "succeeded"


def test_symlink_parents_do_not_escape_the_work_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    world = _world(tmp_path)
    campaigns = world.work / "campaigns"
    campaigns.symlink_to(outside)
    with pytest.raises(CampaignError) as exc:
        run_campaign(world.database, world.work)
    assert exc.value.code == "symlink"
    assert list(outside.rglob("*")) == []
    campaigns.unlink()
    media = world.sources["src-before-famous"].media.parent
    moved = tmp_path / "moved-media"
    media.rename(moved)
    media.symlink_to(moved)
    blocked = run_campaign(world.database, world.work)
    by_id = {item.source_id: item for item in blocked.sources}
    assert by_id["src-before-famous"].reason_code == "symlink"
    assert list(outside.rglob("*")) == []


def test_promotion_failure_leaves_no_orphan_manifest(tmp_path: Path) -> None:
    world = _world(tmp_path)

    def fail(step: str) -> None:
        if step == "database_commit":
            raise CampaignError("commit failed", code="promotion_failed")

    with pytest.raises(CampaignError):
        run_campaign(world.database, world.work, promotion_hook=fail)
    assert list(world.work.glob("campaigns/runs/*/manifest.json")) == []
    with world.database.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'campaign_production'").fetchone()
    assert count is not None
    assert int(count[0]) == 0
    first = run_campaign(world.database, world.work)

    def fail_rename(step: str) -> None:
        if step == "final_rename":
            raise CampaignError("rename failed", code="promotion_failed")

    with pytest.raises(CampaignError):
        run_campaign(world.database, world.work, force=True, promotion_hook=fail_rename)
    stored_path = world.work / "campaigns" / "runs" / first.campaign_run_id / "manifest.json"
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    assert stored["campaign_run_id"] == first.campaign_run_id
    assert stored["status"] == "succeeded"


def test_missing_artifact_row_fails_verification(tmp_path: Path) -> None:
    world = _world(tmp_path)
    document = run_campaign(world.database, world.work)
    with world.database.transaction() as connection:
        connection.execute("DELETE FROM artifacts WHERE artifact_id = 'qa-before'")
    with pytest.raises(CampaignError) as exc:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert exc.value.code == "artifact_missing"


def test_narration_requires_a_succeeded_producer(tmp_path: Path) -> None:
    world = _world(tmp_path)
    document = run_campaign(world.database, world.work)
    with world.database.transaction() as connection:
        insert_job(
            connection,
            JobRecord(
                job_id="job-narration-failed",
                project_id=world.project_id,
                kind="narration",
                status=JobStatus.FAILED,
                created_at=stamp(),
                updated_at=stamp(),
                error_message="provider",
                payload={},
            ),
        )
        connection.execute(
            "UPDATE artifacts SET job_id = 'job-narration-failed' WHERE artifact_id = 'narration-before'"
        )
    with pytest.raises(CampaignError) as exc:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert exc.value.code == "producer_failed"


def _video(work: Path, slug: str) -> Path:
    return work / "deliveries" / f"delivery-{slug}" / "candidates" / f"candidate-{slug}" / "video.mp4"


def _set_review(world: object, review_id: str, column: str, value: str) -> None:
    if column not in {"candidate_id", "artifact_id", "subject_kind", "decision", "project_id"}:
        raise AssertionError(column)
    database = world.database
    with database.transaction() as connection:
        connection.execute(f"UPDATE reviews SET {column} = ? WHERE review_id = ?", (value, review_id))
