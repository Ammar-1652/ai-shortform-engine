import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clipforge.campaign.overlays import (
    _selected_source_sample_times,
    choose_tarteel_foreground_position,
    choose_tarteel_overlay_start_us,
    overlay_spec_sha256,
    require_tarteel_overlay_matches_plan,
)
from clipforge.campaign.quran import (
    _apply_display_corrections,
    canonicalize_quran_alignment,
    load_tarteel_quran_review,
    load_tarteel_speech_review,
    quran_review_for_alignment,
    reviewed_quran_font,
    validate_tarteel_speech_review_ranges,
)
from clipforge.errors import MediaError
from clipforge.hero.advanced_service import _tarteel_face_samples_for_plan
from clipforge.schemas.advanced import AdvancedHeroPlanDocument, ReframingStrategy, ReframingWindow
from clipforge.schemas.campaign import (
    CampaignOverlaySpec,
    OverlayExclusionEvidence,
    OverlayExclusionRegion,
    OverlayExclusionSample,
    QuranAudioMapping,
    QuranCanonicalSource,
    QuranCaptionReview,
    QuranVerificationPolicy,
    TarteelArabicCorrection,
    TarteelArabicCorrectionDocument,
    TarteelDisplayCorrection,
    TarteelSpeechInterval,
    TarteelSpeechReview,
)
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimelineSegment, TimeMapDocument
from clipforge.schemas.vision import FaceDetectionSample, NormalizedBoundingBox


def _font_policy(relative: str, digest: str) -> QuranVerificationPolicy:
    return QuranVerificationPolicy(
        quran_text="canonical_uthmani_only",
        timing="forced_alignment_required",
        pronunciation_status="canonical_match_verified",
        font_identity="amiri-quran-local-v1",
        font_relative_path=relative,
        font_sha256=digest,
    )


def test_reviewed_font_resolves_exact_bytes_without_environment_configuration(tmp_path: Path) -> None:
    font = tmp_path / "fonts" / "AmiriQuran.ttf"
    font.parent.mkdir()
    font.write_bytes(b"reviewed-font-fixture")
    policy = _font_policy("fonts/AmiriQuran.ttf", hashlib.sha256(font.read_bytes()).hexdigest())
    assert reviewed_quran_font(tmp_path, policy) == font
    font.write_bytes(b"changed-font")
    with pytest.raises(MediaError, match="hash changed"):
        reviewed_quran_font(tmp_path, policy)


@pytest.mark.parametrize("relative", ["../outside.ttf", "/tmp/outside.ttf", "fonts\\outside.ttf"])
def test_reviewed_font_rejects_unconfined_paths(tmp_path: Path, relative: str) -> None:
    with pytest.raises(MediaError, match="relative path"):
        reviewed_quran_font(tmp_path, _font_policy(relative, "a" * 64))


def test_reviewed_font_rejects_missing_file_and_symlink(tmp_path: Path) -> None:
    policy = _font_policy("AmiriQuran.ttf", "a" * 64)
    with pytest.raises(MediaError, match="missing"):
        reviewed_quran_font(tmp_path, policy)
    real = tmp_path / "real.ttf"
    real.write_bytes(b"font")
    (tmp_path / "AmiriQuran.ttf").symlink_to(real)
    with pytest.raises(MediaError, match="symlink"):
        reviewed_quran_font(tmp_path, policy)


def test_tarteel_speech_review_requires_reviewed_text_for_captioned_speech() -> None:
    with pytest.raises(ValueError, match="observed text"):
        TarteelSpeechInterval(
            span_id="speech-1",
            source_start_us=0,
            source_end_us=1_000_000,
            kind="dialogue",
            caption_decision="captioned",
            review_note="listened",
        )


