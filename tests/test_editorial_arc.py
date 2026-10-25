from __future__ import annotations

import pytest
from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.editorial_arc import (
    load_editorial_arc_review,
    rebase_codex_arc_review,
    remap_alignment,
    validate_arc_review,
    validate_editorial_arc,
)
from clipforge.schemas.arc import (
    EditorialArcDocument,
    EditorialArcReview,
    EditorialArcReviewBeat,
    EditorialArcSegment,
)
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimelineSegment, TimeMapDocument, digest_time_map
from clipforge.transcription.io import dump_json


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


def _review_for_arc() -> EditorialArcReview:
    from datetime import UTC, datetime

    arc = _arc()
    return EditorialArcReview(
        review_id="exact-cut-review",
        campaign="tarteel",
        source_asset_id=arc.source_asset_id,
        candidate_id=arc.candidate_id,
        source_sha256=arc.source_sha256,
        transcript_sha256="d" * 64,
        visual_analysis_sha256="e" * 64,
        arc_sha256="f" * 64,
        hook_promise="question",
        body_development="explanation",
        punch_payoff="answer",
        beats=[
            EditorialArcReviewBeat(
                beat_id=f"review-{segment.segment_id}",
                segment_id=segment.segment_id,
                beat=segment.beat,
                source_start_us=segment.source_start_us,
                source_end_us=segment.source_end_us,
                transcript_word_ids=segment.word_ids,
                representative_frame_relative_path=f"frames/{index}.png",
                representative_frame_sha256="a" * 64,
                subject_label="same subject",
                event_label="same event",
                continuity_to_next="accepted" if index < len(arc.segments) - 1 else "not_applicable",
                rationale="source context inspected",
            )
            for index, segment in enumerate(arc.segments)
        ],
        decision="accepted",
        reviewer="test",
        reviewed_at=datetime.now(UTC),
        provenance=_provenance(),
    )


@pytest.mark.parametrize(
    "change",
    [
        {"source_start_us": 10},
        {"source_end_us": 900_000},
        {"transcript_word_ids": ["unreviewed-word"]},
        {"segment_id": "another-cut"},
        {"continuity_to_next": "not_applicable"},
    ],
)
def test_arc_review_must_describe_the_exact_kept_cut(change: dict[str, object]) -> None:
    review = _review_for_arc()
    bad = review.model_copy(update={"beats": [review.beats[0].model_copy(update=change), *review.beats[1:]]})
    with pytest.raises(MediaError, match="arc review"):
        validate_arc_review(bad, _arc())


def test_arc_review_matches_every_kept_segment() -> None:
    validate_arc_review(_review_for_arc(), _arc())


def test_codex_arc_review_rebases_when_only_hero_plan_identity_changed(tmp_path) -> None:
    import hashlib
    from types import SimpleNamespace

    base_arc = _arc()
    arc = base_arc.model_copy(
        update={
            "segments": [segment.model_copy(update={"continuation": True}) for segment in base_arc.segments]
        }
    )
    review = _review_for_arc().model_copy(update={"reviewer_role": "codex_operator"})
    frame_sha = hashlib.sha256(b"frame").hexdigest()
    review = review.model_copy(
        update={
            "arc_sha256": hashlib.sha256(dump_json(arc).encode("utf-8")).hexdigest(),
            "beats": [
                beat.model_copy(update={"representative_frame_sha256": frame_sha}) for beat in review.beats
            ],
        }
    )
    for beat in review.beats:
        frame = tmp_path / beat.representative_frame_relative_path
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(b"frame")
    sidecar = tmp_path / "campaigns/Tarteel/candidate-1/editorial-arc-review.json"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text(review.model_dump_json(), encoding="utf-8")
    alignment = _alignment()
    rebased, digest = rebase_codex_arc_review(
        tmp_path,
        arc=arc,
        hero_plan=SimpleNamespace(edit_plan=SimpleNamespace(time_map=arc.time_map)),  # type: ignore[arg-type]
        hero_plan_sha256="e" * 64,
        source_sha256="a" * 64,
        alignment=alignment,
        alignment_sha256="c" * 64,
        transcript_sha256="d" * 64,
        visual_analysis_sha256="e" * 64,
    )
    assert rebased.hero_plan_sha256 == "e" * 64
    assert rebased.arc_id.endswith("-rebase-eeeeeeeeeeee")
    assert digest
    current = load_editorial_arc_review(
        tmp_path,
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        transcript_sha256="d" * 64,
        visual_analysis_sha256="e" * 64,
        arc_sha256=digest,
        arc=rebased,
    )
    assert current[0].reviewer_role == "codex_operator"


def test_arc_opening_boundary_must_match_the_first_hook_word() -> None:
    arc = _arc().model_copy(
        update={
            "opening_word_id": "word-2",
            "opening_boundary_note": "Reviewed opening question",
        }
    )
    with pytest.raises(ValidationError, match="opening_word_id"):
        EditorialArcDocument.model_validate(arc.model_dump(mode="json"))


def test_arc_opening_boundary_requires_a_review_note() -> None:
    arc = _arc().model_copy(update={"opening_word_id": "word-1"})
    with pytest.raises(ValidationError, match="review note"):
        EditorialArcDocument.model_validate(arc.model_dump(mode="json"))


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


