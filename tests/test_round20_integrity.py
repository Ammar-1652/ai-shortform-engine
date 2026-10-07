"""Fail-closed campaign integrity. A green manifest is not evidence by itself."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from clipforge.campaign.production import resume_campaign, run_campaign, verify_campaign_run
from clipforge.campaign.providers import CampaignError
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.storage import insert_job, insert_review
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


@pytest.mark.parametrize(
    "artifact_id",
    [
        "transcript_json-before",
        "visual_analysis_json-before",
        "mine-before",
        "rough_preview_set_json-before",
        "hero_draft_set_json-before",
        "advanced-before",
        "qa-before",
        "publish-before",
    ],
)
def test_failed_producer_blocks_the_run(tmp_path: Path, artifact_id: str) -> None:
    world = _world(tmp_path)
    failed_job = f"failed-{artifact_id}"
    with world.database.transaction() as connection:
        insert_job(
            connection,
            JobRecord(
                job_id=failed_job,
                project_id=world.project_id,
                kind="fixture",
                status=JobStatus.FAILED,
                created_at=stamp(),
                updated_at=stamp(),
                error_message="encoder",
                payload={},
            ),
        )
        connection.execute(
            "UPDATE artifacts SET job_id = ? WHERE artifact_id = ?",
            (failed_job, artifact_id),
        )
    document = run_campaign(world.database, world.work)
    by_id = {item.source_id: item for item in document.sources}
    assert document.status != "succeeded"
    assert by_id["src-before-famous"].status != "succeeded"
    assert by_id["src-american-secret"].status == "succeeded"
    with world.database.connect() as connection:
        row = connection.execute(
            "SELECT status FROM jobs WHERE kind = 'campaign_production' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row[0] != "succeeded"
    again = run_campaign(world.database, world.work)
    assert again.status != "succeeded"


def test_missing_transcription_producer_blocks_the_run(tmp_path: Path) -> None:
    world = _world(tmp_path)
    with world.database.transaction() as connection:
        connection.execute("UPDATE artifacts SET job_id = NULL WHERE artifact_id = 'transcript_json-before'")
    document = run_campaign(world.database, world.work)
    by_id = {item.source_id: item for item in document.sources}
    assert by_id["src-before-famous"].reason_code == "producer_missing"
    assert by_id["src-american-secret"].status == "succeeded"


def test_newer_hero_rejection_invalidates_the_cache(tmp_path: Path) -> None:
    world = _world(tmp_path)
    first = run_campaign(world.database, world.work)
    cached = run_campaign(world.database, world.work)
    assert cached.campaign_run_id == first.campaign_run_id
    _add_hero_review(world, "hero-rejected", "rejected")
    with pytest.raises(CampaignError) as exc:
        verify_campaign_run(world.database, world.work, first.campaign_run_id)
    assert exc.value.code == "review_rejected"
    third = run_campaign(world.database, world.work)
    by_id = {item.source_id: item for item in third.sources}
    assert third.campaign_run_id != first.campaign_run_id
    assert by_id["src-before-famous"].status != "succeeded"
    assert by_id["src-before-famous"].reason_code == "review_rejected"
    assert by_id["src-american-secret"].status == "succeeded"
    stored = _campaign_text(world.work, first.campaign_run_id)
    assert stored["status"] == "blocked"
    assert _campaign_job_status(world, first.campaign_run_id) == "blocked"


def test_newer_changes_requested_and_a_later_approval(tmp_path: Path) -> None:
    world = _world(tmp_path)
    first = run_campaign(world.database, world.work)
    _add_hero_review(world, "hero-changes", "changes_requested")
    with pytest.raises(CampaignError) as exc:
        verify_campaign_run(world.database, world.work, first.campaign_run_id)
    assert exc.value.code == "review_changes_requested"
    blocked = run_campaign(world.database, world.work)
    assert {item.source_id: item.reason_code for item in blocked.sources}["src-before-famous"] == (
        "review_changes_requested"
    )
    _add_hero_review(world, "hero-approved-again", "approved", days=2)
    restored = run_campaign(world.database, world.work)
    assert restored.status == "succeeded"
    assert verify_campaign_run(world.database, world.work, restored.campaign_run_id).startswith("PASS")


def test_hero_review_bindings(tmp_path: Path) -> None:
    world = _world(tmp_path)
    with world.database.transaction() as connection:
        connection.execute("DELETE FROM reviews WHERE review_id = 'hero-review-before'")
    _add_hero_review(world, "hero-other-candidate", "approved", candidate_id="candidate-secret")
    other = run_campaign(world.database, world.work)
    assert {item.source_id: item.reason_code for item in other.sources}["src-before-famous"] == "stale_review"
    with world.database.transaction() as connection:
        connection.execute("DELETE FROM reviews WHERE review_id = 'hero-other-candidate'")
    _add_hero_review(
        world,
        "hero-other-source",
        "approved",
        artifact_id="hero_draft_set_json-secret",
    )
    cross = run_campaign(world.database, world.work, force=True)
    assert {item.source_id: item.reason_code for item in cross.sources}["src-before-famous"] == "cross_source"
    with world.database.transaction() as connection:
        connection.execute("DELETE FROM reviews WHERE review_id = 'hero-other-source'")
    _add_hero_review(world, "hero-wrong-subject", "approved", subject_kind="caption")
    wrong = run_campaign(world.database, world.work, force=True)
    assert {item.source_id: item.reason_code for item in wrong.sources}["src-before-famous"] == "review_subject"
    with world.database.transaction() as connection:
        connection.execute("DELETE FROM reviews WHERE artifact_id = 'hero_draft_set_json-before'")
    missing = run_campaign(world.database, world.work, force=True)
    assert _reason(missing, "src-before-famous") == "review_missing"


def test_alignment_file_failures(tmp_path: Path) -> None:
    world = _world(tmp_path)
    document = run_campaign(world.database, world.work)
    path = _alignment_path(world.work, "before")
    original = path.read_bytes()
    path.unlink()
    with pytest.raises(CampaignError) as verify_missing:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert verify_missing.value.code == "alignment_missing"
    missing = run_campaign(world.database, world.work, force=True)
    assert _reason(missing, "src-before-famous") == "alignment_missing"
    path.write_bytes(b"not-json")
    corrupt = run_campaign(world.database, world.work, force=True)
    assert _reason(corrupt, "src-before-famous") == "alignment_changed"
    path.write_bytes(original)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["whisperx_version"] = "9.9.9"
    path.write_text(json.dumps(payload), encoding="utf-8")
    _retie_alignment_hash(world.work, "before")
    revised = run_campaign(world.database, world.work, force=True)
    assert {item.source_id: item.reason_code for item in revised.sources}["src-before-famous"] == (
        "stale_alignment"
    )
    path.write_bytes(original)
    _retie_alignment_hash(world.work, "before")
    manifest = world.work / "deliveries" / "delivery-before" / "manifest.json"
    package = json.loads(manifest.read_text(encoding="utf-8"))
    package["alignment_id"] = "align-secret"
    manifest.write_text(json.dumps(package), encoding="utf-8")
    _refresh_checksum(manifest)
    wrong = run_campaign(world.database, world.work, force=True)
    assert _reason(wrong, "src-before-famous") == "alignment_changed"


def test_invalidation_keeps_sidecar_and_job_together(tmp_path: Path) -> None:
    world = _world(tmp_path)
    first = run_campaign(world.database, world.work)
    _video(world.work, "before").write_bytes(b"broken")

    def cancel(step: str) -> None:
        if step == "cancellation":
            raise CampaignError("cancelled", code="cancelled")

    cancelled = run_campaign(world.database, world.work, invalidation_hook=cancel)
    assert cancelled.status != "succeeded"
    assert _campaign_text(world.work, first.campaign_run_id)["status"] == "succeeded"
    assert _campaign_job_status(world, first.campaign_run_id) == "succeeded"

    def fail_db(step: str) -> None:
        if step == "database":
            raise RuntimeError("database unavailable")

    failed_db = run_campaign(world.database, world.work, invalidation_hook=fail_db)
    assert failed_db.status != "succeeded"
    assert _campaign_text(world.work, first.campaign_run_id)["status"] == "succeeded"
    assert _campaign_job_status(world, first.campaign_run_id) == "succeeded"

    def fail_sidecar(step: str) -> None:
        if step == "sidecar":
            raise RuntimeError("sidecar unavailable")

    failed_side = run_campaign(world.database, world.work, invalidation_hook=fail_sidecar)
    assert failed_side.status != "succeeded"
    assert _campaign_text(world.work, first.campaign_run_id)["status"] == "succeeded"
    assert _campaign_job_status(world, first.campaign_run_id) == "succeeded"
    applied = run_campaign(world.database, world.work)
    assert _campaign_text(world.work, first.campaign_run_id)["status"] == "blocked"
    assert _campaign_job_status(world, first.campaign_run_id) == "blocked"
    assert applied.status != "succeeded"


def _reason(document: object, source_id: str) -> str:
    sources = document.sources
    return str({item.source_id: item.reason_code for item in sources}[source_id])


def _video(work: Path, slug: str) -> Path:
    return work / "deliveries" / f"delivery-{slug}" / "candidates" / f"candidate-{slug}" / "video.mp4"


def _alignment_path(work: Path, slug: str) -> Path:
    return (
        work
        / "projects"
        / "project-1"
        / "sources"
        / f"asset-{slug}"
        / "hero"
        / "alignments"
        / f"candidate-{slug}"
        / "alignment.json"
    )


def _retie_alignment_hash(work: Path, slug: str) -> None:
    import hashlib

    path = _alignment_path(work, slug)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = work / "deliveries" / f"delivery-{slug}" / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["alignment_sha256"] = digest
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_checksum(manifest)


def _add_hero_review(
    world: object,
    review_id: str,
    decision: str,
    *,
    candidate_id: str = "candidate-before",
    artifact_id: str = "hero_draft_set_json-before",
    subject_kind: str = "hero",
    days: int = 1,
) -> None:
    database = world.database
    with database.transaction() as connection:
        insert_review(
            connection,
            ReviewDecision(
                review_id=review_id,
                project_id="project-1",
                artifact_id=artifact_id,
                candidate_id=candidate_id,
                subject_kind=subject_kind,  # type: ignore[arg-type]
                decision=decision,  # type: ignore[arg-type]
                reviewer_id="reviewer",
                created_at=stamp() + timedelta(days=days),
                notes="",
            ),
        )


def _campaign_text(work: Path, campaign_run_id: str) -> dict[str, object]:
    path = work / "campaigns" / "runs" / campaign_run_id / "manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _campaign_job_status(world: object, campaign_run_id: str) -> str:
    database = world.database
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT status, payload_json FROM jobs WHERE kind = 'campaign_production'"
        ).fetchall()
    for status, payload_json in rows:
        payload = json.loads(payload_json)
        if payload.get("campaign_run_id") == campaign_run_id:
            return str(status)
    raise AssertionError(campaign_run_id)


def _set_review(world: object, review_id: str, column: str, value: str) -> None:
    if column not in {"candidate_id", "artifact_id", "subject_kind", "decision", "project_id"}:
        raise AssertionError(column)
    database = world.database
    with database.transaction() as connection:
        connection.execute(f"UPDATE reviews SET {column} = ? WHERE review_id = ?", (value, review_id))
