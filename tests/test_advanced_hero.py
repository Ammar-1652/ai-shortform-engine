"""Advanced Hero editing. Assets are local fixtures. No Envato and no music."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from clipforge.cli.hero_advanced_cmd import _portrait_crop_size
from clipforge.errors import ClipforgeError, MediaError
from clipforge.hero.advanced_backend import (
    FakeAdvancedRenderBackend,
    RemotionAdvancedRenderBackend,
)
from clipforge.hero.advanced_build import _broll, _directed_typography, _sfx, _typography
from clipforge.hero.advanced_service import (
    _require_production_direction,
    default_advanced_profile,
    plan_advanced_candidate,
    render_advanced_drafts,
    select_advanced_backend,
)
from clipforge.hero.backend import FakeHeroRenderBackend
from clipforge.hero.motion_style import EDITORIAL_CLEAN_V1, LEGACY_V1
from clipforge.hero.show import load_current_hero
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri, path_to_file_uri
from clipforge.preview.inputs import load_preview_inputs
from clipforge.preview.service import default_profile
from clipforge.review.hero_board import decision_context_for
from clipforge.review.service import parse_decision_body, record_hero_decision, review_board
from clipforge.schemas.advanced import (
    AdvancedHeroDraftSetDocument,
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
from clipforge.schemas.arc import EditorialArcDocument, EditorialArcSegment
from clipforge.schemas.direction import DirectionAssetPlacement
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.governance import AssetLicenseRecord, RightsStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimelineSegment, TimeMapDocument, digest_time_map
from clipforge.storage import insert_asset_license_record
from tests.candidate_support import PROJECT_ID, SOURCE_ID
from tests.test_hero_service import CountingAligner, _hero, _reviewed

pytestmark = pytest.mark.hero


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1280, 720, (405, 720)),
        (1920, 1080, (603, 1072)),
        (1080, 1920, (1080, 1920)),
    ],
)
def test_manual_portrait_crop_uses_largest_integer_9_by_16_window(
    width: int, height: int, expected: tuple[int, int]
) -> None:
    crop_width, crop_height = _portrait_crop_size(width, height)
    assert (crop_width, crop_height) == expected
    assert crop_width <= width
    assert crop_height <= height
    assert crop_width * 16 == crop_height * 9


def test_manual_portrait_crop_rejects_empty_frame() -> None:
    with pytest.raises(ClipforgeError, match="too small"):
        _portrait_crop_size(0, 720)


def test_manual_crop_trajectory_is_typed_and_fingerprinted() -> None:
    strategy = ReframingStrategy(strategy_id="manual_window")
    windows = [
        ReframingWindow(
            window_id="window-a",
            strategy_id=strategy,
            output_start_us=0,
            output_end_us=1_000_000,
            source_x=100,
            source_y=0,
            source_width=405,
            source_height=720,
            frame_width=1280,
            frame_height=720,
        ),
        ReframingWindow(
            window_id="window-b",
            strategy_id=strategy,
            output_start_us=1_000_000,
            output_end_us=2_000_000,
            source_x=300,
            source_y=0,
            source_width=405,
            source_height=720,
            frame_width=1280,
            frame_height=720,
        ),
    ]
    base = default_advanced_profile()
    trajectory = AdvancedHeroProfile.model_validate(
        {
            **base.model_dump(mode="json"),
            "reframing": strategy.model_dump(mode="json"),
            "manual_windows": [item.model_dump(mode="json") for item in windows],
        }
    )
    assert trajectory.fingerprint() != base.fingerprint()
    assert len(trajectory.manual_windows) == 2
    with pytest.raises(ValidationError, match="choose the legacy singular crop"):
        AdvancedHeroProfile.model_validate(
            {
                **trajectory.model_dump(mode="json"),
                "manual_window": windows[0].model_dump(mode="json"),
            }
        )


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
    assert plan.time_map is not None
    assert plan.time_map_sha256 == digest_time_map(plan.time_map)
    # Clean production does not fabricate cards when no reviewed direction
    # exists. The explicit legacy recipe is the only compatibility path for
    # the old heuristic hook/punch behavior.
    assert plan.typography == []
    assert plan.captions and all(item.words for item in plan.captions)
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


def test_editorial_arc_persists_remapped_alignment_and_time_map(tmp_path: Path) -> None:
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
        notes="arc",
    )
    from clipforge.hero.advanced_service import _context

    context = _context(fixture.database, SOURCE_ID, ids[0], fixture.work)
    words = context.alignment.words
    assert len(words) >= 3
    chosen = [words[0], words[len(words) // 2], words[-1]]
    mapped = TimeMapDocument(
        time_map_id="arc-map",
        segments=[
            TimelineSegment(
                segment_id=f"arc-{index}",
                source_start_us=word.source_start_us,
                source_end_us=word.source_end_us,
            )
            for index, word in enumerate(chosen)
        ],
    )
    arc = EditorialArcDocument(
        arc_id="arc-test",
        transition_style="clean_cut_v1",
        project_id=context.project_id,
        source_asset_id=SOURCE_ID,
        candidate_id=ids[0],
        source_sha256=context.source_sha256,
        hero_plan_sha256=context.hero_plan_sha256,
        alignment_sha256=context.alignment_sha256,
        time_map=mapped,
        time_map_sha256=digest_time_map(mapped),
        segments=[
            EditorialArcSegment(
                segment_id=segment.segment_id,
                source_start_us=segment.source_start_us,
                source_end_us=segment.source_end_us,
                word_ids=[word.word_id],
                beat=beat,
                purpose=f"{beat} evidence",
                continuation=True,
                claim_closure="complete",
            )
            for segment, word, beat in zip(mapped.segments, chosen, ("hook", "body", "punch"), strict=True)
        ],
    )
    plan = plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=ids[0],
        work_root=fixture.work,
        editorial_arc=arc,
        editorial_arc_sha256="a" * 64,
    )
    assert plan.editorial_arc_id == "arc-test"
    assert plan.time_map is not None
    assert len(plan.time_map.segments) == 3
    assert len(plan.transitions) == 2
    mapped_runtime = mapped.to_time_map().segments
    assert [event.interval.output_start_us for event in plan.transitions] == [
        mapped_runtime[1].output_start_us,
        mapped_runtime[2].output_start_us,
    ]
    advanced_alignment = fixture.workspace.advanced_alignment_file(ids[0])
    assert advanced_alignment.is_file()
    assert plan.alignment_sha256 == sha256_file(advanced_alignment)
    assert plan.alignment_sha256 != context.alignment_sha256
    assert plan.editorial_arc_sha256 == sha256_file(fixture.workspace.advanced_arc_file(ids[0]))


def test_typography_builds_exact_hook_and_punch_cards() -> None:
    words = []
    for index, text in enumerate(("Intro", "line", "never", "knew", "his", "biological", "father,", "final.")):
        start = index * 1_000_000
        words.append(
            SimpleNamespace(
                text=text,
                output_start_us=start,
                output_end_us=start + 900_000,
            )
        )
    events = _typography(SimpleNamespace(words=words), [], "candidate")
    assert [item.component_id for item in events] == ["hook-card-v1", "punch-card-v1"]
    assert events[0].text == "never knew his biological father,"
    assert events[1].text == "biological father, final."


def test_direction_accent_tracks_stay_below_face_space_and_above_captions() -> None:
    words = [
        SimpleNamespace(
            word_id=f"word-{index}", output_start_us=index * 1_000_000, output_end_us=(index + 1) * 1_000_000
        )
        for index in range(3)
    ]
    beats = [
        SimpleNamespace(
            beat_id=f"beat-{kind}",
            kind=kind,
            display_text=f"source phrase {kind}",
            evidence_ids=[f"evidence-{kind}"],
        )
        for kind in ("hook", "body", "punch")
    ]
    evidence = [
        SimpleNamespace(evidence_id=f"evidence-{kind}", source_word_ids=[f"word-{index}"])
        for index, kind in enumerate(("hook", "body", "punch"))
    ]
    direction = SimpleNamespace(
        direction_id="direction",
        selected_option_id="selected",
        options=[SimpleNamespace(option_id="selected", beats=beats, evidence=evidence)],
    )
    events = _directed_typography(direction, SimpleNamespace(words=words), "candidate")
    line_top = [event.y + (-34 if event.component_id == "punch-card-v1" else 68) for event in events]
    assert line_top == [1280, 1280, 1280]
    line_width = {"hook-card-v1": 620, "body-card-v1": 520, "punch-card-v1": 760}
    assert [event.x + line_width[event.component_id] // 2 for event in events] == [540, 540, 540]
    assert all(event.y >= 1_212 for event in events)


def test_clean_production_requires_direction_before_remotion() -> None:
    plan = SimpleNamespace(
        style_id="editorial-clean-v1",
        direction_id="",
        direction_sha256="",
        broll=[],
        sfx=[],
    )
    with pytest.raises(MediaError, match="requires a persisted source-grounded direction"):
        _require_production_direction(plan, RemotionAdvancedRenderBackend())  # type: ignore[arg-type]


def test_clean_production_rejects_unbound_asset_timing() -> None:
    plan = SimpleNamespace(
        style_id="editorial-clean-v1",
        direction_id="direction-1",
        direction_sha256="a" * 64,
        broll=[SimpleNamespace(source_evidence_ids=[], relevance_note="")],
        sfx=[],
    )
    with pytest.raises(MediaError, match="B-roll requires source evidence"):
        _require_production_direction(plan, RemotionAdvancedRenderBackend())  # type: ignore[arg-type]


def test_reviewed_repeated_asset_placements_keep_order_and_inpoints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Reusing one asset must not collapse later placements onto the first cue."""
    entry = SimpleNamespace(
        asset_id="asset-1", file_sha256="a" * 64, reference=SimpleNamespace(content_tags=["phrase"])
    )
    license_record = SimpleNamespace(license_record_id="license-1", status=SimpleNamespace(value="licensed"))
    monkeypatch.setattr(
        "clipforge.hero.advanced_build.require_asset",
        lambda *args, **kwargs: (entry, license_record, tmp_path / "asset"),
    )
    monkeypatch.setattr(
        "clipforge.hero.advanced_build.binding_for",
        lambda entry, license_record, slot: SimpleNamespace(asset_id=entry.asset_id),
    )
    placements = [
        DirectionAssetPlacement(
            placement_id="placement-a",
            asset_id="asset-1",
            kind="graphic",
            interval=OutputInterval(output_start_us=100_000, output_end_us=400_000),
            source_in_us=2_000_000,
            source_evidence_ids=["evidence-a"],
            purpose=MotionPurpose.CONCEPT,
            relevance_note="The first phrase is illustrated here.",
            asset_tags=["phrase"],
        ),
        DirectionAssetPlacement(
            placement_id="placement-b",
            asset_id="asset-1",
            kind="graphic",
            interval=OutputInterval(output_start_us=1_100_000, output_end_us=1_500_000),
            source_in_us=7_000_000,
            source_evidence_ids=["evidence-b"],
            purpose=MotionPurpose.VISUAL_REVEAL,
            relevance_note="The later phrase gets a deliberate return.",
            asset_tags=["phrase"],
        ),
    ]
    assets: list[object] = []
    events = _broll(
        None,
        None,
        tmp_path,
        "project-1",
        "candidate-1",
        2_000_000,
        ["asset-1", "asset-1"],
        assets,
        placements,
    )  # type: ignore[arg-type]
    assert [event.interval.output_start_us for event in events] == [100_000, 1_100_000]
    assert [event.broll_source_in_us for event in events] == [2_000_000, 7_000_000]
    assert events[0].event_id != events[1].event_id
    assert len(assets) == 1

    sfx_placements = [item.model_copy(update={"kind": "audio"}) for item in placements]
    audio_assets: list[object] = []
    sfx = _sfx(
        None,
        None,
        tmp_path,
        "project-1",
        "candidate-1",
        2_000_000,
        ["asset-1", "asset-1"],
        audio_assets,
        default_advanced_profile(),
        sfx_placements,
    )  # type: ignore[arg-type]
    assert [event.sfx_source_in_us for event in sfx] == [2_000_000, 7_000_000]
    assert [event.gain_db for event in sfx] == [-18, -18]
    assert [(event.fade_in_us, event.fade_out_us) for event in sfx] == [
        (20_000, 60_000),
        (20_000, 60_000),
    ]
    assert len(audio_assets) == 1


