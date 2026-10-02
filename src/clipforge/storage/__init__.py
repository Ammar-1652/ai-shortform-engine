"""SQLite state for projects, sources, jobs, artifacts, and reviews."""

from clipforge.storage.db import Database, DatabaseStatus
from clipforge.storage.migrations import CURRENT_SCHEMA_VERSION
from clipforge.storage.repository import (
    get_project,
    insert_artifact,
    insert_job,
    insert_project,
    insert_review,
    insert_source_asset,
    list_artifact_ids,
    list_jobs,
    list_projects,
    list_reviews,
    list_source_assets,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "Database",
    "DatabaseStatus",
    "get_project",
    "insert_artifact",
    "insert_job",
    "insert_project",
    "insert_review",
    "insert_source_asset",
    "list_artifact_ids",
    "list_jobs",
    "list_projects",
    "list_reviews",
    "list_source_assets",
]
