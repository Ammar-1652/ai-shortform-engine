"""Row access for the durable tables. Corrupt JSON is an error, not a skipped row."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, TypeVar

from pydantic import ValidationError

from clipforge.errors import StorageError
from clipforge.schemas.governance import AssetLicenseRecord, ReviewDecision
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


def insert_asset_license_record(connection: sqlite3.Connection, record: AssetLicenseRecord) -> None:
    data = record.model_dump(mode="json")
    _insert(
        connection,
        """
        INSERT INTO asset_license_records (
            license_record_id, asset_id, schema_version, status, license_name, evidence_uri,
            notes, recorded_at, recorded_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["license_record_id"],
            data["asset_id"],
            data["schema_version"],
            data["status"],
            data["license_name"],
            data["evidence_uri"],
            data["notes"],
            data["recorded_at"],
            data["recorded_by"],
        ),
        f"asset license record {record.license_record_id}",
    )


def get_asset_license_record(connection: sqlite3.Connection, license_record_id: str) -> AssetLicenseRecord:
    row = connection.execute(
        "SELECT * FROM asset_license_records WHERE license_record_id = ?",
        (license_record_id,),
    ).fetchone()
    if row is None:
        raise StorageError(
            f"no asset license record with id {license_record_id}. "
            "Insert the rights record before storing a source that cites it."
        )
    return _license_from_row(row)


def list_asset_license_records(
    connection: sqlite3.Connection, asset_id: str | None = None
) -> list[AssetLicenseRecord]:
    if asset_id is None:
        rows = connection.execute("SELECT * FROM asset_license_records ORDER BY license_record_id").fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM asset_license_records WHERE asset_id = ? ORDER BY license_record_id",
            (asset_id,),
        ).fetchall()
    return [_license_from_row(row) for row in rows]


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
    """Store an artifact pointer. The file at ``uri`` is not opened or created.

    When ``job_id`` is set, ``provenance.job_id`` is required and must be the same id.
    When ``source_asset_id`` is set, that id must be listed in ``provenance.source_asset_ids``.
    """
    if not kind.strip() or not uri.strip():
        raise StorageError("artifact kind and uri must be non-empty. The row was not written.")
    if source_asset_id is None and not provenance.source_asset_ids:
        raise StorageError(f"artifact {artifact_id} has no source asset. Refusing to store an unlinked file.")
    if source_asset_id is not None and source_asset_id not in provenance.source_asset_ids:
        raise StorageError(
            f"artifact {artifact_id} source_asset_id is {source_asset_id} but "
            f"provenance.source_asset_ids is {list(provenance.source_asset_ids)}. "
            "Refusing to store contradictory lineage."
        )
    if (job_id or None) != (provenance.job_id or None):
        raise StorageError(
            f"artifact {artifact_id} job_id is {job_id!r} but provenance.job_id is {provenance.job_id!r}. "
            "When an artifact names a producing job, provenance.job_id must be that same id. "
            "The row was not written."
        )
    if source_asset_id is not None:
        _reject_cross_project(
            connection,
            child_label="artifact",
            child_id=artifact_id,
            child_project=project_id,
            parent_table="source_assets",
            parent_id_column="source_asset_id",
            parent_id=source_asset_id,
            parent_label="source asset",
        )
    if job_id is not None:
        _reject_cross_project(
            connection,
            child_label="artifact",
            child_id=artifact_id,
            child_project=project_id,
            parent_table="jobs",
            parent_id_column="job_id",
            parent_id=job_id,
            parent_label="job",
        )
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
    if review.artifact_id is not None:
        _reject_cross_project(
            connection,
            child_label="review",
            child_id=review.review_id,
            child_project=review.project_id,
            parent_table="artifacts",
            parent_id_column="artifact_id",
            parent_id=review.artifact_id,
            parent_label="artifact",
        )
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


def _reject_cross_project(
    connection: sqlite3.Connection,
    *,
    child_label: str,
    child_id: str,
    child_project: str,
    parent_table: str,
    parent_id_column: str,
    parent_id: str,
    parent_label: str,
) -> None:
    """Raise when a parent row exists and belongs to a different project.

    A missing parent is left to the foreign key so this function does not invent a second
    existence check. ``parent_table`` and ``parent_id_column`` are fixed by the caller.
    """
    if parent_table not in {"source_assets", "jobs", "artifacts"}:
        raise StorageError(f"refusing to check an unknown parent table {parent_table}")
    if parent_id_column not in {"source_asset_id", "job_id", "artifact_id"}:
        raise StorageError(f"refusing to check an unknown parent column {parent_id_column}")
    row = connection.execute(
        f"SELECT project_id FROM {parent_table} WHERE {parent_id_column} = ?",
        (parent_id,),
    ).fetchone()
    if row is None:
        return
    parent_project = str(row["project_id"])
    if parent_project != child_project:
        raise StorageError(
            f"{child_label} {child_id} is in project {child_project} but {parent_label} {parent_id} "
            f"belongs to project {parent_project}. A child record cannot point across projects. "
            "The row was not written. Use the same project_id on both sides."
        )


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
            f"could not store {label}. The id may already exist, or a parent project, job, "
            "source asset, artifact, or rights record is missing or belongs to a different asset. "
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


_ModelT = TypeVar("_ModelT", Project, SourceAsset, JobRecord, ReviewDecision, AssetLicenseRecord)


def _validate(model: type[_ModelT], payload: dict[str, Any], label: str) -> _ModelT:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise StorageError(
            f"{label} is stored in a shape this version of clipforge cannot read: {exc}"
        ) from exc


def _license_from_row(row: sqlite3.Row) -> AssetLicenseRecord:
    label = f"asset license record {row['license_record_id']}"
    return _validate(
        AssetLicenseRecord,
        {
            "schema_version": row["schema_version"],
            "license_record_id": row["license_record_id"],
            "asset_id": row["asset_id"],
            "status": row["status"],
            "license_name": row["license_name"],
            "evidence_uri": row["evidence_uri"],
            "notes": row["notes"],
            "recorded_at": row["recorded_at"],
            "recorded_by": row["recorded_by"],
        },
        label,
    )


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
