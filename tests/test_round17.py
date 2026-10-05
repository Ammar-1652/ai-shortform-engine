"""Platform boundary and real-source reporting. Uploads stay off unless opted in."""

from __future__ import annotations

import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.benchmark.service import readiness_report, run_benchmark
from clipforge.platform.publisher import DryRunPublisher, FakePublisher
from clipforge.platform.service import (
    cancel_attempt,
    dry_run_attempt,
    recover_attempt,
    show_attempt,
    status_attempt,
    submit_attempt,
)
from clipforge.publish.errors import PublishError
from clipforge.publish.service import export_delivery
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.publish import PublishTarget
from clipforge.storage import insert_review
from tests.helpers import stamp
from tests.test_round15 import _chain
from tests.test_round16 import _store, _world

_SHA = "ab" * 32


def _target(delivery_id: str, manifest: str) -> PublishTarget:
    return PublishTarget(
        platform="fake",
        account_label="desk",
        destination_id="channel-1",
        title="Cafe note",
        description="A local package.",
        tags=["cafe"],
        campaign_id="campaign-1",
        privacy="public",
        delivery_id=delivery_id,
        manifest_sha256=manifest,
    )


def _reject(**updates: object) -> None:
    payload = _target("delivery-1", _SHA).model_dump()
    payload.update(updates)
    PublishTarget.model_validate(payload)


def test_target_rejects_unsafe_text() -> None:
    with pytest.raises(ValidationError):
        _reject(title="<script>alert(1)</script>")
    with pytest.raises(ValidationError):
        _reject(description="bearer secret")
    with pytest.raises(ValidationError):
        _reject(account_label="  ")
    with pytest.raises(ValidationError):
        _reject(destination_id="../etc")
    with pytest.raises(ValidationError):
        _reject(description="https://example.invalid/a.mp4")


def test_fake_and_dry_run_open_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("publisher opened a socket")

    monkeypatch.setattr(socket, "socket", explode)
    request_target = _target("delivery-1", _SHA)
    del request_target
    publisher = FakePublisher()
    dry = DryRunPublisher()
    assert publisher.capabilities()["network"] is False
    assert "not_configured" in publisher.doctor()
    assert dry.calls == 0


@pytest.mark.benchmark
def test_dry_run_and_idempotent_submit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(tmp_path)
    exported = export_delivery(world.database, world.work, "source-1", "cand-1")
    video = world.work / exported.relative_package / "candidates" / "cand-1" / "video.mp4"
    before = video.read_bytes()
    target = _target(exported.delivery_id, exported.manifest_sha256)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("dry-run opened a socket")

    monkeypatch.setattr(socket, "socket", explode)
    dry = dry_run_attempt(world.database, world.work, "source-1", "cand-1", target, publisher=DryRunPublisher())
    assert dry.state == "dry_run_passed"
    monkeypatch.undo()
    publisher = FakePublisher()
    first = submit_attempt(world.database, world.work, "source-1", "cand-1", target, publisher=publisher)
    second = submit_attempt(world.database, world.work, "source-1", "cand-1", target, publisher=publisher)
    assert first.state == "published"
    assert first.receipt is not None
    assert second.attempt_id == first.attempt_id
    assert publisher.calls == 1
    assert video.read_bytes() == before
    text = (world.work / "platform" / first.attempt_id / "attempt.json").read_text(encoding="utf-8")
    assert "bearer " not in text.lower()
    with world.database.connect() as connection:
        stored = "\n".join(str(row) for row in connection.execute("SELECT payload_json FROM jobs").fetchall())
    assert "bearer " not in stored.lower()
    assert "token=" not in stored.lower()


@pytest.mark.benchmark
def test_provider_failures_keep_the_local_package(tmp_path: Path) -> None:
    world = _world(tmp_path)
    exported = export_delivery(world.database, world.work, "source-1", "cand-1")
    video = world.work / exported.relative_package / "candidates" / "cand-1" / "video.mp4"
    before = video.read_bytes()
    target = _target(exported.delivery_id, exported.manifest_sha256)
    timed = submit_attempt(
        world.database, world.work, "source-1", "cand-1", target, publisher=FakePublisher(mode="timeout")
    )
    assert timed.state == "unknown"
    rejected = submit_attempt(
        world.database,
        world.work,
        "source-1",
        "cand-1",
        target,
        publisher=FakePublisher(mode="reject"),
        force=True,
    )
    assert rejected.state == "failed"
    malformed = submit_attempt(
        world.database,
        world.work,
        "source-1",
        "cand-1",
        target,
        publisher=FakePublisher(mode="malformed"),
        force=True,
    )
    assert malformed.state == "failed"
    secret = submit_attempt(
        world.database,
        world.work,
        "source-1",
        "cand-1",
        target,
        publisher=FakePublisher(mode="secret"),
        force=True,
    )
    assert secret.state == "failed"
    body = (world.work / "platform" / secret.attempt_id / "attempt.json").read_text(encoding="utf-8")
    assert "bearer" not in body.lower()
    assert video.read_bytes() == before
    status = status_attempt(world.database, world.work, "source-1", timed.attempt_id, publisher=FakePublisher())
    assert "unknown" in status
    assert "published" not in status.split("external platform:")[1].split("\n", 1)[0]


