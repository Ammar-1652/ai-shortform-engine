"""SQL migrations applied in order. ``executescript`` is avoided so a transaction can wrap them.

Migration 1 is the Round 1 schema and must not be edited. Migration 2 adds rights
rows and foreign keys. See ADR 0011.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from clipforge.errors import StorageError

INITIAL_SQL = """
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    profile_id TEXT,
    created_at TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE TABLE source_assets (
    source_asset_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    uri TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    license_record_id TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE jobs (
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
);

CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    job_id TEXT REFERENCES jobs(job_id),
    source_asset_id TEXT,
    kind TEXT NOT NULL,
    uri TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE reviews (
    review_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    artifact_id TEXT,
    candidate_id TEXT,
    subject_kind TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (
        decision IN ('approved', 'rejected', 'changes_requested')
    ),
    reviewer_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    notes TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (artifact_id IS NOT NULL OR candidate_id IS NOT NULL)
);

CREATE INDEX idx_source_assets_project ON source_assets(project_id);
CREATE INDEX idx_jobs_project ON jobs(project_id);
CREATE INDEX idx_artifacts_project ON artifacts(project_id);
CREATE INDEX idx_reviews_project ON reviews(project_id);
"""


# Notes text has no semicolons: the runner splits SQL on ';'.
_LEGACY_RIGHTS_NOTE = (
    "Unresolved legacy reference. Migration 2 created this row because schema version 1 "
    "stored a license id without a rights record. Rights were not verified. "
    "Do not treat this as owned, licensed, or campaign-provided."
)

RIGHTS_AND_LINEAGE_SQL = f"""
CREATE TABLE asset_license_records (
    license_record_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('owned', 'licensed', 'campaign_provided', 'unknown', 'prohibited')
    ),
    license_name TEXT,
    evidence_uri TEXT,
    notes TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    PRIMARY KEY (license_record_id),
    UNIQUE (license_record_id, asset_id)
);

INSERT INTO asset_license_records (
    license_record_id, asset_id, schema_version, status, license_name, evidence_uri,
    notes, recorded_at, recorded_by
)
SELECT
    license_record_id,
    source_asset_id,
    '1.0.0',
    'unknown',
    NULL,
    NULL,
    '{_LEGACY_RIGHTS_NOTE}',
    created_at,
    'clipforge-migration-2'
FROM source_assets;

CREATE TABLE source_assets_v2 (
    source_asset_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    uri TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    license_record_id TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (license_record_id, source_asset_id)
        REFERENCES asset_license_records (license_record_id, asset_id)
);

INSERT INTO source_assets_v2 (
    source_asset_id, project_id, uri, schema_version, license_record_id, provenance_json, created_at
)
SELECT
    source_asset_id, project_id, uri, schema_version, license_record_id, provenance_json, created_at
FROM source_assets;

DROP TABLE source_assets;
ALTER TABLE source_assets_v2 RENAME TO source_assets;
CREATE INDEX idx_source_assets_project ON source_assets(project_id);

CREATE TABLE artifacts_v2 (
    artifact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    job_id TEXT REFERENCES jobs(job_id),
    source_asset_id TEXT REFERENCES source_assets(source_asset_id),
    kind TEXT NOT NULL,
    uri TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO artifacts_v2 (
    artifact_id, project_id, job_id, source_asset_id, kind, uri, schema_version,
    provenance_json, created_at
)
SELECT
    artifact_id, project_id, job_id, source_asset_id, kind, uri, schema_version,
    provenance_json, created_at
FROM artifacts;

DROP TABLE artifacts;
ALTER TABLE artifacts_v2 RENAME TO artifacts;
CREATE INDEX idx_artifacts_project ON artifacts(project_id);

CREATE TABLE reviews_v2 (
    review_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    artifact_id TEXT REFERENCES artifacts(artifact_id),
    candidate_id TEXT,
    subject_kind TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (
        decision IN ('approved', 'rejected', 'changes_requested')
    ),
    reviewer_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    notes TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (artifact_id IS NOT NULL OR candidate_id IS NOT NULL)
);

INSERT INTO reviews_v2 (
    review_id, project_id, artifact_id, candidate_id, subject_kind, decision,
    reviewer_id, schema_version, notes, created_at
)
SELECT
    review_id, project_id, artifact_id, candidate_id, subject_kind, decision,
    reviewer_id, schema_version, notes, created_at
FROM reviews;

DROP TABLE reviews;
ALTER TABLE reviews_v2 RENAME TO reviews;
CREATE INDEX idx_reviews_project ON reviews(project_id);
CREATE INDEX idx_asset_license_records_asset ON asset_license_records(asset_id);
"""


def precheck_rights_and_lineage(connection: sqlite3.Connection) -> None:
    """Reject version-1 rows that cannot be given a foreign key without deleting them.

    Shared license ids are not split into owned or licensed records. Orphan artifact
    and review pointers are left in place and the migration stops.
    """
    conflicts = connection.execute(
        """
        SELECT license_record_id
        FROM source_assets
        GROUP BY license_record_id
        HAVING COUNT(DISTINCT source_asset_id) > 1
        """
    ).fetchall()
    if conflicts:
        ids = ", ".join(str(row[0]) for row in conflicts)
        raise StorageError(
            "migration 2 stopped: license id(s) "
            f"{ids} are used by more than one source asset. "
            "A rights record belongs to one asset. Repair those rows, then run "
            "`clipforge db init` again. No rights status was invented and no rows were deleted."
        )
    _reject_orphan_artifacts(connection)
    _reject_artifact_lineage(connection)
    _reject_orphan_reviews(connection)


def _reject_orphan_artifacts(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT artifact_id, source_asset_id
        FROM artifacts
        WHERE source_asset_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM source_assets
              WHERE source_assets.source_asset_id = artifacts.source_asset_id
          )
        """
    ).fetchall()
    if rows:
        listed = ", ".join(f"{row[0]} -> {row[1]}" for row in rows)
        raise StorageError(
            "migration 2 stopped: artifacts point at source assets that are not in source_assets "
            f"({listed}). Restore the missing source rows or remove the artifact rows yourself. "
            "They were not deleted automatically."
        )