def test_tarteel_arabic_correction_keeps_raw_and_corrected_text_separate() -> None:
    correction = TarteelArabicCorrection(
        correction_id="correction-1",
        source_word_id="word-1",
        source_window_us=(0, 500_000),
        original_text="الحفظ",
        corrected_text="الحفظ",
        locale="ar",
        evidence_kind="listening_context",
        reviewer="reviewer-1",
        review_note="confirmed against the selected audio",
    )
    document = TarteelArabicCorrectionDocument(
        correction_set_id="corrections-1",
        campaign="tarteel",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        raw_asr_sha256="b" * 64,
        transcript_sha256="c" * 64,
        locale="ar",
        corrections=[correction],
        reviewer="reviewer-1",
        reviewed_at=datetime.now(UTC),
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="reviewer-1",
            tool="tarteel-review",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )
    assert document.corrections[0].original_text != ""
    assert document.raw_asr_sha256 == "b" * 64


def test_cta_beat_prefers_a_caption_free_middle_or_latter_slot() -> None:
    start = choose_tarteel_overlay_start_us(
        50_000_000,
        3_000_000,
        [(30_000_000, 50_000_000)],
    )
    assert start == 23_000_000


def test_cta_beat_uses_payoff_slot_when_every_candidate_contains_speech() -> None:
    start = choose_tarteel_overlay_start_us(
        42_778_000,
        3_000_000,
        [(0, 42_778_000)],
    )
    assert start == 33_366_840


def test_new_tarteel_overlay_coordinates_are_foreground_relative() -> None:
    overlay = CampaignOverlaySpec(
        cta_asset_id="cta-asset",
        cta_asset_sha256="a" * 64,
        cta_asset_name="tarteel-cta-alpha.webm",
        cta_start_us=1_000_000,
        cta_end_us=3_000_000,
        watermark_asset_id="watermark-asset",
        watermark_asset_sha256="b" * 64,
        watermark_asset_name="tarteel-watermark-alpha.png",
        sizing_method="source_frame_scan_v1",
        sizing_measurement_sha256="c" * 64,
    )
    assert overlay.cta_position == "foreground_attention_v1"
    assert overlay.overlay_coordinate_space == "foreground_v1"
    assert overlay.watermark_position == "foreground_top_right_v1"


def _exclusion_sample(phase: str, *, overlap_face: bool = False) -> OverlayExclusionSample:
    regions = [
        OverlayExclusionRegion(kind=kind, status="absent_reviewed")
        for kind in (
            "face",
            "child_body",
            "tablet",
            "caption",
            "context_line",
            "source_logo",
            "watermark",
            "platform_rail",
        )
    ]
    if overlap_face:
        regions[0] = OverlayExclusionRegion(
            kind="face",
            status="present",
            left=100,
            top=100,
            width=200,
            height=200,
            annotation_id="face-1",
        )
    return OverlayExclusionSample(
        sample_id=f"sample-{phase}",
        phase=phase,
        output_frame_index={"entrance": 10, "hold": 20, "exit": 30, "maximum_extent": 25}[phase],
        output_time_us={
            "entrance": 1_100_000,
            "hold": 1_500_000,
            "exit": 2_500_000,
            "maximum_extent": 1_900_000,
        }[phase],
        sample_frame_sha256="a" * 64,
        cta_left=500 if not overlap_face else 100,
        cta_top=500 if not overlap_face else 100,
        cta_width=200,
        cta_height=120,
        exclusions=regions,
    )


