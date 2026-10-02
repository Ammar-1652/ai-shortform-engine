"""Row access for the five Round 1 tables. Corrupt JSON is an error, not a skipped row."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, TypeVar

from pydantic import ValidationError

from clipforge.errors import StorageError
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.jobs import JobRecord
from clipforge.schemas.media import SourceAsset
from clipforge.schemas.project import Project
from clipforge.schemas.provenance import ArtifactProvenance


def insert_project(connection: sqlite3.Connection, project: Project) -> None:
    data = project.model_dump(mode="json")
    _insert(
        connection,
        """
        INSERT INTO projects (
            project_id, name, schema_version, profile_id, created_at, provenance_json, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["project_id"],
            data["name"],
            data["schema_version"],
            data["profile_id"],
            data["created_at"],
            _dump(data["provenance"]),
            _dump(data["metadata"]),
        ),
        f"project {project.project_id}",
    )


def list_projects(connection: sqlite3.Connection) -> list[Project]:
    rows = connection.execute("SELECT * FROM projects ORDER BY created_at, project_id").fetchall()
    return [_project_from_row(row) for row in rows]


def get_project(connection: sqlite3.Connection, project_id: str) -> Project:
    row = connection.execute(
        "SELECT * FROM projects WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if row is None:
        raise StorageError(f"no project with id {project_id}. Run `clipforge project list` to see stored ids.")
    return _project_from_row(row)


def insert_source_asset(connection: sqlite3.Connection, asset: SourceAsset) -> None:
    data = asset.model_dump(mode="json")
    _insert(
        connection,
        """
        INSERT INTO source_assets (
            source_asset_id, project_id, uri, schema_version, license_record_id,
            provenance_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["source_asset_id"],
            data["project_id"],
            data["uri"],
            data["schema_version"],
            data["license_record_id"],
            _dump(data["provenance"]),
            data["provenance"]["created_at"],
        ),
        f"source asset {asset.source_asset_id}",
    )


def list_source_assets(connection: sqlite3.Connection, project_id: str) -> list[SourceAsset]:
    rows = connection.execute(
        "SELECT * FROM source_assets WHERE project_id = ? ORDER BY source_asset_id",
        (project_id,),
    ).fetchall()
    return [_source_from_row(row) for row in rows]


def insert_job(connection: sqlite3.Connection, job: JobRecord) -> None:
    data = job.model_dump(mode="json")
    _insert(
        connection,
        """
        INSERT INTO jobs (
            job_id, project_id, kind, status, schema_version, created_at, updated_at,
            error_message, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["job_id"],
            data["project_id"],
            data["kind"],
            data["status"],
            data["schema_version"],
            data["created_at"],
            data["updated_at"],
            data["error_message"],
            _dump(data["payload"]),
        ),
        f"job {job.job_id}",
    )


def list_jobs(connection: sqlite3.Connection, project_id: str) -> list[JobRecord]:
    rows = connection.execute(
        "SELECT * FROM jobs WHERE project_id = ? ORDER BY created_at, job_id",
        (project_id,),
    ).fetchall()
    return [_job_from_row(row) for row in rows]


def insert_artifact(
    connection: sqlite3.Connection,
    *,
    artifact_id: str,
    project_id: str,
    job_id: str | None,
    source_asset_id: str | None,
    kind: str,
    uri: str,
    provenance: ArtifactProvenance,
) -> None:
    """Store an artifact pointer. The file at ``uri`` is not opened or created."""
    if not kind.strip() or not uri.strip():
        raise StorageError("artifact kind and uri must be non-empty. The row was not written.")
    if source_asset_id is None and not provenance.source_asset_ids:
        raise StorageError(f"artifact {artifact_id} has no source asset. Refusing to store an unlinked file.")
    data = provenance.model_dump(mode="json")
    _insert(
        connection,
        """
        INSERT INTO artifacts (
            artifact_id, project_id, job_id, source_asset_id, kind, uri, schema_version,
            provenance_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            project_id,
            job_id,
            source_asset_id,
            kind,
            uri,
            data["schema_version"],
            _dump(data),
            data["created_at"],
        ),
        f"artifact {artifact_id}",
    )


def list_artifact_ids(connection: sqlite3.Connection, project_id: str) -> list[str]:
    rows = connection.execute(
        "SELECT artifact_id FROM artifacts WHERE project_id = ? ORDER BY artifact_id",
        (project_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def insert_review(connection: sqlite3.Connection, review: ReviewDecision) -> None:
    data = review.model_dump(mode="json")
    _insert(
        connection,
        """
        INSERT INTO reviews (
            review_id, project_id, artifact_id, candidate_id, subject_kind, decision,
            reviewer_id, schema_version, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["review_id"],
            data["project_id"],
            data["artifact_id"],
            data["candidate_id"],
            data["subject_kind"],
            data["decision"],
            data["reviewer_id"],
            data["schema_version"],
            data["notes"],
            data["created_at"],
        ),
        f"review {review.review_id}",
    )


def list_reviews(connection: sqlite3.Connection, project_id: str) -> list[ReviewDecision]:
    rows = connection.execute(
        "SELECT * FROM reviews WHERE project_id = ? ORDER BY created_at, review_id",
        (project_id,),
    ).fetchall()
    return [_review_from_row(row) for row in rows]


def _insert(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[Any, ...],
    label: str,
) -> None:
    try:
        connection.execute(sql, parameters)
    except sqlite3.IntegrityError as exc:
        raise StorageError(
            f"could not store {label}. The id may already exist, or a parent project/job is missing. "
            f"SQLite said: {exc}"
        ) from exc
    except sqlite3.Error as exc:
        raise StorageError(f"could not store {label}: {exc}") from exc


def _dump(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _object(text: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageError(f"corrupt JSON in {label}: {exc}. The row was not skipped.") from exc
    if not isinstance(value, dict):
        raise StorageError(f"expected a JSON object in {label}, found {type(value).__name__}")
    return value


_ModelT = TypeVar("_ModelT", Project, SourceAsset, JobRecord, ReviewDecision)


def _validate(model: type[_ModelT], payload: dict[str, Any], label: str) -> _ModelT:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise StorageError(
            f"{label} is stored in a shape this version of clipforge cannot read: {exc}"
        ) from exc


def _project_from_row(row: sqlite3.Row) -> Project:
    label = f"project {row['project_id']}"
    return _validate(
        Project,
        {
            "schema_version": row["schema_version"],
            "project_id": row["project_id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "profile_id": row["profile_id"],
            "provenance": _object(row["provenance_json"], f"{label} provenance"),
            "metadata": _object(row["metadata_json"], f"{label} metadata"),
        },
        label,
    )


def _source_from_row(row: sqlite3.Row) -> SourceAsset:
    label = f"source asset {row['source_asset_id']}"
    provenance = _object(row["provenance_json"], f"{label} provenance")
    return _validate(
        SourceAsset,
        {
            "schema_version": row["schema_version"],
            "source_asset_id": row["source_asset_id"],
            "project_id": row["project_id"],
            "uri": row["uri"],
            "license_record_id": row["license_record_id"],
            "provenance": provenance,
        },
        label,
    )


def _job_from_row(row: sqlite3.Row) -> JobRecord:
    label = f"job {row['job_id']}"
    return _validate(
        JobRecord,
        {
            "schema_version": row["schema_version"],
            "job_id": row["job_id"],
            "project_id": row["project_id"],
            "kind": row["kind"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "error_message": row["error_message"],
            "payload": _object(row["payload_json"], f"{label} payload"),
        },
        label,
    )


def _review_from_row(row: sqlite3.Row) -> ReviewDecision:
    label = f"review {row['review_id']}"
    return _validate(
        ReviewDecision,
        {
            "schema_version": row["schema_version"],
            "review_id": row["review_id"],
            "project_id": row["project_id"],
            "artifact_id": row["artifact_id"],
            "candidate_id": row["candidate_id"],
            "subject_kind": row["subject_kind"],
            "decision": row["decision"],
            "reviewer_id": row["reviewer_id"],
            "created_at": row["created_at"],
            "notes": row["notes"],
            "automated": False,
        },
        label,
    )
