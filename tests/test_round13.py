"""Append-only analytics: migration, import, binding, comparison, and read-only checks."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.analytics.compare import ComparisonFilter, compare_outcomes
from clipforge.analytics.service import (
    AnalyticsError,
    compare_project,
    doctor_text,
    import_observations,
    list_outcomes,
    record_outcome,
    show_outcome,
    verify_outcome,
)
from clipforge.schemas.analytics import AnalyticsObservationInput, ManualLabels, PerformanceMetrics
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimelineSegment, TimeMapDocument
from clipforge.storage import (
    Database,
    get_job,
    get_review,
    insert_artifact,
    insert_asset_license_record,
    insert_job,
    insert_project,
    insert_review,
    insert_source_asset,
    insert_source_manifest,
)
from clipforge.storage.db import _execute_script, _prepare
from clipforge.storage.migrations import MIGRATIONS
from tests.helpers import license_record, provenance, stamp

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def test_schema_rejects_bad_metrics_and_unsafe_text() -> None:
    with pytest.raises(ValidationError):
        PerformanceMetrics(views=-1)
    with pytest.raises(ValidationError):
        PerformanceMetrics(views=2, completion_count=3)
    with pytest.raises(ValidationError):
        PerformanceMetrics(completion_rate="1.2")
    with pytest.raises(ValidationError):
        PerformanceMetrics(revenue_amount="-1.00", revenue_currency="USD")
    with pytest.raises(ValidationError):
        ManualLabels(hook_type="<script>alert(1)</script>")
    with pytest.raises(ValidationError):
        ManualLabels(topic_tags=["viewer_id"])
    observation = _input()
    assert observation.metrics.views is None
    assert observation.metrics.model_dump().get("likes") is None


def test_migration_from_version_4_preserves_rows_and_rejects_the_future(tmp_path: Path) -> None:
    path = tmp_path / "v4.sqlite3"
    connection = sqlite3.connect(path)
    _prepare(connection)
    connection.execute("BEGIN IMMEDIATE")
    now = stamp().isoformat()
    for migration in MIGRATIONS:
        if migration.version >= 5:
            break
        if migration.precheck is not None:
            migration.precheck(connection)
        _execute_script(connection, migration.sql)
        connection.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.name, now),
        )
    connection.execute("PRAGMA user_version = 4")
    connection.execute(
        """
        INSERT INTO projects (
            project_id, name, schema_version, profile_id, created_at, provenance_json, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "project-keep",
            "Keep",
            "1.0.0",
            None,
            now,
            json.dumps(provenance().model_dump(mode="json")),
            "{}",
        ),
    )
    connection.commit()
    connection.close()
    database = Database(path)
    assert database.initialize() == 7
    database.health_check()
    with database.connect() as checked:
        assert checked.execute("SELECT name FROM projects").fetchone()["name"] == "Keep"
        assert checked.execute("SELECT COUNT(*) FROM performance_outcomes").fetchone()[0] == 0
        assert checked.execute("SELECT COUNT(*) FROM editorial_label_sets").fetchone()[0] == 0
    with database.connect() as checked:
        checked.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (8, 'future', ?)",
            (now,),
        )
        checked.execute("PRAGMA user_version = 8")
        checked.commit()
    with pytest.raises(Exception, match="newer than this build"):
        Database(path).status()


