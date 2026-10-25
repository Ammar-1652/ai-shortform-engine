from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.direction_lint import lint_direction
from clipforge.hero.direction_service import validate_source_evidence
from clipforge.hero.editorial_arc import remap_direction_intervals
from clipforge.hero.motion_style import style_for_id
from clipforge.schemas.direction import (
    DirectionAssetPlacement,
    DirectionBeat,
    DirectionCameraMotion,
    DirectionContextLine,
    DirectionDocument,
    DirectionEvidence,
    DirectionMotionGraphic,
    DirectionOption,
    DirectionTransitionSpec,
    SourceNativeText,
)
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimelineSegment, TimeMapDocument


def _option(option_id: str, style_id: str, score: float) -> DirectionOption:
    evidence = [
        DirectionEvidence(
            evidence_id=f"e-{option_id}-{index}",
            source_word_ids=[f"word-{index + 1}"],
            source_segment_ids=["segment-1"],
            source_text=text,
            note="Copied from the forced transcript.",
        )
        for index, text in enumerate(("The source", "says this", "today."))
    ]
    beats = [
        DirectionBeat(
            beat_id=f"{option_id}-hook",
            kind="hook",
            purpose="context",
            source_segment_ids=["segment-1"],
            evidence_ids=[evidence[0].evidence_id],
            display_text="The source",
        ),
        DirectionBeat(
            beat_id=f"{option_id}-body",
            kind="body",
            purpose="contrast",
            source_segment_ids=["segment-1"],
            evidence_ids=[evidence[1].evidence_id],
            display_text="says this",
        ),
        DirectionBeat(
            beat_id=f"{option_id}-punch",
            kind="punch",
            purpose="payoff",
            source_segment_ids=["segment-1"],
            evidence_ids=[evidence[2].evidence_id],
            display_text="today.",
        ),
    ]
    return DirectionOption(
        option_id=option_id,
        style_id=style_id,  # type: ignore[arg-type]
        title="Source-grounded option",
        beats=beats,
        evidence=evidence,
        segment_order=["segment-1"],
        selection_score=score,
        selection_reason="The option preserves the complete source claim.",
    )


def _document() -> DirectionDocument:
    options = [
        _option("option-a", "editorial-clean-v1", 0.72),
        _option("option-b", "kinetic-caption-v1", 0.91),
        _option("option-c", "premium-minimal-v1", 0.81),
    ]
    return DirectionDocument(
        direction_id="direction-1",
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        hero_plan_sha256="b" * 64,
        time_map_sha256="c" * 64,
        alignment_sha256="d" * 64,
        visual_analysis_sha256="e" * 64,
        options=options,
        selected_option_id="option-b",
        selection_mode="automatic",
        style_id="kinetic-caption-v1",
        style_fingerprint=style_for_id("kinetic-caption-v1").fingerprint(),
        safe_region_id="portrait-safe-v1",
        direction_recipe_version="direction-v1",
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="test",
            tool="test",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )


def _aligned_words() -> list[AlignedWord]:
    return [
        AlignedWord(
            word_id=f"word-{index + 1}",
            candidate_id="candidate-1",
            text=text,
            source_start_us=index * 1_000_000,
            source_end_us=(index + 1) * 1_000_000,
            output_start_us=index * 1_000_000,
            output_end_us=(index + 1) * 1_000_000,
            output_start_frame=index * 30,
            output_end_frame_exclusive=(index + 1) * 30,
        )
        for index, text in enumerate(("The source", "says this", "today."))
    ]


def _provenance() -> ArtifactProvenance:
    return ArtifactProvenance(
        created_at=datetime.now(UTC),
        created_by="test",
        tool="test",
        tool_version="1",
        source_asset_ids=["source-1"],
    )