def test_clean_broll_rejects_placement_tags_that_do_not_match_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    entry = SimpleNamespace(
        asset_id="asset-1", file_sha256="a" * 64, reference=SimpleNamespace(content_tags=["concept"])
    )
    license_record = SimpleNamespace(license_record_id="license-1", status=SimpleNamespace(value="licensed"))
    monkeypatch.setattr(
        "clipforge.hero.advanced_build.require_asset",
        lambda *args, **kwargs: (entry, license_record, tmp_path / "asset"),
    )
    monkeypatch.setattr(
        "clipforge.hero.advanced_build.binding_for",
        lambda entry, license_record, slot: SimpleNamespace(asset_id=entry.asset_id),
    )
    placement = DirectionAssetPlacement(
        placement_id="placement-a",
        asset_id="asset-1",
        kind="graphic",
        interval=OutputInterval(output_start_us=100_000, output_end_us=400_000),
        source_evidence_ids=["evidence-a"],
        purpose=MotionPurpose.CONCEPT,
        relevance_note="An unrelated insert.",
        asset_tags=["unrelated"],
    )
    with pytest.raises(MediaError, match="placement tags do not match"):
        _broll(
            None,
            None,
            tmp_path,
            "project-1",
            "candidate-1",
            2_000_000,
            ["asset-1"],
            [],
            [placement],
        )  # type: ignore[arg-type]


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


