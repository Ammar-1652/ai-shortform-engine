"""Project-bound foreign keys and current-schema shape checks."""

from __future__ import annotations

import json
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
    get_asset_license_record,
    insert_artifact,
    insert_asset_license_record,
    insert_job,
    insert_project,
    insert_review,
    insert_source_asset,
)
from clipforge.storage.db import _execute_script, _prepare
from clipforge.storage.migrations import MIGRATIONS
from clipforge.storage.schema_shape import _foreign_key_groups
from tests.helpers import license_record, provenance, stamp


def _project(project_id: str) -> Project:
    return Project(
        project_id=project_id,
        name=project_id,
        created_at=stamp(),
        provenance=provenance(),
    )


def _source(source_id: str, project_id: str, license_id: str) -> SourceAsset:
    return SourceAsset(
        source_asset_id=source_id,
        project_id=project_id,
        uri=f"file:///{source_id}.mp4",
        license_record_id=license_id,
        provenance=provenance([source_id]),
    )


def _job(job_id: str, project_id: str) -> JobRecord:
    return JobRecord(
        job_id=job_id,
        project_id=project_id,
        kind="placeholder",
        status=JobStatus.PENDING,
        created_at=stamp(),
        updated_at=stamp(),
    )


def _apply_through(path: Path, stop_at: int) -> None:
    """Build a database with the real migration SQL, stopping at ``stop_at``."""
    connection = sqlite3.connect(path)
    _prepare(connection)
    connection.execute("BEGIN IMMEDIATE")
    now = stamp().isoformat()
    for migration in MIGRATIONS:
        if migration.version > stop_at:
            break
        if migration.precheck is not None:
            migration.precheck(connection)
        _execute_script(connection, migration.sql)
        connection.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.name, now),
        )
    connection.execute(f"PRAGMA user_version = {stop_at}")
    connection.commit()
    connection.close()


def _insert_project_sql(path: Path, project_id: str) -> None:
    payload = json.dumps(provenance().model_dump(mode="json"))
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        INSERT INTO projects (
            project_id, name, schema_version, profile_id, created_at, provenance_json, metadata_json
        ) VALUES (?, ?, '1.0.0', NULL, ?, ?, '{}')
        """,
        (project_id, project_id, stamp().isoformat(), payload),
    )
    connection.commit()
    connection.close()


def _insert_source_sql(path: Path, source_id: str, project_id: str, license_id: str) -> None:
    payload = json.dumps(provenance([source_id]).model_dump(mode="json"))
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        INSERT INTO asset_license_records (
            license_record_id, asset_id, schema_version, status, license_name, evidence_uri,
            notes, recorded_at, recorded_by
        ) VALUES (?, ?, '1.0.0', 'unknown', NULL, NULL, 'test', ?, 'tester')
        """,
        (license_id, source_id, stamp().isoformat()),
    )
    connection.execute(
        """
        INSERT INTO source_assets (
            source_asset_id, project_id, uri, schema_version, license_record_id,
            provenance_json, created_at
        ) VALUES (?, ?, ?, '1.0.0', ?, ?, ?)
        """,
        (
            source_id,
            project_id,
            f"file:///{source_id}.mp4",
            license_id,
            payload,
            stamp().isoformat(),
        ),
    )
    connection.commit()
    connection.close()


