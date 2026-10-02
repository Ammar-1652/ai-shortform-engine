"""SQLite migrations and repositories. Each test uses its own file."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from clipforge.errors import StorageError
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import SourceAsset
from clipforge.schemas.project import Project
from clipforge.storage import (
    Database,
    get_project,
    insert_artifact,
    insert_asset_license_record,
    insert_job,
    insert_project,
    insert_review,
    insert_source_asset,
    list_jobs,
    list_projects,
    list_reviews,
    list_source_assets,
)
from tests.helpers import license_record, provenance, stamp


def _project(project_id: str = "project-1") -> Project:
    return Project(
        project_id=project_id,
        name="Foundation",
        created_at=stamp(),
        provenance=provenance(),
    )


def test_init_is_idempotent_and_health_reports_version(tmp_path: Path) -> None:
    database = Database(tmp_path / "one.sqlite3")
    assert database.initialize() == 3
    assert database.initialize() == 3
    database.health_check()
    status = database.status()
    assert status.schema_version == 3
    assert status.migrations == ("initial", "rights_and_lineage", "project_lineage_integrity")
    assert status.counts["asset_license_records"] == 0
    assert status.counts["projects"] == 0


def test_missing_database_is_an_error(tmp_path: Path) -> None:
    database = Database(tmp_path / "missing.sqlite3")
    with pytest.raises(StorageError, match="db init"):
        database.status()


def test_memory_database_is_rejected() -> None:
    with pytest.raises(StorageError, match="in-memory"):
        Database(Path(":memory:"))


def test_project_round_trip_and_isolation(tmp_path: Path) -> None:
    left = Database(tmp_path / "left.sqlite3")
    right = Database(tmp_path / "right.sqlite3")
    left.initialize()
    right.initialize()
    with left.transaction() as connection:
        insert_project(connection, _project())
    with right.connect() as connection:
        assert list_projects(connection) == []
    with left.connect() as connection:
        assert get_project(connection, "project-1").name == "Foundation"


def test_duplicate_project_and_rollback(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    with pytest.raises(StorageError), database.transaction() as connection:
        insert_project(connection, _project())
        insert_project(connection, _project("project-2"))
        insert_project(connection, _project())
    with database.connect() as connection:
        assert list_projects(connection) == []


def test_related_rows_and_foreign_keys(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    asset = SourceAsset(
        source_asset_id="asset-1",
        project_id="project-1",
        uri="file:///sources/talk.mp4",
        license_record_id="lic-1",
        provenance=provenance(["asset-1"]),
    )
    job = JobRecord(
        job_id="job-1",
        project_id="project-1",
        kind="placeholder",
        status=JobStatus.PENDING,
        created_at=stamp(),
        updated_at=stamp(),
    )
    review = ReviewDecision(
        review_id="review-1",
        project_id="project-1",
        candidate_id="cand-1",
        subject_kind="candidate",
        decision="changes_requested",
        reviewer_id="ada",
        created_at=stamp(),
        notes="watch the cut",
    )
    with database.transaction() as connection:
        insert_project(connection, _project())
        insert_asset_license_record(connection, license_record())
        insert_source_asset(connection, asset)
        insert_job(connection, job)
        insert_artifact(
            connection,
            artifact_id="artifact-1",
            project_id="project-1",
            job_id="job-1",
            source_asset_id="asset-1",
            kind="proxy",
            uri="file:///var/proxy.mp4",
            provenance=provenance(["asset-1"], job_id="job-1"),
        )
        insert_review(connection, review)
    with database.connect() as connection:
        assert list_source_assets(connection, "project-1")[0].uri.endswith("talk.mp4")
        assert list_jobs(connection, "project-1")[0].status is JobStatus.PENDING
        assert list_reviews(connection, "project-1")[0].decision == "changes_requested"
    with pytest.raises(StorageError, match="parent"), database.transaction() as connection:
        insert_source_asset(
            connection,
            SourceAsset(
                source_asset_id="asset-2",
                project_id="missing-project",
                uri="file:///nope.mp4",
                license_record_id="lic-1",
                provenance=provenance(["asset-2"]),
            ),
        )


def test_corrupt_json_is_not_skipped(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        insert_project(connection, _project())
        connection.execute(
            "UPDATE projects SET provenance_json = ? WHERE project_id = ?",
            ("{", "project-1"),
        )
    with database.connect() as connection, pytest.raises(StorageError, match="not skipped"):
        list_projects(connection)


def test_check_constraint_rejects_unknown_job_status(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        insert_project(connection, _project())
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, project_id, kind, status, schema_version, created_at, updated_at,
                    error_message, payload_json
                ) VALUES ('job-x', 'project-1', 'ingest', 'shipped', '1.0.0', 't', 't', NULL, '{}')
                """
            )
