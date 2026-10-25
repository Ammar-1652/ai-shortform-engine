from __future__ import annotations

from datetime import UTC, datetime

import pytest

from clipforge.campaign.speech import apply_arabic_corrections, retained_recitation, validate_speech_captions
from clipforge.errors import MediaError
from clipforge.hero.advanced_build import _captions
from clipforge.schemas.campaign import (
    TarteelArabicCorrection,
    TarteelArabicCorrectionDocument,
    TarteelSpeechInterval,
    TarteelSpeechReview,
)
from clipforge.schemas.hero import ForcedAlignmentDocument
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimelineSegment, TimeMapDocument, digest_time_map


def _map() -> TimeMapDocument:
    return TimeMapDocument(
        time_map_id="speech-map",
        segments=[TimelineSegment(segment_id="kept", source_start_us=10_000_000, source_end_us=12_000_000)],
    )


def _provenance() -> ArtifactProvenance:
    return ArtifactProvenance(
        created_at=datetime.now(UTC),
        created_by="test",
        tool="review",
        tool_version="1",
        source_asset_ids=["source-1"],
    )


def _alignment() -> ForcedAlignmentDocument:
    return ForcedAlignmentDocument(
        alignment_id="alignment-1",
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        transcript_id="transcript-1",
        transcript_sha256="b" * 64,
        asr_audio_sha256="c" * 64,
        time_map_sha256=digest_time_map(_map()),
        review_id="review-1",
        review_digest="d" * 64,
        rough_preview_artifact_id="rough-1",
        model_name="fake-forced-align-v1",
        whisperx_version="test",
        device="cpu",
        config_sha256="e" * 64,
        locale="ar",
        normalized_language="ar",
        words=[
            {
                "word_id": f"word-{i}",
                "candidate_id": "candidate-1",
                "text": text,
                "source_start_us": 10_000_000 + i * 1_000_000,
                "source_end_us": 10_800_000 + i * 1_000_000,
                "output_start_us": i * 1_000_000,
                "output_end_us": 800_000 + i * 1_000_000,
                "output_start_frame": i * 30,
                "output_end_frame_exclusive": 24 + i * 30,
                "segment_index": 0,
            }
            for i, text in enumerate((" أفضل", " نصيحة؟"))
        ],
        provenance=_provenance(),
    )


def _review(
    text: str = "أفضل نصيحة؟", *, kind: str = "dialogue", decision: str = "captioned"
) -> TarteelSpeechReview:
    return TarteelSpeechReview(
        review_id="speech-1",
        campaign="tarteel",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        raw_asr_sha256="c" * 64,
        transcript_sha256="b" * 64,
        locale="ar",
        intervals=[
            TarteelSpeechInterval(
                span_id="span-1",
                source_start_us=10_000_000,
                source_end_us=12_000_000,
                kind=kind,
                caption_decision=decision,
                observed_text=text,
                review_note="reviewed audio and context",
            )
        ],
        reviewer="test",
        reviewed_at=datetime.now(UTC),
        provenance=_provenance(),
    )


def _validate(review: TarteelSpeechReview) -> None:
    alignment = _alignment()
    validate_speech_captions(
        review, alignment=alignment, time_map=_map(), captions=_captions(alignment, "candidate-1")
    )


def test_matching_review_has_exact_retained_caption_coverage() -> None:
    _validate(_review())


def test_review_cannot_certify_a_phrase_with_different_visible_text() -> None:
    alignment = _alignment()
    captions = _captions(alignment, "candidate-1")
    captions[0] = captions[0].model_copy(update={"text": "نص غير مطابق"})
    with pytest.raises(MediaError, match="caption phrase text"):
        validate_speech_captions(_review(), alignment=alignment, time_map=_map(), captions=captions)


@pytest.mark.parametrize(
    "text", ["أفضل", "أفضل نصيحة " + "\u0647" * 5, "كلام مختلف"], ids=["partial", "reaction", "different"]
)
def test_complete_intervals_cannot_hide_missing_or_wrong_speech(text: str) -> None:
    with pytest.raises(MediaError, match="reviewed speech text"):
        _validate(_review(text))


@pytest.mark.parametrize("kind", ["reaction", "nasheed"])
def test_retained_reactions_and_nasheed_cannot_be_marked_excluded(kind: str) -> None:
    with pytest.raises(MediaError, match="retained audible"):
        _validate(_review(kind=kind, decision="reviewed_excluded"))


@pytest.mark.parametrize("kind", ["silence", "uncertain"])
def test_uncertain_or_false_silence_does_not_certify_coverage(kind: str) -> None:
    with pytest.raises(MediaError):
        _validate(_review(kind=kind, decision="reviewed_excluded"))


def test_inventory_must_bind_alignment_locale_and_audio() -> None:
    for update in ({"locale": "fr-FR"}, {"raw_asr_sha256": "f" * 64}):
        with pytest.raises(MediaError, match=r"speech review.*alignment"):
            _validate(_review().model_copy(update=update))


def test_dialogue_does_not_require_an_unrelated_quran_sidecar() -> None:
    assert not retained_recitation(_review(), _map())
    assert retained_recitation(_review(kind="recitation"), _map())
    removed = _map().model_copy(
        update={
            "segments": [
                TimelineSegment(
                    segment_id="other",
                    source_start_us=20_000_000,
                    source_end_us=21_000_000,
                )
            ]
        }
    )
    assert not retained_recitation(_review(kind="recitation"), removed)


def test_arabic_correction_is_display_only_and_original_is_immutable() -> None:
    alignment = _alignment()
    correction = TarteelArabicCorrectionDocument(
        correction_set_id="corrections-1",
        campaign="tarteel",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        raw_asr_sha256="c" * 64,
        transcript_sha256="b" * 64,
        locale="ar",
        corrections=[
            TarteelArabicCorrection(
                correction_id="fix-1",
                source_word_id="word-1",
                source_window_us=(11_000_000, 11_800_000),
                original_text="نصيحة؟",
                corrected_text="نصيحه؟",
                locale="ar",
                evidence_kind="listening_context",
                reviewer="test",
                review_note="source-bound correction regression",
            )
        ],
        reviewer="test",
        reviewed_at=datetime.now(UTC),
        provenance=_provenance(),
    )
    corrected = apply_arabic_corrections(alignment, correction, source_sha256="a" * 64)
    assert alignment.words[1].text == " نصيحة؟"
    assert corrected.words[1].text == " نصيحه؟"
    assert corrected.words[1].model_dump(exclude={"text"}) == alignment.words[1].model_dump(exclude={"text"})
    stale = correction.model_copy(
        update={"corrections": [correction.corrections[0].model_copy(update={"original_text": "خطأ"})]}
    )
    with pytest.raises(MediaError, match="original text"):
        apply_arabic_corrections(alignment, stale, source_sha256="a" * 64)