def _reject_orphan_reviews(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT review_id, artifact_id
        FROM reviews
        WHERE artifact_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM artifacts WHERE artifacts.artifact_id = reviews.artifact_id
          )
        """
    ).fetchall()
    if rows:
        listed = ", ".join(f"{row[0]} -> {row[1]}" for row in rows)
        raise StorageError(
            "migration 2 stopped: reviews point at artifacts that are not in artifacts "
            f"({listed}). Restore the missing artifact rows or remove the review rows yourself. "
            "They were not deleted automatically."
        )


def _reject_artifact_lineage(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT artifact_id, job_id, source_asset_id, provenance_json FROM artifacts"
    ).fetchall()
    for artifact_id, job_id, source_asset_id, raw in rows:
        try:
            provenance = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StorageError(
                f"migration 2 stopped: artifact {artifact_id} has corrupt provenance JSON ({exc}). "
                "The row was not skipped or rewritten."
            ) from exc
        if not isinstance(provenance, dict):
            raise StorageError(
                f"migration 2 stopped: artifact {artifact_id} provenance is not a JSON object. "
                "The row was not rewritten."
            )
        source_ids = provenance.get("source_asset_ids") or []
        if source_asset_id is not None and source_asset_id not in source_ids:
            raise StorageError(
                f"migration 2 stopped: artifact {artifact_id} source_asset_id is {source_asset_id} "
                f"but provenance.source_asset_ids is {source_ids}. "
                "Fix the lineage before migrating. The row was not rewritten."
            )
        provenance_job = provenance.get("job_id")
        if (job_id or None) != (provenance_job or None):
            raise StorageError(
                f"migration 2 stopped: artifact {artifact_id} job_id is {job_id!r} "
                f"but provenance.job_id is {provenance_job!r}. "
                "Those fields must match. When a job id is stored, provenance.job_id is required "
                "and must be the same id. The row was not rewritten."
            )


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str
    precheck: Callable[[sqlite3.Connection], None] | None = None


PROJECT_LINEAGE_SQL = """
CREATE TABLE source_assets_new (
    source_asset_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    uri TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    license_record_id TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (source_asset_id, project_id),
    FOREIGN KEY (license_record_id, source_asset_id)
        REFERENCES asset_license_records (license_record_id, asset_id)
);

INSERT INTO source_assets_new (
    source_asset_id, project_id, uri, schema_version, license_record_id, provenance_json, created_at
)
SELECT
    source_asset_id, project_id, uri, schema_version, license_record_id, provenance_json, created_at
FROM source_assets;

CREATE TABLE jobs_new (
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
    payload_json TEXT NOT NULL,
    UNIQUE (job_id, project_id)
);

INSERT INTO jobs_new (
    job_id, project_id, kind, status, schema_version, created_at, updated_at,
    error_message, payload_json
)
SELECT
    job_id, project_id, kind, status, schema_version, created_at, updated_at,
    error_message, payload_json
FROM jobs;

CREATE TABLE artifacts_new (
    artifact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    job_id TEXT,
    source_asset_id TEXT,
    kind TEXT NOT NULL,
    uri TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (artifact_id, project_id),
    FOREIGN KEY (source_asset_id, project_id)
        REFERENCES source_assets_new (source_asset_id, project_id),
    FOREIGN KEY (job_id, project_id)
        REFERENCES jobs_new (job_id, project_id)
);