def test_import_is_atomic_append_only_and_replays(tmp_path: Path) -> None:
    database, work, digest = _ready(tmp_path)
    second = _payload(digest, outcome_id="outcome-2", key="idem-key-2", views=4)
    path = _write_import(work, [_payload(digest), second])
    stored = import_observations(database, work, path)
    assert [item.outcome_id for item in stored] == ["outcome-1", "outcome-2"]
    again = import_observations(database, work, path)
    assert [item.outcome_id for item in again] == ["outcome-1", "outcome-2"]
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM performance_outcomes").fetchone()[0] == 2
    changed = _payload(digest, views=9)
    changed["idempotency_key"] = "idem-key-1"
    bad = work / "changed.json"
    bad.write_text(json.dumps([changed]), encoding="utf-8")
    with pytest.raises(AnalyticsError, match="different record"):
        import_observations(database, work, bad)
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM performance_outcomes").fetchone()[0] == 2
    later = _payload(digest, outcome_id="outcome-3", key="idem-key-3", views=4)
    later["observed_at"] = "2026-10-05T00:00:00+00:00"
    correction = work / "correction.json"
    correction.write_text(json.dumps([later]), encoding="utf-8")
    import_observations(database, work, correction)
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM performance_outcomes").fetchone()[0] == 3
    partial = work / "partial.jsonl"
    partial.write_text(
        json.dumps(_payload(digest, outcome_id="outcome-4", key="idem-key-4"))
        + "\n"
        + json.dumps(_payload(digest, outcome_id="outcome-5", key="idem-key-5", platform="BAD PLATFORM"))
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(AnalyticsError):
        import_observations(database, work, partial)
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM performance_outcomes").fetchone()[0] == 3

    def cancel() -> None:
        raise RuntimeError("cancelled before commit")

    doomed = work / "cancel.json"
    doomed.write_text(
        json.dumps([_payload(digest, outcome_id="outcome-6", key="idem-key-6")]),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="cancelled"):
        import_observations(database, work, doomed, before_commit=cancel)
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM performance_outcomes").fetchone()[0] == 3


def test_binding_hash_review_and_missing_media(tmp_path: Path) -> None:
    database, work, digest = _ready(tmp_path)
    observation = AnalyticsObservationInput.model_validate(_payload(digest, candidate_id="cand-1"))
    outcome = record_outcome(database, work, observation)
    assert outcome.media_available is True
    assert outcome.candidate_id == "cand-1"
    shown = show_outcome(database, outcome.outcome_id)
    assert "/tmp/" not in shown
    assert "://" not in shown
    text = verify_outcome(database, work, outcome.outcome_id)
    assert "media_evidence: available" in text
    media = work / "artifact.json"
    media.write_text(media.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(AnalyticsError, match="hash"):
        record_outcome(
            database,
            work,
            AnalyticsObservationInput.model_validate(
                _payload(digest, outcome_id="outcome-stale", key="idem-stale-1")
            ),
        )
    media.unlink()
    missing = record_outcome(
        database,
        work,
        AnalyticsObservationInput.model_validate(
            _payload(digest, outcome_id="outcome-gone", key="idem-gone-01")
        ),
    )
    assert missing.media_available is False
    assert "unavailable" in verify_outcome(database, work, missing.outcome_id)
    crossed = _payload(digest, outcome_id="outcome-cross", key="idem-cross-1")
    crossed["project_id"] = "project-2"
    with pytest.raises(AnalyticsError, match="project"):
        record_outcome(database, work, AnalyticsObservationInput.model_validate(crossed))
    other_source = _payload(digest, outcome_id="outcome-source", key="idem-source1")
    other_source["source_asset_id"] = "source-2"
    with pytest.raises(AnalyticsError, match="source"):
        record_outcome(database, work, AnalyticsObservationInput.model_validate(other_source))
    with pytest.raises(AnalyticsError, match="no artifact"):
        record_outcome(
            database,
            work,
            AnalyticsObservationInput.model_validate(
                _payload("a" * 64, artifact_id="missing-art", outcome_id="outcome-miss", key="idem-miss-01")
            ),
        )


def test_feature_snapshot_is_deterministic_and_comparison_skips_missing_values(tmp_path: Path) -> None:
    database, work, digest = _ready(tmp_path, features=True)
    first = record_outcome(
        database,
        work,
        AnalyticsObservationInput.model_validate(
            _payload(
                digest,
                candidate_id="cand-1",
                candidate_media_sha256="ab" * 32,
                views=10,
                completion_rate="0.5",
                completion_count=5,
                revenue="0.10",
            )
        ),
    )
    second = record_outcome(
        database,
        work,
        AnalyticsObservationInput.model_validate(
            _payload(
                digest,
                outcome_id="outcome-b",
                key="idem-key-b1",
                platform="reel",
                views=None,
                revenue="0.20",
            )
        ),
    )
    assert first.snapshot_id != second.snapshot_id
    replay = record_outcome(
        database,
        work,
        AnalyticsObservationInput.model_validate(
            _payload(
                digest,
                candidate_id="cand-1",
                candidate_media_sha256="ab" * 32,
                views=10,
                completion_rate="0.5",
                completion_count=5,
                revenue="0.10",
            )
        ),
    )
    assert replay.snapshot_id == first.snapshot_id
    document = compare_project(
        database,
        "project-1",
        dimension="platform",
        created_by="ada",
    )
    assert document.provenance.source_asset_ids == ["source-1"]
    assert [item.key for item in document.cohorts] == ["reel", "tiktok"]
    tiktok = next(item for item in document.cohorts if item.key == "tiktok")
    reel = next(item for item in document.cohorts if item.key == "reel")
    assert tiktok.aggregate.views_count == 1
    assert tiktok.aggregate.views_total == 10
    assert reel.aggregate.views_total is None
    assert reel.aggregate.missing_views == 1
    assert tiktok.aggregate.completion_rate_count == 1
    assert reel.aggregate.completion_rate_mean is None
    assert tiktok.aggregate.revenue_total == "0.1"
    assert reel.aggregate.revenue_total == "0.2"
    empty = compare_project(
        database,
        "project-1",
        dimension="platform",
        comparison_filter=ComparisonFilter(geography="ZZ"),
        created_by="ada",
    )
    assert empty.status == "insufficient_evidence"
    assert empty.cohorts == []
    text = doctor_text()
    assert "viral" not in text
    assert "best" not in text
    shown = show_outcome(database, first.outcome_id)
    assert "cand-1" in shown
    assert "0-15s" in shown
    assert "broll_count" in shown


def test_read_only_commands_do_not_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, work, digest = _ready(tmp_path)
    outcome = record_outcome(database, work, AnalyticsObservationInput.model_validate(_payload(digest)))
    before = database.path.read_bytes()
    artifact_before = (work / "artifact.json").read_bytes()

    def forbid_write(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("read-only command opened a write transaction")

    monkeypatch.setattr(database, "transaction", forbid_write)
    assert list_outcomes(database, "project-1")
    show_outcome(database, outcome.outcome_id)
    verify_outcome(database, work, outcome.outcome_id)
    compare_project(database, "project-1", dimension="platform", created_by="ada")
    doctor_text()
    assert database.path.read_bytes() == before
    assert (work / "artifact.json").read_bytes() == artifact_before
    with database.connect() as connection:
        assert get_job(connection, "job-1").status is JobStatus.SUCCEEDED


def test_import_path_and_label_rejection(tmp_path: Path) -> None:
    database, work, digest = _ready(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps([_payload(digest, outcome_id="outcome-out", key="idem-out-01")]),
        encoding="utf-8",
    )
    with pytest.raises(AnalyticsError, match="outside"):
        import_observations(database, work, outside)
    link = work / "linked.json"
    real = work / "real.json"
    real.write_text("{}", encoding="utf-8")
    link.symlink_to(real)
    with pytest.raises(AnalyticsError, match="symlink"):
        import_observations(database, work, link)
    nested = work / "inbound"
    nested.mkdir()
    linked_dir = work / "alias"
    linked_dir.symlink_to(nested, target_is_directory=True)
    planted = linked_dir / "rows.json"
    planted.write_text(
        json.dumps([_payload(digest, outcome_id="outcome-link", key="idem-link-1")]),
        encoding="utf-8",
    )
    with pytest.raises(AnalyticsError, match="symlink"):
        import_observations(database, work, planted)
    with pytest.raises(AnalyticsError, match="not allowed"):
        import_observations(database, work, work / ".." / "outside.json")
    remote = _payload(digest, outcome_id="outcome-url", key="idem-url-001")
    remote["platform_post_id"] = "https://example.invalid/post"
    with pytest.raises(ValidationError):
        AnalyticsObservationInput.model_validate(remote)
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM performance_outcomes").fetchone()[0] == 0


def test_analytics_package_does_not_call_the_network() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in Path("src/clipforge/analytics").glob("*.py"))
    for banned in ("urllib", "httpx", "requests", "socket", "UPDATE ", "DELETE "):
        assert banned not in text
    pairs: list[tuple[object, object]] = []
    document = compare_outcomes(
        project_id="project-1",
        dimension="platform",
        pairs=pairs,  # type: ignore[arg-type]
        comparison_filter=ComparisonFilter(),
        created_at=datetime(2026, 10, 4, tzinfo=UTC),
        created_by="ada",
    )
    assert document.status == "insufficient_evidence"


def test_review_snapshot_does_not_change_the_review_row(tmp_path: Path) -> None:
    database, work, digest = _ready(tmp_path)
    from clipforge.schemas.governance import ReviewDecision

    review = ReviewDecision(
        review_id="review-1",
        project_id="project-1",
        artifact_id="artifact-1",
        candidate_id="cand-1",
        subject_kind="candidate",
        decision="approved",
        reviewer_id="ada",
        created_at=stamp(),
        notes="looks fine",
    )
    with database.transaction() as connection:
        insert_review(connection, review)
    payload = _payload(digest, candidate_id="cand-1", candidate_media_sha256="ab" * 32)
    payload["human"] = {"review_id": "review-1", "review_decision": "approved", "reviewer_id": "ada"}
    outcome = record_outcome(database, work, AnalyticsObservationInput.model_validate(payload))
    assert outcome.human.review_decision == "approved"
    with database.connect() as connection:
        stored = get_review(connection, "review-1")
    assert stored.decision == "approved"
    assert stored.notes == "looks fine"
    with database.transaction() as connection:
        connection.execute("DELETE FROM reviews WHERE review_id = ?", ("review-1",))
    with pytest.raises(AnalyticsError, match="review"):
        verify_outcome(database, work, outcome.outcome_id)


def _ready(tmp_path: Path, *, features: bool = False) -> tuple[Database, Path, str]:
    from clipforge.media.hashing import sha256_file
    from clipforge.schemas.ingest import SourceIngestManifest
    from clipforge.schemas.media import SourceAsset
    from clipforge.schemas.project import Project
    from tests.test_media_unit import _probe

    work = tmp_path / "work"
    work.mkdir()
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    media = work / "source.bin"
    media.write_bytes(b"source-bytes")
    document = {
        "source_sha256": "cd" * 32,
        "candidates": [
            {
                "candidate_id": "cand-1",
                "rank": 2,
                "creative_score": "0.5",
                "edit_opportunity_score": "0.25",
                "media_sha256": "ab" * 32,
                "time_map": TimeMapDocument(
                    time_map_id="map-1",
                    segments=[
                        TimelineSegment(
                            segment_id="seg-1",
                            source_start_us=0,
                            source_end_us=5_000_000,
                        )
                    ],
                ).model_dump(mode="json"),
                "broll_events": [
                    {"interval": {"output_start_us": 0, "output_end_us": 1000, "clock": "output"}},
                    {"note": "missing interval"},
                ],
            }
        ],
    }
    artifact = work / "artifact.json"
    artifact.write_text(json.dumps(document), encoding="utf-8")
    digest = sha256_file(artifact)
    now = datetime.now(UTC)
    project = Project(project_id="project-1", name="Analytics", created_at=now, provenance=provenance())
    source = SourceAsset(
        source_asset_id="source-1",
        project_id="project-1",
        uri=media.resolve().as_uri(),
        license_record_id="lic-1",
        provenance=provenance(["source-1"]),
    )
    stat = media.stat()
    manifest = SourceIngestManifest(
        source_asset_id="source-1",
        project_id="project-1",
        content_sha256="11" * 32,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        original_filename=media.name,
        transcription_eligible=False,
        video_stream_index=0,
        audio_stream_index=None,
        canonical_duration_us=2_000_000,
        video_origin_us=0,
        ingested_at=now,
        probe=_probe(),
    )
    job = JobRecord(
        job_id="job-1",
        project_id="project-1",
        kind="media_prepare",
        status=JobStatus.SUCCEEDED,
        created_at=now,
        updated_at=now,
        payload={"source_asset_id": "source-1"},
    )
    with database.transaction() as connection:
        insert_project(connection, project)
        insert_asset_license_record(connection, license_record(asset_id="source-1"))
        insert_source_asset(connection, source)
        insert_source_manifest(connection, manifest)
        insert_job(connection, job)
        insert_artifact(
            connection,
            artifact_id="artifact-1",
            project_id="project-1",
            job_id="job-1",
            source_asset_id="source-1",
            kind="notes_json",
            uri=artifact.resolve().as_uri(),
            provenance=provenance(["source-1"], "job-1"),
        )
    del features
    return database, work, digest


def _payload(
    digest: str,
    *,
    outcome_id: str = "outcome-1",
    key: str = "idem-key-1",
    platform: str = "tiktok",
    views: int | None = None,
    completion_rate: str | None = None,
    completion_count: int | None = None,
    revenue: str | None = None,
    candidate_id: str | None = None,
    candidate_media_sha256: str | None = None,
    artifact_id: str = "artifact-1",
) -> dict[str, object]:
    metrics: dict[str, object] = {}
    if views is not None:
        metrics["views"] = views
    if completion_rate is not None:
        metrics["completion_rate"] = completion_rate
    if completion_count is not None:
        metrics["completion_count"] = completion_count
    if revenue is not None:
        metrics["revenue_amount"] = revenue
        metrics["revenue_currency"] = "USD"
    return {
        "outcome_id": outcome_id,
        "idempotency_key": key,
        "project_id": "project-1",
        "source_asset_id": "source-1",
        "artifact_id": artifact_id,
        "artifact_kind": "notes_json",
        "candidate_id": candidate_id,
        "candidate_media_sha256": candidate_media_sha256,
        "artifact_sha256": digest,
        "platform": platform,
        "observed_at": "2026-10-04T00:00:00+00:00",
        "measurement_window": "day-1",
        "metrics": metrics,
        "created_by": "ada",
    }


def _input() -> AnalyticsObservationInput:
    return AnalyticsObservationInput.model_validate(
        {
            "outcome_id": "outcome-1",
            "idempotency_key": "idem-key-1",
            "project_id": "project-1",
            "source_asset_id": "source-1",
            "artifact_id": "artifact-1",
            "artifact_kind": "notes_json",
            "artifact_sha256": "a" * 64,
            "platform": "tiktok",
            "observed_at": "2026-10-04T00:00:00+00:00",
            "measurement_window": "day-1",
            "created_by": "ada",
        }
    )


def _write_import(work: Path, rows: list[dict[str, object]]) -> Path:
    path = work / "import.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_observed_time_cannot_precede_publication() -> None:
    with pytest.raises(ValidationError, match="observed time"):
        from clipforge.schemas.analytics import PerformanceOutcome

        PerformanceOutcome.model_validate(
            {
                "outcome_id": "outcome-1",
                "project_id": "project-1",
                "source_asset_id": "source-1",
                "artifact_id": "artifact-1",
                "artifact_kind": "notes_json",
                "snapshot_id": "b" * 64,
                "artifact_sha256": "a" * 64,
                "media_available": False,
                "platform": "tiktok",
                "published_at": "2026-10-05T00:00:00+00:00",
                "observed_at": "2026-10-04T00:00:00+00:00",
                "measurement_window": "day-1",
                "metrics": {},
                "human": {},
                "qa_policy": "not_required",
                "idempotency_key": "idem-key-1",
                "provenance": ArtifactProvenance(
                    created_at=stamp(),
                    created_by="ada",
                    tool="clipforge-analytics",
                    tool_version="0",
                    source_asset_ids=["source-1"],
                ).model_dump(mode="json"),
            }
        )