def test_editorial_arc_moves_direction_intervals_with_forced_words() -> None:
    direction = _document()
    source = ForcedAlignmentDocument.model_validate(
        {
            "alignment_id": "source-alignment",
            "project_id": "project-1",
            "source_asset_id": "source-1",
            "candidate_id": "candidate-1",
            "transcript_id": "transcript-1",
            "transcript_sha256": "1" * 64,
            "asr_audio_sha256": "2" * 64,
            "time_map_sha256": "3" * 64,
            "review_id": "review-1",
            "review_digest": "4" * 64,
            "rough_preview_artifact_id": "rough-1",
            "model_name": "fake-forced-align-v1",
            "whisperx_version": "test",
            "device": "cpu",
            "config_sha256": "5" * 64,
            "words": [
                word.model_copy(update={"source_end_us": word.source_start_us + 900_000}).model_dump(
                    mode="json"
                )
                for word in _aligned_words()
            ],
            "provenance": _provenance().model_dump(mode="json"),
            "alignment_status": "available_not_smoked",
            "binding_sha256": "6" * 64,
            "checkpoint_sha256": "7" * 64,
            "manifest_sha256": "8" * 64,
        }
    )
    output = ForcedAlignmentDocument.model_validate(
        {
            **source.model_dump(mode="json"),
            "words": [
                word.model_copy(
                    update={
                        "output_start_us": index * 900_000,
                        "output_end_us": (index + 1) * 900_000,
                    }
                ).model_dump(mode="json")
                for index, word in enumerate(reversed(source.words))
            ],
        }
    )
    parent_map = TimeMapDocument(
        time_map_id="parent",
        segments=[TimelineSegment(segment_id="segment-1", source_start_us=0, source_end_us=3_000_000)],
    )
    output_map = TimeMapDocument(
        time_map_id="recut",
        segments=[
            TimelineSegment(segment_id=f"cut-{index}", source_start_us=start, source_end_us=start + 900_000)
            for index, start in enumerate((2_000_000, 1_000_000, 0))
        ],
    )
    remapped = remap_direction_intervals(direction, source, output, parent_map, output_map)
    selected = next(item for item in remapped.options if item.option_id == remapped.selected_option_id)
    assert [beat.output_start_us for beat in selected.beats] == [1_800_000, 900_000, 0]


def test_direction_requires_three_source_grounded_options() -> None:
    document = _document()
    assert len(document.options) == 3
    assert {beat.kind for beat in document.options[0].beats} == {"hook", "body", "punch"}


def test_direction_accepts_explicit_platform_resilient_portrait_region() -> None:
    document = _document().model_copy(update={"safe_region_id": "platform-resilient-portrait-v1"})
    assert document.safe_region_id == "platform-resilient-portrait-v1"

    with pytest.raises(ValidationError):
        DirectionDocument.model_validate(
            {**_document().model_dump(mode="json"), "safe_region_id": "unknown-safe-region"}
        )


def test_direction_rejects_missing_beat_kind() -> None:
    option = _option("option-a", "editorial-clean-v1", 0.5)
    option = option.model_copy(
        update={
            "beats": [
                *option.beats[:2],
                option.beats[1].model_copy(update={"kind": "body"}),
            ]
        }
    )
    with pytest.raises(ValidationError, match="hook, body, and punch"):
        DirectionDocument(
            direction_id="direction-1",
            project_id="project-1",
            source_asset_id="source-1",
            candidate_id="candidate-1",
            source_sha256="a" * 64,
            hero_plan_sha256="b" * 64,
            time_map_sha256="c" * 64,
            alignment_sha256="d" * 64,
            visual_analysis_sha256="e" * 64,
            options=[
                option,
                _option("option-b", "kinetic-caption-v1", 0.4),
                _option("option-c", "premium-minimal-v1", 0.3),
            ],
            selected_option_id="option-a",
            selection_mode="automatic",
            style_id="editorial-clean-v1",
            style_fingerprint=style_for_id("editorial-clean-v1").fingerprint(),
            provenance=ArtifactProvenance(
                created_at=datetime.now(UTC),
                created_by="test",
                tool="test",
                tool_version="1",
                source_asset_ids=["source-1"],
            ),
        )