INSERT INTO artifacts_new (
    artifact_id, project_id, job_id, source_asset_id, kind, uri, schema_version,
    provenance_json, created_at
)
SELECT
    artifact_id, project_id, job_id, source_asset_id, kind, uri, schema_version,
    provenance_json, created_at
FROM artifacts;

CREATE TABLE reviews_new (
    review_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    artifact_id TEXT,
    candidate_id TEXT,
    subject_kind TEXT NOT NULL CHECK (
        subject_kind IN ('candidate', 'hero', 'caption', 'framing', 'final')
    ),
    decision TEXT NOT NULL CHECK (
        decision IN ('approved', 'rejected', 'changes_requested')
    ),
    reviewer_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    notes TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (artifact_id, project_id)
        REFERENCES artifacts_new (artifact_id, project_id),
    CHECK (
        (
            subject_kind IN ('candidate', 'hero')
            AND candidate_id IS NOT NULL
        )
        OR (
            subject_kind IN ('caption', 'framing', 'final')
            AND artifact_id IS NOT NULL
        )
    )
);

INSERT INTO reviews_new (
    review_id, project_id, artifact_id, candidate_id, subject_kind, decision,
    reviewer_id, schema_version, notes, created_at
)
SELECT
    review_id, project_id, artifact_id, candidate_id, subject_kind, decision,
    reviewer_id, schema_version, notes, created_at
FROM reviews;

DROP TABLE reviews;
DROP TABLE artifacts;
DROP TABLE jobs;
DROP TABLE source_assets;

ALTER TABLE source_assets_new RENAME TO source_assets;
ALTER TABLE jobs_new RENAME TO jobs;
ALTER TABLE artifacts_new RENAME TO artifacts;
ALTER TABLE reviews_new RENAME TO reviews;

CREATE INDEX idx_source_assets_project ON source_assets(project_id);
CREATE INDEX idx_jobs_project ON jobs(project_id);
CREATE INDEX idx_artifacts_project ON artifacts(project_id);
CREATE INDEX idx_reviews_project ON reviews(project_id);
"""


def precheck_project_lineage(connection: sqlite3.Connection) -> None:
    """Stop migration 3 when a child row points at another project's parent.

    Does not change ``project_id``, re-parent a row, or delete anything.
    """
    problems: list[str] = []
    problems.extend(_cross_project_sources(connection))
    problems.extend(_cross_project_jobs(connection))
    problems.extend(_cross_project_reviews(connection))
    problems.extend(_review_subjects(connection))
    if problems:
        listed = " ".join(problems)
        raise StorageError(
            "migration 3 stopped because project lineage is inconsistent. "
            f"{listed} "
            "Repair the rows so each child uses the same project_id as the row it references, "
            "then run `clipforge db init` again. No project_id was changed and no rows were deleted."
        )


def _cross_project_sources(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT artifacts.artifact_id, artifacts.project_id, artifacts.source_asset_id, source_assets.project_id
        FROM artifacts
        JOIN source_assets ON source_assets.source_asset_id = artifacts.source_asset_id
        WHERE artifacts.source_asset_id IS NOT NULL
          AND artifacts.project_id != source_assets.project_id
        """
    ).fetchall()
    return [
        (
            f"artifact {row[0]} (child project {row[1]}) references source asset {row[2]} "
            f"(parent project {row[3]})."
        )
        for row in rows
    ]


def _cross_project_jobs(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT artifacts.artifact_id, artifacts.project_id, artifacts.job_id, jobs.project_id
        FROM artifacts
        JOIN jobs ON jobs.job_id = artifacts.job_id
        WHERE artifacts.job_id IS NOT NULL
          AND artifacts.project_id != jobs.project_id
        """
    ).fetchall()
    return [
        (f"artifact {row[0]} (child project {row[1]}) references job {row[2]} (parent project {row[3]}).")
        for row in rows
    ]


def _cross_project_reviews(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT reviews.review_id, reviews.project_id, reviews.artifact_id, artifacts.project_id
        FROM reviews
        JOIN artifacts ON artifacts.artifact_id = reviews.artifact_id
        WHERE reviews.artifact_id IS NOT NULL
          AND reviews.project_id != artifacts.project_id
        """
    ).fetchall()
    return [
        (f"review {row[0]} (child project {row[1]}) references artifact {row[2]} (parent project {row[3]}).")
        for row in rows
    ]


