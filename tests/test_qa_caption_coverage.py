from types import SimpleNamespace

from clipforge.qa.technical import _caption_alignment_problems
from clipforge.schemas.advanced import CaptionWordTiming
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument
from clipforge.schemas.provenance import ArtifactProvenance


def _alignment() -> ForcedAlignmentDocument:
    words = [
        AlignedWord(
            word_id=f"word-{index}",
            candidate_id="candidate-1",
            text=f" word{index}",
            source_start_us=index * 500_000,
            source_end_us=(index + 1) * 500_000,
            output_start_us=index * 500_000,
            output_end_us=(index + 1) * 500_000,
            output_start_frame=index * 15,
            output_end_frame_exclusive=(index + 1) * 15,
        )
        for index in range(2)
    ]
    return ForcedAlignmentDocument(
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
        model_name="forced-align-test",
        whisperx_version="test",
        device="cpu",
        config_sha256="e" * 64,
        words=words,
        provenance=ArtifactProvenance(
            created_at="2026-01-01T00:00:00Z",
            created_by="test",
            tool="test",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )


def _caption_word(word: AlignedWord) -> CaptionWordTiming:
    return CaptionWordTiming(
        word_id=word.word_id,
        text=word.text,
        output_start_us=word.output_start_us,
        output_end_us=word.output_end_us,
        output_start_frame=word.output_start_frame,
        output_end_frame_exclusive=word.output_end_frame_exclusive,
    )


def test_qa_rejects_missing_captioned_alignment_word() -> None:
    alignment = _alignment()
    plan = SimpleNamespace(
        candidate_id="candidate-1",
        captions=[SimpleNamespace(words=[_caption_word(alignment.words[0])])],
    )
    assert _caption_alignment_problems(plan, alignment) == [
        "candidate=candidate-1 caption_alignment_word_coverage"
    ]


def test_qa_rejects_caption_timing_that_drifted_from_alignment() -> None:
    alignment = _alignment()
    first = _caption_word(alignment.words[0]).model_copy(update={"output_start_us": 100_000})
    plan = SimpleNamespace(
        candidate_id="candidate-1",
        captions=[SimpleNamespace(words=[first, _caption_word(alignment.words[1])])],
    )
    assert _caption_alignment_problems(plan, alignment) == [
        "candidate=candidate-1 caption_alignment_timing:word-0"
    ]
