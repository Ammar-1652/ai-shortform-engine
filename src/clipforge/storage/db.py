"""SQLite access. Each operation opens its own connection. There is no process-global connection."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from clipforge.errors import StorageError
from clipforge.storage.migrations import CURRENT_SCHEMA_VERSION, MIGRATIONS

_REQUIRED_TABLES = frozenset(
    {
        "schema_migrations",
        "projects",
        "source_assets",
        "asset_license_records",
        "jobs",
        "artifacts",
        "reviews",
    }
)
_COUNTED_TABLES = (
    "projects",
    "source_assets",
    "asset_license_records",
    "jobs",
    "artifacts",
    "reviews",
)


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    path: Path
    schema_version: int
    migrations: tuple[str, ...]
    counts: dict[str, int]


class Database:
    """A clipforge SQLite file."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise StorageError(f"database path must be a pathlib.Path, got {type(path).__name__}")
        if path.name == ":memory:" or str(path) == ":memory:":
            raise StorageError(
                "in-memory SQLite is not supported: each connection would see a different database. "
                "Pass a file path. Tests should use a temporary file."
            )
        self.path = path

    def initialize(self) -> int:
        """Create the file if needed and apply pending migrations. Safe to call twice."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(
                f"could not create the directory for {self.path}: {exc}. Choose a writable DATABASE_PATH."
            ) from exc
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
        except sqlite3.Error as exc:
            raise StorageError(f"could not open {self.path}: {exc}") from exc
        try:
            _prepare(connection)
            connection.execute("BEGIN IMMEDIATE")
            current = _read_version(connection)
            if current > CURRENT_SCHEMA_VERSION:
                raise StorageError(
                    f"{self.path} is at schema version {current}, newer than this build "
                    f"({CURRENT_SCHEMA_VERSION}). Upgrade clipforge before opening it."
                )
            if current == CURRENT_SCHEMA_VERSION:
                _assert_current_shape(connection, self.path)
            now = datetime.now(UTC).isoformat()
            for migration in MIGRATIONS:
                if migration.version <= current:
                    continue
                if migration.precheck is not None:
                    migration.precheck(connection)
                _execute_script(connection, migration.sql)
                connection.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (migration.version, migration.name, now),
                )
            _assert_current_shape(connection, self.path)
            connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
            connection.commit()
        except StorageError:
            _rollback_quietly(connection)
            raise
        except sqlite3.DatabaseError as exc:
            _rollback_quietly(connection)
            raise StorageError(
                f"{self.path} is not a readable SQLite database: {exc}. "
                "Restore it from a backup or choose another path. It was not recreated."
            ) from exc
        except sqlite3.Error as exc:
            _rollback_quietly(connection)
            raise StorageError(
                f"migration failed for {self.path}: {exc}. The transaction was rolled back."
            ) from exc
        finally:
            connection.close()
        return CURRENT_SCHEMA_VERSION

    def health_check(self) -> None:
        """Raise ``StorageError`` when the file, its tables, or its foreign keys are unusable.

        ``quick_check`` and ``foreign_key_check`` run here only. Ordinary queries do not.
        """
        try:
            with self.connect() as connection:
                row = connection.execute("SELECT 1").fetchone()
                if row is None or row[0] != 1:
                    raise StorageError(f"SQLite health check failed for {self.path}")
                _assert_current_shape(connection, self.path)
                quick = [str(item[0]) for item in connection.execute("PRAGMA quick_check")]
                if quick != ["ok"]:
                    raise StorageError(
                        f"SQLite quick_check failed for {self.path}: {quick}. "
                        "The file was not repaired. Restore it from a backup."
                    )
                violations = connection.execute("PRAGMA foreign_key_check").fetchall()
                if violations:
                    first = tuple(violations[0])
                    raise StorageError(
                        f"SQLite foreign_key_check found {len(violations)} violation(s) in {self.path}. "
                        f"First violation: {first}. Rows were not deleted or rewritten."
                    )
        except StorageError:
            raise
        except sqlite3.Error as exc:
            raise StorageError(f"SQLite health check failed for {self.path}: {exc}") from exc

    def status(self) -> DatabaseStatus:
        with self.connect() as connection:
            version = _read_version(connection)
            names = tuple(
                row[0] for row in connection.execute("SELECT name FROM schema_migrations ORDER BY version")
            )
            counts = {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in _COUNTED_TABLES
            }
        return DatabaseStatus(
            path=self.path,
            schema_version=version,
            migrations=names,
            counts=counts,
        )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection for a database that is already at the current schema."""
        self._require_current()
        connection = sqlite3.connect(self.path, timeout=5.0)
        try:
            _prepare(connection)
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection inside ``BEGIN IMMEDIATE``. Rolls back on any exception."""
        with self.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _require_current(self) -> None:
        if not self.path.exists():
            raise StorageError(
                f"database file does not exist: {self.path}. Run `clipforge db init --db {self.path}`."
            )
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
        except sqlite3.Error as exc:
            raise StorageError(f"could not open {self.path}: {exc}") from exc
        try:
            _prepare(connection)
            try:
                if not _has_migrations_table(connection):
                    raise StorageError(
                        f"{self.path} is not a clipforge database (schema_migrations is missing). "
                        "Point --db at a clipforge file, or run `clipforge db init` on a new path."
                    )
                version = _read_version(connection)
                if version == CURRENT_SCHEMA_VERSION:
                    _assert_current_shape(connection, self.path)
            except sqlite3.DatabaseError as exc:
                raise StorageError(
                    f"{self.path} is not a readable SQLite database: {exc}. "
                    "Restore it from a backup or pass a different --db path. The file was not modified."
                ) from exc
        finally:
            connection.close()
        if version < CURRENT_SCHEMA_VERSION:
            raise StorageError(
                f"{self.path} is at schema version {version}; this build expects "
                f"{CURRENT_SCHEMA_VERSION}. Run `clipforge db init --db {self.path}` "
                "to apply pending migrations."
            )
        if version > CURRENT_SCHEMA_VERSION:
            raise StorageError(
                f"{self.path} is at schema version {version}, newer than this build "
                f"({CURRENT_SCHEMA_VERSION}). Upgrade clipforge. The file was not modified."
            )


def _assert_current_shape(connection: sqlite3.Connection, path: Path) -> None:
    """Fail when a database claims the current version but is missing a required table.

    Does not create the missing table.
    """
    present = {item[0] for item in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    missing = sorted(_REQUIRED_TABLES - present)
    if missing:
        raise StorageError(
            f"{path} reports schema version {CURRENT_SCHEMA_VERSION} but is missing tables {missing}. "
            "The file was not repaired and the missing tables were not recreated. Restore it from a backup."
        )


def _rollback_quietly(connection: sqlite3.Connection) -> None:
    try:
        connection.rollback()
    except sqlite3.Error:
        return


def _prepare(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")


def _has_migrations_table(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    return row is not None


def _read_version(connection: sqlite3.Connection) -> int:
    if not _has_migrations_table(connection):
        return 0
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    if row is None or row[0] is None:
        return 0
    table_version = int(row[0])
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version != table_version:
        raise StorageError(
            f"schema version mismatch: schema_migrations says {table_version} "
            f"but PRAGMA user_version says {user_version}. "
            "The file was not repaired automatically. Restore it from a copy you trust."
        )
    return table_version


def _execute_script(connection: sqlite3.Connection, sql: str) -> None:
    for statement in sql.split(";"):
        stripped = statement.strip()
        if stripped:
            connection.execute(stripped)
