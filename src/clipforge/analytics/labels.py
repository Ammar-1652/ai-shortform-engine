"""Append-only manual labels. The newest row is effective. Older rows stay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from clipforge.analytics.service import AnalyticsError
from clipforge.errors import ClipforgeError, StorageError
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import ensure_within
from clipforge.schemas.analytics import (
    AnalyticsLabelCacheRecord,
    EditorialFeatureSnapshot,
    EditorialLabelAssignment,
    EditorialLabelHistory,
    EditorialLabelSet,
    PerformanceOutcome,
)
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import Database, get_artifact, get_source_asset

_STALE = "The labels changed while this page was open; reload before saving."


def list_label_history(database: Database, project_id: str, artifact_id: str) -> EditorialLabelHistory:
    with database.connect() as connection:
        entries = _entries(connection, project_id, artifact_id)
    effective = entries[-1].label_set_id if entries else None
    return EditorialLabelHistory(
        project_id=project_id,
        artifact_id=artifact_id,
        effective_label_set_id=effective,
        entries=entries,
    )


def effective_label_set(database: Database, project_id: str, artifact_id: str) -> EditorialLabelSet | None:
    history = list_label_history(database, project_id, artifact_id)
    if not history.entries:
        return None
    return history.entries[-1]


def set_labels(
    database: Database,
    work_root: Path,
    assignment: EditorialLabelAssignment,
    *,
    sidecar_hook: Callable[[], None] | None = None,
) -> EditorialLabelSet:
    """Insert one label set. A stale expected id or artifact hash writes nothing."""
    root = work_root.resolve()
    _reject_linked_analytics(root)
    with database.connect() as connection:
        _require_binding(connection, root, assignment)
        artifact_sha = _artifact_sha(connection, root, assignment.artifact_id, assignment.outcome_id)
    if assignment.expected_artifact_sha256 is not None and assignment.expected_artifact_sha256 != artifact_sha:
        raise AnalyticsError(_STALE)
    history = list_label_history(database, assignment.project_id, assignment.artifact_id)
    current_id = history.effective_label_set_id
    if assignment.expected_label_set_id != current_id:
        raise AnalyticsError(_STALE)
    now = datetime.now(UTC)
    label_set = EditorialLabelSet(
        label_set_id=str(uuid4()),
        project_id=assignment.project_id,
        source_asset_id=assignment.source_asset_id,
        artifact_id=assignment.artifact_id,
        outcome_id=assignment.outcome_id,
        snapshot_id=assignment.snapshot_id,
        previous_label_set_id=current_id,
        labels=assignment.labels,
        platform=assignment.platform,
        campaign_id=assignment.campaign_id,
        geography=assignment.geography,
        reviewer_id=assignment.reviewer_id,
        notes=assignment.notes,
        confidence=assignment.confidence,
        created_at=now,
        provenance=ArtifactProvenance(
            created_at=now,
            created_by=assignment.reviewer_id,
            tool="clipforge-analytics",
            tool_version="0",
            source_asset_ids=[assignment.source_asset_id],
            inputs_sha256=artifact_sha,
        ),
    )
    _publish(database, root, label_set, [*history.entries, label_set], artifact_sha, sidecar_hook)
    return label_set


def label_cache_state(work_root: Path, artifact_id: str, expected: AnalyticsLabelCacheRecord) -> str:
    """Return hit or miss. This does not write."""
    path = _cache_path(work_root.resolve(), artifact_id)
    if path.is_symlink() or not path.is_file():
        return "miss"
    try:
        stored = AnalyticsLabelCacheRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return "miss"
    if stored.model_dump(mode="json") != expected.model_dump(mode="json"):
        return "miss"
    return "hit"


def expected_cache_record(
    database: Database,
    work_root: Path,
    project_id: str,
    artifact_id: str,
) -> AnalyticsLabelCacheRecord | None:
    """Build the cache identity from current rows. This does not write."""
    history = list_label_history(database, project_id, artifact_id)
    if not history.entries:
        return None
    label_set = history.entries[-1]
    root = work_root.resolve()
    with database.connect() as connection:
        artifact_sha = _artifact_sha(connection, root, artifact_id, label_set.outcome_id)
        profile_id = _import_profile(connection, project_id, label_set.outcome_id)
    return _cache_record(label_set, history.entries, artifact_sha, profile_id)


def apply_effective_pair(
    outcome: PerformanceOutcome,
    snapshot: EditorialFeatureSnapshot,
    label_set: EditorialLabelSet | None,
) -> tuple[PerformanceOutcome, EditorialFeatureSnapshot]:
    """Return in-memory copies whose comparison fields use the effective label set."""
    if label_set is None:
        return outcome, snapshot
    platform = outcome.platform
    labeled_platform = label_set.platform
    if labeled_platform is not None and labeled_platform != "unknown":
        platform = labeled_platform
    campaign = label_set.campaign_id if label_set.campaign_id is not None else outcome.campaign_id
    geography = label_set.geography if label_set.geography is not None else outcome.geography
    return (
        outcome.model_copy(update={"platform": platform, "campaign_id": campaign, "geography": geography}),
        snapshot.model_copy(update={"labels": label_set.labels}),
    )


def load_effective_map(connection: object, project_id: str) -> dict[str, EditorialLabelSet]:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        raise AnalyticsError("internal connection was not a database connection")
    rows = connection.execute(
        """
        SELECT artifact_id, document_json FROM editorial_label_sets
        WHERE project_id = ?
        ORDER BY created_at, label_set_id
        """,
        (project_id,),
    ).fetchall()
    found: dict[str, EditorialLabelSet] = {}
    for row in rows:
        label_set = EditorialLabelSet.model_validate_json(str(row["document_json"]))
        found[str(row["artifact_id"])] = label_set
    return found


def verify_labels(database: Database, project_id: str) -> str:
    """Re-read label history. This does not write."""
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT artifact_id, document_json FROM editorial_label_sets
            WHERE project_id = ?
            ORDER BY artifact_id, created_at, label_set_id
            """,
            (project_id,),
        ).fetchall()
        grouped: dict[str, list[EditorialLabelSet]] = {}
        for row in rows:
            label_set = EditorialLabelSet.model_validate_json(str(row["document_json"]))
            if label_set.project_id != project_id or label_set.artifact_id != str(row["artifact_id"]):
                raise AnalyticsError("stored label set does not match its row")
            if _forbidden_document(label_set.model_dump(mode="json")):
                raise AnalyticsError("stored label set contains a forbidden path or URL")
            _require_binding(
                connection,
                None,
                EditorialLabelAssignment(
                    project_id=label_set.project_id,
                    source_asset_id=label_set.source_asset_id,
                    artifact_id=label_set.artifact_id,
                    outcome_id=label_set.outcome_id,
                    snapshot_id=label_set.snapshot_id,
                    reviewer_id=label_set.reviewer_id,
                    notes=label_set.notes,
                    labels=label_set.labels,
                    platform=label_set.platform,
                    campaign_id=label_set.campaign_id,
                    geography=label_set.geography,
                    confidence=label_set.confidence,
                ),
            )
            grouped.setdefault(label_set.artifact_id, []).append(label_set)
    for artifact_id, entries in grouped.items():
        ordered = sorted(entries, key=lambda item: (item.created_at, item.label_set_id))
        if [item.label_set_id for item in ordered] != [item.label_set_id for item in entries]:
            raise AnalyticsError(f"label history for {artifact_id} is not in created order")
    return f"PASS labels\nartifacts: {len(grouped)}\nrows: {len(rows)}"