def test_overlay_exclusion_evidence_requires_all_animation_phases_and_clearance() -> None:
    overlay = CampaignOverlaySpec(
        cta_asset_id="cta-asset",
        cta_asset_sha256="a" * 64,
        cta_asset_name="tarteel-cta-alpha.webm",
        cta_start_us=1_000_000,
        cta_end_us=3_000_000,
        watermark_asset_id="watermark-asset",
        watermark_asset_sha256="b" * 64,
        watermark_asset_name="tarteel-watermark-alpha.png",
        sizing_method="source_frame_scan_v1",
        sizing_measurement_sha256="c" * 64,
    )
    evidence = OverlayExclusionEvidence(
        evidence_id="exclusion-1",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="d" * 64,
        time_map_sha256="e" * 64,
        overlay_spec_sha256=overlay_spec_sha256(overlay),
        transform_sha256="f" * 64,
        cta_start_us=1_000_000,
        cta_end_us=3_000_000,
        samples=[_exclusion_sample(phase) for phase in ("entrance", "hold", "exit", "maximum_extent")],
        decision="clear",
        reviewer="reviewer-1",
        reviewed_at=datetime.now(UTC),
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="reviewer-1",
            tool="tarteel-overlay-review",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )
    assert evidence.decision == "clear"
    with pytest.raises(ValueError, match="intersects face"):
        OverlayExclusionEvidence.model_validate(
            {
                **evidence.model_dump(mode="json"),
                "samples": [
                    _exclusion_sample("entrance", overlap_face=True).model_dump(mode="json"),
                    *[
                        _exclusion_sample(phase).model_dump(mode="json")
                        for phase in ("hold", "exit", "maximum_extent")
                    ],
                ],
            }
        )
    with pytest.raises(ValueError, match="unknown"):
        unknown_sample = _exclusion_sample("maximum_extent").model_dump(mode="json")
        unknown_sample["exclusions"][0]["status"] = "unknown"
        OverlayExclusionEvidence.model_validate(
            {
                **evidence.model_dump(mode="json"),
                "samples": [
                    _exclusion_sample(phase).model_dump(mode="json") for phase in ("entrance", "hold", "exit")
                ]
                + [unknown_sample],
            }
        )


def test_tarteel_speech_inventory_is_source_bound_and_covers_retained_ranges(tmp_path: Path) -> None:
    review = TarteelSpeechReview(
        review_id="speech-review-1",
        campaign="tarteel",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        raw_asr_sha256="b" * 64,
        transcript_sha256="c" * 64,
        locale="ar",
        intervals=[
            TarteelSpeechInterval(
                span_id="speech-1",
                source_start_us=0,
                source_end_us=500_000,
                kind="dialogue",
                caption_decision="captioned",
                observed_text="مرحبا",
                review_note="heard and checked",
            ),
            TarteelSpeechInterval(
                span_id="speech-2",
                source_start_us=500_000,
                source_end_us=1_000_000,
                kind="silence",
                caption_decision="reviewed_excluded",
                review_note="silence",
            ),
        ],
        reviewer="reviewer-1",
        reviewed_at=datetime.now(UTC),
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="reviewer-1",
            tool="tarteel-review",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )
    sidecar = tmp_path / "campaigns/Tarteel/candidate-1/speech-review.json"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text(review.model_dump_json(), encoding="utf-8")
    loaded = load_tarteel_speech_review(
        tmp_path,
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        raw_asr_sha256="b" * 64,
        transcript_sha256="c" * 64,
    )
    assert loaded is not None
    validate_tarteel_speech_review_ranges(loaded[0], [(0, 1_000_000)])
    with pytest.raises(MediaError, match="does not cover"):
        validate_tarteel_speech_review_ranges(loaded[0], [(0, 1_100_000)])
    with pytest.raises(MediaError, match="ASR hash"):
        load_tarteel_speech_review(
            tmp_path,
            source_asset_id="source-1",
            candidate_id="candidate-1",
            raw_asr_sha256="d" * 64,
        )


def test_branding_measurement_samples_only_retained_jump_cut_ranges() -> None:
    samples = _selected_source_sample_times([(0, 1_000_000), (10_000_000, 11_000_000)])
    assert len(samples) == 16
    assert all(0 <= sample < 1_000_000 for sample in samples[:8])
    assert all(10_000_000 <= sample < 11_000_000 for sample in samples[8:])
    assert not any(1_000_000 <= sample < 10_000_000 for sample in samples)
    with pytest.raises(MediaError, match="positive selected source ranges"):
        _selected_source_sample_times([(1_000_000, 1_000_000)])


