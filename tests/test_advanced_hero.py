"""Advanced Hero editing. Assets are local fixtures. No Envato and no music."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.advanced_backend import (
    FakeAdvancedRenderBackend,
    RemotionAdvancedRenderBackend,
)
from clipforge.hero.advanced_service import (
    plan_advanced_candidate,
    render_advanced_drafts,
    select_advanced_backend,
)
from clipforge.hero.backend import FakeHeroRenderBackend
from clipforge.hero.show import load_current_hero
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri, path_to_file_uri
from clipforge.preview.inputs import load_preview_inputs
from clipforge.preview.service import default_profile
from clipforge.review.hero_board import decision_context_for
from clipforge.review.service import parse_decision_body, record_hero_decision, review_board
from clipforge.schemas.advanced import (
    AdvancedHeroPlanDocument,
    AdvancedHeroProfile,
    AdvancedHeroRenderInput,
    AudioMixEvent,
    DiagramEvent,
    DiagramPayload,
    ReframingStrategy,
    ReframingWindow,
    TypographyEvent,
)
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.governance import AssetLicenseRecord, RightsStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import insert_asset_license_record
from tests.candidate_support import PROJECT_ID, SOURCE_ID
from tests.test_hero_service import CountingAligner, _hero, _reviewed

pytestmark = pytest.mark.hero


@pytest.fixture(autouse=True)
def _reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")


def test_advanced_plan_and_render_keep_hero_v1(tmp_path: Path) -> None:
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    board = review_board(fixture.database, SOURCE_ID, fixture.work)
    hero = board["hero"]
    assert isinstance(hero, dict)
    record_hero_decision(
        database=fixture.database,
        work_root=fixture.work,
        context=decision_context_for(hero, ids[0]),
        decision="approved",
        reviewer_id="ada",
        notes="Café costs $12.50",
    )
    _register_asset(fixture, "broll-1", "graphic", b"broll-bytes")
    _register_asset(fixture, "sfx-1", "audio", b"sfx-bytes")
    plan = plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=ids[0],
        work_root=fixture.work,
        broll_asset_ids=["broll-1"],
        sfx_asset_ids=["sfx-1"],
    )
    assert plan.reframing_strategy == "contain"
    assert any("$" in item.text or item.text.strip() for item in plan.typography)
    backend = FakeAdvancedRenderBackend()
    result = render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=backend,
    )
    assert result.status == "rendered"
    assert result.cache_hit is False
    assert backend.calls == 1
    hero_manifest = fixture.workspace.hero_sidecar().read_bytes()
    again = render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=backend,
    )
    assert again.cache_hit is True
    assert backend.calls == 1
    assert fixture.workspace.hero_sidecar().read_bytes() == hero_manifest
    before = sorted(fixture.work.rglob("render-input.json"))
    assert before
    assert all('"narration.wav"' not in path.read_text(encoding="utf-8") for path in before)
    render_input = json.loads(before[-1].read_text(encoding="utf-8"))
    with pytest.raises(ValidationError, match="debug_overlays"):
        AdvancedHeroRenderInput.model_validate({**render_input, "debug_overlays": True})


def test_advanced_render_can_bind_narration_without_changing_the_plain_path(tmp_path: Path) -> None:
    from clipforge.voice.provider import FakeVoiceProvider
    from clipforge.voice.service import VoiceError, generate_narration
    from tests.test_round15 import _narration

    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    board = review_board(fixture.database, SOURCE_ID, fixture.work)
    hero = board["hero"]
    assert isinstance(hero, dict)
    record_hero_decision(
        database=fixture.database,
        work_root=fixture.work,
        context=decision_context_for(hero, ids[0]),
        decision="approved",
        reviewer_id="ada",
        notes="kept",
    )
    plan = plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=ids[0],
        work_root=fixture.work,
    )
    plain = render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
    )
    assert plain.status == "rendered"
    plain_inputs = list(fixture.work.rglob("render-input.json"))
    assert plain_inputs
    assert all('"narration.wav"' not in path.read_text(encoding="utf-8") for path in plain_inputs)
    target = max(item.output_end_us for item in plan.windows)
    request = _narration("Café narration stays optional").model_copy(update={"target_duration_us": target})
    narration = generate_narration(fixture.database, fixture.work, request, FakeVoiceProvider())
    with pytest.raises(VoiceError):
        render_advanced_drafts(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            work_root=fixture.work,
            backend=FakeAdvancedRenderBackend(),
            narration_artifact_id="missing-narration",
            force=True,
        )
    bound = render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
        narration_artifact_id=narration.artifact_id,
        force=True,
    )
    assert bound.status == "rendered"
    latest = max(fixture.work.rglob("render-input.json"), key=lambda path: path.stat().st_mtime)
    rendered = latest.read_text(encoding="utf-8")
    assert "narration.wav" in rendered
    assert "/tmp/" not in rendered
    assert "://" not in rendered
    with fixture.database.connect() as connection:
        payload = connection.execute(
            "SELECT payload_json FROM jobs WHERE kind = 'advanced_hero_render' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert payload is not None
    assert narration.audio_sha256 in str(payload["payload_json"])


def test_rights_and_paths_fail_before_a_job(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    _register_asset(fixture, "broll-1", "graphic", b"broll-bytes")
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
        broll_asset_ids=["broll-1"],
    )
    path = fixture.workspace.advanced_asset_file("broll-1")
    path.write_bytes(b"changed")
    with pytest.raises(MediaError, match="hash"):
        plan_advanced_candidate(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            work_root=fixture.work,
            broll_asset_ids=["broll-1"],
        )
    path.unlink()
    with pytest.raises(MediaError, match="missing"):
        plan_advanced_candidate(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            work_root=fixture.work,
            broll_asset_ids=["broll-1"],
        )


def test_remote_url_and_music_are_rejected() -> None:
    with pytest.raises(ValueError, match="music"):
        AudioMixEvent(
            event_id="sfx-1",
            interval=OutputInterval(output_start_us=0, output_end_us=10),
            asset_id="a",
            role="music",  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError):
        DiagramPayload.model_validate(
            {
                "kind": "number_comparison",
                "left_label": "A",
                "right_label": "B",
                "left_value": 1,
                "right_value": 2,
                "extra": 1,
            }
        )


def test_overlap_typography_and_unsafe_diagram_box() -> None:
    interval = OutputInterval(output_start_us=0, output_end_us=100)
    text = TypographyEvent(
        event_id="t1",
        interval=interval,
        purpose=MotionPurpose.NUMBER,
        component_id="type",
        text="Café $12.50",
        x=72,
        y=1500,
        font_size=54,
    )
    other = text.model_copy(update={"event_id": "t2"})
    with pytest.raises(ValidationError, match="overlapping"):
        AdvancedHeroPlanDocument.model_validate(_minimum_plan(typography=[text, other]))
    with pytest.raises(ValidationError, match="safe area"):
        DiagramEvent(
            event_id="d",
            interval=interval,
            purpose=MotionPurpose.COMPARISON,
            component_id="diagram",
            payload=DiagramPayload(
                kind="callout",
                left_label="<unsafe>",
                right_label="$12.50",
                left_value=12,
                right_value=50,
            ),
            x=900,
            y=1700,
            width=400,
            height=400,
        )


def test_reframing_window_must_stay_inside_the_frame() -> None:
    with pytest.raises(ValidationError, match="visual frame"):
        ReframingWindow(
            window_id="w",
            strategy_id=ReframingStrategy(strategy_id="contain"),
            output_start_us=0,
            output_end_us=10,
            source_x=10,
            source_y=0,
            source_width=100,
            source_height=10,
            frame_width=50,
            frame_height=20,
        )


def test_renderer_failure_does_not_publish_a_set(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    _register_asset(fixture, "broll-1", "graphic", b"broll-bytes")
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
        broll_asset_ids=["broll-1"],
    )

    class Broken(FakeAdvancedRenderBackend):
        def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
            del batch_path, log_path
            raise MediaError("encoder failed")

    with pytest.raises(MediaError, match="encoder failed"):
        render_advanced_drafts(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            work_root=fixture.work,
            backend=Broken(),
        )
    assert not fixture.workspace.advanced_sidecar().exists()


def test_read_only_commands_leave_the_set_in_place(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
    )
    render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
    )
    before = fixture.workspace.advanced_sidecar().read_bytes()
    args = ["--db", str(fixture.database.path), "--work-dir", str(fixture.work)]
    from typer.testing import CliRunner

    from clipforge.cli.main import app

    runner = CliRunner()
    for command in (
        ["hero", "advanced", "doctor", "--work-dir", str(fixture.work)],
        ["hero", "advanced", "list", SOURCE_ID, *args],
        ["hero", "advanced", "show", SOURCE_ID, candidate_id, *args],
        ["hero", "advanced", "verify", SOURCE_ID, *args],
    ):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.stderr
    assert fixture.workspace.advanced_sidecar().read_bytes() == before


def test_advanced_decision_is_bound_to_the_current_set(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
    )
    render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
    )
    from clipforge.hero.advanced_service import KIND_ADVANCED, advanced_review_board, require_advanced_binding
    from clipforge.storage import find_artifact

    with fixture.database.connect() as connection:
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_ADVANCED)
    assert row is not None
    board = advanced_review_board(fixture.database, SOURCE_ID, fixture.work)
    assert board["status"] == "ready"
    require_advanced_binding(
        fixture.database,
        SOURCE_ID,
        fixture.work,
        str(board["advanced_set_id"]),
        row.artifact_id,
    )
    with pytest.raises(MediaError, match="reload before saving"):
        require_advanced_binding(fixture.database, SOURCE_ID, fixture.work, "other-set", row.artifact_id)


def test_unknown_and_prohibited_rights_fail_before_a_job(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    _register_asset(fixture, "broll-unknown", "graphic", b"bytes", status=RightsStatus.UNKNOWN)
    with pytest.raises(MediaError, match="rights status"):
        plan_advanced_candidate(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            work_root=fixture.work,
            broll_asset_ids=["broll-unknown"],
        )
    _register_asset(fixture, "broll-banned", "graphic", b"bytes", status=RightsStatus.PROHIBITED)
    with pytest.raises(MediaError, match="rights status"):
        plan_advanced_candidate(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            work_root=fixture.work,
            broll_asset_ids=["broll-banned"],
        )
    from clipforge.storage import list_jobs

    with fixture.database.connect() as connection:
        jobs = [item for item in list_jobs(connection, PROJECT_ID) if item.kind == "advanced_hero_render"]
    assert jobs == []


def test_symlinked_assets_and_remote_urls_are_rejected(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    _register_asset(fixture, "broll-link", "graphic", b"broll")
    target = tmp_path / "outside.bin"
    target.write_bytes(b"other")
    path = fixture.workspace.advanced_asset_file("broll-link")
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(MediaError, match="symlink"):
        plan_advanced_candidate(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            work_root=fixture.work,
            broll_asset_ids=["broll-link"],
        )
    _register_asset(fixture, "sfx-link", "audio", b"sfx")
    sfx = fixture.workspace.advanced_asset_file("sfx-link")
    sfx.unlink()
    sfx.symlink_to(target)
    with pytest.raises(MediaError, match="symlink"):
        plan_advanced_candidate(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            work_root=fixture.work,
            sfx_asset_ids=["sfx-link"],
        )
    catalog = json.loads(fixture.workspace.advanced_asset_catalog().read_text(encoding="utf-8"))
    catalog["assets"][0]["uri"] = "https://example.invalid/broll.mp4"
    fixture.workspace.advanced_asset_catalog().write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(MediaError, match="remote"):
        plan_advanced_candidate(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            work_root=fixture.work,
            broll_asset_ids=["broll-link"],
        )


def test_changed_sfx_hash_and_review_payload_are_safe(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    _register_asset(fixture, "broll-1", "graphic", b"broll-bytes")
    _register_asset(fixture, "sfx-1", "audio", b"sfx-bytes")
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
        broll_asset_ids=["broll-1"],
        sfx_asset_ids=["sfx-1"],
    )
    render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
    )
    from clipforge.hero.advanced_service import advanced_review_board

    board = advanced_review_board(fixture.database, SOURCE_ID, fixture.work)
    encoded = json.dumps(board)
    assert "file:" not in encoded
    assert "/home/" not in encoded
    assert "/tmp/" not in encoded
    draft = board["drafts"][0]
    assert draft["broll"][0]["display_name"] == "broll-1"
    assert draft["broll"][0]["rights_status"] == "owned"
    assert draft["sfx"][0]["role"] == "sfx"
    assert "gain_db" in draft["sfx"][0]
    assert draft["typography"]
    assert draft["diagrams"][0]["kind"] == "number_comparison"
    assert draft["emphasis"]
    fixture.workspace.advanced_asset_file("sfx-1").write_bytes(b"changed-sfx")
    with pytest.raises(MediaError, match="hash"):
        render_advanced_drafts(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            work_root=fixture.work,
            backend=FakeAdvancedRenderBackend(),
        )


def test_html_text_and_remote_evidence_do_not_become_markup(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    _register_asset(fixture, "broll-1", "graphic", b"broll-bytes")
    _register_asset(fixture, "sfx-1", "audio", b"sfx-bytes")
    with fixture.database.transaction() as connection:
        connection.execute(
            "UPDATE asset_license_records SET evidence_uri = ? WHERE asset_id = ?",
            ("https://example.invalid/evidence", "broll-1"),
        )
    with pytest.raises(MediaError, match="remote"):
        plan_advanced_candidate(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            work_root=fixture.work,
            broll_asset_ids=["broll-1"],
            sfx_asset_ids=["sfx-1"],
        )
    from clipforge.storage import list_jobs

    with fixture.database.connect() as connection:
        jobs = [item for item in list_jobs(connection, PROJECT_ID) if item.kind == "advanced_hero_render"]
    assert jobs == []
    with fixture.database.transaction() as connection:
        connection.execute(
            "UPDATE asset_license_records SET evidence_uri = ? WHERE asset_id = ?",
            ("file:///licenses/owned.txt", "broll-1"),
        )
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
        broll_asset_ids=["broll-1"],
        sfx_asset_ids=["sfx-1"],
    )
    render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
    )
    plan_path = fixture.workspace.advanced_plan_file(candidate_id)
    stored = json.loads(plan_path.read_text(encoding="utf-8"))
    hostile_name = "<img src=x onerror=alert(1)>"
    hostile_label = "<script>alert(1)</script>"
    for asset in stored["assets"]:
        if asset["asset_id"] == "broll-1":
            asset["display_name"] = hostile_name
    stored["diagrams"][0]["payload"]["left_label"] = hostile_label
    plan_path.write_text(json.dumps(stored), encoding="utf-8")
    from clipforge.hero.advanced_service import advanced_review_board, advanced_review_card

    board = advanced_review_board(fixture.database, SOURCE_ID, fixture.work)
    draft = advanced_review_card(fixture.database, SOURCE_ID, candidate_id, fixture.work)
    broll = next(item for item in draft["broll"] if item["asset_id"] == "broll-1")
    assert broll["display_name"] == hostile_name
    assert draft["diagrams"][0]["left_label"] == hostile_label
    encoded = json.dumps(board)
    assert json.loads(encoded)["drafts"][0]["diagrams"][0]["left_label"] == hostile_label
    assert "/home/" not in encoded
    assert "/tmp/" not in encoded
    page = (Path(__file__).parents[1] / "src/clipforge/review/static/advanced-review.js").read_text(
        encoding="utf-8"
    )
    assert "textContent" in page
    assert "innerHTML" not in page
    assert "display_name" in page
    assert "left_label" in page


def test_production_backend_is_remotion() -> None:
    import inspect

    from clipforge.cli.hero_advanced_cmd import advanced_render

    assert isinstance(select_advanced_backend(None), RemotionAdvancedRenderBackend)
    fake = FakeAdvancedRenderBackend()
    assert select_advanced_backend(fake) is fake
    assert "FakeAdvancedRenderBackend" not in inspect.getsource(advanced_render)


def test_review_saves_every_decision(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
    )
    render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
    )
    from clipforge.hero.advanced_service import advanced_review_board, record_advanced_decision

    notes = 'Café 説明 $12.50 <unsafe>&"quoted"'
    board = advanced_review_board(fixture.database, SOURCE_ID, fixture.work)
    for decision in ("rejected", "changes_requested", "approved"):
        record_advanced_decision(
            database=fixture.database,
            work_root=fixture.work,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            advanced_set_id=str(board["advanced_set_id"]),
            artifact_id=str(board["artifact_id"]),
            decision=decision,
            reviewer_id="ada",
            notes=notes,
        )
        time.sleep(0.01)
    shown = advanced_review_board(fixture.database, SOURCE_ID, fixture.work)
    draft = shown["drafts"][0]
    assert draft["current_decision"] == "approved"
    history = [item["decision"] for item in draft["history"]]
    assert history.count("approved") >= 1
    assert "rejected" in history
    assert "changes_requested" in history
    assert any("<unsafe>" in str(item["notes"]) for item in draft["history"])
    with pytest.raises(MediaError, match="decision"):
        record_advanced_decision(
            database=fixture.database,
            work_root=fixture.work,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            advanced_set_id=str(board["advanced_set_id"]),
            artifact_id=str(board["artifact_id"]),
            decision="publish",
            reviewer_id="ada",
            notes="",
        )
    with pytest.raises(MediaError, match="blank"):
        record_advanced_decision(
            database=fixture.database,
            work_root=fixture.work,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            advanced_set_id=str(board["advanced_set_id"]),
            artifact_id=str(board["artifact_id"]),
            decision="rejected",
            reviewer_id=" ",
            notes="",
        )
    with pytest.raises(MediaError, match="4000"):
        record_advanced_decision(
            database=fixture.database,
            work_root=fixture.work,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            advanced_set_id=str(board["advanced_set_id"]),
            artifact_id=str(board["artifact_id"]),
            decision="rejected",
            reviewer_id="ada",
            notes="x" * 4001,
        )
    with pytest.raises(MediaError, match="automated"):
        parse_decision_body({"decision": "approved", "reviewer_id": "ada", "automated": True})


def test_same_content_symlinks_and_escapes_do_not_render(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    _register_asset(fixture, "broll-1", "graphic", b"same-broll")
    _register_asset(fixture, "sfx-1", "audio", b"same-sfx")
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
        broll_asset_ids=["broll-1"],
        sfx_asset_ids=["sfx-1"],
    )
    broll = fixture.workspace.advanced_asset_file("broll-1")
    twin = tmp_path / "same-broll.bin"
    twin.write_bytes(broll.read_bytes())
    broll.unlink()
    broll.symlink_to(twin)
    _assert_render_blocked(fixture, "symlink")
    broll.unlink()
    broll.write_bytes(twin.read_bytes())
    parent = broll.parent
    moved = tmp_path / "real-broll-dir"
    parent.rename(moved)
    parent.symlink_to(moved, target_is_directory=True)
    _assert_render_blocked(fixture, "symlink")


def test_traversal_and_foreign_file_uri_are_rejected(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    _register_asset(fixture, "broll-1", "graphic", b"broll-bytes")
    catalog_path = fixture.workspace.advanced_asset_catalog()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["assets"][0]["relative_path"] = "../outside.bin"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(MediaError, match="escapes"):
        plan_advanced_candidate(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            work_root=fixture.work,
            broll_asset_ids=["broll-1"],
        )
    assert _advanced_jobs(fixture) == []
    catalog["assets"][0]["relative_path"] = str(
        fixture.workspace.advanced_asset_file("broll-1").resolve().relative_to(fixture.work.resolve())
    )
    outside = tmp_path / "elsewhere.bin"
    outside.write_bytes(b"broll-bytes")
    catalog["assets"][0]["uri"] = path_to_file_uri(outside)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(MediaError, match="escapes"):
        plan_advanced_candidate(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            candidate_id=candidate_id,
            work_root=fixture.work,
            broll_asset_ids=["broll-1"],
        )
    assert _advanced_jobs(fixture) == []


def test_changed_asset_hash_blocks_render(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    _register_asset(fixture, "broll-1", "graphic", b"broll-bytes")
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
        broll_asset_ids=["broll-1"],
    )
    fixture.workspace.advanced_asset_file("broll-1").write_bytes(b"changed-bytes")
    _assert_render_blocked(fixture, "hash")


def test_symlinked_advanced_mp4_is_not_served(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
    )
    render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
    )
    from clipforge.hero.advanced_service import advanced_media_path

    video = next(fixture.work.rglob("advanced.mp4"))
    copy = tmp_path / "copy.mp4"
    copy.write_bytes(video.read_bytes())
    video.unlink()
    video.symlink_to(copy)
    with pytest.raises(MediaError, match="symlink"):
        advanced_media_path(fixture.database, SOURCE_ID, candidate_id, fixture.work)


def test_stale_hero_producers_do_not_insert_a_job(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
    )
    hero = review_board(fixture.database, SOURCE_ID, fixture.work)["hero"]
    assert isinstance(hero, dict)
    record_hero_decision(
        database=fixture.database,
        work_root=fixture.work,
        context=decision_context_for(hero, candidate_id),
        decision="rejected",
        reviewer_id="ada",
        notes="",
    )
    _assert_render_blocked(fixture, "approval")


def test_new_hero_artifact_invalidates_the_advanced_plan(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
    )
    _hero(fixture, FakeHeroRenderBackend(), CountingAligner(), force=True)
    hero = review_board(fixture.database, SOURCE_ID, fixture.work)["hero"]
    assert isinstance(hero, dict)
    record_hero_decision(
        database=fixture.database,
        work_root=fixture.work,
        context=decision_context_for(hero, candidate_id),
        decision="approved",
        reviewer_id="ada",
        notes="",
    )
    _assert_render_blocked(fixture, "Hero artifact")


def test_mutated_producers_block_advanced_render(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    _register_asset(fixture, "broll-1", "graphic", b"broll-bytes")
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
        broll_asset_ids=["broll-1"],
    )
    hero = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    alignment = hero.manifest_path.parent / "candidates" / candidate_id / "alignment.json"
    alignment.write_text(alignment.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    _assert_render_blocked(fixture, "alignment")


def test_mutated_hero_plan_source_and_visual_block_render(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
    )
    hero = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    plan = hero.manifest_path.parent / "candidates" / candidate_id / "plan.json"
    original_plan = plan.read_bytes()
    plan.write_bytes(original_plan + b"\n")
    _assert_render_blocked(fixture, "plan")
    plan.write_bytes(original_plan)
    inputs = load_preview_inputs(
        fixture.database,
        SOURCE_ID,
        fixture.work,
        profile_fingerprint=default_profile().fingerprint(),
        create_workspace=False,
    )
    source = path_from_file_uri(inputs.pair.source.uri)
    original = source.read_bytes()
    source.write_bytes(original + b"\x00")
    _assert_render_blocked(fixture, "source")
    source.write_bytes(original)
    visual = inputs.pair.visual_path
    visual_bytes = visual.read_bytes()
    visual.write_bytes(visual_bytes + b"\n")
    _assert_render_blocked(fixture, "visual")


def test_rights_change_and_old_hero_set_block_render(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    _register_asset(fixture, "broll-1", "graphic", b"broll-bytes")
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
        broll_asset_ids=["broll-1"],
    )
    with fixture.database.transaction() as connection:
        connection.execute(
            "UPDATE asset_license_records SET status = ? WHERE asset_id = ?",
            ("prohibited", "broll-1"),
        )
    _assert_render_blocked(fixture, "rights")
    with fixture.database.transaction() as connection:
        connection.execute(
            "UPDATE asset_license_records SET status = ? WHERE asset_id = ?",
            ("owned", "broll-1"),
        )
    stored_path = fixture.workspace.advanced_plan_file(candidate_id)
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    stored["hero_set_id"] = "older-hero-set"
    stored_path.write_text(json.dumps(stored), encoding="utf-8")
    _assert_render_blocked(fixture, "Hero set")
    stored["hero_set_id"] = review_board(fixture.database, SOURCE_ID, fixture.work)["hero"]["hero_set_id"]
    stored["reframing_strategy"] = "center_crop"
    stored_path.write_text(json.dumps(stored), encoding="utf-8")
    render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
        force=True,
    )


def test_profile_disallows_music() -> None:
    profile = AdvancedHeroProfile(reframing=ReframingStrategy(strategy_id="contain"))
    assert profile.music_allowed is False
    assert profile.profile_id == "advanced-hero-v1"
    again = AdvancedHeroProfile(reframing=ReframingStrategy(strategy_id="contain"))
    assert profile.fingerprint() == again.fingerprint()


def _advanced_jobs(fixture) -> list[object]:
    from clipforge.storage import list_jobs

    with fixture.database.connect() as connection:
        return [item for item in list_jobs(connection, PROJECT_ID) if item.kind == "advanced_hero_render"]


def _assert_render_blocked(fixture, match: str) -> None:
    assert not fixture.workspace.advanced_sidecar().exists()
    with pytest.raises(MediaError, match=match):
        render_advanced_drafts(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            work_root=fixture.work,
            backend=FakeAdvancedRenderBackend(),
        )
    assert _advanced_jobs(fixture) == []
    assert not fixture.workspace.advanced_sidecar().exists()


def _approved(tmp_path: Path):
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    board = review_board(fixture.database, SOURCE_ID, fixture.work)
    hero = board["hero"]
    assert isinstance(hero, dict)
    record_hero_decision(
        database=fixture.database,
        work_root=fixture.work,
        context=decision_context_for(hero, ids[0]),
        decision="approved",
        reviewer_id="ada",
        notes="",
    )
    return fixture, ids[0]


def _minimum_plan(typography: list[TypographyEvent]) -> dict[str, object]:
    sha = "a" * 64
    now = datetime.now(UTC).isoformat()
    return {
        "schema_version": "1.0.0",
        "plan_id": "plan-1",
        "project_id": PROJECT_ID,
        "source_asset_id": SOURCE_ID,
        "candidate_id": "cand-1",
        "source_sha256": sha,
        "candidate_set_artifact_id": "cand-set",
        "candidate_set_sha256": sha,
        "rough_preview_artifact_id": "rough",
        "rough_manifest_sha256": sha,
        "hero_artifact_id": "hero",
        "hero_set_id": "hero-set",
        "hero_manifest_sha256": sha,
        "hero_review_id": "review",
        "hero_review_digest": sha,
        "alignment_id": "align",
        "alignment_sha256": sha,
        "hero_plan_id": "hero-plan",
        "hero_plan_sha256": sha,
        "visual_analysis_id": "visual",
        "visual_analysis_sha256": sha,
        "time_map_sha256": sha,
        "profile_fingerprint": sha,
        "reframing_strategy": "contain",
        "reframing_config_sha256": sha,
        "windows": [],
        "typography": [item.model_dump(mode="json") for item in typography],
        "diagrams": [],
        "emphasis": [],
        "broll": [],
        "sfx": [],
        "assets": [],
        "qa_requirements": ["forced_alignment"],
        "provenance": {
            "schema_version": "1.0.0",
            "created_at": now,
            "created_by": "ada",
            "tool": "clipforge-test",
            "tool_version": "0",
            "source_asset_ids": [SOURCE_ID],
            "parent_artifact_ids": [],
            "job_id": None,
            "inputs_sha256": None,
        },
    }


def _register_asset(
    fixture,
    asset_id: str,
    kind: str,
    payload: bytes,
    status: RightsStatus = RightsStatus.OWNED,
) -> None:
    path = fixture.workspace.advanced_asset_file(asset_id)
    fixture.workspace.prepare_advanced_file(path)
    path.write_bytes(payload)
    digest = sha256_file(path)
    relative = str(path.resolve().relative_to(fixture.work.resolve()))
    now = datetime.now(UTC)
    provenance = ArtifactProvenance(
        created_at=now,
        created_by="ada",
        tool="clipforge-test",
        tool_version="0",
        source_asset_ids=[SOURCE_ID],
    )
    license_id = f"lic-{asset_id}"
    record = AssetLicenseRecord(
        license_record_id=license_id,
        asset_id=asset_id,
        status=status,
        evidence_uri=path_to_file_uri(path),
        recorded_at=now,
        recorded_by="ada",
    )
    with fixture.database.transaction() as connection:
        insert_asset_license_record(connection, record)
    catalog = fixture.workspace.advanced_asset_catalog()
    existing: dict[str, object] = {"assets": []}
    if catalog.is_file():
        existing = json.loads(catalog.read_text(encoding="utf-8"))
    assets = existing.get("assets")
    assert isinstance(assets, list)
    assets.append(
        {
            "schema_version": "1.0.0",
            "asset_id": asset_id,
            "project_id": PROJECT_ID,
            "uri": path_to_file_uri(path),
            "kind": kind,
            "license_record_id": license_id,
            "provenance": provenance.model_dump(mode="json"),
            "relative_path": relative,
            "file_sha256": digest,
        }
    )
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(json.dumps({"assets": assets}), encoding="utf-8")
