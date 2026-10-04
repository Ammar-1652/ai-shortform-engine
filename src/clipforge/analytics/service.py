"""Record and read local outcome observations. Rows are inserted, never updated."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from clipforge.analytics.compare import ComparisonFilter, compare_outcomes, format_comparison
from clipforge.analytics.features import ExtractedFeatures, extract_features
from clipforge.errors import ClipforgeError, StorageError
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import ensure_within
from clipforge.schemas.analytics import (
    AnalyticsComparison,
    AnalyticsImportRecord,
    AnalyticsObservationInput,
    EditorialFeatureSnapshot,
    ManualLabels,
    PerformanceOutcome,
)
from clipforge.schemas.jobs import JobStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.qa import QASetDocument
from clipforge.storage import (
    Database,
    find_artifact,
    get_artifact,
    get_job,
    get_project,
    get_review,
    get_source_asset,
    list_reviews,
)
from clipforge.storage.repository import ArtifactRow

_ADVANCED = "advanced_hero_draft_set_json"
_QA_KIND = "qa_set_json"


class AnalyticsError(ClipforgeError):
    """An observation cannot be recorded or does not verify. Nothing was published."""


def doctor_text() -> str:
    return "\n".join(
        [
            "PASS storage: one sqlite database",
            "PASS writes: append only",
            "PASS network: none",
            "PASS metrics: missing stays missing",
            "PASS use: descriptive evidence only",
        ]
    )


def load_observation(work_root: Path, path: Path) -> AnalyticsObservationInput:
    """Read one local observation. The path must be a regular file inside the work root."""
    root = work_root.resolve()
    _require_local_file(root, path)
    documents = _parse_file(path.read_bytes())
    if len(documents) != 1:
        raise AnalyticsError("record accepts one observation")
    return documents[0]


def record_outcome(
    database: Database,
    work_root: Path,
    observation: AnalyticsObservationInput,
    *,
    before_commit: Callable[[], None] | None = None,
) -> PerformanceOutcome:
    """Insert one observation, or return the original row when the same record is replayed."""
    prepared = _prepare(database, work_root, observation)
    with database.transaction() as connection:
        stored = _apply(connection, prepared, before_commit)
    return stored


def import_observations(
    database: Database,
    work_root: Path,
    path: Path,
    *,
    before_commit: Callable[[], None] | None = None,
) -> list[PerformanceOutcome]:
    """Validate a whole local file, then insert it in one transaction."""
    root = work_root.resolve()
    _require_local_file(root, path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    documents = _parse_file(raw)
    if not documents:
        raise AnalyticsError("import file has no observations")
    prepared = [_prepare(database, root, item) for item in documents]
    projects = {item.outcome.project_id for item in prepared}
    if len(projects) != 1:
        raise AnalyticsError("one import file cannot mix projects")
    keys = [item.outcome.idempotency_key for item in prepared]
    ids = [item.outcome.outcome_id for item in prepared]
    if len(keys) != len(set(keys)) or len(ids) != len(set(ids)):
        raise AnalyticsError("import file repeats an outcome id or idempotency key")
    modes = {item.replay for item in prepared}
    if modes == {True}:
        return [item.outcome for item in prepared]
    if False in modes and True in modes:
        raise AnalyticsError("import must be entirely new or an exact replay")
    created_by = documents[0].created_by
    observed = min(item.outcome.observed_at for item in prepared)
    with database.transaction() as connection:
        stored = [_apply(connection, item, None) for item in prepared]
        if before_commit is not None:
            before_commit()
        _insert_import(
            connection,
            AnalyticsImportRecord(
                import_id=digest,
                project_id=stored[0].project_id,
                content_sha256=digest,
                outcome_ids=[item.outcome_id for item in stored],
                created_at=observed,
                created_by=created_by,
                provenance=ArtifactProvenance(
                    created_at=observed,
                    created_by=created_by,
                    tool="clipforge-analytics",
                    tool_version="0",
                    source_asset_ids=[stored[0].source_asset_id],
                ),
            ),
        )
    return stored


def list_outcomes(
    database: Database,
    project_id: str,
    comparison_filter: ComparisonFilter | None = None,
) -> list[PerformanceOutcome]:
    chosen = comparison_filter or ComparisonFilter()
    with database.connect() as connection:
        rows = _load_pairs(connection, project_id)
    matched = [outcome for outcome, snapshot in rows if _kept(outcome, snapshot, chosen)]
    return sorted(matched, key=lambda item: (item.observed_at, item.outcome_id))


def show_outcome(database: Database, outcome_id: str) -> str:
    outcome, snapshot = _load_one(database, outcome_id)
    payload = {
        "outcome": outcome.model_dump(mode="json"),
        "snapshot": snapshot.model_dump(mode="json"),
    }
    return json.dumps(payload, sort_keys=True)


def verify_outcome(database: Database, work_root: Path, outcome_id: str) -> str:
    """Re-read one outcome. This does not write."""
    outcome, snapshot = _load_one(database, outcome_id)
    blob = outcome.model_dump_json() + snapshot.model_dump_json()
    if any(token in blob for token in ("/tmp/", "/home/", "/Users/", "\\", "://")):
        raise AnalyticsError("stored analytics record contains a forbidden path or URL")
    if outcome.snapshot_id != snapshot.snapshot_id:
        raise AnalyticsError("feature snapshot is not bound to this outcome")
    if outcome.artifact_id != snapshot.artifact_id or outcome.project_id != snapshot.project_id:
        raise AnalyticsError("outcome lineage does not match its feature snapshot")
    if outcome.artifact_sha256 != snapshot.artifact_sha256:
        raise AnalyticsError("outcome artifact hash does not match its feature snapshot")
    with database.connect() as connection:
        artifact = get_artifact(connection, outcome.artifact_id)
        _require_lineage(
            connection,
            artifact,
            outcome.project_id,
            outcome.source_asset_id,
            outcome.artifact_kind,
        )
        column_observed = connection.execute(
            "SELECT observed_at, idempotency_key FROM performance_outcomes WHERE outcome_id = ?",
            (outcome.outcome_id,),
        ).fetchone()
    if column_observed is None:
        raise AnalyticsError("outcome row is missing")
    if str(column_observed["idempotency_key"]) != outcome.idempotency_key:
        raise AnalyticsError("idempotency key does not match the stored outcome")
    if str(column_observed["observed_at"]) != outcome.observed_at.isoformat():
        raise AnalyticsError("observed time column does not match the stored outcome")
    _verify_review_and_qa(database, work_root.resolve(), outcome, artifact)
    file_state = _inspect_media(work_root.resolve(), artifact.uri, outcome.artifact_sha256)
    lines = ["PASS outcome", f"media_evidence: {file_state}"]
    return "\n".join(lines)


def _verify_review_and_qa(
    database: Database,
    root: Path,
    outcome: PerformanceOutcome,
    artifact: ArtifactRow,
) -> None:
    """Revalidate immutable review and QA references stored on an outcome."""
    with database.connect() as connection:
        if outcome.human.review_id is not None:
            try:
                review = get_review(connection, outcome.human.review_id)
            except StorageError as exc:
                raise AnalyticsError("stored review reference is missing") from exc
            if review.project_id != outcome.project_id:
                raise AnalyticsError("stored review belongs to a different project")
            if review.artifact_id is not None and review.artifact_id != artifact.artifact_id:
                raise AnalyticsError("stored review is bound to a different artifact")
            if (
                outcome.candidate_id is not None
                and review.candidate_id is not None
                and review.candidate_id != outcome.candidate_id
            ):
                raise AnalyticsError("stored review is bound to a different candidate")
            if outcome.human.review_decision != review.decision:
                raise AnalyticsError("stored review decision no longer matches the review row")
            if outcome.human.reviewer_id != review.reviewer_id:
                raise AnalyticsError("stored reviewer no longer matches the review row")

        if outcome.artifact_kind == _ADVANCED and outcome.qa_policy == "not_required":
            raise AnalyticsError("advanced Hero outcomes require historical or current QA evidence")
        if outcome.qa_policy == "not_required":
            return
        if outcome.qa_artifact_id is None:
            raise AnalyticsError("stored QA reference is missing")
        try:
            qa_row = get_artifact(connection, outcome.qa_artifact_id)
            qa_job = get_job(connection, qa_row.job_id or "")
        except StorageError as exc:
            raise AnalyticsError("stored QA reference is missing") from exc
        if qa_row.kind != _QA_KIND:
            raise AnalyticsError("stored QA artifact kind does not match")
        if qa_row.project_id != outcome.project_id or qa_row.source_asset_id != outcome.source_asset_id:
            raise AnalyticsError("stored QA artifact lineage does not match the outcome")
        if qa_job.project_id != outcome.project_id or qa_job.status is not JobStatus.SUCCEEDED:
            raise AnalyticsError("stored QA producer is not a succeeded job")
        if outcome.qa_policy == "current":
            current = find_artifact(connection, outcome.project_id, outcome.source_asset_id, _QA_KIND)
            if current is None or current.artifact_id != qa_row.artifact_id:
                raise AnalyticsError("stored QA artifact is no longer current")
        document = _read_json(root, qa_row.uri)
    if document is None:
        if outcome.qa_policy == "current":
            raise AnalyticsError("current QA evidence file is unavailable")
        if outcome.qa_status != "unavailable":
            raise AnalyticsError("historical QA evidence is unavailable but the stored status disagrees")
        return
    try:
        parsed = QASetDocument.model_validate(document)
    except ValidationError as exc:
        raise AnalyticsError("QA evidence file does not match the QA set contract") from exc
    if (
        parsed.project_id != outcome.project_id
        or parsed.source_asset_id != outcome.source_asset_id
        or parsed.target_artifact_id != artifact.artifact_id
        or parsed.target_artifact_kind != artifact.kind
    ):
        raise AnalyticsError("QA evidence is bound to a different artifact")
    if outcome.qa_status != parsed.status.value:
        raise AnalyticsError("stored QA status no longer matches the QA evidence")


def compare_project(
    database: Database,
    project_id: str,
    *,
    dimension: str,
    comparison_filter: ComparisonFilter | None = None,
    created_by: str,
) -> AnalyticsComparison:
    chosen = comparison_filter or ComparisonFilter()
    with database.connect() as connection:
        pairs = _load_pairs(connection, project_id)
    return compare_outcomes(
        project_id=project_id,
        dimension=dimension,
        pairs=pairs,
        comparison_filter=chosen,
        created_at=datetime.fromisoformat("2026-10-04T00:00:00+00:00"),
        created_by=created_by,
    )


def format_project_comparison(document: AnalyticsComparison) -> str:
    return format_comparison(document)


class _Prepared:
    def __init__(
        self,
        outcome: PerformanceOutcome,
        snapshot: EditorialFeatureSnapshot,
        replay: bool,
    ) -> None:
        self.outcome = outcome
        self.snapshot = snapshot
        self.replay = replay


def _prepare(database: Database, work_root: Path, observation: AnalyticsObservationInput) -> _Prepared:
    root = work_root.resolve()
    with database.connect() as connection:
        try:
            artifact = get_artifact(connection, observation.artifact_id)
        except StorageError as exc:
            raise AnalyticsError(str(exc)) from exc
        _require_lineage(
            connection,
            artifact,
            observation.project_id,
            observation.source_asset_id,
            observation.artifact_kind,
        )
        review = _review(connection, observation, artifact)
        qa_status = _qa(connection, root, observation, artifact)
        project = get_project(connection, observation.project_id)
    media_available, document = _read_artifact(root, artifact, observation.artifact_sha256)
    try:
        extracted = extract_features(document, candidate_id=observation.candidate_id)
    except ValueError as exc:
        raise AnalyticsError(str(exc)) from exc
    _check_hashes(observation, extracted, media_available)
    duration = extracted.duration_us if extracted.duration_us is not None else observation.duration_us
    if (
        observation.duration_us is not None
        and extracted.duration_us is not None
        and observation.duration_us != extracted.duration_us
    ):
        raise AnalyticsError("duration does not match the artifact time map")
    if (
        observation.candidate_media_sha256 is not None
        and extracted.candidate_media_sha256 != observation.candidate_media_sha256
    ):
        raise AnalyticsError("candidate media hash does not match the artifact")
    decision = review[0] if review is not None else None
    reviewer = review[1] if review is not None else observation.human.reviewer_id
    if (
        observation.human.review_decision is not None
        and decision is not None
        and observation.human.review_decision != decision
    ):
        raise AnalyticsError("analytics review decision does not match the review row")
    present = _review_presence(database, artifact, observation)
    labels = observation.labels
    snapshot = _snapshot(
        observation,
        extracted,
        duration,
        media_available,
        project.profile_id,
        present,
        decision if decision is not None else observation.human.review_decision,
        labels,
    )
    human = observation.human.model_copy(
        update={
            "review_decision": decision if decision is not None else observation.human.review_decision,
            "reviewer_id": reviewer,
        }
    )
    outcome = PerformanceOutcome(
        outcome_id=observation.outcome_id,
        project_id=observation.project_id,
        source_asset_id=observation.source_asset_id,
        artifact_id=observation.artifact_id,
        artifact_kind=artifact.kind,
        snapshot_id=snapshot.snapshot_id,
        candidate_id=observation.candidate_id,
        artifact_sha256=observation.artifact_sha256,
        manifest_sha256=observation.manifest_sha256 or extracted.manifest_sha256,
        media_available=media_available,
        duration_us=duration,
        platform=observation.platform,
        platform_post_id=observation.platform_post_id,
        campaign_id=observation.campaign_id,
        geography=observation.geography,
        published_at=observation.published_at,
        observed_at=observation.observed_at,
        measurement_window=observation.measurement_window,
        metrics=observation.metrics,
        human=human,
        qa_policy=observation.qa_policy,
        qa_artifact_id=observation.qa_artifact_id,
        qa_status=qa_status,
        idempotency_key=observation.idempotency_key,
        provenance=_actor_provenance(observation),
    )
    replay = _replay_status(database, outcome, snapshot)
    return _Prepared(outcome, snapshot, replay)


def _require_lineage(
    connection: object,
    artifact: ArtifactRow,
    project_id: str,
    source_asset_id: str,
    artifact_kind: str,
) -> None:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        raise AnalyticsError("internal connection was not a database connection")
    if artifact.project_id != project_id:
        raise AnalyticsError("artifact belongs to a different project")
    if artifact.source_asset_id != source_asset_id:
        raise AnalyticsError("artifact belongs to a different source")
    if artifact.kind != artifact_kind:
        raise AnalyticsError("artifact kind does not match the observation")
    if artifact.job_id is None:
        raise AnalyticsError("artifact has no producing job")
    try:
        source = get_source_asset(connection, source_asset_id)
        job = get_job(connection, artifact.job_id)
    except StorageError as exc:
        raise AnalyticsError(str(exc)) from exc
    if source.project_id != project_id:
        raise AnalyticsError("source belongs to a different project")
    if job.project_id != project_id or job.status is not JobStatus.SUCCEEDED:
        raise AnalyticsError("artifact producer is not a succeeded job in this project")
    if artifact.provenance.job_id != job.job_id:
        raise AnalyticsError("artifact provenance does not match its producing job")


def _review(
    connection: object,
    observation: AnalyticsObservationInput,
    artifact: ArtifactRow,
) -> tuple[str, str] | None:
    from sqlite3 import Connection

    if not isinstance(connection, Connection) or observation.human.review_id is None:
        return None
    try:
        review = get_review(connection, observation.human.review_id)
    except StorageError as exc:
        raise AnalyticsError(str(exc)) from exc
    if review.project_id != observation.project_id:
        raise AnalyticsError("review belongs to a different project")
    if review.artifact_id is not None and review.artifact_id != artifact.artifact_id:
        raise AnalyticsError("review is bound to a different artifact")
    if (
        observation.candidate_id is not None
        and review.candidate_id is not None
        and review.candidate_id != observation.candidate_id
    ):
        raise AnalyticsError("review is bound to a different candidate")
    return review.decision, review.reviewer_id


def _review_presence(
    database: Database,
    artifact: ArtifactRow,
    observation: AnalyticsObservationInput,
) -> bool | None:
    if observation.human.review_id is not None:
        return True
    with database.connect() as connection:
        reviews = list_reviews(connection, observation.project_id)
    matched = [item for item in reviews if item.artifact_id == artifact.artifact_id]
    return bool(matched)


def _qa(
    connection: object,
    root: Path,
    observation: AnalyticsObservationInput,
    artifact: ArtifactRow,
) -> Literal["pass", "fail", "insufficient_evidence", "unavailable"] | None:
    from sqlite3 import Connection

    if observation.artifact_kind == _ADVANCED and observation.qa_policy == "not_required":
        raise AnalyticsError("advanced Hero outcomes require historical or current QA evidence")
    if observation.qa_policy == "not_required":
        return None
    if not isinstance(connection, Connection) or observation.qa_artifact_id is None:
        raise AnalyticsError("QA artifact id is required")
    try:
        qa_row = get_artifact(connection, observation.qa_artifact_id)
        job = get_job(connection, qa_row.job_id or "")
    except StorageError as exc:
        raise AnalyticsError(str(exc)) from exc
    if qa_row.kind != _QA_KIND or qa_row.project_id != observation.project_id:
        raise AnalyticsError("QA artifact is not a QA set in this project")
    if qa_row.source_asset_id != observation.source_asset_id:
        raise AnalyticsError("QA artifact belongs to a different source")
    if job.status is not JobStatus.SUCCEEDED or job.project_id != observation.project_id:
        raise AnalyticsError("QA producer is not a succeeded job")
    if observation.qa_policy == "current":
        current = find_artifact(connection, observation.project_id, observation.source_asset_id, _QA_KIND)
        if current is None or current.artifact_id != qa_row.artifact_id:
            raise AnalyticsError("QA artifact is not the current QA set")
    document = _read_json(root, qa_row.uri)
    if document is None:
        if observation.qa_policy == "current":
            raise AnalyticsError("current QA evidence file is unavailable")
        return "unavailable"
    try:
        parsed = QASetDocument.model_validate(document)
    except ValidationError as exc:
        raise AnalyticsError("QA evidence file does not match the QA set contract") from exc
    if parsed.target_artifact_id != artifact.artifact_id or parsed.project_id != observation.project_id:
        raise AnalyticsError("QA evidence is bound to a different artifact")
    status = parsed.status.value
    if status == "pass":
        return "pass"
    if status == "fail":
        return "fail"
    if status == "insufficient_evidence":
        return "insufficient_evidence"
    raise AnalyticsError("QA status is not a known value")


def _read_artifact(
    root: Path,
    artifact: ArtifactRow,
    expected_sha: str,
) -> tuple[bool, dict[str, object] | None]:
    path = _contained_file(root, artifact.uri)
    if path is None:
        return False, None
    digest = sha256_file(path)
    if digest != expected_sha:
        raise AnalyticsError("artifact file hash does not match the observation")
    if path.suffix != ".json" and not artifact.kind.endswith("json"):
        return True, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnalyticsError("artifact JSON could not be read") from exc
    if not isinstance(payload, dict):
        raise AnalyticsError("artifact JSON must be an object")
    return True, payload


def _read_json(root: Path, uri: str) -> dict[str, object] | None:
    path = _contained_file(root, uri)
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _contained_file(root: Path, uri: str) -> Path | None:
    if not uri.startswith("file:"):
        raise AnalyticsError("artifact URI is not a local file reference")
    path = path_from_file_uri(uri)
    if path.is_symlink():
        raise AnalyticsError("artifact file is a symlink")
    try:
        ensure_within(root, path)
    except ClipforgeError as exc:
        raise AnalyticsError("artifact file is outside the work root") from exc
    if not path.exists():
        return None
    if not path.is_file():
        raise AnalyticsError("artifact file is not a regular file")
    return path


def _check_hashes(
    observation: AnalyticsObservationInput,
    extracted: ExtractedFeatures,
    media_available: bool,
) -> None:
    if (
        observation.manifest_sha256 is not None
        and extracted.manifest_sha256 is not None
        and observation.manifest_sha256 != extracted.manifest_sha256
    ):
        raise AnalyticsError("manifest hash does not match the artifact")
    if (
        observation.manifest_sha256 is not None
        and media_available
        and extracted.manifest_sha256 is None
        and observation.manifest_sha256 != observation.artifact_sha256
    ):
        raise AnalyticsError("manifest hash does not match the artifact file")


def _snapshot(
    observation: AnalyticsObservationInput,
    extracted: ExtractedFeatures,
    duration: int | None,
    media_available: bool,
    project_profile: str | None,
    review_present: bool | None,
    decision: str | None,
    labels: ManualLabels,
) -> EditorialFeatureSnapshot:
    profile_id = extracted.profile_id or project_profile
    body = {
        "project_id": observation.project_id,
        "source_asset_id": observation.source_asset_id,
        "artifact_id": observation.artifact_id,
        "artifact_kind": observation.artifact_kind,
        "observed_at": observation.observed_at.isoformat(),
        "artifact_sha256": observation.artifact_sha256,
        "manifest_sha256": observation.manifest_sha256 or extracted.manifest_sha256,
        "media_available": media_available,
        "candidate_id": observation.candidate_id,
        "duration_us": duration,
        "duration_bucket": _bucket(duration),
        "candidate_rank": extracted.candidate_rank,
        "rank_band": _rank_band(extracted.candidate_rank),
        "creative_score": extracted.creative_score,
        "edit_opportunity_score": extracted.edit_opportunity_score,
        "transcript_word_count": extracted.transcript_word_count,
        "caption_count": extracted.caption_count,
        "caption_style": extracted.caption_style,
        "caption_algorithm_version": extracted.caption_algorithm_version,
        "alignment_quality": extracted.alignment_quality,
        "profile_id": profile_id,
        "profile_sha256": extracted.profile_sha256,
        "policy_ids": list(extracted.policy_ids),
        "motion_library_version": extracted.motion_library_version,
        "renderer_recipe": extracted.renderer_recipe,
        "reframing_strategy": extracted.reframing_strategy,
        "broll_count": extracted.broll_count,
        "broll_duration_us": extracted.broll_duration_us,
        "sfx_count": extracted.sfx_count,
        "sfx_duration_us": extracted.sfx_duration_us,
        "sfx_roles": list(extracted.sfx_roles),
        "sfx_gain_min_db": extracted.sfx_gain_min_db,
        "sfx_gain_max_db": extracted.sfx_gain_max_db,
        "typography_count": extracted.typography_count,
        "diagram_count": extracted.diagram_count,
        "emphasis_count": extracted.emphasis_count,
        "evidence_sha256": list(extracted.evidence_sha256),
        "human_review_present": review_present,
        "human_decision": decision,
        "labels": labels.model_dump(mode="json"),
        "platform": observation.platform,
        "geography": observation.geography,
        "campaign_id": observation.campaign_id,
    }
    snapshot_id = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    body["snapshot_id"] = snapshot_id
    body["provenance"] = _actor_provenance(observation).model_dump(mode="json")
    return EditorialFeatureSnapshot.model_validate(body)


def _actor_provenance(observation: AnalyticsObservationInput) -> ArtifactProvenance:
    return ArtifactProvenance(
        created_at=observation.observed_at,
        created_by=observation.created_by,
        tool="clipforge-analytics",
        tool_version="0",
        source_asset_ids=[observation.source_asset_id],
    )


def _replay_status(
    database: Database,
    outcome: PerformanceOutcome,
    snapshot: EditorialFeatureSnapshot,
) -> bool:
    with database.connect() as connection:
        existing = _outcome_by_key(connection, outcome.idempotency_key)
        by_id = _outcome_by_id(connection, outcome.outcome_id)
    if existing is None and by_id is None:
        return False
    if existing is None or by_id is None or existing.outcome_id != outcome.outcome_id:
        raise AnalyticsError("idempotency key or outcome id already belongs to a different record")
    if _canonical(existing) != _canonical(outcome):
        raise AnalyticsError("idempotency key already belongs to a different record")
    with database.connect() as connection:
        stored_snapshot = _snapshot_by_id(connection, snapshot.snapshot_id)
    if stored_snapshot is None or _canonical_snapshot(stored_snapshot) != _canonical_snapshot(snapshot):
        raise AnalyticsError("feature snapshot does not match the original observation")
    return True


def _apply(
    connection: object,
    prepared: _Prepared,
    before_commit: Callable[[], None] | None,
) -> PerformanceOutcome:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        raise AnalyticsError("internal connection was not a database connection")
    if prepared.replay:
        if before_commit is not None:
            before_commit()
        return prepared.outcome
    if _snapshot_by_id(connection, prepared.snapshot.snapshot_id) is None:
        _insert_snapshot(connection, prepared.snapshot)
    _insert_outcome(connection, prepared.outcome)
    if before_commit is not None:
        before_commit()
    return prepared.outcome


def _inspect_media(root: Path, uri: str, expected: str) -> str:
    path = _contained_file(root, uri)
    if path is None:
        return "unavailable"
    if sha256_file(path) != expected:
        raise AnalyticsError("artifact file hash does not match the stored outcome")
    return "available"


def _bucket(duration_us: int | None) -> str | None:
    if duration_us is None:
        return None
    seconds = duration_us / 1_000_000
    if seconds < 15:
        return "0-15s"
    if seconds < 30:
        return "15-30s"
    if seconds < 60:
        return "30-60s"
    if seconds < 180:
        return "60-180s"
    return "180s+"


def _rank_band(rank: int | None) -> str | None:
    if rank is None:
        return None
    if rank == 1:
        return "1"
    if rank <= 3:
        return "2-3"
    if rank <= 10:
        return "4-10"
    return "11+"


def _canonical(outcome: PerformanceOutcome) -> str:
    return json.dumps(outcome.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _canonical_snapshot(snapshot: EditorialFeatureSnapshot) -> str:
    return json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _kept(
    outcome: PerformanceOutcome,
    snapshot: EditorialFeatureSnapshot,
    chosen: ComparisonFilter,
) -> bool:
    from clipforge.analytics.compare import _matches

    return _matches(outcome, snapshot, chosen)


def _load_one(database: Database, outcome_id: str) -> tuple[PerformanceOutcome, EditorialFeatureSnapshot]:
    with database.connect() as connection:
        outcome = _outcome_by_id(connection, outcome_id)
        if outcome is None:
            raise AnalyticsError(f"no outcome {outcome_id}")
        snapshot = _snapshot_by_id(connection, outcome.snapshot_id)
    if snapshot is None:
        raise AnalyticsError("feature snapshot row is missing")
    return outcome, snapshot


def _load_pairs(
    connection: object, project_id: str
) -> list[tuple[PerformanceOutcome, EditorialFeatureSnapshot]]:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        raise AnalyticsError("internal connection was not a database connection")
    rows = connection.execute(
        """
        SELECT document_json FROM performance_outcomes
        WHERE project_id = ?
        ORDER BY observed_at, outcome_id
        """,
        (project_id,),
    ).fetchall()
    pairs: list[tuple[PerformanceOutcome, EditorialFeatureSnapshot]] = []
    for row in rows:
        outcome = PerformanceOutcome.model_validate_json(str(row["document_json"]))
        snapshot = _snapshot_by_id(connection, outcome.snapshot_id)
        if snapshot is None:
            raise AnalyticsError("feature snapshot row is missing")
        pairs.append((outcome, snapshot))
    return pairs


def _outcome_by_id(connection: object, outcome_id: str) -> PerformanceOutcome | None:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        return None
    row = connection.execute(
        "SELECT document_json FROM performance_outcomes WHERE outcome_id = ?",
        (outcome_id,),
    ).fetchone()
    if row is None:
        return None
    return PerformanceOutcome.model_validate_json(str(row["document_json"]))


def _outcome_by_key(connection: object, key: str) -> PerformanceOutcome | None:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        return None
    row = connection.execute(
        "SELECT document_json FROM performance_outcomes WHERE idempotency_key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    return PerformanceOutcome.model_validate_json(str(row["document_json"]))


def _snapshot_by_id(connection: object, snapshot_id: str) -> EditorialFeatureSnapshot | None:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        return None
    row = connection.execute(
        "SELECT document_json FROM editorial_feature_snapshots WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchone()
    if row is None:
        return None
    return EditorialFeatureSnapshot.model_validate_json(str(row["document_json"]))


def _insert_snapshot(connection: object, snapshot: EditorialFeatureSnapshot) -> None:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        raise AnalyticsError("internal connection was not a database connection")
    connection.execute(
        """
        INSERT INTO editorial_feature_snapshots (
            snapshot_id, project_id, source_asset_id, artifact_id, artifact_sha256,
            document_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.snapshot_id,
            snapshot.project_id,
            snapshot.source_asset_id,
            snapshot.artifact_id,
            snapshot.artifact_sha256,
            _canonical_snapshot(snapshot),
            snapshot.observed_at.isoformat(),
        ),
    )