def test_render_staging_cannot_replace_reviewed_cta_geometry_or_visibility() -> None:
    planned = CampaignOverlaySpec(
        cta_asset_id="cta-asset",
        cta_asset_sha256="a" * 64,
        cta_asset_name="tarteel-cta-alpha.webm",
        cta_start_us=1_000_000,
        cta_end_us=3_000_000,
        cta_left_permille=60,
        cta_top_permille=180,
        watermark_asset_id="watermark-asset",
        watermark_asset_sha256="b" * 64,
        watermark_asset_name="tarteel-watermark-alpha.png",
        sizing_method="source_frame_scan_v1",
        sizing_measurement_sha256="c" * 64,
    )
    require_tarteel_overlay_matches_plan(planned, planned.model_copy(deep=True))
    for change, field in (
        ({"cta_left_permille": 340}, "cta_left_permille"),
        ({"cta_start_us": 1_500_000}, "cta_start_us"),
        ({"watermark_visibility": "source_visible_v1"}, "watermark_visibility"),
        ({"sizing_measurement_sha256": "d" * 64}, "sizing_measurement_sha256"),
    ):
        with pytest.raises(MediaError, match=field):
            require_tarteel_overlay_matches_plan(planned, planned.model_copy(update=change))


def test_cta_position_avoids_the_most_occupied_face_region() -> None:
    left_top = choose_tarteel_foreground_position([(0.02, 0.05, 0.55, 0.35)])
    assert left_top != (60, 180)


def test_cta_position_uses_upper_center_slot_when_faces_are_lower() -> None:
    assert choose_tarteel_foreground_position([(0.1, 0.35, 0.2, 0.3)]) == (340, 60)


def test_cta_position_keeps_visible_source_logo_clear() -> None:
    assert choose_tarteel_foreground_position([], source_logo_visible=True) == (340, 60)


def test_cta_position_fails_when_every_candidate_overlaps_a_face() -> None:
    with pytest.raises(MediaError, match="no face-clear"):
        choose_tarteel_foreground_position(
            [(0.0, 0.0, 1.0, 1.0)],
        )


def test_cta_position_requires_face_evidence_inside_the_cta_interval() -> None:
    with pytest.raises(MediaError, match="no face-clearance sample"):
        choose_tarteel_foreground_position(
            [],
            face_boxes_by_time=[(1_000_000, 0.02, 0.05, 0.1, 0.1)],
            cta_start_us=2_000_000,
            cta_end_us=3_000_000,
        )


def test_tarteel_faces_are_mapped_through_the_selected_crop_window() -> None:
    time_map = TimeMapDocument(
        time_map_id="map-1",
        segments=[TimelineSegment(segment_id="seg-1", source_start_us=0, source_end_us=1_000_000)],
    )
    plan = AdvancedHeroPlanDocument.model_construct(
        candidate_id="candidate-1",
        time_map=time_map,
        windows=[
            ReframingWindow(
                window_id="window-1",
                strategy_id=ReframingStrategy(strategy_id="face_follow"),
                output_start_us=0,
                output_end_us=1_000_000,
                source_x=80,
                source_y=0,
                source_width=160,
                source_height=180,
                frame_width=320,
                frame_height=180,
            )
        ],
    )
    sample = FaceDetectionSample(
        detection_id="face-1",
        scene_id="scene-1",
        timestamp_us=500_000,
        confidence=1,
        bounding_box=NormalizedBoundingBox(x=0.25, y=0.25, width=0.5, height=0.5),
        center_x=0.5,
        center_y=0.5,
        area_ratio=0.25,
    )
    mapped = _tarteel_face_samples_for_plan(plan, [sample])
    assert mapped == [(500_000, 0.0, 0.25, 1.0, 0.5)]


