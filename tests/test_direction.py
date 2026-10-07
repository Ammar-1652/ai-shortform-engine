from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.direction_service import validate_source_evidence
from clipforge.hero.motion_style import style_for_id
from clipforge.schemas.direction import (
    DirectionBeat,
    DirectionDocument,
    DirectionEvidence,
    DirectionOption,
)
from clipforge.schemas.hero import AlignedWord
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimelineSegment, TimeMapDocument


def _option(option_id: str, style_id: str, score: float) -> DirectionOption:
    evidence = DirectionEvidence(
        evidence_id=f"e-{option_id}",
        source_word_ids=["word-1"],
        source_segment_ids=["segment-1"],
        source_text="The source says this.",
        note="Copied from the forced transcript.",
    )
    beats = [
        DirectionBeat(
            beat_id=f"{option_id}-hook",
            kind="hook",
            purpose="context",
            source_segment_ids=["segment-1"],
            evidence_ids=[evidence.evidence_id],
            display_text="The source says this.",
        ),
        DirectionBeat(
            beat_id=f"{option_id}-body",
            kind="body",
            purpose="contrast",
            source_segment_ids=["segment-1"],
            evidence_ids=[evidence.evidence_id],
            display_text="The source says this.",
        ),
        DirectionBeat(
            beat_id=f"{option_id}-punch",
            kind="punch",
            purpose="payoff",
            source_segment_ids=["segment-1"],
            evidence_ids=[evidence.evidence_id],
            display_text="The source says this.",
        ),
    ]
    return DirectionOption(
        option_id=option_id,
        style_id=style_id,  # type: ignore[arg-type]
        title="Source-grounded option",
        beats=beats,
        evidence=[evidence],
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
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="test",
            tool="test",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )


def test_direction_requires_three_source_grounded_options() -> None:
    document = _document()
    assert len(document.options) == 3
    assert {beat.kind for beat in document.options[0].beats} == {"hook", "body", "punch"}


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
    with pytest.raises(ValueError, match="unsupported motion style"):
        style_for_id("random-css")


def test_direction_evidence_binds_words_and_time_map() -> None:
    document = _document()
    words = [
        AlignedWord(
            word_id="word-1",
            candidate_id="candidate-1",
            text="The source says this.",
            source_start_us=0,
            source_end_us=1_000_000,
            output_start_us=0,
            output_end_us=1_000_000,
            output_start_frame=0,
            output_end_frame_exclusive=30,
        )
    ]
    time_map = TimeMapDocument(
        time_map_id="map-1",
        segments=[TimelineSegment(segment_id="segment-1", source_start_us=0, source_end_us=1_000_000)],
    )
    validate_source_evidence(document, words, time_map, set())


def test_direction_evidence_rejects_invented_display_text() -> None:
    document = _document()
    option = document.options[0]
    beat = option.beats[0].model_copy(update={"display_text": "Invented claim"})
    document = document.model_copy(
        update={
            "options": [option.model_copy(update={"beats": [beat, *option.beats[1:]]}), *document.options[1:]]
        }
    )
    words = [
        AlignedWord(
            word_id="word-1",
            candidate_id="candidate-1",
            text="The source says this.",
            source_start_us=0,
            source_end_us=1_000_000,
            output_start_us=0,
            output_end_us=1_000_000,
            output_start_frame=0,
            output_end_frame_exclusive=30,
        )
    ]
    time_map = TimeMapDocument(
        time_map_id="map-1",
        segments=[TimelineSegment(segment_id="segment-1", source_start_us=0, source_end_us=1_000_000)],
    )
    with pytest.raises(MediaError, match="display text"):
        validate_source_evidence(document, words, time_map, set())
