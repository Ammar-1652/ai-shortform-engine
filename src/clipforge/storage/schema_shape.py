"""Semantic checks for a database that claims the current schema version.

This is not a byte-for-byte copy of ``sqlite_master``. It checks migration
history, required columns, required unique/primary keys, and the foreign-key
groups later code relies on.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from clipforge.errors import StorageError
from clipforge.storage.migrations import MIGRATIONS

# Parent table, then (child column, parent column) in foreign_key_list seq order.
ExpectedForeignKey = tuple[str, tuple[tuple[str, str], ...]]
ExpectedUniqueKey = tuple[str, ...]

REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "schema_migrations": frozenset({"version", "name", "applied_at"}),
    "projects": frozenset(
        {
            "project_id",
            "name",
            "schema_version",
            "profile_id",
            "created_at",
            "provenance_json",
            "metadata_json",
        }
    ),
    "source_assets": frozenset(
        {
            "source_asset_id",
            "project_id",
            "uri",
            "schema_version",
            "license_record_id",
            "provenance_json",
            "created_at",
        }
    ),
    "asset_license_records": frozenset(
        {
            "license_record_id",
            "asset_id",
            "schema_version",
            "status",
            "license_name",
            "evidence_uri",
            "notes",
            "recorded_at",
            "recorded_by",
        }
    ),
    "jobs": frozenset(
        {
            "job_id",
            "project_id",
            "kind",
            "status",
            "schema_version",
            "created_at",
            "updated_at",
            "error_message",
            "payload_json",
        }
    ),
    "artifacts": frozenset(
        {
            "artifact_id",
            "project_id",
            "job_id",
            "source_asset_id",
            "kind",
            "uri",
            "schema_version",
            "provenance_json",
            "created_at",
        }
    ),
    "reviews": frozenset(
        {
            "review_id",
            "project_id",
            "artifact_id",
            "candidate_id",
            "subject_kind",
            "decision",
            "reviewer_id",
            "schema_version",
            "notes",
            "created_at",
        }
    ),
    "source_manifests": frozenset(
        {
            "source_asset_id",
            "project_id",
            "content_sha256",
            "size_bytes",
            "mtime_ns",
            "original_filename",
            "storage_mode",
            "transcription_eligible",
            "video_stream_index",
            "audio_stream_index",
            "canonical_duration_us",
            "video_origin_us",
            "ingested_at",
            "probe_json",
        }
    ),
    "editorial_feature_snapshots": frozenset(
        {
            "snapshot_id",
            "project_id",
            "source_asset_id",
            "artifact_id",
            "artifact_sha256",
            "document_json",
            "created_at",
        }
    ),
    "performance_outcomes": frozenset(
        {
            "outcome_id",
            "project_id",
            "source_asset_id",
            "artifact_id",
            "snapshot_id",
            "idempotency_key",
            "observed_at",
            "document_json",
            "created_at",
        }
    ),
    "analytics_imports": frozenset(
        {
            "import_id",
            "project_id",
            "content_sha256",
            "outcome_count",
            "created_at",
            "created_by",
            "profile_id",
            "validation_summary",
            "outcome_ids_json",
        }
    ),
    "editorial_label_sets": frozenset(
        {
            "label_set_id",
            "project_id",
            "source_asset_id",
            "artifact_id",
            "outcome_id",
            "snapshot_id",
            "document_json",
            "created_at",
        }
    ),
}

REQUIRED_FOREIGN_KEYS: dict[str, frozenset[ExpectedForeignKey]] = {
    "source_assets": frozenset(
        {
            ("projects", (("project_id", "project_id"),)),
            (
                "asset_license_records",
                (
                    ("license_record_id", "license_record_id"),
                    ("source_asset_id", "asset_id"),
                ),
            ),
        }
    ),
    "jobs": frozenset({("projects", (("project_id", "project_id"),))}),
    "artifacts": frozenset(
        {
            ("projects", (("project_id", "project_id"),)),
            (
                "source_assets",
                (
                    ("source_asset_id", "source_asset_id"),
                    ("project_id", "project_id"),
                ),
            ),
            (
                "jobs",
                (
                    ("job_id", "job_id"),
                    ("project_id", "project_id"),
                ),
            ),
        }
    ),
    "reviews": frozenset(
        {
            ("projects", (("project_id", "project_id"),)),
            (
                "artifacts",
                (
                    ("artifact_id", "artifact_id"),
                    ("project_id", "project_id"),
                ),
            ),
        }
    ),
    "source_manifests": frozenset(
        {
            (
                "source_assets",
                (
                    ("source_asset_id", "source_asset_id"),
                    ("project_id", "project_id"),
                ),
            ),
        }
    ),
    "editorial_feature_snapshots": frozenset(
        {
            ("projects", (("project_id", "project_id"),)),
            (
                "artifacts",
                (
                    ("artifact_id", "artifact_id"),
                    ("project_id", "project_id"),
                ),
            ),
            (
                "source_assets",
                (
                    ("source_asset_id", "source_asset_id"),
                    ("project_id", "project_id"),
                ),
            ),
        }
    ),
    "performance_outcomes": frozenset(
        {
            ("projects", (("project_id", "project_id"),)),
            (
                "artifacts",
                (
                    ("artifact_id", "artifact_id"),
                    ("project_id", "project_id"),
                ),
            ),
            (
                "source_assets",
                (
                    ("source_asset_id", "source_asset_id"),
                    ("project_id", "project_id"),
                ),
            ),
            ("editorial_feature_snapshots", (("snapshot_id", "snapshot_id"),)),
        }
    ),
    "analytics_imports": frozenset({("projects", (("project_id", "project_id"),))}),
    "editorial_label_sets": frozenset(
        {
            ("projects", (("project_id", "project_id"),)),
            (
                "artifacts",
                (
                    ("artifact_id", "artifact_id"),
                    ("project_id", "project_id"),
                ),
            ),
            (
                "source_assets",
                (
                    ("source_asset_id", "source_asset_id"),
                    ("project_id", "project_id"),
                ),
            ),
            ("performance_outcomes", (("outcome_id", "outcome_id"),)),
            ("editorial_feature_snapshots", (("snapshot_id", "snapshot_id"),)),
        }
    ),
}

REQUIRED_UNIQUE_KEYS: dict[str, frozenset[ExpectedUniqueKey]] = {
    "schema_migrations": frozenset({("version",)}),
    "projects": frozenset({("project_id",)}),
    "source_assets": frozenset(
        {
            ("source_asset_id",),
            ("source_asset_id", "project_id"),
        }
    ),
    "asset_license_records": frozenset(
        {
            ("license_record_id",),
            ("license_record_id", "asset_id"),
        }
    ),
    "jobs": frozenset(
        {
            ("job_id",),
            ("job_id", "project_id"),
        }
    ),
    "artifacts": frozenset(
        {
            ("artifact_id",),
            ("artifact_id", "project_id"),
        }
    ),
    "reviews": frozenset({("review_id",)}),
    "source_manifests": frozenset(
        {
            ("source_asset_id",),
            ("source_asset_id", "project_id"),
            ("project_id", "content_sha256"),
        }
    ),
    "editorial_feature_snapshots": frozenset({("snapshot_id",)}),
    "performance_outcomes": frozenset({("outcome_id",), ("idempotency_key",)}),
    "analytics_imports": frozenset({("import_id",)}),
    "editorial_label_sets": frozenset({("label_set_id",)}),
}

REQUIRED_TABLES = frozenset(REQUIRED_COLUMNS)


def assert_current_schema(connection: sqlite3.Connection, path: Path) -> None:
    """Reject a current-version file whose tables, columns, keys, or history are wrong.

    Does not add columns, recreate tables, or rewrite ``schema_migrations``.
    """
    _assert_tables(connection, path)
    _assert_columns(connection, path)
    _assert_unique_keys(connection, path)
    _assert_foreign_keys(connection, path)
    _assert_migration_history(connection, path)


def _assert_tables(connection: sqlite3.Connection, path: Path) -> None:
    present = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    missing = sorted(REQUIRED_TABLES - present)
    if missing:
        raise StorageError(
            f"{path} reports the current schema version but is missing tables {missing}. "
            "The file was not repaired and the missing tables were not recreated. Restore it from a backup."
        )


def _assert_columns(connection: sqlite3.Connection, path: Path) -> None:
    for table, expected in REQUIRED_COLUMNS.items():
        found = _column_names(connection, table)
        missing = sorted(expected - found)
        if missing:
            raise StorageError(
                f"{path} claims the current schema version but table {table} is missing "
                f"column(s) {missing}. The file was not rewritten and the columns were not added. "
                "Restore it from a backup."
            )


def _assert_unique_keys(connection: sqlite3.Connection, path: Path) -> None:
    for table, expected in REQUIRED_UNIQUE_KEYS.items():
        found = _unique_keys(connection, table)
        missing = sorted(expected - found)
        if missing:
            raise StorageError(
                f"{path} claims the current schema version but table {table} is missing "
                f"required unique/primary key(s) {missing}. Composite foreign keys depend on "
                "their parent keys being unique. The file was not rewritten. Restore it from a backup."
            )


def _assert_foreign_keys(connection: sqlite3.Connection, path: Path) -> None:
    for table, expected in REQUIRED_FOREIGN_KEYS.items():
        found = _foreign_key_groups(connection, table)
        missing = sorted(expected - found, key=repr)
        if missing:
            raise StorageError(
                f"{path} claims the current schema version but table {table} is missing "
                f"foreign key(s) {missing}. The file was not rewritten. Restore it from a backup."
            )


def _assert_migration_history(connection: sqlite3.Connection, path: Path) -> None:
    expected = [(migration.version, migration.name) for migration in MIGRATIONS]
    rows = connection.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
    actual = [(int(row[0]), str(row[1])) for row in rows]
    if actual != expected:
        raise StorageError(
            f"{path} claims the current schema version but schema_migrations is {actual}, "
            f"expected {expected}. The history was not rewritten. Restore the file from a backup."
        )


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _unique_keys(connection: sqlite3.Connection, table: str) -> set[ExpectedUniqueKey]:
    found: set[ExpectedUniqueKey] = set()

    table_info = connection.execute(f"PRAGMA table_info({table})").fetchall()
    primary_key = sorted((int(row[5]), str(row[1])) for row in table_info if int(row[5]) > 0)
    if primary_key:
        found.add(tuple(name for _, name in primary_key))

    for row in connection.execute(f"PRAGMA index_list({table})").fetchall():
        is_unique = bool(row[2])
        is_partial = bool(row[4]) if len(row) > 4 else False
        if not is_unique or is_partial:
            continue
        index_name = str(row[1])
        parts = connection.execute(
            "SELECT name FROM pragma_index_info(?) ORDER BY seqno",
            (index_name,),
        ).fetchall()
        if not parts or any(item[0] is None for item in parts):
            continue
        found.add(tuple(str(item[0]) for item in parts))

    return found


def _foreign_key_groups(connection: sqlite3.Connection, table: str) -> set[ExpectedForeignKey]:
    rows = connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    grouped: dict[int, list[tuple[int, str, str, str]]] = {}
    for row in rows:
        grouped.setdefault(int(row[0]), []).append((int(row[1]), str(row[2]), str(row[3]), str(row[4])))
    found: set[ExpectedForeignKey] = set()
    for parts in grouped.values():
        parts.sort()
        parent = parts[0][1]
        columns = tuple((item[2], item[3]) for item in parts)
        found.add((parent, columns))
    return found