@pytest.mark.benchmark
def test_cancel_recover_and_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(tmp_path)
    exported = export_delivery(world.database, world.work, "source-1", "cand-1")
    target = _target(exported.delivery_id, exported.manifest_sha256)
    published = submit_attempt(
        world.database, world.work, "source-1", "cand-1", target, publisher=FakePublisher(mode="cancel")
    )
    assert published.state == "cancelled"
    held = dry_run_attempt(
        world.database, world.work, "source-1", "cand-1", target, publisher=DryRunPublisher()
    )
    path = world.work / "platform" / held.attempt_id / "attempt.json"
    path.write_text(path.read_text(encoding="utf-8").replace("dry_run_passed", "uploading"), encoding="utf-8")
    assert (
        recover_attempt(
            world.database,
            world.work,
            "source-1",
            held.attempt_id,
            now=datetime.now(UTC) + timedelta(hours=2),
        )
        == held.attempt_id
    )
    shown = show_attempt(world.database, world.work, "source-1", held.attempt_id)
    assert "unknown" in shown
    before = world.database.path.read_bytes()

    def forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("read-only command wrote")

    monkeypatch.setattr(world.database, "transaction", forbid)
    status_attempt(world.database, world.work, "source-1", held.attempt_id)
    show_attempt(world.database, world.work, "source-1", held.attempt_id)
    monkeypatch.undo()
    assert world.database.path.read_bytes() == before
    cancelled = cancel_attempt(world.database, world.work, "source-1", held.attempt_id)
    assert cancelled.state == "cancelled"


@pytest.mark.benchmark
def test_stale_local_package_is_not_uploaded(tmp_path: Path) -> None:
    world = _world(tmp_path)
    exported = export_delivery(world.database, world.work, "source-1", "cand-1")
    video = world.work / exported.relative_package / "candidates" / "cand-1" / "video.mp4"
    video.write_bytes(video.read_bytes() + b"x")
    target = _target(exported.delivery_id, exported.manifest_sha256)
    with pytest.raises(PublishError) as exc:
        dry_run_attempt(world.database, world.work, "source-1", "cand-1", target)
    assert exc.value.category == "artifact_changed"
    with world.database.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'platform_publish'").fetchone()
    assert count is not None and count[0] == 0


def test_real_source_is_not_inferred(tmp_path: Path) -> None:
    database, work = _chain(tmp_path)
    recorded = run_benchmark(database, work, "source-1", fixture_kind="real_authorized")
    observed = {"recorded_evidence", "blocked", "not_run"}
    assert all(stage.execution in observed for stage in recorded.stages)
    assert all(stage.execution != "executed_stage" for stage in recorded.stages)
    report = readiness_report(database, work, recorded.benchmark_run_id)
    assert report.real_source_verified == "unavailable"
    assert report.real_source_reason == "no authorized source supplied"
    assert report.external_upload == "not_configured"
    assert report.platform_adapter == "passed"
    executed = run_benchmark(
        database,
        work,
        "source-1",
        fixture_kind="deterministic_synthetic",
        execute=True,
        force=True,
    )
    assert all(stage.execution != "executed_stage" for stage in executed.stages if stage.stage == "transcript")
    assert "synthetic_only" in executed.warnings
    assert executed.stages
    publish = next(stage for stage in executed.stages if stage.stage == "local_delivery")
    assert publish.execution != "executed_stage"


@pytest.mark.benchmark
def test_verified_delivery_dry_run_does_not_upload(tmp_path: Path) -> None:
    world = _world(tmp_path)
    exported = export_delivery(world.database, world.work, "source-1", "cand-1")
    visual = world.workspace.metadata_file("visual.json")
    with world.database.transaction() as connection:
        for artifact_id, kind in (
            ("art-transcript", "transcript_json"),
            ("art-alignment", "alignment_json"),
            ("art-hero-plan", "hero_plan_json"),
        ):
            _store(connection, artifact_id, "job-evidence", kind, visual)
        insert_review(
            connection,
            ReviewDecision(
                review_id="review-candidate",
                project_id="project-1",
                artifact_id="art-preview",
                candidate_id="cand-1",
                subject_kind="candidate",
                decision="approved",
                reviewer_id="ada",
                created_at=stamp(),
                notes="kept",
                automated=False,
            ),
        )
    run = run_benchmark(
        world.database,
        world.work,
        "source-1",
        fixture_kind="deterministic_synthetic",
        candidate_id="cand-1",
    )
    blocked = [
        (stage.stage, stage.status, stage.error_category) for stage in run.stages if stage.status != "passed"
    ]
    dry = next(stage for stage in run.stages if stage.stage == "platform_dry_run")
    submit = next(stage for stage in run.stages if stage.stage == "platform_submit")
    assert dry.status == "passed", blocked
    assert dry.execution == "executed_stage"
    assert submit.status == "not_run"
    assert submit.execution == "not_run"
    report = readiness_report(world.database, world.work, run.benchmark_run_id)
    assert report.local_delivery == "passed"
    assert report.platform_adapter == "passed"
    assert report.platform_dry_run == "passed"
    assert report.external_upload == "not_configured"
    assert report.overall == "blocked_for_external_publish"
    assert report.real_source_verified == "unavailable"
    assert report.real_source_reason == "no authorized source supplied"
    assert "synthetic_only" in run.warnings
    with world.database.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'platform_publish'").fetchone()
    assert count is not None and int(count[0]) == 1
    again = run_benchmark(
        world.database,
        world.work,
        "source-1",
        fixture_kind="deterministic_synthetic",
        candidate_id="cand-1",
    )
    assert again.benchmark_run_id == run.benchmark_run_id
    with world.database.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'platform_publish'").fetchone()
    assert count is not None and int(count[0]) == 1
    video = world.work / exported.relative_package / "candidates" / "cand-1" / "video.mp4"
    assert video.is_file()
    assert b"bearer " not in video.read_bytes()
