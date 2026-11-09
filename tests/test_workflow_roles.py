"""Role-boundary contracts for the operator-driven workflow."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.qa import HumanPlaybackReview
from clipforge.schemas.roles import WorkflowRolePolicy
from clipforge.storage import Database, insert_project, insert_review, list_reviews
from tests.helpers import stamp
from tests.test_storage import _project


def _review(*, subject_kind: str, role: str) -> ReviewDecision:
    return ReviewDecision(
        review_id="review-role-1",
        project_id="project-1",
        artifact_id="artifact-1" if subject_kind == "final" else None,
        candidate_id=None if subject_kind == "final" else "candidate-1",
        subject_kind=subject_kind,  # type: ignore[arg-type]
        decision="approved",
        reviewer_id="codex" if role == "codex_operator" else "reviewer",
        reviewer_role=role,  # type: ignore[arg-type]
        created_at=stamp(),
        notes="source-grounded decision",
    )


def test_codex_can_record_editorial_decisions_but_not_final_approval() -> None:
    assert _review(subject_kind="candidate", role="codex_operator").reviewer_role == "codex_operator"
    assert _review(subject_kind="hero", role="codex_operator").reviewer_role == "codex_operator"
    with pytest.raises(ValidationError, match="final approval"):
        _review(subject_kind="final", role="codex_operator")


def test_role_policy_has_one_operator_one_enforcer_and_human_final() -> None:
    policy = WorkflowRolePolicy()
    assert policy.editorial_operator == "codex_operator"
    assert policy.deterministic_enforcer == "system_enforcer"
    assert policy.final_reviewer == "human_reviewer"
    assert policy.final_playback_required is True


def test_review_role_survives_sqlite_migration_and_round_trip(tmp_path: Path) -> None:
    database = Database(tmp_path / "roles.sqlite3")
    assert database.initialize() == 7
    with database.transaction() as connection:
        insert_project(connection, _project())
        insert_review(connection, _review(subject_kind="candidate", role="codex_operator"))
    with database.connect() as connection:
        stored = list_reviews(connection, "project-1")
    assert stored[0].reviewer_role == "codex_operator"


def test_human_playback_review_cannot_claim_codex_role() -> None:
    payload = {
        "project_id": "project-1",
        "source_asset_id": "source-1",
        "candidate_id": "candidate-1",
        "advanced_artifact_id": "artifact-1",
        "advanced_manifest_sha256": "a" * 64,
        "advanced_plan_sha256": "b" * 64,
        "source_sha256": "c" * 64,
        "video_sha256": "d" * 64,
        "watch": {
            "reviewer": "codex",
            "watched_with_audio": True,
            "watched_muted": True,
            "observations": ["observed"],
            "decision": "accepted_for_final_review",
            "reviewed_at": datetime.now(UTC),
            "player": "local-player",
        },
        "automated": False,
        "reviewer_role": "codex_operator",
    }
    with pytest.raises(ValidationError, match="reviewer_role"):
        HumanPlaybackReview.model_validate(payload)