def _publish(
    database: Database,
    root: Path,
    label_set: EditorialLabelSet,
    history: list[EditorialLabelSet],
    artifact_sha: str,
    sidecar_hook: Callable[[], None] | None,
) -> None:
    current = _current_path(root, label_set.artifact_id)
    cache = _cache_path(root, label_set.artifact_id)
    partial = current.with_name("current.json.partial")
    _reject_linked_analytics(root)
    try:
        ensure_within(root, current)
    except ClipforgeError as exc:
        raise _confine_error(exc) from exc
    for path in (current, cache, partial):
        if path.is_symlink():
            raise AnalyticsError("label sidecar is a symlink")
    payload = json.dumps(label_set.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    if _forbidden_document(label_set.model_dump(mode="json")):
        raise AnalyticsError("label set contained a forbidden path and was not written")
    previous = current.read_bytes() if current.is_file() else None
    previous_cache = cache.read_bytes() if cache.is_file() else None
    replaced = False
    try:
        current.parent.mkdir(parents=True, exist_ok=True)
        _reject_linked_analytics(root)
        partial.write_text(payload + "\n", encoding="utf-8")
        EditorialLabelSet.model_validate_json(payload)
        with database.transaction() as connection:
            fresh = _entries(connection, label_set.project_id, label_set.artifact_id)
            fresh_id = fresh[-1].label_set_id if fresh else None
            if fresh_id != label_set.previous_label_set_id:
                raise AnalyticsError(_STALE)
            fresh_sha = _artifact_sha(connection, root, label_set.artifact_id, label_set.outcome_id)
            if fresh_sha != artifact_sha:
                raise AnalyticsError(_STALE)
            connection.execute(
                """
                INSERT INTO editorial_label_sets (
                    label_set_id, project_id, source_asset_id, artifact_id, outcome_id,
                    snapshot_id, document_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    label_set.label_set_id,
                    label_set.project_id,
                    label_set.source_asset_id,
                    label_set.artifact_id,
                    label_set.outcome_id,
                    label_set.snapshot_id,
                    payload,
                    label_set.created_at.isoformat(),
                ),
            )
            if sidecar_hook is not None:
                sidecar_hook()
            profile_id = _import_profile(connection, label_set.project_id, label_set.outcome_id)
            record = _cache_record(label_set, history, artifact_sha, profile_id)
            partial.replace(current)
            replaced = True
            cache.write_text(record.model_dump_json() + "\n", encoding="utf-8")
    except Exception as exc:
        _restore(partial, current, cache, previous, previous_cache, replaced)
        if isinstance(exc, AnalyticsError):
            raise
        raise AnalyticsError("label sidecar was not saved") from exc
    if partial.exists():
        partial.unlink()


def _restore(
    partial: Path,
    current: Path,
    cache: Path,
    previous: bytes | None,
    previous_cache: bytes | None,
    replaced: bool,
) -> None:
    if partial.is_file() and not partial.is_symlink():
        partial.unlink()
    if not replaced:
        return
    if previous is None:
        if current.is_file() and not current.is_symlink():
            current.unlink()
    else:
        current.write_bytes(previous)
    if previous_cache is None:
        if cache.is_file() and not cache.is_symlink():
            cache.unlink()
    else:
        cache.write_bytes(previous_cache)


def _cache_record(
    label_set: EditorialLabelSet,
    history: list[EditorialLabelSet],
    artifact_sha: str,
    profile_id: str,
) -> AnalyticsLabelCacheRecord:
    identity = hashlib.sha256("|".join(item.label_set_id for item in history).encode()).hexdigest()
    return AnalyticsLabelCacheRecord(
        project_id=label_set.project_id,
        source_asset_id=label_set.source_asset_id,
        artifact_id=label_set.artifact_id,
        artifact_sha256=artifact_sha,
        outcome_id=label_set.outcome_id,
        snapshot_id=label_set.snapshot_id,
        label_set_id=label_set.label_set_id,
        label_history_sha256=identity,
        import_profile_id=profile_id,
        created_at=label_set.created_at,
    )


def _require_binding(connection: object, root: Path | None, assignment: EditorialLabelAssignment) -> None:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        raise AnalyticsError("internal connection was not a database connection")
    try:
        artifact = get_artifact(connection, assignment.artifact_id)
        source = get_source_asset(connection, assignment.source_asset_id)
    except StorageError as exc:
        raise AnalyticsError(str(exc)) from exc
    if artifact.project_id != assignment.project_id or source.project_id != assignment.project_id:
        raise AnalyticsError("label set belongs to a different project")
    if artifact.source_asset_id != assignment.source_asset_id:
        raise AnalyticsError("label set belongs to a different source")
    if assignment.outcome_id is None:
        return
    row = connection.execute(
        """
        SELECT project_id, source_asset_id, artifact_id, snapshot_id, document_json
        FROM performance_outcomes WHERE outcome_id = ?
        """,
        (assignment.outcome_id,),
    ).fetchone()
    if row is None:
        raise AnalyticsError("label set names an unknown outcome")
    if (
        str(row["project_id"]) != assignment.project_id
        or str(row["source_asset_id"]) != assignment.source_asset_id
        or str(row["artifact_id"]) != assignment.artifact_id
    ):
        raise AnalyticsError("label set outcome lineage does not match")
    if assignment.snapshot_id is not None and str(row["snapshot_id"]) != assignment.snapshot_id:
        raise AnalyticsError("label set snapshot does not match the outcome")
    if root is None:
        return
    outcome = PerformanceOutcome.model_validate_json(str(row["document_json"]))
    file_sha = _file_sha(root, artifact.uri)
    if file_sha is not None and file_sha != outcome.artifact_sha256:
        raise AnalyticsError(_STALE)


def _artifact_sha(connection: object, root: Path, artifact_id: str, outcome_id: str | None) -> str:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        raise AnalyticsError("internal connection was not a database connection")
    try:
        artifact = get_artifact(connection, artifact_id)
    except StorageError as exc:
        raise AnalyticsError(str(exc)) from exc
    file_sha = _file_sha(root, artifact.uri)
    if outcome_id is not None:
        row = connection.execute(
            "SELECT document_json FROM performance_outcomes WHERE outcome_id = ?",
            (outcome_id,),
        ).fetchone()
        if row is None:
            raise AnalyticsError("label set names an unknown outcome")
        outcome = PerformanceOutcome.model_validate_json(str(row["document_json"]))
        if file_sha is not None and file_sha != outcome.artifact_sha256:
            raise AnalyticsError(_STALE)
        return outcome.artifact_sha256
    if file_sha is not None:
        return file_sha
    return hashlib.sha256(f"unavailable:{artifact_id}".encode()).hexdigest()


def _file_sha(root: Path, uri: str) -> str | None:
    if not uri.startswith("file:"):
        return None
    path = path_from_file_uri(uri)
    if path.is_symlink():
        raise AnalyticsError("artifact file is a symlink")
    try:
        ensure_within(root, path)
    except ClipforgeError as exc:
        raise _confine_error(exc) from exc
    if not path.exists():
        return None
    if not path.is_file():
        raise AnalyticsError("artifact file is not a regular file")
    return sha256_file(path)


def import_profile_for_outcome(connection: object, project_id: str, outcome_id: str | None) -> str:
    return _import_profile(connection, project_id, outcome_id)


def _import_profile(connection: object, project_id: str, outcome_id: str | None) -> str:
    from sqlite3 import Connection

    if outcome_id is None or not isinstance(connection, Connection):
        return "none"
    rows = connection.execute(
        """
        SELECT profile_id, outcome_ids_json FROM analytics_imports
        WHERE project_id = ?
        ORDER BY created_at, import_id
        """,
        (project_id,),
    ).fetchall()
    found = "none"
    for row in rows:
        try:
            parsed = json.loads(str(row["outcome_ids_json"]))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list) and outcome_id in parsed:
            found = str(row["profile_id"])
    return found


def _entries(connection: object, project_id: str, artifact_id: str) -> list[EditorialLabelSet]:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        raise AnalyticsError("internal connection was not a database connection")
    rows = connection.execute(
        """
        SELECT document_json FROM editorial_label_sets
        WHERE project_id = ? AND artifact_id = ?
        ORDER BY created_at, label_set_id
        """,
        (project_id, artifact_id),
    ).fetchall()
    return [EditorialLabelSet.model_validate_json(str(row["document_json"])) for row in rows]


def _current_path(root: Path, artifact_id: str) -> Path:
    _safe_id(artifact_id)
    return root / "analytics" / "labels" / artifact_id / "current.json"


def _cache_path(root: Path, artifact_id: str) -> Path:
    _safe_id(artifact_id)
    return root / "analytics" / "labels" / artifact_id / "cache.json"


def _safe_id(artifact_id: str) -> None:
    if "/" in artifact_id or "\\" in artifact_id or ".." in artifact_id or "\x00" in artifact_id:
        raise AnalyticsError("artifact id is not a safe identifier")


def _reject_linked_analytics(root: Path) -> None:
    current = root
    for part in ("analytics", "labels"):
        current = current / part
        if current.is_symlink():
            raise AnalyticsError("analytics directory is a symlink")
        if current.exists() and not current.is_dir():
            raise AnalyticsError("analytics directory is not a directory")


def _forbidden_document(value: object) -> bool:
    if isinstance(value, str):
        return any(token in value for token in ("/tmp/", "/home/", "/Users/", "\\", "://"))
    if isinstance(value, dict):
        return any(_forbidden_document(item) for item in value.values())
    if isinstance(value, list):
        return any(_forbidden_document(item) for item in value)
    return False


def _confine_error(exc: ClipforgeError) -> AnalyticsError:
    text = str(exc)
    if any(token in text for token in ("/tmp/", "/home/", "/Users/", "\\")):
        return AnalyticsError("label path was rejected")
    return AnalyticsError(text)