def test_tarteel_face_samples_ignore_faces_outside_a_jump_cut_map() -> None:
    time_map = TimeMapDocument(
        time_map_id="map-jump",
        segments=[
            TimelineSegment(segment_id="kept-1", source_start_us=10_000_000, source_end_us=11_000_000),
            TimelineSegment(segment_id="kept-2", source_start_us=20_000_000, source_end_us=21_000_000),
        ],
    )
    plan = AdvancedHeroPlanDocument.model_construct(
        candidate_id="candidate-jump",
        time_map=time_map,
        windows=[
            ReframingWindow(
                window_id="window-jump-1",
                strategy_id=ReframingStrategy(strategy_id="face_follow"),
                output_start_us=0,
                output_end_us=2_000_000,
                source_x=0,
                source_y=0,
                source_width=320,
                source_height=180,
                frame_width=320,
                frame_height=180,
            )
        ],
    )
    outside = FaceDetectionSample(
        detection_id="face-outside",
        scene_id="scene-outside",
        timestamp_us=4_160_000,
        confidence=1,
        bounding_box=NormalizedBoundingBox(x=0.25, y=0.25, width=0.5, height=0.5),
        center_x=0.5,
        center_y=0.5,
        area_ratio=0.25,
    )
    kept = FaceDetectionSample(
        detection_id="face-kept",
        scene_id="scene-kept",
        timestamp_us=10_500_000,
        confidence=1,
        bounding_box=NormalizedBoundingBox(x=0.25, y=0.25, width=0.5, height=0.5),
        center_x=0.5,
        center_y=0.5,
        area_ratio=0.25,
    )
    mapped = _tarteel_face_samples_for_plan(plan, [outside, kept])
    assert len(mapped) == 1


def test_quran_review_blocks_unreviewed_pronunciation(tmp_path: Path) -> None:
    sidecar = tmp_path / "campaigns" / "Tarteel" / "pilot" / "quran-caption-review.json"
    sidecar.parent.mkdir(parents=True)
    payload = {
        "review_kind": "source_grounded_quran_caption",
        "campaign": "tarteel",
        "source_asset_id": "source-1",
        "candidate_id": "candidate-1",
        "source_window_us": [0, 2_000_000],
        "canonical_source": {
            "provider": "Quran.com",
            "url": "https://quran.com/qaf/16-18",
            "surah": 50,
            "ayah_start": 16,
            "ayah_end": 16,
            "text_uthmani": ["وَقُلْ رَبِّ زِدْنِي عِلْمًا"],
        },
        "source_audio_mapping": [{"source_start_us": 0, "source_end_us": 2_000_000, "ayah": 16}],
        "verification_policy": {
            "quran_text": "canonical_uthmani_only",
            "timing": "forced_alignment_required",
            "pronunciation_status": "human_review_required",
            "unverified_words_must_not_be_colored_green": True,
            "incorrect_words_require_human_evidence": True,
            "font_identity": "amiri-quran-local-v1",
            "font_relative_path": "fonts/AmiriQuran.ttf",
            "font_sha256": "a" * 64,
        },
        "notes": [],
    }
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MediaError, match="human_reviewed"):
        load_tarteel_quran_review(
            tmp_path,
            source_asset_id="source-1",
            candidate_id="candidate-1",
        )
    payload["verification_policy"]["pronunciation_status"] = "canonical_match_verified"
    snapshot = {"verses": [{"verse_key": "50:16", "text_uthmani": "وَقُلْ رَبِّ زِدْنِي عِلْمًا"}]}
    snapshot_path = tmp_path / "campaigns" / "Tarteel" / "pilot" / "quran.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    payload["source_sha256"] = "a" * 64
    payload["transcript_sha256"] = "b" * 64
    payload["canonical_source"].update(
        {
            "snapshot_relative_path": "campaigns/Tarteel/pilot/quran.json",
            "snapshot_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
            "snapshot_url": "https://api.quran.com/api/v4/quran/verses/uthmani?chapter_number=50",
        }
    )
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    review, _digest, _path = load_tarteel_quran_review(
        tmp_path,
        source_asset_id="source-1",
        candidate_id="candidate-1",
    )
    assert review.verification_policy.pronunciation_status == "canonical_match_verified"
    with pytest.raises(MediaError, match="source hash"):
        load_tarteel_quran_review(
            tmp_path,
            source_asset_id="source-1",
            candidate_id="candidate-1",
            source_sha256="c" * 64,
        )