def test_repository_rejects_cross_project_lineage(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    with database.transaction() as connection:
        insert_project(connection, _project("project-a"))
        insert_project(connection, _project("project-b"))
        insert_asset_license_record(connection, license_record(asset_id="source-a", license_record_id="lic-a"))
        insert_asset_license_record(connection, license_record(asset_id="source-b", license_record_id="lic-b"))
        insert_source_asset(connection, _source("source-a", "project-a", "lic-a"))
        insert_source_asset(connection, _source("source-b", "project-b", "lic-b"))
        insert_job(connection, _job("job-a", "project-a"))
        insert_job(connection, _job("job-b", "project-b"))
        insert_artifact(
            connection,
            artifact_id="artifact-b",
            project_id="project-b",
            job_id=None,
            source_asset_id="source-b",
            kind="proxy",
            uri="file:///b.mp4",
            provenance=provenance(["source-b"]),
        )
        insert_artifact(
            connection,
            artifact_id="artifact-null-job",
            project_id="project-a",
            job_id=None,
            source_asset_id="source-a",
            kind="proxy",
            uri="file:///a.mp4",
            provenance=provenance(["source-a"]),
        )
    with (
        pytest.raises(StorageError, match="cannot point across projects"),
        database.transaction() as connection,
    ):
        insert_artifact(
            connection,
            artifact_id="artifact-cross-source",
            project_id="project-a",
            job_id=None,
            source_asset_id="source-b",
            kind="proxy",
            uri="file:///cross.mp4",
            provenance=provenance(["source-b"]),
        )
    with (
        pytest.raises(StorageError, match="cannot point across projects"),
        database.transaction() as connection,
    ):
        insert_artifact(
            connection,
            artifact_id="artifact-cross-job",
            project_id="project-a",
            job_id="job-b",
            source_asset_id="source-a",
            kind="proxy",
            uri="file:///cross-job.mp4",
            provenance=provenance(["source-a"], job_id="job-b"),
        )
    with (
        pytest.raises(StorageError, match="cannot point across projects"),
        database.transaction() as connection,
    ):
        insert_review(
            connection,
            ReviewDecision(
                review_id="review-cross",
                project_id="project-a",
                artifact_id="artifact-b",
                subject_kind="final",
                decision="rejected",
                reviewer_id="ada",
                created_at=stamp(),
            ),
        )
    connection = sqlite3.connect(database.path)
    connection.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO artifacts (
                artifact_id, project_id, job_id, source_asset_id, kind, uri, schema_version,
                provenance_json, created_at
            ) VALUES (
                'raw-cross', 'project-a', NULL, 'source-b', 'proxy', 'file:///raw.mp4', '1.0.0', '{}', ?
            )
            """,
            (stamp().isoformat(),),
        )
    connection.close()


def test_valid_version_2_database_migrates_to_current_schema(tmp_path: Path) -> None:
    path = tmp_path / "v2.sqlite3"
    _apply_through(path, 1)
    _insert_project_sql(path, "project-a")
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    payload = json.dumps(provenance(["source-a"]).model_dump(mode="json"))
    connection.execute(
        """
        INSERT INTO source_assets (
            source_asset_id, project_id, uri, schema_version, license_record_id,
            provenance_json, created_at
        ) VALUES ('source-a', 'project-a', 'file:///source-a.mp4', '1.0.0', 'lic-a', ?, ?)
        """,
        (payload, stamp().isoformat()),
    )
    connection.commit()
    connection.close()
    _apply_through_from_existing(path, start_after=1, stop_at=2)

    _insert_job_artifact_review(path)
    database = Database(path)
    assert database.initialize() == 4
    assert database.initialize() == 4
    database.health_check()
    with database.connect() as connection:
        record = get_asset_license_record(connection, "lic-a")
        assert record.status.value == "unknown"
        assert record.recorded_by == "clipforge-migration-2"
        assert connection.execute(
            "SELECT project_id FROM artifacts WHERE artifact_id = 'artifact-a'"
        ).fetchone()[0] == ("project-a")
        assert connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1
        groups = _foreign_key_groups(connection, "artifacts")
        assert (
            "source_assets",
            (("source_asset_id", "source_asset_id"), ("project_id", "project_id")),
        ) in groups
        assert ("jobs", (("job_id", "job_id"), ("project_id", "project_id"))) in groups
        review_groups = _foreign_key_groups(connection, "reviews")
        assert (
            "artifacts",
            (("artifact_id", "artifact_id"), ("project_id", "project_id")),
        ) in review_groups
        indexes = {
            str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }
    for name in (
        "idx_source_assets_project",
        "idx_jobs_project",
        "idx_artifacts_project",
        "idx_reviews_project",
        "idx_asset_license_records_asset",
    ):
        assert name in indexes


def test_cross_project_version_2_rows_block_migration_3(tmp_path: Path) -> None:
    path = tmp_path / "v2.sqlite3"
    _apply_through(path, 2)
    _insert_project_sql(path, "project-a")
    _insert_project_sql(path, "project-b")
    _insert_source_sql(path, "source-b", "project-b", "lic-b")
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        INSERT INTO artifacts (
            artifact_id, project_id, job_id, source_asset_id, kind, uri, schema_version,
            provenance_json, created_at
        ) VALUES (
            'artifact-cross', 'project-a', NULL, 'source-b', 'proxy', 'file:///cross.mp4', '1.0.0', ?, ?
        )
        """,
        (json.dumps(provenance(["source-b"]).model_dump(mode="json")), stamp().isoformat()),
    )
    connection.commit()
    connection.close()

    with pytest.raises(StorageError, match="parent project project-b"):
        Database(path).initialize()

    connection = sqlite3.connect(path)
    version = connection.execute("PRAGMA user_version").fetchone()
    history = connection.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
    artifact = connection.execute(
        "SELECT project_id, source_asset_id FROM artifacts WHERE artifact_id = 'artifact-cross'"
    ).fetchone()
    tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    connection.close()
    assert version is not None and version[0] == 2
    assert [(int(row[0]), str(row[1])) for row in history] == [(1, "initial"), (2, "rights_and_lineage")]
    assert artifact == ("project-a", "source-b")
    assert "artifacts_new" not in tables
    assert "source_assets_new" not in tables


