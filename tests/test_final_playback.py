"""Human watch can be recorded after rendering without modifying immutable media."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.publish.preflight import preflight_delivery
from clipforge.review.final_gate import (
    FinalReviewError,
    approval_code,
    evidence_for_facts,
    record_final_decision,
)
from clipforge.review.playback import playback_target, validate_playback
from clipforge.schemas.qa import HumanPlaybackReview, HumanWatchRecord
from tests.test_round16 import _world


def _watch(evidence: dict[str, str]) -> HumanPlaybackReview:
    return HumanPlaybackReview(
        **playback_target(evidence).model_dump(),
        watch=HumanWatchRecord(
            reviewer="independent-reviewer",
            watched_with_audio=True,
            watched_muted=True,
            player="local browser player",
            observations=["00:00-00:05: words, picture and speech match; no overlay collisions"],
            decision="accepted_for_final_review",
            reviewed_at=datetime.now(UTC) - timedelta(seconds=1),
        ),
        automated=False,
    )


def test_clean_final_watch_is_append_only_without_rewriting_render(tmp_path: Path) -> None:
    world = _world(tmp_path)
    facts = replace(
        preflight_delivery(world.database, world.work, "source-1", "cand-1", require_final=False),
        style_id="editorial-clean-v1",
    )
    evidence = evidence_for_facts(facts)
    assert {
        "preset_id",
        "pilot_sha256",
        "motion_recipe_ids",
        "motion_catalog_sha256",
        "knowledge_context_id",
        "knowledge_release_id",
        "knowledge_context_sha256",
        "knowledge_decision_trace_id",
        "knowledge_decision_trace_sha256",
    } <= evidence.keys()
    video_before = world.video.read_bytes()
    manifest_before = world.manifest.read_bytes()
    with pytest.raises(FinalReviewError, match="playback record"):
        record_final_decision(
            database=world.database,
            work_root=world.work,
            facts=facts,
            evidence=evidence,
            decision="approved",
            reviewer_id="independent-reviewer",
            notes="",
        )
    review = record_final_decision(
        database=world.database,
        work_root=world.work,
        facts=facts,
        evidence=evidence,
        decision="approved",
        reviewer_id="independent-reviewer",
        notes="reviewed",
        playback=_watch(evidence),
    )
    assert approval_code(world.work, facts, [review], evidence) == "approved"
    sidecar = world.work / "final-reviews" / f"{review.review_id}.json"
    accepted_before = sidecar.read_bytes()
    rejection = record_final_decision(
        database=world.database,
        work_root=world.work,
        facts=facts,
        evidence=evidence,
        decision="changes_requested",
        reviewer_id="independent-reviewer",
        notes="00:02: caption needs another look",
    )
    assert approval_code(world.work, facts, [review, rejection], evidence) == "final_approval_changes_requested"
    assert sidecar.read_bytes() == accepted_before
    assert world.video.read_bytes() == video_before
    assert world.manifest.read_bytes() == manifest_before
    changed = {**evidence, "video_sha256": "f" * 64}
    assert approval_code(world.work, facts, [review], changed) == "stale_final_review"
    payload = json.loads(sidecar.read_text())
    payload["playback"]["watch"]["observations"] = ["altered after approval"]
    sidecar.write_text(json.dumps(payload))
    assert approval_code(world.work, facts, [review], evidence) == "stale_final_review"


@pytest.mark.parametrize("field", ["video_sha256", "source_sha256", "advanced_manifest_sha256"])
def test_playback_for_another_video_or_source_fails(field: str) -> None:
    evidence = {
        "project_id": "project-1",
        "source_asset_id": "source-1",
        "candidate_id": "candidate-1",
        "advanced_artifact_id": "artifact-1",
        "advanced_manifest_sha256": "a" * 64,
        "advanced_plan_sha256": "b" * 64,
        "source_sha256": "c" * 64,
        "video_sha256": "d" * 64,
    }
    review = _watch(evidence)
    with pytest.raises(MediaError, match="stale"):
        validate_playback(
            review.model_copy(update={field: "e" * 64}),
            evidence,
            reviewer=review.watch.reviewer,
            approving=True,
        )
    with pytest.raises(MediaError, match="reviewer"):
        validate_playback(review, evidence, reviewer="someone-else", approving=True)
    with pytest.raises(MediaError, match="not accepted"):
        validate_playback(
            review.model_copy(update={"watch": review.watch.model_copy(update={"decision": "needs_changes"})}),
            evidence,
            reviewer=review.watch.reviewer,
            approving=True,
        )


@pytest.mark.parametrize(
    "watch_change",
    [{"watched_muted": False}, {"watched_with_audio": False}, {"player": " "}, {"observations": [" "]}],
)
def test_incomplete_watch_cannot_enter_clean_final_review(watch_change: dict[str, object]) -> None:
    payload = {
        "project_id": "project-1",
        "source_asset_id": "source-1",
        "candidate_id": "candidate-1",
        "advanced_artifact_id": "artifact-1",
        "advanced_manifest_sha256": "a" * 64,
        "advanced_plan_sha256": "b" * 64,
        "source_sha256": "c" * 64,
        "video_sha256": "d" * 64,
    }
    review = _watch(payload).model_dump(mode="json")
    review["watch"].update(watch_change)
    with pytest.raises(ValidationError):
        HumanPlaybackReview.model_validate(review)
    review["automated"] = True
    with pytest.raises(ValidationError):
        HumanPlaybackReview.model_validate(review)


def test_watch_target_cli_is_read_only_and_does_not_invent_a_watch(tmp_path: Path) -> None:
    world = _world(tmp_path)
    before = world.database.path.read_bytes()
    result = CliRunner().invoke(
        app,
        [
            "final",
            "review",
            "watch-target",
            "source-1",
            "cand-1",
            "--db",
            str(world.database.path),
            "--work-dir",
            str(world.work),
        ],
    )
    assert result.exit_code == 0, result.output
    target = json.loads(result.stdout)
    assert target["video_sha256"]
    assert "watch" not in target
    assert world.database.path.read_bytes() == before


def test_failed_final_sidecar_write_rolls_back_the_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from clipforge.storage import list_reviews

    world = _world(tmp_path)
    facts = preflight_delivery(world.database, world.work, "source-1", "cand-1", require_final=False)
    with world.database.connect() as connection:
        before = list_reviews(connection, facts.project_id)

    def fail_sidecar(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("clipforge.review.final_gate._write_sidecar", fail_sidecar)
    with pytest.raises(OSError, match="disk full"):
        record_final_decision(
            database=world.database,
            work_root=world.work,
            facts=facts,
            evidence=evidence_for_facts(facts),
            decision="changes_requested",
            reviewer_id="reviewer",
            notes="00:01 needs repair",
        )
    with world.database.connect() as connection:
        assert list_reviews(connection, facts.project_id) == before


def test_final_sidecars_cannot_be_overwritten_or_symlinked(tmp_path: Path) -> None:
    from clipforge.review.final_gate import _write_sidecar, evidence_sha256

    evidence = {"artifact": "artifact-1"}
    _write_sidecar(tmp_path, "review-1", evidence, evidence_sha256(evidence))
    original = (tmp_path / "final-reviews/review-1.json").read_bytes()
    with pytest.raises(FileExistsError):
        _write_sidecar(tmp_path, "review-1", {"changed": "value"}, "f" * 64)
    assert (tmp_path / "final-reviews/review-1.json").read_bytes() == original
    outside = tmp_path / "other"
    outside.mkdir()
    (tmp_path / "linked").mkdir()
    (tmp_path / "linked/final-reviews").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FinalReviewError, match="symlink"):
        _write_sidecar(tmp_path / "linked", "review-2", evidence, evidence_sha256(evidence))
    assert not list(outside.iterdir())


def test_campaign_package_reuse_checks_all_supplied_evidence(tmp_path: Path) -> None:
    from clipforge.review.final_gate import package_blocker

    world = _world(tmp_path)
    facts = preflight_delivery(world.database, world.work, "source-1", "cand-1", require_final=False)
    binding = {
        "project_id": facts.project_id,
        "candidate_id": facts.candidate_id,
        "advanced_artifact_id": facts.advanced_artifact_id,
        "qa_set_sha256": facts.qa_set_sha256,
        "source_sha256": facts.source_sha256,
        "delivery_manifest_sha256": facts.delivery_manifest_sha256,
    }
    assert package_blocker(world.database, world.work, **binding) is None
    assert (
        package_blocker(world.database, world.work, **{**binding, "source_sha256": "f" * 64}) == "stale_source"
    )
    assert package_blocker(world.database, world.work, **{**binding, "qa_set_sha256": "f" * 64}) == "stale_qa"


def test_final_verify_exits_nonzero_when_no_approval_is_effective(tmp_path: Path) -> None:
    world = _world(tmp_path)
    with world.database.transaction() as connection:
        connection.execute("DELETE FROM reviews WHERE subject_kind = 'final'")
    result = CliRunner().invoke(
        app,
        [
            "final",
            "review",
            "verify",
            "source-1",
            "cand-1",
            "--db",
            str(world.database.path),
            "--work-dir",
            str(world.work),
        ],
    )
    assert result.exit_code == 1, result.output
    assert "final_approval_required" in result.stdout