def test_style_contract_is_fingerprintable_and_allowlisted() -> None:
    profile = style_for_id("data-explainer-v1")
    assert profile.contract().style_id == "data-explainer-v1"
    assert profile.max_travel_px <= 80
    readable = style_for_id("quran-readable-v2")
    assert readable.contract().style_id == "quran-readable-v2"
    assert readable.max_scale_permille == 1000
    with pytest.raises(ValueError, match="unsupported motion style"):
        style_for_id("random-css")


def test_direction_evidence_binds_words_and_time_map() -> None:
    document = _document()
    words = _aligned_words()
    time_map = TimeMapDocument(
        time_map_id="map-1",
        segments=[TimelineSegment(segment_id="segment-1", source_start_us=0, source_end_us=3_000_000)],
    )
    validate_source_evidence(document, words, time_map, set())


def test_camera_motion_is_bounded_and_bound_to_source_evidence() -> None:
    option = _option("option-a", "editorial-clean-v1", 0.8).model_copy(
        update={
            "camera_motion": [
                DirectionCameraMotion(
                    motion_id="camera-1",
                    intent="emphasize",
                    path="push_in",
                    interval=OutputInterval(output_start_us=0, output_end_us=1_000_000),
                    source_evidence_ids=["e-option-a-0"],
                    scale_start_permille=1000,
                    scale_end_permille=1060,
                    travel_px=32,
                    intensity="quiet",
                )
            ]
        }
    )
    document = _document().model_copy(
        update={
            "options": [
                option,
                _option("option-b", "kinetic-caption-v1", 0.9),
                _option("option-c", "premium-minimal-v1", 0.7),
            ]
        }
    )
    validate_source_evidence(
        document,
        _aligned_words(),
        TimeMapDocument(
            time_map_id="map-1",
            segments=[TimelineSegment(segment_id="segment-1", source_start_us=0, source_end_us=3_000_000)],
        ),
        set(),
    )
    with pytest.raises(ValidationError, match="quiet camera motion"):
        DirectionCameraMotion(
            motion_id="camera-bad",
            intent="emphasize",
            path="push_in",
            interval=OutputInterval(output_start_us=0, output_end_us=1_000_000),
            source_evidence_ids=["e-1"],
            scale_end_permille=1100,
            intensity="quiet",
        )

    with pytest.raises(ValidationError, match="push_in camera motion"):
        DirectionCameraMotion(
            motion_id="camera-reverse",
            intent="emphasize",
            path="push_in",
            interval=OutputInterval(output_start_us=0, output_end_us=1_000_000),
            source_evidence_ids=["e-1"],
            scale_start_permille=1060,
            scale_end_permille=1000,
            intensity="gentle",
        )


def test_transition_requires_a_narrative_purpose() -> None:
    with pytest.raises(ValidationError, match="clean cut transition"):
        DirectionTransitionSpec(
            transition_id="transition-1",
            interval=OutputInterval(output_start_us=1_000_000, output_end_us=1_100_000),
            purpose="reveal",
            style="clean_cut_v1",
            source_evidence_ids=["e-1"],
        )


def test_direction_lint_reports_pass_and_restraint_info() -> None:
    document = _document()
    report = lint_direction(
        document,
        direction_sha256="f" * 64,
        words=_aligned_words(),
        time_map=TimeMapDocument(
            time_map_id="map-1",
            segments=[TimelineSegment(segment_id="segment-1", source_start_us=0, source_end_us=3_000_000)],
        ),
        scene_ids=set(),
    )
    assert report.status == "pass"
    assert any(item.code == "optional_layers_omitted" for item in report.findings)


def test_quran_style_requires_a_context_line() -> None:
    with pytest.raises(ValidationError, match="upper context line"):
        _option("quran", "quran-editorial-v1", 0.8)


def test_new_direction_recipe_requires_context_line() -> None:
    payload = _document().model_dump(mode="json")
    payload["direction_recipe_version"] = "direction-v2"
    with pytest.raises(ValidationError, match="reviewed upper context line"):
        DirectionDocument.model_validate(payload)