def test_quran_canonicalizer_replaces_asr_errors_and_preserves_timing() -> None:
    review = QuranCaptionReview(
        review_kind="source_grounded_quran_caption",
        campaign="tarteel",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_window_us=(0, 20_000_000),
        canonical_source=QuranCanonicalSource(
            provider="Quran.com",
            url="https://quran.com/qaf/16-18",
            surah=50,
            ayah_start=16,
            ayah_end=16,
            text_uthmani=["وَلَقَدْ خَلَقْنَا ٱلْإِنسَـٰنَ وَنَعْلَمُ مَا تُوَسْوِسُ بِهِۦ نَفْسُهُۥ ۖ وَنَحْنُ أَقْرَبُ إِلَيْهِ مِنْ حَبْلِ ٱلْوَرِيدِ"],
        ),
        source_audio_mapping=[QuranAudioMapping(source_start_us=0, source_end_us=15_000_000, ayah=16)],
        verification_policy=QuranVerificationPolicy(
            quran_text="canonical_uthmani_only",
            timing="forced_alignment_required",
            pronunciation_status="canonical_match_verified",
            font_identity="amiri-quran-local-v1",
            font_relative_path="fonts/AmiriQuran.ttf",
            font_sha256="a" * 64,
        ),
    )
    observed = [
        "ولا",
        "قد",
        "خلقنا",
        "الإنسان",
        "ونعلم",
        "ما",
        "توسويس",
        "به",
        "نفسه",
        "ونحن",
        "أقرب",
        "إليه",
        "من",
        "حبر",
        "الوريد",
    ]
    words = [
        AlignedWord(
            word_id=f"word-{index}",
            candidate_id="candidate-1",
            text=f" {text}",
            source_start_us=index * 1_000_000,
            source_end_us=(index + 1) * 1_000_000,
            output_start_us=index * 1_000_000,
            output_end_us=(index + 1) * 1_000_000,
            output_start_frame=index * 30,
            output_end_frame_exclusive=(index + 1) * 30,
        )
        for index, text in enumerate(observed)
    ]
    alignment = ForcedAlignmentDocument(
        alignment_id="alignment-1",
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        transcript_id="transcript-1",
        transcript_sha256="a" * 64,
        asr_audio_sha256="b" * 64,
        time_map_sha256="c" * 64,
        review_id="review-1",
        review_digest="d" * 64,
        rough_preview_artifact_id="rough-1",
        model_name="fake-forced-align-v1",
        whisperx_version="test",
        device="cpu",
        config_sha256="e" * 64,
        words=words,
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="test",
            tool="test",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )
    corrected = canonicalize_quran_alignment(alignment, review)
    assert "وَلَقَدْ" in corrected.words[0].text
    assert "حَبْلِ" in corrected.words[-2].text
    assert corrected.words[0].source_start_us == words[0].source_start_us
    assert corrected.words[0].source_end_us == words[1].source_end_us
    assert all(word.verification_status == "correct" for word in corrected.words if word.source_word_ids)
    assert corrected.words[0].source_word_ids == ["word-0", "word-1"]
    assert any(" ۖ" in word.text for word in corrected.words)