def test_editorial_clean_style_is_versioned_and_cache_distinct() -> None:
    assert EDITORIAL_CLEAN_V1.style_id == "editorial-clean-v1"
    assert EDITORIAL_CLEAN_V1.fingerprint() != LEGACY_V1.fingerprint()
    assert default_advanced_profile().renderer_recipe_version == "advanced-hero-renderer-directed-v4"
    prior_geometry_recipe = default_advanced_profile().model_copy(
        update={"renderer_recipe_version": "advanced-hero-renderer-directed-v3"}
    )
    assert prior_geometry_recipe.fingerprint() != default_advanced_profile().fingerprint()
    legacy = default_advanced_profile().model_copy(
        update={
            "caption_algorithm_version": "advanced-caption-v1",
            "typography_version": "advanced-typography-v1",
            "diagram_version": "advanced-diagram-v1",
            "renderer_recipe_version": "advanced-hero-renderer-v1",
            "motion_library_version": "advanced-motion-v1",
        }
    )
    assert legacy.fingerprint() != default_advanced_profile().fingerprint()


def test_overlap_typography_and_unsupported_diagram_box() -> None:
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
    with pytest.raises(ValidationError, match="unsupported production diagram kind"):
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


def test_draft_only_advanced_render_is_marked_pending_and_not_default_renderable(tmp_path: Path) -> None:
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    plan = plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=ids[0],
        work_root=fixture.work,
        allow_unapproved=True,
    )
    assert plan.hero_review_status == "pending"
    default_render = render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
    )
    assert default_render.status == "noop"
    assert not fixture.workspace.advanced_plan_file(ids[0]).exists()
    assert not fixture.workspace.advanced_sidecar().exists()
    rendered = render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
        draft_only=True,
    )
    assert rendered.status == "rendered"
    manifest = fixture.workspace.advanced_review_run_dir(rendered.advanced_set_id or "") / "manifest.json"
    document = AdvancedHeroDraftSetDocument.model_validate_json(manifest.read_text(encoding="utf-8"))
    assert document.hero_review_status == "pending"
    assert fixture.workspace.advanced_review_sidecar().is_file()
    assert fixture.workspace.advanced_review_plan_file(ids[0]).is_file()