def test_context_line_is_full_clip_reviewed_and_not_a_duplicate() -> None:
    document = _document()
    base = document.options[0]
    line = DirectionContextLine(
        context_id="context-1",
        text="Why this lesson matters",
        emoji="📖",
        evidence_ids=[base.evidence[0].evidence_id],
        interval=OutputInterval(output_start_us=0, output_end_us=3_000_000),
        copy_mode="human_reviewed_summary",
        reviewed_by="editor-1",
        review_note="Summary is visibly related to the bound lesson and is not a caption duplicate.",
    )
    option = base.model_copy(update={"context_line": line})
    valid = document.model_copy(update={"options": [option, *document.options[1:]]})
    validate_source_evidence(
        valid,
        _aligned_words(),
        TimeMapDocument(
            time_map_id="map-1",
            segments=[TimelineSegment(segment_id="segment-1", source_start_us=0, source_end_us=3_000_000)],
        ),
        set(),
    )
    duplicate = line.model_copy(update={"text": "The source"})
    invalid = document.model_copy(
        update={"options": [base.model_copy(update={"context_line": duplicate}), *document.options[1:]]}
    )
    with pytest.raises(MediaError, match="must not duplicate"):
        validate_source_evidence(
            invalid,
            _aligned_words(),
            TimeMapDocument(
                time_map_id="map-1",
                segments=[TimelineSegment(segment_id="segment-1", source_start_us=0, source_end_us=3_000_000)],
            ),
            set(),
        )


def test_direction_evidence_rejects_invented_display_text() -> None:
    document = _document()
    option = document.options[0]
    beat = option.beats[0].model_copy(update={"display_text": "Invented claim"})
    document = document.model_copy(
        update={
            "options": [option.model_copy(update={"beats": [beat, *option.beats[1:]]}), *document.options[1:]]
        }
    )
    words = _aligned_words()
    time_map = TimeMapDocument(
        time_map_id="map-1",
        segments=[TimelineSegment(segment_id="segment-1", source_start_us=0, source_end_us=3_000_000)],
    )
    with pytest.raises(MediaError, match="display text"):
        validate_source_evidence(document, words, time_map, set())


def test_asset_placement_must_overlap_its_source_evidence() -> None:
    document = _document()
    placement = DirectionAssetPlacement(
        placement_id="placement-1",
        asset_id="asset-1",
        kind="graphic",
        interval=OutputInterval(output_start_us=1_100_000, output_end_us=1_500_000),
        source_evidence_ids=["e-option-a-0"],
        purpose=MotionPurpose.CONCEPT,
        relevance_note="A reviewed visual explanation of the phrase.",
    )
    option = document.options[0].model_copy(update={"asset_placements": [placement]})
    document = document.model_copy(update={"options": [option, *document.options[1:]]})
    words = _aligned_words()
    time_map = TimeMapDocument(
        time_map_id="map-1",
        segments=[TimelineSegment(segment_id="segment-1", source_start_us=0, source_end_us=3_000_000)],
    )
    with pytest.raises(MediaError, match="does not overlap"):
        validate_source_evidence(document, words, time_map, set())