def test_tarteel_display_correction_changes_only_reviewed_word_text() -> None:
    words = [
        AlignedWord(
            word_id=f"word-{index}",
            candidate_id="candidate-1",
            text=f" {text}",
            source_start_us=index * 1_000_000,
            source_end_us=(index + 1) * 1_000_000,
            output_start_us=index * 1_000_000,
            output_end_us=(index + 1) * 1_000_000,
            output_start_frame=index * 30,
            output_end_frame_exclusive=(index + 1) * 30,
        )
        for index, text in enumerate(("حافظ", "الطفل"))
    ]
    alignment = ForcedAlignmentDocument(
        alignment_id="alignment-1",
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        transcript_id="transcript-1",
        transcript_sha256="a" * 64,
        asr_audio_sha256="b" * 64,
        time_map_sha256="c" * 64,
        review_id="review-1",
        review_digest="d" * 64,
        rough_preview_artifact_id="rough-1",
        model_name="fake-forced-align-v1",
        whisperx_version="test",
        device="cpu",
        config_sha256="e" * 64,
        words=words,
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="test",
            tool="test",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )
    review = QuranCaptionReview(
        review_kind="source_grounded_quran_caption",
        campaign="tarteel",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_window_us=(0, 2_000_000),
        canonical_source=QuranCanonicalSource(
            provider="Quran.com",
            url="https://quran.com/qaf/16-18",
            surah=50,
            ayah_start=16,
            ayah_end=16,
            text_uthmani=["وَقُلْ رَبِّ زِدْنِي عِلْمًا"],
        ),
        source_audio_mapping=[QuranAudioMapping(source_start_us=0, source_end_us=2_000_000, ayah=16)],
        display_corrections=[TarteelDisplayCorrection(source_word_id="word-0", display_text="حفظ")],
        verification_policy=QuranVerificationPolicy(
            quran_text="canonical_uthmani_only",
            timing="forced_alignment_required",
            pronunciation_status="human_review_required",
            font_identity="amiri-quran-local-v1",
            font_relative_path="fonts/AmiriQuran.ttf",
            font_sha256="a" * 64,
        ),
    )
    corrected = _apply_display_corrections(alignment, review)
    assert corrected.words[0].text == " حفظ"
    assert corrected.words[0].source_start_us == alignment.words[0].source_start_us
    assert corrected.words[0].source_end_us == alignment.words[0].source_end_us
    assert corrected.words[1].text == alignment.words[1].text


def test_tarteel_review_drops_corrections_for_words_removed_by_reviewed_arc() -> None:
    words = [
        AlignedWord(
            word_id=f"word-{index}",
            candidate_id="candidate-1",
            text=f" word-{index}",
            source_start_us=index * 1_000_000,
            source_end_us=(index + 1) * 1_000_000,
            output_start_us=index * 1_000_000,
            output_end_us=(index + 1) * 1_000_000,
            output_start_frame=index * 30,
            output_end_frame_exclusive=(index + 1) * 30,
        )
        for index in range(2)
    ]
    alignment = ForcedAlignmentDocument(
        alignment_id="alignment-1",
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        transcript_id="transcript-1",
        transcript_sha256="a" * 64,
        asr_audio_sha256="b" * 64,
        time_map_sha256="c" * 64,
        review_id="review-1",
        review_digest="d" * 64,
        rough_preview_artifact_id="rough-1",
        model_name="fake-forced-align-v1",
        whisperx_version="test",
        device="cpu",
        config_sha256="e" * 64,
        words=words,
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="test",
            tool="test",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )
    review = QuranCaptionReview(
        review_kind="source_grounded_quran_caption",
        campaign="tarteel",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_window_us=(0, 2_000_000),
        canonical_source=QuranCanonicalSource(
            provider="Quran.com",
            url="https://quran.com/qaf/16-18",
            surah=50,
            ayah_start=16,
            ayah_end=16,
            text_uthmani=["وَقُلْ رَبِّ زِدْنِي عِلْمًا"],
        ),
        source_audio_mapping=[QuranAudioMapping(source_start_us=0, source_end_us=2_000_000, ayah=16)],
        display_corrections=[
            TarteelDisplayCorrection(source_word_id="word-0", display_text="الأول"),
            TarteelDisplayCorrection(source_word_id="word-1", display_text="الثاني"),
        ],
        verification_policy=QuranVerificationPolicy(
            quran_text="canonical_uthmani_only",
            timing="forced_alignment_required",
            pronunciation_status="human_review_required",
            font_identity="amiri-quran-local-v1",
            font_relative_path="fonts/AmiriQuran.ttf",
            font_sha256="a" * 64,
        ),
    )
    target = alignment.model_copy(update={"words": [words[0]]})
    filtered = quran_review_for_alignment(review, source_alignment=alignment, target_alignment=target)
    assert [item.source_word_id for item in filtered.display_corrections] == ["word-0"]
