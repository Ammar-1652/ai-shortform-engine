"""SQL migrations applied in order. ``executescript`` is avoided so a transaction can wrap them."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


MIGRATIONS: tuple[Migration, ...] = (Migration(1, "initial", INITIAL_SQL),)
CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version
