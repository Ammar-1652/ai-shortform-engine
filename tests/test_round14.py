"""Analytics labels, local exports, comparison filters, and the loopback page."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from clipforge.analytics.compare import ComparisonFilter
from clipforge.analytics.importers import list_import_profiles
from clipforge.analytics.labels import (
    expected_cache_record,
    label_cache_state,
    list_label_history,
    set_labels,
    verify_labels,
)
from clipforge.analytics.page import overview
from clipforge.analytics.server import open_analytics_server, static_bundle_text
from clipforge.analytics.service import (
    AnalyticsError,
    compare_project,
    import_observations,
    list_imports,
    record_outcome,
    show_import,
    verify_import,
    verify_outcome,
)
from clipforge.cli.main import app
from clipforge.schemas.analytics import (
    AnalyticsImportProfile,
    EditorialLabelAssignment,
    EditorialLabelSet,
    ManualLabels,
    PerformanceMetrics,
)
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.registry import CONTRACT_MODELS
from clipforge.storage import Database, insert_review
from clipforge.storage.db import _execute_script, _prepare
from clipforge.storage.migrations import MIGRATIONS
from tests.helpers import provenance, stamp
from tests.test_round13 import _payload, _ready

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]


def test_label_schemas_are_exported_and_reject_unsafe_text() -> None:
    for model in (EditorialLabelSet, EditorialLabelAssignment, AnalyticsImportProfile):
        assert model in CONTRACT_MODELS
    generated = ROOT / "schemas" / "generated" / "EditorialLabelSet.schema.json"
    document = json.loads(generated.read_text(encoding="utf-8"))
    assert "label_set_id" in document["properties"]
    with pytest.raises(ValidationError):
        ManualLabels(hook_type="<b>hook</b>")
    with pytest.raises(ValidationError):
        EditorialLabelAssignment(
            project_id="project-1",
            source_asset_id="source-1",
            artifact_id="artifact-1",
            reviewer_id="ada",
            notes="see https://example.test/secret",
        )
    with pytest.raises(ValidationError):
        EditorialLabelAssignment(
            project_id="project-1",
            source_asset_id="source-1",
            artifact_id="artifact-1",
            reviewer_id="ada",
            notes="token=/tmp/secret",
        )
    with pytest.raises(ValidationError):
        EditorialLabelAssignment(
            project_id="project-1",
            source_asset_id="source-1",
            artifact_id="artifact-1",
            reviewer_id="viewer_id",
            notes="Café",
        )
    with pytest.raises(ValidationError):
        EditorialLabelAssignment(
            project_id="project-1",
            source_asset_id="source-1",
            artifact_id="artifact-1",
            reviewer_id="ada",
            notes="bearer secret",
        )
    with pytest.raises(ValidationError):
        EditorialLabelAssignment(
            project_id="project-1",
            source_asset_id="source-1",
            artifact_id="artifact-1",
            reviewer_id="ada",
            notes="x" * 501,
        )
    with pytest.raises(ValidationError):
        EditorialLabelAssignment.model_validate(
            {
                "project_id": "project-1",
                "source_asset_id": "source-1",
                "artifact_id": "artifact-1",
                "reviewer_id": "ada",
                "automated": True,
            }
        )
    with pytest.raises(ValidationError):
        PerformanceMetrics(revenue_amount="1.00", revenue_currency="EUR")  # type: ignore[arg-type]


def test_version_5_database_upgrades_in_place(tmp_path: Path) -> None:
    path = tmp_path / "v5.sqlite3"
    connection = sqlite3.connect(path)
    _prepare(connection)
    connection.execute("BEGIN IMMEDIATE")
    now = stamp().isoformat()
    for migration in MIGRATIONS:
        if migration.version >= 6:
            break
        if migration.precheck is not None:
            migration.precheck(connection)
        _execute_script(connection, migration.sql)
        connection.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.name, now),
        )
    connection.execute("PRAGMA user_version = 5")
    connection.execute(
        """
        INSERT INTO projects (
            project_id, name, schema_version, profile_id, created_at, provenance_json, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("project-keep", "Keep", "1.0.0", None, now, json.dumps(provenance().model_dump(mode="json")), "{}"),
    )
    connection.execute(
        """
        INSERT INTO analytics_imports (
            import_id, project_id, content_sha256, outcome_count, created_at, created_by
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("a" * 64, "project-keep", "b" * 64, 1, now, "ada"),
    )
    connection.commit()
    connection.close()
    database = Database(path)
    assert database.initialize() == 6
    with database.connect() as checked:
        assert checked.execute("SELECT name FROM projects").fetchone()["name"] == "Keep"
        row = checked.execute("SELECT * FROM analytics_imports").fetchone()
        assert row["profile_id"] == "clipforge-observation-v1"
        assert row["validation_summary"] == ""
        assert row["outcome_ids_json"] == "[]"
        assert checked.execute("SELECT COUNT(*) FROM editorial_label_sets").fetchone()[0] == 0


def test_tabular_import_is_atomic_idempotent_and_corrects(tmp_path: Path) -> None:
    database, work, digest = _ready(tmp_path)
    path = work / "export.csv"
    path.write_text(_csv(digest, views="10", likes="2"), encoding="utf-8")
    stored = import_observations(database, work, path, profile_id="generic-metrics-v1")
    assert len(stored) == 1
    assert stored[0].metrics.views == 10
    assert stored[0].metrics.likes == 2
    assert stored[0].metrics.comments is None
    again = import_observations(database, work, path, profile_id="generic-metrics-v1")
    assert again[0].outcome_id == stored[0].outcome_id
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM performance_outcomes").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM analytics_imports").fetchone()[0] == 1
        summary = connection.execute("SELECT validation_summary, profile_id FROM analytics_imports").fetchone()
        assert summary["profile_id"] == "generic-metrics-v1"
        assert "export.csv" not in str(summary["validation_summary"])
        assert (
            path.name not in connection.execute("SELECT outcome_ids_json FROM analytics_imports").fetchone()[0]
        )
    shown = show_import(database, _import_id(database))
    assert path.name not in shown
    assert "PASS import" in verify_import(database, _import_id(database))
    corrected = work / "correction.csv"
    corrected.write_text(_csv(digest, views="11", likes="2"), encoding="utf-8")
    import_observations(database, work, corrected, profile_id="generic-metrics-v1")
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM performance_outcomes").fetchone()[0] == 2
    jsonl = work / "rows.jsonl"
    jsonl.write_text(_json_row(digest, views=3) + "\n" + _json_row(digest, views=4) + "\n", encoding="utf-8")
    third = import_observations(database, work, jsonl, profile_id="generic-metrics-v1")
    assert len(third) == 2
    array_path = work / "rows.json"
    array_path.write_text("[" + _json_row(digest, views=8) + "]", encoding="utf-8")
    import_observations(database, work, array_path, profile_id="generic-metrics-v1")


def test_import_failures_write_nothing(tmp_path: Path) -> None:
    database, work, digest = _ready(tmp_path)
    base = _csv(digest, views="4", likes="1")
    before = _counts(database)

    def rejected(name: str, text: str) -> None:
        path = work / name
        path.write_text(text, encoding="utf-8")
        with pytest.raises(AnalyticsError):
            import_observations(database, work, path, profile_id="generic-metrics-v1")
        assert _counts(database) == before

    rejected("dup.csv", base + "\n" + _csv_line(digest, views="4", likes="1"))
    rejected("negative.csv", _csv(digest, views="-1", likes="1"))
    rejected("currency.csv", _csv(digest, views="4", likes="1", currency="EUR", revenue="1.00"))
    rejected("date.csv", _csv(digest, views="4", likes="1", observed="2026-13-40"))
    rejected("naive.csv", _csv(digest, views="4", likes="1", observed="2026-10-04T00:00:00"))
    rejected("rate.csv", _csv(digest, views="1", likes="1", completion_count="2", completion_rate="2"))
    rejected("formula.csv", _csv(digest, views="=1+1", likes="1"))
    rejected("unknown.csv", _with_extra(_csv(digest, views="4", likes="1")))
    mixed = _csv(digest, views="4", likes="1").splitlines()
    mixed.append(_csv_line(digest, views="5", likes="1", project_id="project-2"))
    rejected("mixed.csv", "\n".join(mixed) + "\n")

    ignored = work / "ignored.csv"
    ignored.write_text(_with_extra(_csv(digest, views="7", likes="1")), encoding="utf-8")
    stored = import_observations(database, work, ignored, profile_id="generic-metrics-ignore-v1")
    assert "abc" not in stored[0].model_dump_json()

    def cancel() -> None:
        raise RuntimeError("cancelled before commit")

    doomed = work / "cancel.csv"
    doomed.write_text(_csv(digest, views="6", likes="1"), encoding="utf-8")
    with pytest.raises(RuntimeError, match="cancelled"):
        import_observations(database, work, doomed, profile_id="generic-metrics-v1", before_commit=cancel)
    checked = import_observations(
        database,
        work,
        doomed,
        profile_id="generic-metrics-v1",
        validate_only=True,
    )
    assert len(checked) == 1
    assert _counts(database)[0] == 1


def test_labels_are_append_only_and_stale_writes_fail(tmp_path: Path) -> None:
    database, work, digest = _ready(tmp_path)
    outcome = record_outcome(database, work, _observation(digest))
    first = set_labels(database, work, _assignment(outcome, notes="Café 説明 $12.50"))
    second = set_labels(
        database,
        work,
        _assignment(outcome, notes="later", expected=first.label_set_id, hook="question"),
    )
    history = list_label_history(database, "project-1", "artifact-1")
    assert [item.label_set_id for item in history.entries] == [first.label_set_id, second.label_set_id]
    assert history.effective_label_set_id == second.label_set_id
    assert history.entries[0].notes == "Café 説明 $12.50"
    with pytest.raises(AnalyticsError, match="reload before saving"):
        set_labels(database, work, _assignment(outcome, notes="stale", expected=first.label_set_id))
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM editorial_label_sets").fetchone()[0] == 2
    crossed = _assignment(outcome, notes="other")
    crossed = crossed.model_copy(
        update={"project_id": "project-2", "expected_label_set_id": second.label_set_id}
    )
    with pytest.raises(AnalyticsError, match="project"):
        set_labels(database, work, crossed)
    other_source = _assignment(outcome, notes="source", expected=second.label_set_id).model_copy(
        update={"source_asset_id": "source-2"}
    )
    with pytest.raises(AnalyticsError, match="source"):
        set_labels(database, work, other_source)
    media = work / "artifact.json"
    original = media.read_bytes()
    media.write_bytes(original + b"\n")
    with pytest.raises(AnalyticsError, match="reload before saving"):
        set_labels(database, work, _assignment(outcome, notes="changed", expected=second.label_set_id))
    media.write_bytes(original)
    media.unlink()
    missing = set_labels(
        database,
        work,
        _assignment(outcome, notes="missing media", expected=second.label_set_id),
    )
    assert missing.notes == "missing media"
    assert "unavailable" in verify_outcome(database, work, outcome.outcome_id)
    assert "PASS labels" in verify_labels(database, "project-1")


def test_effective_labels_drive_comparison_and_keep_missing_metrics(tmp_path: Path) -> None:
    database, work, digest = _ready(tmp_path)
    outcome = record_outcome(database, work, _observation(digest))
    set_labels(database, work, _assignment(outcome, hook="question", topic="coffee", format_tag="talking-head"))
    document = compare_project(
        database,
        "project-1",
        dimension="hook_type",
        comparison_filter=ComparisonFilter(hook_type="question", format_tag="talking-head", topic_tag="coffee"),
        created_by="ada",
    )
    assert document.status == "described"
    assert document.cohorts[0].key == "question"
    assert document.provenance.source_asset_ids == ["source-1"]
    assert document.cohorts[0].aggregate.views_total is None
    assert document.cohorts[0].aggregate.missing_views == 1
    assert document.cohorts[0].aggregate.views_count == 0
    empty = compare_project(
        database,
        "project-1",
        dimension="audience_tag",
        comparison_filter=ComparisonFilter(audience_tag="buyers"),
        created_by="ada",
    )
    assert empty.status == "insufficient_evidence"
    assert empty.provenance.source_asset_ids == []
    card = overview(database, work, "project-1")["outcomes"][0]
    assert card["metrics"]["likes"] is None
    assert "/tmp/" not in json.dumps(card)
    assert "://" not in json.dumps(card)


def test_sidecar_cache_miss_and_failure_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, work, digest = _ready(tmp_path)
    outcome = record_outcome(database, work, _observation(digest))
    label_set = set_labels(database, work, _assignment(outcome, notes="first"))
    expected = expected_cache_record(database, work, "project-1", "artifact-1")
    assert expected is not None
    assert label_cache_state(work, "artifact-1", expected) == "hit"
    current = work / "analytics" / "labels" / "artifact-1" / "current.json"
    cache = current.with_name("cache.json")
    original_current = current.read_bytes()
    original_cache = cache.read_bytes()
    cache.write_text("{", encoding="utf-8")
    assert label_cache_state(work, "artifact-1", expected) == "miss"
    cache.write_bytes(original_cache)
    link = cache.with_name("linked.json")
    link.write_text("nope", encoding="utf-8")
    cache.unlink()
    cache.symlink_to(link)
    assert label_cache_state(work, "artifact-1", expected) == "miss"
    cache.unlink()
    cache.write_bytes(original_cache)

    def fail() -> None:
        raise RuntimeError("sidecar failed")

    with pytest.raises(AnalyticsError, match="sidecar"):
        set_labels(
            database,
            work,
            _assignment(outcome, notes="second", expected=label_set.label_set_id),
            sidecar_hook=fail,
        )
    assert current.read_bytes() == original_current
    assert not current.with_name("current.json.partial").exists()
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM editorial_label_sets").fetchone()[0] == 1

    fresh = Database(tmp_path / "fresh.sqlite3")
    # The first-run database is the same file. A new work root has no sidecar yet.
    empty_work = tmp_path / "empty-work"
    empty_work.mkdir()
    (empty_work / "artifact.json").write_bytes((work / "artifact.json").read_bytes())
    del fresh
    before_rows = _label_count(database)

    def fail_cache_write() -> None:
        original = Path.write_text

        def wrapped(self: Path, data: str, *args: object, **kwargs: object) -> int:
            if self.name == "cache.json":
                raise OSError("disk full")
            return original(self, data, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", wrapped)

    with pytest.raises(AnalyticsError):
        set_labels(
            database,
            work,
            _assignment(outcome, notes="disk", expected=label_set.label_set_id),
            sidecar_hook=fail_cache_write,
        )
    assert current.read_bytes() == original_current
    assert _label_count(database) == before_rows
    assert not current.with_name("current.json.partial").exists()


def test_read_only_commands_and_loopback_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, work, digest = _ready(tmp_path)
    outcome = record_outcome(database, work, _observation(digest))
    set_labels(database, work, _assignment(outcome, notes="kept"))
    import_path = work / "native.json"
    import_path.write_text(
        json.dumps([_payload(digest, outcome_id="outcome-native", key="idem-native")]), encoding="utf-8"
    )
    import_observations(database, work, import_path)
    before_db = database.path.read_bytes()
    before_files = _files(work)

    def forbid_write(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("read-only command opened a write transaction")

    monkeypatch.setattr(database, "transaction", forbid_write)
    verify_outcome(database, work, outcome.outcome_id)
    verify_labels(database, "project-1")
    verify_import(database, list_imports(database, "project-1")[0][0])
    show_import(database, list_imports(database, "project-1")[0][0])
    compare_project(database, "project-1", dimension="platform", created_by="ada")
    overview(database, work, "project-1")
    record = expected_cache_record(database, work, "project-1", "artifact-1")
    assert record is not None
    assert label_cache_state(work, "artifact-1", record) == "hit"
    assert "PASS dashboard" in static_bundle_text()
    monkeypatch.undo()
    assert database.path.read_bytes() == before_db
    assert _files(work) == before_files

    listed = runner.invoke(app, ["analytics", "labels", "list", "project-1", "--db", str(database.path)])
    assert listed.exit_code == 0
    history = runner.invoke(app, ["analytics", "labels", "history", "artifact-1", "--db", str(database.path)])
    assert history.exit_code == 0
    assert "Café" not in history.stdout or "kept" in history.stdout
    missing = runner.invoke(app, ["analytics", "import-profile", "show", "missing-profile"])
    assert missing.exit_code != 0
    profiles = runner.invoke(app, ["analytics", "import-profile", "list"])
    assert profiles.exit_code == 0
    assert "generic-metrics-v1" in profiles.stdout
    validated = runner.invoke(
        app,
        [
            "analytics",
            "import",
            "validate",
            str(import_path),
            "--profile",
            "clipforge-observation-v1",
            "--db",
            str(database.path),
            "--work-dir",
            str(work),
        ],
    )
    assert validated.exit_code == 0
    assert database.path.read_bytes() == before_db

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("socket opened")

    monkeypatch.setattr("clipforge.analytics.server.ThreadingHTTPServer", explode)
    with pytest.raises(AnalyticsError, match=r"127\.0\.0\.1"):
        open_analytics_server(database=database, project_id="project-1", work_root=work, host="0.0.0.0")
    monkeypatch.undo()
    server = open_analytics_server(database=database, project_id="project-1", work_root=work, port=0)
    thread_started = False
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    thread_started = True
    port = int(server.server_address[1])
    try:
        from http.client import HTTPConnection

        connection = HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request("GET", "/api/analytics/../../etc/passwd")
        response = connection.getresponse()
        assert response.status == 400
        connection.close()
        connection = HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request(
            "POST",
            "/api/analytics/labels",
            body=json.dumps({"project_id": "project-1", "automated": True}).encode(),
            headers={"Content-Type": "application/json"},
        )
        denied = connection.getresponse()
        assert denied.status == 400
        assert b"approval" in denied.read()
        connection.close()
        page = (ROOT / "src" / "clipforge" / "analytics" / "static" / "app.js").read_text(encoding="utf-8")
        assert "eval(" not in page
        assert "innerHTML" not in page
        assert "http://" not in page
        assert "https://" not in page
    finally:
        if thread_started:
            server.shutdown()
            server.server_close()
    linked = tmp_path / "linked-analytics"
    linked.mkdir()
    analytics = work / "analytics"
    if analytics.exists():
        # A symlink in place of the analytics directory is refused before a new row.
        moved = tmp_path / "analytics-real"
        analytics.rename(moved)
        analytics.symlink_to(moved, target_is_directory=True)
        with pytest.raises(AnalyticsError, match="symlink"):
            set_labels(
                database,
                work,
                _assignment(
                    outcome,
                    notes="linked",
                    expected=list_label_history(database, "project-1", "artifact-1").effective_label_set_id,
                ),
            )
        analytics.unlink()
        moved.rename(analytics)


def test_review_binding_is_visible_and_profiles_load() -> None:
    profiles = list_import_profiles()
    assert {item.profile_id for item in profiles} >= {
        "clipforge-observation-v1",
        "generic-metrics-v1",
        "generic-metrics-ignore-v1",
    }
    native = next(item for item in profiles if item.profile_id == "clipforge-observation-v1")
    assert native.kind == "native"


def test_review_history_is_copied_onto_the_card(tmp_path: Path) -> None:
    database, work, digest = _ready(tmp_path)
    now = datetime.now(UTC)
    with database.transaction() as connection:
        insert_review(
            connection,
            ReviewDecision(
                review_id="review-1",
                project_id="project-1",
                artifact_id="artifact-1",
                candidate_id="cand-1",
                subject_kind="candidate",
                decision="approved",
                reviewer_id="ada",
                created_at=now,
                notes="kept",
                automated=False,
            ),
        )
    payload = _payload(digest, candidate_id="cand-1")
    payload["human"] = {"review_id": "review-1"}
    outcome = record_outcome(database, work, _observation_from(payload))
    card = overview(database, work, "project-1")["outcomes"][0]
    assert card["review_history"][0]["decision"] == "approved"
    assert card["qa_status"] is None
    assert outcome.human.review_decision == "approved"


def _observation(digest: str):
    from clipforge.schemas.analytics import AnalyticsObservationInput

    return AnalyticsObservationInput.model_validate(_payload(digest))


def _observation_from(payload: dict[str, object]):
    from clipforge.schemas.analytics import AnalyticsObservationInput

    return AnalyticsObservationInput.model_validate(payload)


def _assignment(
    outcome: object,
    *,
    notes: str = "",
    expected: str | None = None,
    hook: str = "unknown",
    topic: str | None = None,
    format_tag: str = "unknown",
) -> EditorialLabelAssignment:
    return EditorialLabelAssignment(
        project_id=outcome.project_id,  # type: ignore[attr-defined]
        source_asset_id=outcome.source_asset_id,  # type: ignore[attr-defined]
        artifact_id=outcome.artifact_id,  # type: ignore[attr-defined]
        outcome_id=outcome.outcome_id,  # type: ignore[attr-defined]
        snapshot_id=outcome.snapshot_id,  # type: ignore[attr-defined]
        expected_label_set_id=expected,
        expected_artifact_sha256=outcome.artifact_sha256,  # type: ignore[attr-defined]
        labels=ManualLabels(hook_type=hook, topic_tags=[topic] if topic else [], format_tag=format_tag),
        reviewer_id="ada",
        notes=notes,
    )


def _csv(digest: str, **values: str) -> str:
    return _header() + "\n" + _csv_line(digest, **values) + "\n"


def _header() -> str:
    return ",".join(
        [
            "project_id",
            "source_id",
            "artifact_id",
            "artifact_kind",
            "artifact_sha256",
            "platform",
            "observed_timestamp",
            "publication_timestamp",
            "window",
            "geography",
            "campaign",
            "views",
            "likes",
            "completion_count",
            "completion_rate",
            "watch_time",
            "currency",
            "revenue",
        ]
    )


def _csv_line(
    digest: str,
    *,
    views: str = "4",
    likes: str = "1",
    project_id: str = "project-1",
    observed: str = "2026-10-04T00:00:00+00:00",
    currency: str = "",
    revenue: str = "",
    completion_count: str = "",
    completion_rate: str = "",
) -> str:
    return ",".join(
        [
            project_id,
            "source-1",
            "artifact-1",
            "notes_json",
            digest,
            "tiktok",
            observed,
            "",
            "day-1",
            "",
            "",
            views,
            likes,
            completion_count,
            completion_rate,
            "1.5",
            currency,
            revenue,
        ]
    )


def _with_extra(text: str) -> str:
    lines = text.strip().splitlines()
    lines[0] = lines[0] + ",viewer_id"
    lines[1] = lines[1] + ",abc"
    return "\n".join(lines) + "\n"


def _json_row(digest: str, *, views: int) -> str:
    return json.dumps(
        {
            "project_id": "project-1",
            "source_asset_id": "source-1",
            "artifact_id": "artifact-1",
            "artifact_kind": "notes_json",
            "artifact_sha256": digest,
            "platform": "tiktok",
            "observed_at": "2026-10-04T00:00:00+00:00",
            "measurement_window": "day-1",
            "views": views,
            "watch_time": "1.5",
        }
    )


def _counts(database: Database) -> tuple[int, int]:
    with database.connect() as connection:
        outcomes = connection.execute("SELECT COUNT(*) FROM performance_outcomes").fetchone()[0]
        imports = connection.execute("SELECT COUNT(*) FROM analytics_imports").fetchone()[0]
    return int(outcomes), int(imports)


def _label_count(database: Database) -> int:
    with database.connect() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM editorial_label_sets").fetchone()[0])


def _import_id(database: Database) -> str:
    return list_imports(database, "project-1")[0][0]


def _files(root: Path) -> list[tuple[str, bytes]]:
    found: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        found.append((str(path.relative_to(root)), path.read_bytes()))
    return found
