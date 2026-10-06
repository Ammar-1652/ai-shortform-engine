"""Final approval is required before local delivery. Hero approval and QA are not enough."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from clipforge.errors import MediaError
from clipforge.publish.errors import PublishError
from clipforge.publish.service import export_delivery, verify_delivery
from clipforge.review.final_gate import capture_final_decision, final_board
from clipforge.review.server import open_final_review_server, require_loopback
from clipforge.schemas.governance import ReviewDecision
from tests.helpers import stamp
from tests.test_round16 import _world

runner = CliRunner()


def test_final_approval_allows_delivery_and_hero_or_qa_alone_do_not(tmp_path: Path) -> None:
    world = _world(tmp_path)
    exported = export_delivery(world.database, world.work, "source-1", "cand-1")
    assert exported.status == "succeeded"
    again = export_delivery(world.database, world.work, "source-1", "cand-1")
    assert again.status == "cache_hit"
    blocked = _world(tmp_path / "hero-only")
    with blocked.database.transaction() as connection:
        connection.execute("DELETE FROM reviews WHERE subject_kind = 'final'")
    with pytest.raises(PublishError) as missing:
        export_delivery(blocked.database, blocked.work, "source-1", "cand-1")
    assert missing.value.category == "final_approval_required"


def test_rejected_and_changes_requested_block_and_newer_rejection_wins(tmp_path: Path) -> None:
    world = _world(tmp_path)
    capture_final_decision(
        world.database,
        world.work,
        "source-1",
        "cand-1",
        decision="rejected",
        reviewer_id="ada",
        notes="no",
    )
    with pytest.raises(PublishError) as rejected:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert rejected.value.category == "final_approval_rejected"
    world = _world(tmp_path / "changes")
    capture_final_decision(
        world.database,
        world.work,
        "source-1",
        "cand-1",
        decision="changes_requested",
        reviewer_id="ada",
        notes="again",
    )
    with pytest.raises(PublishError) as changes:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert changes.value.category == "final_approval_changes_requested"
    with world.database.connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM reviews WHERE subject_kind = 'final'").fetchone()
    assert count is not None
    assert int(count[0]) == 2


def test_stale_source_artifact_and_qa_block(tmp_path: Path) -> None:
    world = _world(tmp_path)
    world.source_path.write_bytes(b"changed-source")
    with pytest.raises(PublishError) as source:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert source.value.category == "source_changed"
    world = _world(tmp_path / "empty")
    world.video.write_bytes(b"")
    with pytest.raises(PublishError) as empty:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert empty.value.category == "corrupt_media"
    world = _world(tmp_path / "link")
    target = tmp_path / "other.mp4"
    target.write_bytes(world.video.read_bytes())
    world.video.unlink()
    world.video.symlink_to(target)
    with pytest.raises(PublishError) as linked:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert linked.value.category == "unsafe_path"


def test_older_artifact_approval_is_not_effective(tmp_path: Path) -> None:
    world = _world(tmp_path)
    with world.database.transaction() as connection:
        connection.execute("UPDATE reviews SET artifact_id = 'art-hero' WHERE subject_kind = 'final'")
    with pytest.raises(PublishError) as stale:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert stale.value.category == "final_approval_required"


def test_missing_advanced_hero_and_prohibited_rights_block(tmp_path: Path) -> None:
    world = _world(tmp_path)
    world.manifest.unlink()
    with pytest.raises(PublishError) as missing:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert missing.value.category in {"artifact_missing", "missing_advanced_hero", "qa_missing"}
    world = _world(tmp_path / "rights")
    with world.database.transaction() as connection:
        connection.execute(
            "UPDATE asset_license_records SET status = 'prohibited' WHERE license_record_id = 'lic-source'"
        )
    with pytest.raises(PublishError) as rights:
        export_delivery(world.database, world.work, "source-1", "cand-1")
    assert rights.value.category == "rights_blocked"


def test_verify_is_read_only_and_history_stays_append_only(tmp_path: Path) -> None:
    world = _world(tmp_path)
    before_db = (tmp_path / "clipforge.sqlite3").read_bytes()
    card = final_board(world.database, world.work, "source-1", "cand-1")
    assert card["effective_decision"] == "approved"
    assert card["blockers"] == []
    assert "Café" in " ".join(str(item) for item in card["typography"])
    assert "/home/" not in json.dumps(card)
    assert (tmp_path / "clipforge.sqlite3").read_bytes() == before_db
    result = runner.invoke(
        __import__("clipforge.cli.main", fromlist=["app"]).app,
        [
            "final",
            "review",
            "verify",
            "source-1",
            "cand-1",
            "--db",
            str(tmp_path / "clipforge.sqlite3"),
            "--work-dir",
            str(world.work),
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert "effective_decision: approved" in result.stdout
    assert "whop: deferred" in result.stdout
    assert (tmp_path / "clipforge.sqlite3").read_bytes() == before_db


def test_stale_post_is_rejected_and_loopback_is_required(tmp_path: Path) -> None:
    import threading
    import urllib.error
    import urllib.request

    world = _world(tmp_path)
    with pytest.raises(MediaError):
        require_loopback("0.0.0.0")
    server = open_final_review_server(
        database=world.database,
        source_asset_id="source-1",
        candidate_id="cand-1",
        work_root=world.work,
        port=0,
    )
    try:
        port = int(server.server_address[1])
        threading.Thread(target=server.serve_forever, daemon=True).start()
        body = json.dumps(
            {
                "subject_kind": "final",
                "source_asset_id": "source-1",
                "candidate_id": "cand-1",
                "artifact_id": "art-advanced",
                "manifest_sha256": "a" * 64,
                "decision": "approved",
                "reviewer_id": "ada",
                "notes": "stale",
                "automated": False,
            }
        ).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/review/decisions",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request)
        assert rejected.value.code == 409
        payload = json.loads(rejected.value.read().decode())
        assert "reload before saving" in payload["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_changed_package_bytes_fail_verification(tmp_path: Path) -> None:
    world = _world(tmp_path)
    exported = export_delivery(world.database, world.work, "source-1", "cand-1")
    video = world.work / exported.relative_package / "candidates" / "cand-1" / "video.mp4"
    video.write_bytes(video.read_bytes() + b"x")
    with pytest.raises(PublishError):
        verify_delivery(world.database, world.work, "source-1", exported.delivery_id)


def test_static_final_board_has_no_remote_execution_helpers() -> None:
    root = Path(__file__).parents[1] / "src" / "clipforge" / "review" / "static"
    page = (root / "final-review.html").read_text(encoding="utf-8")
    script = (root / "final-review.js").read_text(encoding="utf-8")
    combined = page + script
    assert "autoplay" not in page
    assert "controls" in page
    assert "textContent" in script
    for token in ("eval(", "innerHTML", "dangerouslySetInnerHTML", "https://", "http://"):
        assert token not in combined


def test_automated_final_decision_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ReviewDecision(
            review_id="review-auto",
            project_id="project-1",
            artifact_id="art-advanced",
            candidate_id="cand-1",
            subject_kind="final",
            decision="approved",
            reviewer_id="ada",
            created_at=stamp(),
            notes="no",
            automated=True,  # type: ignore[arg-type]
        )