def test_accepted_arc_review_requires_continuity_decisions() -> None:
    from datetime import UTC, datetime

    beats = [
        EditorialArcReviewBeat(
            beat_id=f"review-beat-{index}",
            segment_id=f"arc-{label}",
            beat=label,
            source_start_us=index * 1_000_000,
            source_end_us=(index + 1) * 1_000_000,
            transcript_word_ids=[f"word-{index}"],
            representative_frame_relative_path=f"review/arc-{index}.png",
            representative_frame_sha256="a" * 64,
            subject_label="children",
            event_label="same memorization challenge",
            continuity_to_next="accepted" if index < 2 else "not_applicable",
            rationale="the selected source moment completes this beat",
        )
        for index, label in enumerate(("hook", "body", "punch"))
    ]
    review = EditorialArcReview(
        review_id="arc-review-1",
        campaign="tarteel",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        transcript_sha256="b" * 64,
        visual_analysis_sha256="c" * 64,
        arc_sha256="d" * 64,
        hook_promise="the child faces a memorization challenge",
        body_development="the exchange shows the attempt",
        punch_payoff="the answer resolves the challenge",
        beats=beats,
        decision="accepted",
        reviewer="reviewer-1",
        reviewed_at=datetime.now(UTC),
        provenance=_provenance(),
    )
    assert review.beats[0].beat == "hook"


def test_arc_review_loader_requires_hash_bound_representative_frames(tmp_path) -> None:
    import hashlib
    from datetime import UTC, datetime

    frame_paths = []
    beats = []
    for index, label in enumerate(("hook", "body", "punch")):
        frame = tmp_path / f"review/arc-{index}.png"
        frame.parent.mkdir(parents=True, exist_ok=True)
        frame.write_bytes(f"frame-{index}".encode())
        frame_paths.append(frame)
        beats.append(
            EditorialArcReviewBeat(
                beat_id=f"review-beat-{index}",
                segment_id=f"arc-{label}",
                beat=label,
                source_start_us=index * 1_000_000,
                source_end_us=(index + 1) * 1_000_000,
                transcript_word_ids=[f"word-{index}"],
                representative_frame_relative_path=frame.relative_to(tmp_path).as_posix(),
                representative_frame_sha256=hashlib.sha256(frame.read_bytes()).hexdigest(),
                subject_label="children",
                event_label="same memorization challenge",
                continuity_to_next="accepted" if index < 2 else "not_applicable",
                rationale="reviewed source context",
            )
        )
    review = EditorialArcReview(
        review_id="arc-review-loader-1",
        campaign="tarteel",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        transcript_sha256="b" * 64,
        visual_analysis_sha256="c" * 64,
        arc_sha256="d" * 64,
        hook_promise="same challenge",
        body_development="attempt is shown",
        punch_payoff="answer resolves it",
        beats=beats,
        decision="accepted",
        reviewer="reviewer-1",
        reviewed_at=datetime.now(UTC),
        provenance=_provenance(),
    )
    sidecar = tmp_path / "campaigns/Tarteel/candidate-1/editorial-arc-review.json"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text(review.model_dump_json(), encoding="utf-8")
    loaded = load_editorial_arc_review(
        tmp_path,
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        transcript_sha256="b" * 64,
        visual_analysis_sha256="c" * 64,
        arc_sha256="d" * 64,
    )
    assert loaded[0].review_id == "arc-review-loader-1"
    with pytest.raises(MediaError, match="arc hash"):
        load_editorial_arc_review(
            tmp_path,
            source_asset_id="source-1",
            candidate_id="candidate-1",
            source_sha256="a" * 64,
            transcript_sha256="b" * 64,
            visual_analysis_sha256="c" * 64,
            arc_sha256="e" * 64,
        )


def test_arc_review_rejects_unresolved_accepted_transition() -> None:
    from datetime import UTC, datetime

    beats = [
        {
            "schema_version": "1.0.0",
            "beat_id": f"review-beat-{index}",
            "segment_id": f"arc-{label}",
            "beat": label,
            "source_start_us": index * 1_000_000,
            "source_end_us": (index + 1) * 1_000_000,
            "transcript_word_ids": [f"word-{index}"],
            "representative_frame_relative_path": f"review/arc-{index}.png",
            "representative_frame_sha256": "a" * 64,
            "subject_label": "children",
            "event_label": "same event",
            "continuity_to_next": "requires_review" if index == 0 else "not_applicable",
            "rationale": "needs a continuity decision",
        }
        for index, label in enumerate(("hook", "body", "punch"))
    ]
    with pytest.raises(ValidationError, match="unresolved continuity"):
        EditorialArcReview(
            review_id="arc-review-2",
            source_asset_id="source-1",
            candidate_id="candidate-1",
            source_sha256="a" * 64,
            transcript_sha256="b" * 64,
            visual_analysis_sha256="c" * 64,
            arc_sha256="d" * 64,
            hook_promise="hook",
            body_development="body",
            punch_payoff="punch",
            beats=beats,
            decision="accepted",
            reviewer="reviewer-1",
            reviewed_at=datetime.now(UTC),
            provenance=_provenance(),
        )