def test_pending_review_render_preserves_approved_advanced_namespace(tmp_path: Path) -> None:
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
        notes="approved baseline",
    )
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=ids[0],
        work_root=fixture.work,
    )
    render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
    )
    approved_sidecar = fixture.workspace.advanced_sidecar().read_bytes()
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=ids[0],
        work_root=fixture.work,
        allow_unapproved=True,
    )
    pending = render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
        draft_only=True,
    )
    assert pending.status == "rendered"
    assert fixture.workspace.advanced_sidecar().read_bytes() == approved_sidecar
    assert fixture.workspace.advanced_review_sidecar().is_file()
    with fixture.database.connect() as connection:
        kinds = [
            str(row["kind"])
            for row in connection.execute(
                "SELECT kind FROM artifacts WHERE project_id = ? AND source_asset_id = ? ORDER BY created_at",
                (PROJECT_ID, SOURCE_ID),
            ).fetchall()
        ]
    assert "advanced_hero_draft_set_json" in kinds
    assert "advanced_hero_review_draft_set_json" in kinds


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
    assert draft["typography"] == []
    assert draft["diagrams"] == []
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
    for asset in stored["assets"]:
        if asset["asset_id"] == "broll-1":
            asset["display_name"] = hostile_name
    stored["diagrams"] = []
    plan_path.write_text(json.dumps(stored), encoding="utf-8")
    from clipforge.hero.advanced_service import advanced_review_board, advanced_review_card

    board = advanced_review_board(fixture.database, SOURCE_ID, fixture.work)
    draft = advanced_review_card(fixture.database, SOURCE_ID, candidate_id, fixture.work)
    broll = next(item for item in draft["broll"] if item["asset_id"] == "broll-1")
    assert broll["display_name"] == hostile_name
    encoded = json.dumps(board)
    assert json.loads(encoded)["drafts"][0]["diagrams"] == []
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


def test_profile_fingerprint_binds_time_map_staging_recipe() -> None:
    current = default_advanced_profile()
    legacy = current.model_copy(update={"staging_recipe_version": "time-map-v1-audio-envelope"})
    assert current.staging_recipe_version == "time-map-v2-frame-quantized"
    assert current.fingerprint() != legacy.fingerprint()


def test_directed_v2_profile_remains_verifiable_without_native_graphics_field() -> None:
    v2 = default_advanced_profile().model_copy(
        update={"renderer_recipe_version": "advanced-hero-renderer-directed-v2"}
    )
    old_payload = v2.model_dump(mode="json")
    old_payload.pop("motion_graphics_version")
    loaded_old = AdvancedHeroProfile.model_validate(old_payload)
    assert loaded_old.fingerprint() == v2.fingerprint()
    assert default_advanced_profile().fingerprint() != v2.fingerprint()


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
            "content_tags": ["concept"] if kind == "graphic" else [],
            "relative_path": relative,
            "file_sha256": digest,
        }
    )
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(json.dumps({"assets": assets}), encoding="utf-8")
