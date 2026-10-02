"""Regression tests for the Round 1.1 review findings."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.errors import ComplianceGateError, StorageError
from clipforge.schemas.editorial import (
    CandidateClip,
    CandidateEvidence,
    CandidateStatus,
    EditPlan,
    EvidenceKind,
)
from clipforge.schemas.governance import (
    ComplianceResult,
    ComplianceStatus,
    ReviewDecision,
    require_rights_cleared,
)
from clipforge.schemas.media import FaceObservation, Scene, SourceAsset
from clipforge.schemas.project import Project
from clipforge.schemas.time import SourceTimeRange, TimeMapDocument, digest_time_map
from clipforge.storage import (
    Database,
    get_asset_license_record,
    insert_artifact,
    insert_asset_license_record,
    insert_project,
    insert_review,
    insert_source_asset,
    list_source_assets,
)
from clipforge.storage.db import _execute_script, _prepare
from clipforge.storage.migrations import INITIAL_SQL
from tests.helpers import license_record, provenance, stamp


def _empty_map() -> TimeMapDocument:
    return TimeMapDocument(time_map_id="map-empty", segments=[])


def _candidate(status: CandidateStatus) -> CandidateClip:
    return CandidateClip(
        candidate_id="cand-1",
        project_id="project-1",
        source_asset_id="asset-1",
        status=status,
        time_map=_empty_map(),
        evidence=[CandidateEvidence(evidence_id="ev-1", kind=EvidenceKind.TRANSCRIPT, detail="hook")],
        compliance=[
            ComplianceResult(
                result_id="result-1",
                rule_id="rule-1",
                status=ComplianceStatus.PASS,
                evidence="not the point of this test",
            )
        ],
        provenance=provenance(["asset-1"]),
    )


@pytest.mark.parametrize("status", list(CandidateStatus))
def test_candidate_rejects_a_zero_duration_time_map(status: CandidateStatus) -> None:
    with pytest.raises(ValidationError, match="not a clip"):
        _candidate(status)


def test_edit_plan_rejects_a_zero_duration_time_map() -> None:
    empty = _empty_map()
    with pytest.raises(ValidationError, match="not an edit"):
        EditPlan(
            edit_plan_id="plan-1",
            project_id="project-1",
            candidate_id="cand-1",
            stage="rough",
            time_map=empty,
            time_map_sha256=digest_time_map(empty),
            provenance=provenance(["asset-1"]),
        )


def test_scene_provenance_must_name_the_same_source() -> None:
    with pytest.raises(ValidationError, match="asset-a"):
        Scene(
            scene_id="scene-1",
            source_asset_id="asset-a",
            time_range=SourceTimeRange(start_us=0, end_us=1_000),
            provenance=provenance(["asset-b"]),
        )


def test_face_provenance_must_name_the_same_source_and_not_a_speaker() -> None:
    with pytest.raises(ValidationError, match="asset-a"):
        FaceObservation(
            observation_id="face-1",
            source_asset_id="asset-a",
            time_range=SourceTimeRange(start_us=0, end_us=1_000),
            confidence=0.4,
            provenance=provenance(["asset-b"]),
        )
    face = FaceObservation(
        observation_id="face-1",
        source_asset_id="asset-a",
        time_range=SourceTimeRange(start_us=0, end_us=1_000),
        confidence=0.4,
        provenance=provenance(["asset-a"]),
    )
    assert face.speaker_attribution == "unknown"


def test_review_subject_kinds_require_the_primary_id() -> None:
    with pytest.raises(ValidationError, match="candidate_id"):
        ReviewDecision(
            review_id="review-1",
            project_id="project-1",
            artifact_id="artifact-1",
            subject_kind="candidate",
            decision="rejected",
            reviewer_id="ada",
            created_at=stamp(),
        )
    with pytest.raises(ValidationError, match="candidate_id"):
        ReviewDecision(
            review_id="review-1",
            project_id="project-1",
            artifact_id="artifact-1",
            subject_kind="hero",
            decision="approved",
            reviewer_id="ada",
            created_at=stamp(),
        )
    ReviewDecision(
        review_id="review-1",
        project_id="project-1",
        candidate_id="cand-1",
        artifact_id="artifact-1",
        subject_kind="hero",
        decision="approved",
        reviewer_id="ada",
        created_at=stamp(),
    )
    for kind in ("caption", "framing", "final"):
        with pytest.raises(ValidationError, match="artifact_id"):
            ReviewDecision(
                review_id="review-1",
                project_id="project-1",
                candidate_id="cand-1",
                subject_kind=kind,  # type: ignore[arg-type]
                decision="rejected",
                reviewer_id="ada",
                created_at=stamp(),
            )
    ReviewDecision(
        review_id="review-1",
        project_id="project-1",
        artifact_id="artifact-1",
        subject_kind="final",
        decision="rejected",
        reviewer_id="ada",
        created_at=stamp(),
    )


def _make_v1(path: Path) -> None:
    connection = sqlite3.connect(path)
    _prepare(connection)
    connection.execute("BEGIN IMMEDIATE")
    _execute_script(connection, INITIAL_SQL)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (1, 'initial', ?)",
        (stamp().isoformat(),),
    )
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()


def _insert_v1_project(path: Path) -> None:
    payload = provenance().model_dump(mode="json")
    connection = sqlite3.connect(path)
    connection.execute(
        """
        INSERT INTO projects (
            project_id, name, schema_version, profile_id, created_at, provenance_json, metadata_json
        ) VALUES ('project-1', 'Legacy', '1.0.0', NULL, ?, ?, '{}')
        """,
        (stamp().isoformat(), json.dumps(payload)),
    )
    connection.commit()
    connection.close()


def _insert_v1_source(path: Path, source_id: str, license_id: str) -> None:
    payload = provenance([source_id]).model_dump(mode="json")
    connection = sqlite3.connect(path)
    connection.execute(
        """
        INSERT INTO source_assets (
            source_asset_id, project_id, uri, schema_version, license_record_id,
            provenance_json, created_at
        ) VALUES (?, 'project-1', ?, '1.0.0', ?, ?, ?)
        """,
        (source_id, f"file:///{source_id}.mp4", license_id, json.dumps(payload), stamp().isoformat()),
    )
    connection.commit()
    connection.close()


def test_version_1_source_gains_a_blocked_legacy_rights_row(tmp_path: Path) -> None:
    path = tmp_path / "v1.sqlite3"
    _make_v1(path)
    _insert_v1_project(path)
    _insert_v1_source(path, "asset-1", "lic-legacy")
    assert "asset_license_records" not in INITIAL_SQL

    database = Database(path)
    assert database.initialize() == 3
    with database.connect() as connection:
        record = get_asset_license_record(connection, "lic-legacy")
        assert record.status.value == "unknown"
        assert record.asset_id == "asset-1"
        assert record.schema_version == "1.0.0"
        assert record.recorded_by == "clipforge-migration-2"
        assert "not verified" in record.notes
        assert list_source_assets(connection, "project-1")[0].license_record_id == "lic-legacy"
    with pytest.raises(ComplianceGateError, match="unknown"):
        require_rights_cleared(record)


def test_shared_legacy_license_id_stops_migration_without_deleting_rows(tmp_path: Path) -> None:
    path = tmp_path / "v1.sqlite3"
    _make_v1(path)
    _insert_v1_project(path)
    _insert_v1_source(path, "asset-1", "lic-shared")
    _insert_v1_source(path, "asset-2", "lic-shared")
    with pytest.raises(StorageError, match="more than one source"):
        Database(path).initialize()
    connection = sqlite3.connect(path)
    version = connection.execute("PRAGMA user_version").fetchone()
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    sources = connection.execute("SELECT COUNT(*) FROM source_assets").fetchone()
    connection.close()
    assert version is not None and version[0] == 1
    assert "asset_license_records" not in tables
    assert sources is not None and sources[0] == 2


def test_source_cannot_cite_a_missing_or_foreign_license(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        insert_project(
            connection,
            Project(
                project_id="project-1",
                name="Foundation",
                created_at=stamp(),
                provenance=provenance(),
            ),
        )
        insert_asset_license_record(connection, license_record(asset_id="asset-b", license_record_id="lic-b"))
    with pytest.raises(StorageError, match="rights"), database.transaction() as connection:
        insert_source_asset(
            connection,
            SourceAsset(
                source_asset_id="asset-a",
                project_id="project-1",
                uri="file:///a.mp4",
                license_record_id="lic-missing",
                provenance=provenance(["asset-a"]),
            ),
        )
    with pytest.raises(StorageError, match="rights"), database.transaction() as connection:
        insert_source_asset(
            connection,
            SourceAsset(
                source_asset_id="asset-a",
                project_id="project-1",
                uri="file:///a.mp4",
                license_record_id="lic-b",
                provenance=provenance(["asset-a"]),
            ),
        )


def test_artifact_lineage_and_review_foreign_keys(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        insert_project(
            connection,
            Project(
                project_id="project-1",
                name="Foundation",
                created_at=stamp(),
                provenance=provenance(),
            ),
        )
        insert_asset_license_record(connection, license_record())
        insert_source_asset(
            connection,
            SourceAsset(
                source_asset_id="asset-1",
                project_id="project-1",
                uri="file:///a.mp4",
                license_record_id="lic-1",
                provenance=provenance(["asset-1"]),
            ),
        )
    with pytest.raises(StorageError, match="contradictory lineage"), database.transaction() as connection:
        insert_artifact(
            connection,
            artifact_id="artifact-bad",
            project_id="project-1",
            job_id=None,
            source_asset_id="asset-a",
            kind="proxy",
            uri="file:///proxy.mp4",
            provenance=provenance(["asset-b"]),
        )
    with pytest.raises(StorageError, match="source asset"), database.transaction() as connection:
        insert_artifact(
            connection,
            artifact_id="artifact-missing",
            project_id="project-1",
            job_id=None,
            source_asset_id="asset-missing",
            kind="proxy",
            uri="file:///proxy.mp4",
            provenance=provenance(["asset-missing"]),
        )
    with database.transaction() as connection:
        insert_artifact(
            connection,
            artifact_id="artifact-1",
            project_id="project-1",
            job_id=None,
            source_asset_id="asset-1",
            kind="proxy",
            uri="file:///proxy.mp4",
            provenance=provenance(["asset-1"]),
        )
    with pytest.raises(StorageError, match="artifact"), database.transaction() as connection:
        insert_review(
            connection,
            ReviewDecision(
                review_id="review-1",
                project_id="project-1",
                artifact_id="artifact-missing",
                subject_kind="final",
                decision="rejected",
                reviewer_id="ada",
                created_at=stamp(),
            ),
        )


def test_current_version_missing_table_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    database = Database(path)
    database.initialize()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("DROP TABLE asset_license_records")
    connection.commit()
    connection.close()
    with pytest.raises(StorageError, match="missing tables"):
        database.status()
    with pytest.raises(StorageError, match="missing tables"):
        database.initialize()
    connection = sqlite3.connect(path)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    connection.close()
    assert "asset_license_records" not in tables


def test_health_check_reports_a_foreign_key_violation(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    database = Database(path)
    database.initialize()
    with database.transaction() as connection:
        insert_project(
            connection,
            Project(
                project_id="project-1",
                name="Foundation",
                created_at=stamp(),
                provenance=provenance(),
            ),
        )
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        """
        INSERT INTO reviews (
            review_id, project_id, artifact_id, candidate_id, subject_kind, decision,
            reviewer_id, schema_version, notes, created_at
        ) VALUES (
            'review-x', 'project-1', 'missing-artifact', NULL, 'final', 'rejected',
            'ada', '1.0.0', '', ?
        )
        """,
        (stamp().isoformat(),),
    )
    connection.commit()
    connection.close()
    with pytest.raises(StorageError, match="foreign_key_check"):
        database.health_check()


def test_non_database_file_is_a_storage_error(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("this is not a database", encoding="utf-8")
    with pytest.raises(StorageError, match="not a readable SQLite"):
        Database(path).status()