def _review_subjects(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT review_id, subject_kind, artifact_id, candidate_id
        FROM reviews
        WHERE subject_kind NOT IN ('candidate', 'hero', 'caption', 'framing', 'final')
           OR (subject_kind IN ('candidate', 'hero') AND candidate_id IS NULL)
           OR (subject_kind IN ('caption', 'framing', 'final') AND artifact_id IS NULL)
        """
    ).fetchall()
    return [
        (
            f"review {row[0]} has subject_kind {row[1]!r} with artifact_id {row[2]!r} "
            f"and candidate_id {row[3]!r}, which does not match the subject rule."
        )
        for row in rows
    ]


SOURCE_MANIFESTS_SQL = """
CREATE TABLE source_manifests (
    source_asset_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    original_filename TEXT NOT NULL,
    storage_mode TEXT NOT NULL CHECK (storage_mode = 'referenced'),
    transcription_eligible INTEGER NOT NULL CHECK (transcription_eligible IN (0, 1)),
    video_stream_index INTEGER NOT NULL,
    audio_stream_index INTEGER,
    canonical_duration_us INTEGER NOT NULL CHECK (canonical_duration_us > 0),
    video_origin_us INTEGER NOT NULL,
    ingested_at TEXT NOT NULL,
    probe_json TEXT NOT NULL,
    UNIQUE (source_asset_id, project_id),
    UNIQUE (project_id, content_sha256),
    FOREIGN KEY (source_asset_id, project_id)
        REFERENCES source_assets (source_asset_id, project_id)
);

CREATE INDEX idx_source_manifests_project ON source_manifests(project_id);
"""


ANALYTICS_SQL = """
CREATE TABLE editorial_feature_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_asset_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    document_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects (project_id),
    FOREIGN KEY (artifact_id, project_id) REFERENCES artifacts (artifact_id, project_id),
    FOREIGN KEY (source_asset_id, project_id) REFERENCES source_assets (source_asset_id, project_id)
);

CREATE INDEX idx_editorial_snapshots_artifact
    ON editorial_feature_snapshots (artifact_id, project_id);

CREATE TABLE performance_outcomes (
    outcome_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_asset_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    observed_at TEXT NOT NULL,
    document_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects (project_id),
    FOREIGN KEY (artifact_id, project_id) REFERENCES artifacts (artifact_id, project_id),
    FOREIGN KEY (source_asset_id, project_id) REFERENCES source_assets (source_asset_id, project_id),
    FOREIGN KEY (snapshot_id) REFERENCES editorial_feature_snapshots (snapshot_id)
);

CREATE INDEX idx_performance_outcomes_project
    ON performance_outcomes (project_id, observed_at, outcome_id);

CREATE TABLE analytics_imports (
    import_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    outcome_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects (project_id)
);
"""


ANALYTICS_LABELS_SQL = """
ALTER TABLE analytics_imports ADD COLUMN profile_id TEXT NOT NULL DEFAULT 'clipforge-observation-v1';

ALTER TABLE analytics_imports ADD COLUMN validation_summary TEXT NOT NULL DEFAULT '';

ALTER TABLE analytics_imports ADD COLUMN outcome_ids_json TEXT NOT NULL DEFAULT '[]';

CREATE TABLE editorial_label_sets (
    label_set_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_asset_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    outcome_id TEXT,
    snapshot_id TEXT,
    document_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects (project_id),
    FOREIGN KEY (artifact_id, project_id) REFERENCES artifacts (artifact_id, project_id),
    FOREIGN KEY (source_asset_id, project_id) REFERENCES source_assets (source_asset_id, project_id),
    FOREIGN KEY (outcome_id) REFERENCES performance_outcomes (outcome_id),
    FOREIGN KEY (snapshot_id) REFERENCES editorial_feature_snapshots (snapshot_id)
);

CREATE INDEX idx_editorial_label_sets_artifact
    ON editorial_label_sets (project_id, artifact_id, created_at, label_set_id);
"""


REVIEW_ROLES_SQL = """
ALTER TABLE reviews ADD COLUMN reviewer_role TEXT NOT NULL DEFAULT 'human_reviewer'
    CHECK (reviewer_role IN ('codex_operator', 'human_reviewer'));
"""


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "initial", INITIAL_SQL),
    Migration(2, "rights_and_lineage", RIGHTS_AND_LINEAGE_SQL, precheck_rights_and_lineage),
    Migration(3, "project_lineage_integrity", PROJECT_LINEAGE_SQL, precheck_project_lineage),
    Migration(4, "source_manifests", SOURCE_MANIFESTS_SQL),
    Migration(5, "analytics_outcomes", ANALYTICS_SQL),
    Migration(6, "analytics_labels", ANALYTICS_LABELS_SQL),
    Migration(7, "review_roles", REVIEW_ROLES_SQL),
)
CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version
