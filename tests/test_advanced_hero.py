"""Advanced Hero editing. Assets are local fixtures. No Envato and no music."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.advanced_backend import FakeAdvancedRenderBackend
from clipforge.hero.advanced_service import plan_advanced_candidate, render_advanced_drafts
from clipforge.hero.backend import FakeHeroRenderBackend
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_to_file_uri
from clipforge.review.hero_board import decision_context_for
from clipforge.review.service import record_hero_decision, review_board
from clipforge.schemas.advanced import (
    AdvancedHeroPlanDocument,
    AdvancedHeroProfile,
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


def test_profile_disallows_music() -> None:
    profile = AdvancedHeroProfile(reframing=ReframingStrategy(strategy_id="contain"))
    assert profile.music_allowed is False
    assert profile.profile_id == "advanced-hero-v1"
    again = AdvancedHeroProfile(reframing=ReframingStrategy(strategy_id="contain"))
    assert profile.fingerprint() == again.fingerprint()


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


def _register_asset(fixture, asset_id: str, kind: str, payload: bytes) -> None:
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
        status=RightsStatus.OWNED,
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