def test_missing_column_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    database = Database(path)
    database.initialize()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        """
        CREATE TABLE reviews_tampered (
            review_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            artifact_id TEXT,
            candidate_id TEXT,
            subject_kind TEXT NOT NULL,
            decision TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO reviews_tampered (
            review_id, project_id, artifact_id, candidate_id, subject_kind, decision,
            reviewer_id, schema_version, created_at
        )
        SELECT review_id, project_id, artifact_id, candidate_id, subject_kind, decision,
            reviewer_id, schema_version, created_at
        FROM reviews
        """
    )
    connection.execute("DROP TABLE reviews")
    connection.execute("ALTER TABLE reviews_tampered RENAME TO reviews")
    connection.commit()
    connection.close()
    for call in (database.status, database.initialize, database.health_check):
        with pytest.raises(StorageError, match="missing column"):
            call()
    connection = sqlite3.connect(path)
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(reviews)")}
    connection.close()
    assert "notes" not in columns


def test_missing_parent_unique_key_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    database = Database(path)
    database.initialize()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        """
        CREATE TABLE jobs_tampered (
            job_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            kind TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled', 'blocked')
            ),
            schema_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            error_message TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO jobs_tampered
        SELECT job_id, project_id, kind, status, schema_version, created_at, updated_at,
            error_message, payload_json
        FROM jobs
        """
    )
    connection.execute("DROP TABLE jobs")
    connection.execute("ALTER TABLE jobs_tampered RENAME TO jobs")
    connection.commit()
    connection.close()

    for call in (database.status, database.initialize, database.health_check):
        with pytest.raises(StorageError, match="unique/primary key"):
            call()


def test_missing_foreign_key_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    database = Database(path)
    database.initialize()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        """
        CREATE TABLE artifacts_tampered (
            artifact_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            job_id TEXT,
            source_asset_id TEXT,
            kind TEXT NOT NULL,
            uri TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO artifacts_tampered
        SELECT artifact_id, project_id, job_id, source_asset_id, kind, uri, schema_version,
            provenance_json, created_at
        FROM artifacts
        """
    )
    connection.execute("DROP TABLE artifacts")
    connection.execute("ALTER TABLE artifacts_tampered RENAME TO artifacts")
    connection.commit()
    connection.close()
    with pytest.raises(StorageError, match="foreign key"):
        database.status()


def test_incomplete_and_misnamed_migration_history_fail(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    database = Database(path)
    database.initialize()
    connection = sqlite3.connect(path)
    connection.execute("DELETE FROM schema_migrations WHERE version = 2")
    connection.commit()
    connection.close()
    with pytest.raises(StorageError, match="schema_migrations"):
        database.status()

    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (2, 'something_else', ?)",
        (stamp().isoformat(),),
    )
    connection.commit()
    connection.close()
    with pytest.raises(StorageError, match="something_else"):
        database.health_check()


def _apply_through_from_existing(path: Path, start_after: int, stop_at: int) -> None:
    connection = sqlite3.connect(path)
    _prepare(connection)
    connection.execute("BEGIN IMMEDIATE")
    now = stamp().isoformat()
    for migration in MIGRATIONS:
        if migration.version <= start_after or migration.version > stop_at:
            continue
        if migration.precheck is not None:
            migration.precheck(connection)
        _execute_script(connection, migration.sql)
        connection.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.name, now),
        )
    connection.execute(f"PRAGMA user_version = {stop_at}")
    connection.commit()
    connection.close()


def _insert_job_artifact_review(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    created = stamp().isoformat()
    connection.execute(
        """
        INSERT INTO jobs (
            job_id, project_id, kind, status, schema_version, created_at, updated_at,
            error_message, payload_json
        ) VALUES ('job-a', 'project-a', 'placeholder', 'pending', '1.0.0', ?, ?, NULL, '{}')
        """,
        (created, created),
    )
    connection.execute(
        """
        INSERT INTO artifacts (
            artifact_id, project_id, job_id, source_asset_id, kind, uri, schema_version,
            provenance_json, created_at
        ) VALUES ('artifact-a', 'project-a', NULL, 'source-a', 'proxy', 'file:///a.mp4', '1.0.0', ?, ?)
        """,
        (json.dumps(provenance(["source-a"]).model_dump(mode="json")), created),
    )
    connection.execute(
        """
        INSERT INTO reviews (
            review_id, project_id, artifact_id, candidate_id, subject_kind, decision,
            reviewer_id, schema_version, notes, created_at
        ) VALUES (
            'review-a', 'project-a', 'artifact-a', NULL, 'final', 'rejected', 'ada', '1.0.0', 'notes', ?
        )
        """,
        (created,),
    )
    connection.commit()
    connection.close()
