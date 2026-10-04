"""Human review decisions over a verified rough-preview set."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.preview.backend import FakeRoughRenderBackend
from clipforge.review.service import (
    STALE_MESSAGE,
    DecisionContext,
    format_review_list,
    record_decision,
    require_current_preview,
    review_board,
    verify_review,
)
from clipforge.storage import list_reviews
from tests.candidate_support import PROJECT_ID, SOURCE_ID
from tests.preview_support import isolated_segments, mine, ready_stack, render, short_profile

pytestmark = pytest.mark.review
runner = CliRunner()


@pytest.fixture(autouse=True)
def _reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")


def _rendered(tmp_path: Path, count: int):
    pieces, duration = isolated_segments(count)
    fixture = ready_stack(tmp_path, segments=pieces, duration_us=duration)
    mined = mine(fixture, profile=short_profile(max_candidates=max(count, 1), soft_target_min=0))
    assert mined.selected_count == count
    result = render(fixture, FakeRoughRenderBackend())
    return fixture, result


def _context(
    database: object,
    work: Path,
    candidate_id: str | None = None,
) -> tuple[DecisionContext, dict[str, object]]:
    board = review_board(database, SOURCE_ID, work)
    cards = board["candidates"]
    assert isinstance(cards, list)
    card = cards[0]
    assert isinstance(card, dict)
    if candidate_id is None:
        candidate_id = str(card["candidate_id"])
    return (
        DecisionContext(
            source_asset_id=str(board["source_asset_id"]),
            project_id=str(board["project_id"]),
            artifact_id=str(board["artifact_id"]),
            preview_set_id=str(board["preview_set_id"]),
            manifest_sha256=str(board["manifest_sha256"]),
            candidate_id=candidate_id,
        ),
        board,
    )


def _rows(database) -> list:
    with database.connect() as connection:
        return list_reviews(connection, PROJECT_ID)


def test_review_requires_a_current_preview(tmp_path: Path) -> None:
    pieces, duration = isolated_segments(1)
    fixture = ready_stack(tmp_path, segments=pieces, duration_us=duration)
    mine(fixture, profile=short_profile())
    with pytest.raises(MediaError, match="preview render"):
        require_current_preview(fixture.database, SOURCE_ID, fixture.work)


def test_invalid_preview_blocks_review(tmp_path: Path) -> None:
    fixture, result = _rendered(tmp_path, 1)
    result.manifest_path.write_bytes(result.manifest_path.read_bytes() + b"\n")
    with pytest.raises(MediaError, match=r"not reviewable|could not be read|hash"):
        review_board(fixture.database, SOURCE_ID, fixture.work)


def test_counts_order_and_empty_state(tmp_path: Path) -> None:
    for count in (7, 25):
        directory = tmp_path / str(count)
        directory.mkdir()
        fixture, _result = _rendered(directory, count)
        board = review_board(fixture.database, SOURCE_ID, fixture.work)
        cards = board["candidates"]
        assert isinstance(cards, list)
        assert [card["rank"] for card in cards] == list(range(1, count + 1))
        assert len(cards) == count
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    empty = ready_stack(empty_root, segments=[], duration_us=30_000_000)
    mine(empty, profile=short_profile())
    render(empty, FakeRoughRenderBackend())
    text = format_review_list(empty.database, SOURCE_ID, empty.work)
    assert "No candidates were selected in the current candidate set." in text
    assert review_board(empty.database, SOURCE_ID, empty.work)["candidate_count"] == 0


def test_decisions_are_append_only_and_bound_to_the_artifact(tmp_path: Path) -> None:
    fixture, result = _rendered(tmp_path, 1)
    manifest_bytes = result.manifest_path.read_bytes()
    from clipforge.media.local_file import path_from_file_uri
    from clipforge.storage import find_artifact

    with fixture.database.connect() as connection:
        candidate_row = find_artifact(connection, PROJECT_ID, SOURCE_ID, "candidate_set_json")
    assert candidate_row is not None
    candidate_file = path_from_file_uri(candidate_row.uri)
    before_candidate = candidate_file.read_bytes()
    context, board = _context(fixture.database, fixture.work)
    video = result.manifest_path.parent / f"candidates/{context.candidate_id}/preview.mp4"
    before_video = sha256_file(video)
    saved = []
    for name in ("approved", "rejected", "changes_requested"):
        saved.append(
            record_decision(
                database=fixture.database,
                work_root=fixture.work,
                context=context,
                decision=name,
                reviewer_id="ada",
                notes=f"note {name}",
            )
        )
    rows = _rows(fixture.database)
    assert [row.decision for row in rows] == ["approved", "rejected", "changes_requested"]
    assert rows[0].notes == "note approved"
    assert rows[0].review_id == saved[0].review_id
    again = review_board(fixture.database, SOURCE_ID, fixture.work)
    cards = again["candidates"]
    assert isinstance(cards, list)
    card = cards[0]
    assert isinstance(card, dict)
    current = card["current_decision"]
    assert isinstance(current, dict)
    assert current["decision"] == "changes_requested"
    history = card["history"]
    assert isinstance(history, list) and len(history) == 3
    forced = render(fixture, FakeRoughRenderBackend(), force=True)
    assert forced.preview_set_id != board["preview_set_id"]
    moved = review_board(fixture.database, SOURCE_ID, fixture.work)
    moved_cards = moved["candidates"]
    assert isinstance(moved_cards, list)
    moved_card = moved_cards[0]
    assert isinstance(moved_card, dict)
    assert moved_card["current_decision"] is None
    moved_history = moved_card["history"]
    assert isinstance(moved_history, list) and moved_history[0]["current_artifact"] is False
    assert candidate_file.read_bytes() == before_candidate
    assert result.manifest_path.read_bytes() == manifest_bytes
    assert sha256_file(video) == before_video


def test_rejected_writes(tmp_path: Path) -> None:
    fixture, _result = _rendered(tmp_path, 1)
    context, _board = _context(fixture.database, fixture.work)
    with pytest.raises(MediaError, match="unknown candidate"):
        record_decision(
            database=fixture.database,
            work_root=fixture.work,
            context=DecisionContext(
                source_asset_id=context.source_asset_id,
                project_id=context.project_id,
                artifact_id=context.artifact_id,
                preview_set_id=context.preview_set_id,
                manifest_sha256=context.manifest_sha256,
                candidate_id="missing-candidate",
            ),
            decision="approved",
            reviewer_id="ada",
            notes="",
        )
    with pytest.raises(MediaError, match="reload before saving"):
        record_decision(
            database=fixture.database,
            work_root=fixture.work,
            context=DecisionContext(
                source_asset_id=context.source_asset_id,
                project_id="other-project",
                artifact_id=context.artifact_id,
                preview_set_id=context.preview_set_id,
                manifest_sha256=context.manifest_sha256,
                candidate_id=context.candidate_id,
            ),
            decision="approved",
            reviewer_id="ada",
            notes="",
        )
    with pytest.raises(MediaError):
        record_decision(
            database=fixture.database,
            work_root=fixture.work,
            context=DecisionContext(
                source_asset_id="source-2",
                project_id=context.project_id,
                artifact_id=context.artifact_id,
                preview_set_id=context.preview_set_id,
                manifest_sha256=context.manifest_sha256,
                candidate_id=context.candidate_id,
            ),
            decision="approved",
            reviewer_id="ada",
            notes="",
        )
    stale_values = {
        "preview_set_id": "other-set",
        "manifest_sha256": "a" * 64,
        "artifact_id": "other-artifact",
    }
    for field, value in stale_values.items():
        with pytest.raises(MediaError, match="reload before saving"):
            record_decision(
                database=fixture.database,
                work_root=fixture.work,
                context=DecisionContext(
                    source_asset_id=context.source_asset_id,
                    project_id=context.project_id,
                    artifact_id=value if field == "artifact_id" else context.artifact_id,
                    preview_set_id=value if field == "preview_set_id" else context.preview_set_id,
                    manifest_sha256=value if field == "manifest_sha256" else context.manifest_sha256,
                    candidate_id=context.candidate_id,
                ),
                decision="approved",
                reviewer_id="ada",
                notes="",
            )
    with pytest.raises(MediaError, match="blank"):
        record_decision(
            database=fixture.database,
            work_root=fixture.work,
            context=context,
            decision="approved",
            reviewer_id="   ",
            notes="",
        )
    with pytest.raises(MediaError, match="4000"):
        record_decision(
            database=fixture.database,
            work_root=fixture.work,
            context=context,
            decision="approved",
            reviewer_id="ada",
            notes="x" * 4001,
        )
    with pytest.raises(MediaError, match="decision must be"):
        record_decision(
            database=fixture.database,
            work_root=fixture.work,
            context=context,
            decision="maybe",
            reviewer_id="ada",
            notes="",
        )
    assert _rows(fixture.database) == []
    assert STALE_MESSAGE.startswith("the preview set changed")


def test_changed_time_map_is_rejected(tmp_path: Path) -> None:
    fixture, result = _rendered(tmp_path, 1)
    from clipforge.schemas.preview import RoughPreviewCacheRecord, RoughPreviewSetDocument
    from clipforge.transcription.io import dump_json

    document = RoughPreviewSetDocument.model_validate_json(result.manifest_path.read_text(encoding="utf-8"))
    changed_preview = document.previews[0].model_copy(update={"time_map_sha256": "b" * 64})
    changed = RoughPreviewSetDocument.model_validate(
        document.model_copy(update={"previews": [changed_preview]}).model_dump(mode="json")
    )
    result.manifest_path.write_text(dump_json(changed), encoding="utf-8")
    sidecar = fixture.workspace.preview_sidecar()
    record = RoughPreviewCacheRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
    sidecar.write_text(
        dump_json(
            record.model_copy(
                update={
                    "manifest_sha256": sha256_file(result.manifest_path),
                    "manifest_size_bytes": result.manifest_path.stat().st_size,
                }
            )
        ),
        encoding="utf-8",
    )
    with pytest.raises(MediaError, match="time map"):
        review_board(fixture.database, SOURCE_ID, fixture.work)


def test_read_only_commands_do_not_change_state(tmp_path: Path) -> None:
    fixture, _result = _rendered(tmp_path, 1)
    before_files = _tree(fixture.work)
    before_reviews = _rows(fixture.database)
    report = verify_review(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work)
    assert report.status == "PASS"
    format_review_list(fixture.database, SOURCE_ID, fixture.work)
    doctor = runner.invoke(app, ["review", "doctor"])
    listed = runner.invoke(
        app,
        ["review", "list", SOURCE_ID, "--db", str(fixture.database.path), "--work-dir", str(fixture.work)],
    )
    checked = runner.invoke(
        app,
        ["review", "verify", SOURCE_ID, "--db", str(fixture.database.path), "--work-dir", str(fixture.work)],
    )
    assert doctor.exit_code == 0
    assert "127.0.0.1" in doctor.stdout
    assert listed.exit_code == 0
    assert checked.exit_code == 0
    assert _tree(fixture.work) == before_files
    assert _rows(fixture.database) == before_reviews
    top = runner.invoke(app, ["--help"])
    assert "review" in top.stdout
    assert "publish" in top.stdout
    for absent in ("transcribe", "render", "upload"):
        assert absent not in top.stdout


def _tree(root: Path) -> list[tuple[str, int, str]]:
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append((str(path.relative_to(root)), path.stat().st_size, digest))
    return rows