def test_motion_graphic_requires_exact_source_text_and_supported_semantics() -> None:
    document = _document()
    options: list[DirectionOption] = []
    for current in document.options:
        evidence = current.evidence[0].model_copy(update={"source_text": "credit card"})
        beat = current.beats[0].model_copy(update={"display_text": "credit card"})
        options.append(
            current.model_copy(
                update={"evidence": [evidence, *current.evidence[1:]], "beats": [beat, *current.beats[1:]]}
            )
        )
    option = options[0]
    evidence = option.evidence[0]
    beat = option.beats[0]
    graphic = DirectionMotionGraphic(
        graphic_id="credit-card-1",
        template="credit_card",
        interval=OutputInterval(output_start_us=0, output_end_us=900_000),
        source_evidence_ids=[evidence.evidence_id],
        purpose=MotionPurpose.NUMBER,
        display_text="credit card",
        x=72,
        y=900,
        width=360,
        height=260,
    )
    option = option.model_copy(
        update={
            "evidence": [evidence, *option.evidence[1:]],
            "beats": [beat, *option.beats[1:]],
            "motion_graphics": [graphic],
        }
    )
    document = document.model_copy(update={"options": [option, *options[1:]]})
    words = _aligned_words()
    words[0] = words[0].model_copy(update={"text": "credit card"})
    time_map = TimeMapDocument(
        time_map_id="map-1",
        segments=[TimelineSegment(segment_id="segment-1", source_start_us=0, source_end_us=3_000_000)],
    )
    validate_source_evidence(document, words, time_map, set())

    invented = graphic.model_copy(update={"display_text": "Free money"})
    invalid_option = option.model_copy(update={"motion_graphics": [invented]})
    invalid = document.model_copy(update={"options": [invalid_option, *options[1:]]})
    with pytest.raises(MediaError, match="display text"):
        validate_source_evidence(invalid, words, time_map, set())

    unrelated = graphic.model_copy(update={"template": "business_spotlight"})
    invalid_option = option.model_copy(update={"motion_graphics": [unrelated]})
    invalid = document.model_copy(update={"options": [invalid_option, *options[1:]]})
    with pytest.raises(MediaError, match="not supported"):
        validate_source_evidence(invalid, words, time_map, set())

    company_options: list[DirectionOption] = []
    for current in document.options:
        evidence = current.evidence[0].model_copy(update={"source_text": "company"})
        beat = current.beats[0].model_copy(update={"display_text": "company"})
        company_options.append(
            current.model_copy(
                update={
                    "evidence": [evidence, *current.evidence[1:]],
                    "beats": [beat, *current.beats[1:]],
                }
            )
        )
    company_words = [words[0].model_copy(update={"text": "company"}), *words[1:]]
    company_evidence = company_options[0].evidence[0]
    company_graphic = graphic.model_copy(
        update={
            "template": "business_spotlight",
            "source_evidence_ids": [company_evidence.evidence_id],
            "display_text": "company",
        }
    )
    company_options[0] = company_options[0].model_copy(update={"motion_graphics": [company_graphic]})
    company_document = document.model_copy(update={"options": company_options})
    with pytest.raises(MediaError, match="not supported"):
        validate_source_evidence(company_document, company_words, time_map, set())


def test_motion_graphic_cannot_enter_caption_lane() -> None:
    with pytest.raises(ValidationError, match="caption lane"):
        DirectionMotionGraphic(
            graphic_id="graphic-1",
            template="travel_postcard",
            interval=OutputInterval(output_start_us=0, output_end_us=1),
            source_evidence_ids=["e-option-a-0"],
            purpose=MotionPurpose.CONCEPT,
            display_text="The source",
            x=72,
            y=1240,
            width=360,
            height=260,
        )


def test_source_native_text_is_reviewed_and_scene_bound() -> None:
    document = _document()
    native = SourceNativeText(
        region_id="native-title-1",
        interval=OutputInterval(output_start_us=0, output_end_us=900_000),
        text="The source",
        visual_scene_ids=["scene-1"],
        note="Opening title is already burned into the source frame.",
    )
    option = document.options[0].model_copy(update={"source_native_text": [native]})
    document = document.model_copy(update={"options": [option, *document.options[1:]]})
    words = _aligned_words()
    time_map = TimeMapDocument(
        time_map_id="map-1",
        segments=[TimelineSegment(segment_id="segment-1", source_start_us=0, source_end_us=3_000_000)],
    )
    validate_source_evidence(document, words, time_map, {"scene-1"})
    with pytest.raises(MediaError, match="unknown visual scene"):
        validate_source_evidence(document, words, time_map, set())

    with pytest.raises(ValidationError, match="requires annotations"):
        DirectionOption.model_validate(
            {**document.options[1].model_dump(mode="json"), "source_native_text_status": "annotated"}
        )
