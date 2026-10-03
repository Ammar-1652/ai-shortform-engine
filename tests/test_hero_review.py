"""Hero review binding, integrity, and read-only commands."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.hero.alignment import FakeForcedAlignment
from clipforge.hero.backend import FakeHeroRenderBackend
from clipforge.hero.constants import KIND_HERO
from clipforge.hero.service import render_hero_drafts
from clipforge.hero.show import load_current_hero
from clipforge.media.hashing import sha256_file
from clipforge.preview.backend import FakeRoughRenderBackend
from clipforge.review.hero_board import hero_review_board
from clipforge.review.server import open_hero_review_server
from clipforge.review.service import LOOPBACK_HOST, DecisionContext, record_decision, review_board
from clipforge.storage import find_artifact, list_reviews
from tests.candidate_support import PROJECT_ID, SOURCE_ID, segment
from tests.preview_support import mine, ready_stack, render, short_profile

pytestmark = pytest.mark.hero
runner = CliRunner()
_PHRASE = 'Café costs $12.50 today <unsafe>&"quoted" 説明'


@pytest.fixture(autouse=True)
def _reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")


def test_ready_board_keeps_manifest_order_and_exact_words(tmp_path: Path) -> None:
    fixture = _hero_stack(tmp_path, (_PHRASE, "Second clip stays in rank order here."))
    board = hero_review_board(fixture.database, SOURCE_ID, fixture.work)
    current = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    drafts = board["drafts"]
    assert isinstance(drafts, list)
    assert [item["candidate_id"] for item in drafts] == [item.candidate_id for item in current.document.drafts]
    assert [item["rank"] for item in drafts] == [1, 2]
    words = drafts[0]["words"]
    assert isinstance(words, list)
    assert [word["text"].strip() for word in words] == _PHRASE.split()
    assert drafts[0]["timing_quality"] == "forced"
    assert drafts[0]["alignment_checkpoint_sha256"] is None
    assert drafts[0]["alignment_language"] is None
    assert drafts[0]["audio_sample_rate"] is None
    assert "説明" in "".join(word["text"] for word in words)
    assert "$12.50" in "".join(word["text"] for word in words)


def test_missing_hero_is_an_empty_board(tmp_path: Path) -> None:
    fixture = _preview_only(tmp_path)
    board = hero_review_board(fixture.database, SOURCE_ID, fixture.work)
    assert board["status"] == "empty"
    assert board["drafts"] == []
    server = _serve(fixture)
    try:
        status, payload = _get(server, "/api/hero-review")
    finally:
        server.shutdown()
        server.server_close()
    assert status == 200
    assert json.loads(payload)["detail"] == "No current Hero drafts are stored for this source."


def test_corrupt_and_missing_manifest_block_opening(tmp_path: Path) -> None:
    fixture = _hero_stack(tmp_path, (_PHRASE,))
    current = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    current.manifest_path.write_text("{", encoding="utf-8")
    with pytest.raises(MediaError, match=r"\[corrupt_manifest\]"):
        open_hero_review_server(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            work_root=fixture.work,
            port=0,
        )
    current.manifest_path.unlink()
    with pytest.raises(MediaError, match=r"\[missing_manifest\]"):
        hero_review_board(fixture.database, SOURCE_ID, fixture.work)


def test_missing_and_corrupt_mp4_are_named(tmp_path: Path) -> None:
    fixture = _hero_stack(tmp_path, (_PHRASE,))
    video = _video(fixture)
    video.unlink()
    with pytest.raises(MediaError, match=r"\[missing_mp4\]"):
        hero_review_board(fixture.database, SOURCE_ID, fixture.work)
    video.write_bytes(b"not-an-mp4")
    with pytest.raises(MediaError, match=r"\[corrupt_mp4\]"):
        hero_review_board(fixture.database, SOURCE_ID, fixture.work)


def test_ffprobe_failure_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _hero_stack(tmp_path, (_PHRASE,))

    def broken(path: Path, *, expected_duration_us: int) -> object:
        del path, expected_duration_us
        raise MediaError("ffprobe could not read the file")

    monkeypatch.setattr("clipforge.hero.integrity.probe_hero", broken)
    with pytest.raises(MediaError, match=r"\[ffprobe\]"):
        hero_review_board(fixture.database, SOURCE_ID, fixture.work)


def test_wrong_bindings_are_named(tmp_path: Path) -> None:
    fixture = _hero_stack(tmp_path, (_PHRASE,))
    current = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    original = current.manifest_path.read_text(encoding="utf-8")
    payload = json.loads(original)
    payload["hero_set_id"] = "other-hero-set"
    current.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MediaError, match=r"\[hero_set_binding\]"):
        hero_review_board(fixture.database, SOURCE_ID, fixture.work)
    current.manifest_path.write_text(original, encoding="utf-8")
    alignment = current.manifest_path.parent / "candidates" / current.document.drafts[0].candidate_id
    _flip(alignment / "alignment.json")
    with pytest.raises(MediaError, match=r"\[alignment_binding\]"):
        hero_review_board(fixture.database, SOURCE_ID, fixture.work)


def test_wrong_plan_and_artifact_binding(tmp_path: Path) -> None:
    fixture = _hero_stack(tmp_path, (_PHRASE,))
    current = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    plan = current.manifest_path.parent / "candidates" / current.document.drafts[0].candidate_id / "plan.json"
    original = plan.read_bytes()
    _flip(plan)
    with pytest.raises(MediaError, match=r"\[plan_binding\]"):
        hero_review_board(fixture.database, SOURCE_ID, fixture.work)
    plan.write_bytes(original)
    with fixture.database.transaction() as connection:
        preview = find_artifact(connection, PROJECT_ID, SOURCE_ID, "rough_preview_set_json")
        assert preview is not None and preview.job_id is not None
        connection.execute(
            "UPDATE artifacts SET job_id = ? WHERE artifact_id = ?",
            (preview.job_id, current.artifact_id),
        )
    with pytest.raises(MediaError, match=r"\[artifact_binding\]"):
        hero_review_board(fixture.database, SOURCE_ID, fixture.work)


def test_wrong_artifact_kind_is_not_an_empty_board(tmp_path: Path) -> None:
    fixture = _hero_stack(tmp_path, (_PHRASE,))
    current = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    with fixture.database.transaction() as connection:
        connection.execute(
            "UPDATE artifacts SET kind = ? WHERE artifact_id = ?",
            ("not_a_hero_set", current.artifact_id),
        )
    with pytest.raises(MediaError, match=r"\[artifact_kind\]"):
        hero_review_board(fixture.database, SOURCE_ID, fixture.work)


def test_media_rejects_escape_symlink_and_previous_set(tmp_path: Path) -> None:
    fixture = _hero_stack(tmp_path, (_PHRASE,))
    previous = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    candidate_id = previous.document.drafts[0].candidate_id
    old_video = previous.manifest_path.parent / "candidates" / candidate_id / "hero.mp4"
    render_hero_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        force=True,
        backend=FakeHeroRenderBackend(),
        alignment_backend=FakeForcedAlignment(),
    )
    old_video.write_bytes(b"old-set-marker-not-served")
    server = _serve(fixture)
    try:
        board = json.loads(_get(server, "/api/hero-review")[1])
        current = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
        current_video = (
            current.manifest_path.parent / "candidates" / current.document.drafts[0].candidate_id / "hero.mp4"
        )
        media = _get(server, str(board["drafts"][0]["preview_url"]))
        assert media[0] == 200
        assert media[1] == current_video.read_bytes()
        assert b"old-set-marker" not in media[1]
        assert _get(server, "/media/hero/..")[0] == 404
        assert _get(server, "/media/hero/%2Ftmp%2Fsecret.mp4")[0] == 404
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"outside-bytes")
        current_video.unlink()
        current_video.symlink_to(outside)
        denied = _get(server, str(board["drafts"][0]["preview_url"]))
        assert denied[0] != 200
        assert b"outside-bytes" not in denied[1]
    finally:
        server.shutdown()
        server.server_close()


def test_public_hero_bind_is_refused(tmp_path: Path) -> None:
    fixture = _hero_stack(tmp_path, (_PHRASE,))
    with pytest.raises(MediaError, match=r"127\.0\.0\.1"):
        open_hero_review_server(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            work_root=fixture.work,
            host="0.0.0.0",
            port=0,
        )


def test_decision_rules_and_history(tmp_path: Path) -> None:
    fixture = _hero_stack(tmp_path, (_PHRASE,))
    server = _serve(fixture)
    try:
        board = json.loads(_get(server, "/api/hero-review")[1])
        draft = board["drafts"][0]
        notes = "Café 説明 $12.50 <img src=x onerror=alert(1)>"
        body = _body(board, draft, decision="changes_requested", notes=notes)
        created = _post(server, body)
        assert created[0] == 201
        saved = json.loads(created[1])
        assert saved["notes"] == body["notes"]
        assert saved["automated"] is False
        again = _post(server, body)
        assert again[0] == 201
        assert json.loads(again[1])["review_id"] != saved["review_id"]
        unknown = dict(body)
        unknown["html"] = "<b>"
        assert _post(server, unknown)[0] == 400
        blank = dict(body)
        blank["reviewer_id"] = "  "
        assert _post(server, blank)[0] == 400
        huge = dict(body)
        huge["notes"] = "x" * 4001
        assert _post(server, huge)[0] == 400
        bad = dict(body)
        bad["decision"] = "yes"
        assert _post(server, bad)[0] == 400
        automated = dict(body)
        automated["automated"] = True
        assert _post(server, automated)[0] == 400
        malformed = dict(body)
        malformed["candidate_id"] = "bad id"
        assert _post(server, malformed)[0] == 400
        stale = dict(body)
        stale["manifest_sha256"] = "a" * 64
        conflict = _post(server, stale)
        assert conflict[0] == 409
        assert b"reload before saving" in conflict[1]
        first_artifact = saved["artifact_id"]
    finally:
        server.shutdown()
        server.server_close()
    source_before = fixture.source_path.read_bytes()
    video_before = _video(fixture).read_bytes()
    render_hero_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        force=True,
        backend=FakeHeroRenderBackend(),
        alignment_backend=FakeForcedAlignment(),
    )
    assert fixture.source_path.read_bytes() == source_before
    fresh = hero_review_board(fixture.database, SOURCE_ID, fixture.work)
    fresh_draft = fresh["drafts"][0]
    assert isinstance(fresh_draft, dict)
    history = fresh_draft["history"]
    assert isinstance(history, list)
    assert any(item["artifact_id"] == first_artifact and item["current_artifact"] is False for item in history)
    assert fresh_draft["current_decision"] is None
    assert _video(fixture).read_bytes() != video_before or fresh["artifact_id"] != first_artifact
    context = DecisionContext(
        source_asset_id=str(fresh["source_asset_id"]),
        project_id=str(fresh["project_id"]),
        artifact_id=str(fresh["artifact_id"]),
        preview_set_id=str(fresh["hero_set_id"]),
        manifest_sha256=str(fresh["manifest_sha256"]),
        candidate_id=str(fresh_draft["candidate_id"]),
        subject_kind="hero",
        hero_set_id=str(fresh["hero_set_id"]),
        source_sha256=str(fresh["source_sha256"]),
        alignment_id=str(fresh_draft["alignment_id"]),
        alignment_sha256=str(fresh_draft["alignment_sha256"]),
        plan_id=str(fresh_draft["plan_id"]),
        plan_sha256=str(fresh_draft["plan_sha256"]),
    )
    from clipforge.review.service import record_hero_decision

    approved = record_hero_decision(
        database=fixture.database,
        work_root=fixture.work,
        context=context,
        decision="approved",
        reviewer_id="ada",
        notes="kept",
    )
    assert approved.artifact_id == fresh["artifact_id"]
    assert approved.artifact_id != first_artifact
    assert fixture.source_path.read_bytes() == source_before


def test_read_only_commands_do_not_change_state(tmp_path: Path) -> None:
    fixture = _hero_stack(tmp_path, (_PHRASE,))
    before_files = _files(fixture.work)
    before_reviews = _review_rows(fixture)
    before_artifact = _hero_artifact(fixture)
    args = ["--db", str(fixture.database.path), "--work-dir", str(fixture.work)]
    candidate = load_current_hero(fixture.database, SOURCE_ID, fixture.work).document.drafts[0].candidate_id
    for command in (
        ["hero", "review", "doctor", SOURCE_ID, *args],
        ["hero", "review", "list", SOURCE_ID, *args],
        ["hero", "review", "show", SOURCE_ID, candidate, *args],
        ["hero", "review", "verify", SOURCE_ID, *args],
    ):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.stderr
    assert _files(fixture.work) == before_files
    assert _review_rows(fixture) == before_reviews
    assert _hero_artifact(fixture) == before_artifact
    shown = runner.invoke(app, ["hero", "review", "show", SOURCE_ID, candidate, *args])
    assert "Café" in shown.stdout
    assert "$12.50" in shown.stdout
    assert "説明" in shown.stdout
    assert "unavailable" in shown.stdout


def _hero_stack(tmp_path: Path, texts: tuple[str, ...]):
    fixture = _preview_only(tmp_path, texts)
    board = review_board(fixture.database, SOURCE_ID, fixture.work)
    cards = board["candidates"]
    assert isinstance(cards, list)
    assert len(cards) == len(texts)
    for card in cards:
        assert isinstance(card, dict)
        record_decision(
            database=fixture.database,
            work_root=fixture.work,
            context=DecisionContext(
                source_asset_id=str(board["source_asset_id"]),
                project_id=str(board["project_id"]),
                artifact_id=str(board["artifact_id"]),
                preview_set_id=str(board["preview_set_id"]),
                manifest_sha256=str(board["manifest_sha256"]),
                candidate_id=str(card["candidate_id"]),
            ),
            decision="approved",
            reviewer_id="ada",
            notes="",
        )
    result = render_hero_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeHeroRenderBackend(),
        alignment_backend=FakeForcedAlignment(),
    )
    assert result.status == "rendered"
    return fixture


def _preview_only(tmp_path: Path, texts: tuple[str, ...] = (_PHRASE,)):
    pieces = []
    for index, text in enumerate(texts):
        start = index * 4_000_000
        pieces.append(segment(index, start, start + 1_200_000, text))
    fixture = ready_stack(tmp_path, segments=pieces, duration_us=pieces[-1].end_us + 1_000_000)
    mine(fixture, profile=short_profile(max_candidates=len(texts)))
    render(fixture, FakeRoughRenderBackend())
    return fixture


def _serve(fixture):
    server = open_hero_review_server(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        port=0,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _get(server, path: str) -> tuple[int, bytes]:
    port = int(server.server_address[1])
    connection = HTTPConnection(LOOPBACK_HOST, port, timeout=10)
    connection.request("GET", path)
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response.status, payload


def _post(server, body: dict[str, object]) -> tuple[int, bytes]:
    port = int(server.server_address[1])
    connection = HTTPConnection(LOOPBACK_HOST, port, timeout=10)
    raw = json.dumps(body).encode("utf-8")
    connection.request("POST", "/api/review/decisions", body=raw, headers={"Content-Type": "application/json"})
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response.status, payload


def _body(
    board: dict[str, object],
    draft: dict[str, object],
    *,
    decision: str,
    notes: str,
) -> dict[str, object]:
    return {
        "source_asset_id": board["source_asset_id"],
        "project_id": board["project_id"],
        "artifact_id": board["artifact_id"],
        "preview_set_id": board["hero_set_id"],
        "hero_set_id": board["hero_set_id"],
        "manifest_sha256": board["manifest_sha256"],
        "source_sha256": board["source_sha256"],
        "candidate_id": draft["candidate_id"],
        "plan_id": draft["plan_id"],
        "plan_sha256": draft["plan_sha256"],
        "alignment_id": draft["alignment_id"],
        "alignment_sha256": draft["alignment_sha256"],
        "subject_kind": "hero",
        "decision": decision,
        "reviewer_id": "ada",
        "notes": notes,
    }


def _video(fixture) -> Path:
    current = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    return current.manifest_path.parent / "candidates" / current.document.drafts[0].candidate_id / "hero.mp4"


def _flip(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[-1] ^= 0x01
    path.write_bytes(data)


def _files(root: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            found[str(path.relative_to(root))] = sha256_file(path)
    return found


def _review_rows(fixture) -> list[tuple[str, str, str | None]]:
    with fixture.database.connect() as connection:
        rows = list_reviews(connection, PROJECT_ID)
    return [(item.review_id, item.decision, item.artifact_id) for item in rows]


def _hero_artifact(fixture) -> str | None:
    with fixture.database.connect() as connection:
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_HERO)
    return None if row is None else row.artifact_id