def _insert_outcome(connection: object, outcome: PerformanceOutcome) -> None:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        raise AnalyticsError("internal connection was not a database connection")
    connection.execute(
        """
        INSERT INTO performance_outcomes (
            outcome_id, project_id, source_asset_id, artifact_id, snapshot_id,
            idempotency_key, observed_at, document_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            outcome.outcome_id,
            outcome.project_id,
            outcome.source_asset_id,
            outcome.artifact_id,
            outcome.snapshot_id,
            outcome.idempotency_key,
            outcome.observed_at.isoformat(),
            _canonical(outcome),
            outcome.observed_at.isoformat(),
        ),
    )


def _insert_import(connection: object, record: AnalyticsImportRecord) -> None:
    from sqlite3 import Connection

    if not isinstance(connection, Connection):
        raise AnalyticsError("internal connection was not a database connection")
    connection.execute(
        """
        INSERT INTO analytics_imports (
            import_id, project_id, content_sha256, outcome_count, created_at, created_by
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            record.import_id,
            record.project_id,
            record.content_sha256,
            len(record.outcome_ids),
            record.created_at.isoformat(),
            record.created_by,
        ),
    )


def _require_local_file(root: Path, path: Path) -> None:
    if "\\" in str(path) or ".." in path.parts:
        raise AnalyticsError("import path is not allowed")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise AnalyticsError("import file is outside the work root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise AnalyticsError("import path is a symlink")
    if not path.is_file():
        raise AnalyticsError("import file is missing")
    try:
        ensure_within(root, path)
    except ClipforgeError as exc:
        raise AnalyticsError("import file is outside the work root") from exc


def _parse_file(raw: bytes) -> list[AnalyticsObservationInput]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise AnalyticsError("import file is not utf-8") from exc
    stripped = text.strip()
    if not stripped:
        raise AnalyticsError("import file is empty")
    try:
        if stripped.startswith("["):
            payload = json.loads(stripped)
            if not isinstance(payload, list):
                raise AnalyticsError("import JSON must be a list or one object per line")
            rows = payload
        elif stripped.startswith("{") and "\n" not in stripped:
            rows = [json.loads(stripped)]
        else:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise AnalyticsError("import file is not valid JSON") from exc
    documents: list[AnalyticsObservationInput] = []
    try:
        for row in rows:
            documents.append(AnalyticsObservationInput.model_validate(row))
    except ValidationError as exc:
        raise AnalyticsError(_public_validation(exc)) from exc
    return documents


def _public_validation(exc: ValidationError) -> str:
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        messages.append(f"{location}: {error['msg']}")
    text = "; ".join(messages)[:500]
    if any(token in text for token in ("/tmp/", "/home/", "\\")):
        return "import row failed validation"
    return text or "import row failed validation"
