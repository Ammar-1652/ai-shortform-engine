from __future__ import annotations

import pytest
from pydantic import ValidationError

from clipforge.editorial.presets import PresetCatalog
from clipforge.hero.advanced_build import _build_treatment_audio_mix
from clipforge.hero.advanced_service import default_advanced_profile
from clipforge.hero.treatment import materialize_treatment, summarize_treatment, treatment_fingerprint
from clipforge.hero.treatment_policy import evaluate_treatment_policy
from clipforge.schemas.advanced import AudioMixEvent
from clipforge.schemas.direction import DirectionAssetPlacement
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.treatment import (
    BrollTreatmentDecision,
    SfxTreatmentDecision,
)
from tests.candidate_support import visual_document
from tests.test_direction import _aligned_words, _document


def test_materialized_generic_treatment_covers_beats_and_adds_bounded_camera() -> None:
    option = _document().options[0]
    preset = PresetCatalog.load().find("clean_explainer")
    treated = materialize_treatment(option, _aligned_words(), preset)

    assert len(treated.treatment_decisions) == len(treated.beats)
    assert len(treated.camera_motion) == 2
    fingerprint = treatment_fingerprint(treated)
    assert all(item.dependency_fingerprint == fingerprint for item in treated.treatment_decisions)
    summary = summarize_treatment(treated)
    assert summary.provider_request_count == 4
    assert "camera" in summary.used_layers
    assert "motion_graphics" in summary.blocked_layers


def test_restricted_treatment_blocks_outside_broll_and_sfx() -> None:
    option = _document().options[0]
    preset = PresetCatalog.load().find("clean_explainer")
    treated = materialize_treatment(option, _aligned_words(), preset, restricted_profile=True)

    assert all(item.broll.state == "blocked_by_policy" for item in treated.treatment_decisions)
    assert all(item.sfx.state == "blocked_by_policy" for item in treated.treatment_decisions)
    assert all(not item.asset_requests for item in treated.treatment_decisions)


def test_treatment_rejects_use_without_event_or_asset() -> None:
    with pytest.raises(ValidationError, match="used treatment must reference"):
        BrollTreatmentDecision(
            state="use",
            rationale="missing binding",
            role="context",
            relevance_note="missing",
            source_evidence_ids=["e-1"],
        )


def test_treatment_rejects_missing_omission_reason() -> None:
    with pytest.raises(ValidationError, match="omission_reason"):
        SfxTreatmentDecision(
            state="omit_with_reason",
            rationale="missing reason",
            source_evidence_ids=["e-1"],
        )


def test_treatment_fingerprint_changes_when_camera_changes() -> None:
    option = _document().options[0]
    preset = PresetCatalog.load().find("clean_explainer")
    treated = materialize_treatment(option, _aligned_words(), preset)
    changed = treated.model_copy(
        update={
            "camera_motion": [
                treated.camera_motion[0].model_copy(update={"travel_px": 20}),
                *treated.camera_motion[1:],
            ]
        }
    )
    assert treatment_fingerprint(treated) != treatment_fingerprint(changed)


def test_broll_relevance_is_related_or_unrelated_from_reviewed_tags() -> None:
    option = _document().options[0]
    placement = DirectionAssetPlacement(
        placement_id="placement-1",
        asset_id="asset-1",
        kind="graphic",
        interval=OutputInterval(output_start_us=0, output_end_us=1_000_000),
        source_evidence_ids=[option.evidence[0].evidence_id],
        purpose=MotionPurpose.CONCEPT,
        relevance_note="source context",
        asset_tags=["source", "the"],
    )
    preset = PresetCatalog.load().find("clean_explainer")
    related = materialize_treatment(
        option.model_copy(update={"asset_placements": [placement]}),
        _aligned_words(),
        preset,
        require_asset_selection=False,
    )
    assert related.treatment_decisions[0].visual_evidence is not None
    assert related.treatment_decisions[0].visual_evidence.relevance_status == "related"
    unrelated = materialize_treatment(
        option.model_copy(
            update={"asset_placements": [placement.model_copy(update={"asset_tags": ["ocean"]})]}
        ),
        _aligned_words(),
        preset,
        require_asset_selection=False,
    )
    assert unrelated.treatment_decisions[0].visual_evidence is not None
    assert unrelated.treatment_decisions[0].visual_evidence.relevance_status == "unrelated"


