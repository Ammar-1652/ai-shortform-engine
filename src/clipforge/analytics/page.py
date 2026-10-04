"""JSON for the loopback analytics page. Paths are not included."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from clipforge.analytics.compare import ComparisonFilter, compare_outcomes
from clipforge.analytics.labels import (
    expected_cache_record,
    import_profile_for_outcome,
    label_cache_state,
    list_label_history,
)
from clipforge.analytics.service import (
    AnalyticsError,
    _load_pairs,
    _outcome_by_id,
    _snapshot_by_id,
    _with_effective_labels,
    show_outcome,
)
from clipforge.schemas.analytics import PerformanceOutcome
from clipforge.schemas.governance import ReviewDecision
from clipforge.storage import Database, get_project, list_reviews

_METRIC_NAMES = (
    "views",
    "unique_viewers",
    "total_watch_time_us",
    "average_watch_time_us",
    "completion_count",
    "completion_rate",
    "likes",
    "comments",
    "shares",
    "saves",
    "follows",
    "clicks",
    "paid_views",
    "revenue_amount",
    "revenue_currency",
)


def overview(database: Database, work_root: Path, project_id: str) -> dict[str, object]:
    with database.connect() as connection:
        get_project(connection, project_id)
        pairs = _with_effective_labels(connection, project_id, _load_pairs(connection, project_id))
        reviews = list_reviews(connection, project_id)
    cards = [_card(database, work_root, outcome, reviews) for outcome, _snapshot in pairs]
    comparison = compare_outcomes(
        project_id=project_id,
        dimension="platform",
        pairs=pairs,
        comparison_filter=ComparisonFilter(),
        created_at=_frozen(),
        created_by="analytics-page",
    )
    return {
        "project_id": project_id,
        "outcomes": cards,
        "comparison": _comparison_public(comparison.model_dump(mode="json")),
    }


def outcome_card(database: Database, work_root: Path, project_id: str, outcome_id: str) -> dict[str, object]:
    with database.connect() as connection:
        outcome = _outcome_by_id(connection, outcome_id)
        if outcome is None or outcome.project_id != project_id:
            raise AnalyticsError("no outcome in this project")
        reviews = list_reviews(connection, project_id)
    return _card(database, work_root, outcome, reviews)


def outcome_document(database: Database, project_id: str, outcome_id: str) -> dict[str, object]:
    """Stored outcome JSON with filesystem paths removed."""
    text = show_outcome(database, outcome_id)
    if any(token in text for token in ("/tmp/", "/home/", "/Users/", "\\", "file:")):
        raise AnalyticsError("stored analytics record contains a forbidden path")
    loaded: object = json.loads(text)
    if not isinstance(loaded, dict):
        raise AnalyticsError("stored analytics record is not an object")
    outcome = loaded.get("outcome")
    if not isinstance(outcome, dict) or outcome.get("project_id") != project_id:
        raise AnalyticsError("no outcome in this project")
    public: dict[str, object] = {}
    for key, value in loaded.items():
        if not isinstance(key, str):
            raise AnalyticsError("stored analytics record is not an object")
        public[key] = value
    return public


def labels_document(
    database: Database, work_root: Path, project_id: str, artifact_id: str
) -> dict[str, object]:
    history = list_label_history(database, project_id, artifact_id)
    with database.connect() as connection:
        pairs = [pair for pair in _load_pairs(connection, project_id) if pair[0].artifact_id == artifact_id]
    outcome_id = pairs[-1][0].outcome_id if pairs else None
    snapshot_id = pairs[-1][0].snapshot_id if pairs else None
    source_asset_id = pairs[-1][0].source_asset_id if pairs else None
    record = expected_cache_record(database, work_root, project_id, artifact_id)
    cache = "none" if record is None else label_cache_state(work_root, artifact_id, record)
    artifact_sha = None if record is None else record.artifact_sha256
    if artifact_sha is None and pairs:
        artifact_sha = pairs[-1][0].artifact_sha256
    return {
        "project_id": project_id,
        "artifact_id": artifact_id,
        "source_asset_id": source_asset_id,
        "outcome_id": outcome_id,
        "snapshot_id": snapshot_id,
        "artifact_sha256": artifact_sha,
        "effective_label_set_id": history.effective_label_set_id,
        "entries": [item.model_dump(mode="json") for item in history.entries],
        "cache": cache,
    }


def comparison_document(
    database: Database,
    project_id: str,
    *,
    dimension: str,
    comparison_filter: ComparisonFilter,
) -> dict[str, object]:
    with database.connect() as connection:
        get_project(connection, project_id)
        pairs = _with_effective_labels(connection, project_id, _load_pairs(connection, project_id))
    document = compare_outcomes(
        project_id=project_id,
        dimension=dimension,
        pairs=pairs,
        comparison_filter=comparison_filter,
        created_at=_frozen(),
        created_by="analytics-page",
    )
    return _comparison_public(document.model_dump(mode="json"))


def _card(
    database: Database,
    work_root: Path,
    outcome: PerformanceOutcome,
    reviews: list[ReviewDecision],
) -> dict[str, object]:
    history = list_label_history(database, outcome.project_id, outcome.artifact_id)
    effective = history.entries[-1] if history.entries else None
    metrics = outcome.metrics.model_dump(mode="json")
    reported = [name for name in _METRIC_NAMES if metrics.get(name) is not None]
    missing = [name for name in _METRIC_NAMES if metrics.get(name) is None]
    warnings: list[str] = []
    if not outcome.media_available:
        warnings.append("media evidence is unavailable")
    record = expected_cache_record(database, work_root, outcome.project_id, outcome.artifact_id)
    if record is not None and label_cache_state(work_root, outcome.artifact_id, record) == "miss":
        warnings.append("label cache is stale")
    review_rows = []
    for review in reviews:
        if review.artifact_id != outcome.artifact_id:
            continue
        review_rows.append(
            {
                "review_id": review.review_id,
                "decision": review.decision,
                "reviewer_id": review.reviewer_id,
                "created_at": review.created_at.isoformat(),
            }
        )
    with database.connect() as connection:
        profile_id = import_profile_for_outcome(connection, outcome.project_id, outcome.outcome_id)
        snapshot = _snapshot_by_id(connection, outcome.snapshot_id)
    return {
        "project_id": outcome.project_id,
        "outcome_id": outcome.outcome_id,
        "platform": outcome.platform,
        "measurement_window": outcome.measurement_window,
        "observed_at": outcome.observed_at.isoformat(),
        "published_at": None if outcome.published_at is None else outcome.published_at.isoformat(),
        "artifact_id": outcome.artifact_id,
        "source_asset_id": outcome.source_asset_id,
        "artifact_available": "available" if outcome.media_available else "unavailable",
        "duration_us": outcome.duration_us,
        "metrics": {name: metrics.get(name) for name in _METRIC_NAMES},
        "metric_coverage": {"reported": len(reported), "missing": len(missing)},
        "missing_metrics": missing,
        "qa_policy": outcome.qa_policy,
        "qa_status": outcome.qa_status,
        "review_decision": outcome.human.review_decision,
        "review_history": review_rows,
        "labels": None if effective is None else effective.labels.model_dump(mode="json"),
        "label_notes": "" if effective is None else effective.notes,
        "label_history": [item.label_set_id for item in history.entries],
        "effective_label_set_id": history.effective_label_set_id,
        "import_profile_id": profile_id,
        "provenance_source_ids": list(outcome.provenance.source_asset_ids),
        "snapshot_id": outcome.snapshot_id,
        "artifact_sha256": outcome.artifact_sha256,
        "duration_bucket": None if snapshot is None else snapshot.duration_bucket,
        "warnings": warnings,
    }


def _comparison_public(payload: dict[str, object]) -> dict[str, object]:
    text = json.dumps(payload)
    if any(token in text for token in ("/tmp/", "/home/", "/Users/", "\\", "file:", "://")):
        raise AnalyticsError("comparison contained a forbidden path")
    return payload


def _frozen() -> datetime:
    return datetime.fromisoformat("2026-10-04T00:00:00+00:00")
