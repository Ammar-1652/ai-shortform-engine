from __future__ import annotations

import pytest
from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.editorial_arc import remap_alignment, validate_editorial_arc
from clipforge.schemas.arc import EditorialArcDocument, EditorialArcSegment
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimelineSegment, TimeMapDocument, digest_time_map


def _provenance() -> ArtifactProvenance:
    from datetime import UTC, datetime

    return ArtifactProvenance(
        created_at=datetime.now(UTC),
        created_by="test",
        tool="test",
        tool_version="1",
        source_asset_ids=["source-1"],
    )


def _arc() -> EditorialArcDocument:
    time_map = TimeMapDocument(
        time_map_id="arc-map",
        segments=[
            TimelineSegment(segment_id="arc-hook", source_start_us=0, source_end_us=1_000_000),
            TimelineSegment(segment_id="arc-body", source_start_us=2_000_000, source_end_us=3_000_000),
            TimelineSegment(segment_id="arc-punch", source_start_us=4_000_000, source_end_us=5_000_000),
        ],
    )
    return EditorialArcDocument(
        arc_id="arc-1",
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        hero_plan_sha256="b" * 64,
        alignment_sha256="c" * 64,
        time_map=time_map,
        time_map_sha256=digest_time_map(time_map),
        segments=[
            EditorialArcSegment(
                segment_id="arc-hook",
                source_start_us=0,
                source_end_us=1_000_000,
                word_ids=["word-1"],
                beat="hook",
                purpose="open with the source question",
                claim_closure="complete",
            ),
            EditorialArcSegment(
                segment_id="arc-body",
                source_start_us=2_000_000,
                source_end_us=3_000_000,
                word_ids=["word-2"],
                beat="body",
                purpose="explain the mechanism",
                claim_closure="complete",
            ),
            EditorialArcSegment(
                segment_id="arc-punch",
                source_start_us=4_000_000,
                source_end_us=5_000_000,
                word_ids=["word-3"],
                beat="punch",
                purpose="land the consequence",
                claim_closure="complete",
            ),
        ],
    )


def _alignment() -> ForcedAlignmentDocument:
    words = [
        AlignedWord(
            word_id=f"word-{index}",
            candidate_id="candidate-1",
            text=f"word-{index}",
            source_start_us=(index - 1) * 2_000_000,
            source_end_us=(index - 1) * 2_000_000 + 900_000,
            output_start_us=(index - 1) * 2_000_000,
            output_end_us=(index - 1) * 2_000_000 + 900_000,
            output_start_frame=(index - 1) * 60,
            output_end_frame_exclusive=(index - 1) * 60 + 27,
            segment_index=0,
        )
        for index in range(1, 4)
    ]
    return ForcedAlignmentDocument(
        alignment_id="alignment-1",
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        transcript_id="transcript-1",
        transcript_sha256="d" * 64,
        asr_audio_sha256="e" * 64,
        time_map_sha256="f" * 64,
        review_id="review-1",
        review_digest="1" * 64,
        rough_preview_artifact_id="rough-1",
        model_name="fake-forced-align-v1",
        whisperx_version="test",
        device="cpu",
        config_sha256="2" * 64,
        words=words,
        provenance=_provenance(),
        alignment_status="available_not_smoked",
        binding_sha256="3" * 64,
        checkpoint_sha256="4" * 64,
        manifest_sha256="5" * 64,
    )


def test_arc_requires_ordered_hook_body_punch_and_exact_map() -> None:
    arc = _arc()
    assert [item.beat for item in arc.segments] == ["hook", "body", "punch"]


@pytest.mark.parametrize("transition", ["concat_push_v1", "concat_blur_dissolve_v1"])
def test_concat_transition_styles_are_explicit_arc_choices(transition: str) -> None:
    arc = _arc().model_copy(update={"transition_style": transition})
    assert arc.transition_style == transition
    with pytest.raises(ValidationError, match="segment order"):
        EditorialArcDocument.model_validate(
            {
                **arc.model_dump(mode="json"),
                "segments": [
                    arc.segments[0].model_dump(mode="json"),
                    arc.segments[2].model_dump(mode="json"),
                    arc.segments[1].model_dump(mode="json"),
                ],
            }
        )


def test_arc_requires_explicit_claim_closure_review() -> None:
    base = _arc()
    arc = base.model_copy(
        update={
            "segments": [
                base.segments[0].model_copy(update={"claim_closure": "requires_review"}),
                *base.segments[1:],
            ]
        }
    )
    alignment = _alignment()
    from types import SimpleNamespace

    hero_plan = SimpleNamespace(edit_plan=SimpleNamespace(time_map=arc.time_map))
    with pytest.raises(MediaError, match="claim-closure review"):
        validate_editorial_arc(
            arc,
            source_sha256="a" * 64,
            hero_plan=hero_plan,  # type: ignore[arg-type]
            hero_plan_sha256="b" * 64,
            alignment=alignment,
            alignment_sha256="c" * 64,
        )


def test_arc_remaps_forced_words_to_the_ordered_output_clock() -> None:
    arc = _arc()
    remapped = remap_alignment(_alignment(), arc, source_sha256="a" * 64)
    assert remapped.time_map_sha256 == arc.time_map_sha256
    assert [word.output_start_us for word in remapped.words] == [0, 1_000_000, 2_000_000]
    assert [word.segment_index for word in remapped.words] == [0, 1, 2]
    assert remapped.alignment_id != "alignment-1"
    assert remapped.binding_sha256 != "3" * 64


def test_arc_can_reorder_source_moments_while_carrying_their_speech() -> None:
    base = _arc()
    reordered_map = TimeMapDocument(
        time_map_id="arc-map",
        segments=[
            TimelineSegment(segment_id="arc-punch", source_start_us=4_000_000, source_end_us=5_000_000),
            TimelineSegment(segment_id="arc-body", source_start_us=2_000_000, source_end_us=3_000_000),
            TimelineSegment(segment_id="arc-hook", source_start_us=0, source_end_us=1_000_000),
        ],
    )
    reordered = EditorialArcDocument.model_validate(
        {
            **base.model_dump(mode="json"),
            "time_map": {
                **reordered_map.model_dump(mode="json"),
            },
            "time_map_sha256": digest_time_map(reordered_map),
            "segments": [
                {
                    **base.segments[2].model_dump(mode="json"),
                    "beat": "hook",
                    "segment_id": "arc-punch",
                },
                {
                    **base.segments[1].model_dump(mode="json"),
                    "beat": "body",
                    "segment_id": "arc-body",
                },
                {
                    **base.segments[0].model_dump(mode="json"),
                    "beat": "punch",
                    "segment_id": "arc-hook",
                },
            ],
        }
    )
    remapped = remap_alignment(_alignment(), reordered, source_sha256="a" * 64)
    assert [word.word_id for word in remapped.words] == ["word-3", "word-2", "word-1"]
    assert [word.output_start_us for word in remapped.words] == [0, 1_000_000, 2_000_000]