def test_face_collision_removes_camera_event_from_render_treatment() -> None:
    option = (
        _document()
        .options[0]
        .model_copy(
            update={
                "evidence": [
                    item.model_copy(update={"visual_scene_ids": ["scene-0"]})
                    for item in _document().options[0].evidence
                ]
            }
        )
    )
    visual = visual_document(
        3_000_000,
        [(0, 3_000_000)],
        source_sha256="a" * 64,
        proxy_sha256="b" * 64,
        faces=True,
    )
    treated = materialize_treatment(
        option,
        _aligned_words(),
        PresetCatalog.load().find("clean_explainer"),
        visual=visual,
    )
    assert not treated.camera_motion
    assert all(item.camera.state != "use" for item in treated.treatment_decisions)


def test_shared_policy_evaluator_rejects_unbound_asset_placement() -> None:
    option = _document().options[0]
    placement = DirectionAssetPlacement(
        placement_id="placement-unbound",
        asset_id="asset-1",
        kind="graphic",
        interval=OutputInterval(output_start_us=0, output_end_us=1_000_000),
        source_evidence_ids=[option.evidence[0].evidence_id],
        purpose=MotionPurpose.CONCEPT,
        relevance_note="context",
        asset_tags=["source"],
    )
    treated = materialize_treatment(
        option.model_copy(update={"asset_placements": [placement]}),
        _aligned_words(),
        PresetCatalog.load().find("clean_explainer"),
        require_asset_selection=False,
    )
    findings = evaluate_treatment_policy(
        treated,
        PresetCatalog.load().find("clean_explainer").treatment_policy,
    )
    assert any(item.code == "asset_request_not_acquired" for item in findings)


def test_audio_mix_records_real_speech_overlap_and_silence() -> None:
    direction = _document()
    event = AudioMixEvent(
        event_id="sfx-1",
        interval=OutputInterval(output_start_us=3_000_000, output_end_us=4_000_000),
        asset_id="asset-1",
        gain_db=-18,
    )
    mix = _build_treatment_audio_mix(direction, [event], default_advanced_profile(), _aligned_words())
    assert mix is not None
    assert mix.speech_overlap_windows == [None]

    overlap = event.model_copy(
        update={"interval": OutputInterval(output_start_us=1_500_000, output_end_us=2_500_000)}
    )
    overlap_mix = _build_treatment_audio_mix(direction, [overlap], default_advanced_profile(), _aligned_words())
    assert overlap_mix is not None
    assert overlap_mix.speech_overlap_windows[0] == OutputInterval(
        output_start_us=1_500_000, output_end_us=2_500_000
    )


def test_audio_mix_preserves_disjoint_speech_and_silence_windows() -> None:
    direction = _document()
    words = [
        _aligned_words()[0].model_copy(update={"output_start_us": 0, "output_end_us": 500_000}),
        _aligned_words()[1].model_copy(update={"output_start_us": 1_500_000, "output_end_us": 2_000_000}),
    ]
    event = AudioMixEvent(
        event_id="sfx-disjoint",
        interval=OutputInterval(output_start_us=0, output_end_us=2_500_000),
        asset_id="asset-1",
        gain_db=-18,
    )
    mix = _build_treatment_audio_mix(direction, [event], default_advanced_profile(), words)
    assert mix is not None
    assert mix.speech_overlap_windows_v2 == [
        [
            OutputInterval(output_start_us=0, output_end_us=500_000),
            OutputInterval(output_start_us=1_500_000, output_end_us=2_000_000),
        ]
    ]
    assert mix.silence_windows_v2 == [
        [
            OutputInterval(output_start_us=500_000, output_end_us=1_500_000),
            OutputInterval(output_start_us=2_000_000, output_end_us=2_500_000),
        ]
    ]
