from datetime import UTC, datetime
from pathlib import Path

import pytest

from clipforge.campaign.quran import load_codex_speech_review
from clipforge.campaign.speech import apply_speech_review_emojis
from clipforge.errors import MediaError
from clipforge.schemas.advanced import TypographyEvent
from clipforge.schemas.campaign import SpeechVerification, TarteelSpeechInterval, TarteelSpeechReview
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimelineSegment, TimeMapDocument


def _time_map() -> TimeMapDocument:
    return TimeMapDocument(
        time_map_id="map-1",
        segments=[TimelineSegment(segment_id="seg-1", source_start_us=0, source_end_us=2_000_000)],
    )


def _review(*, reviewer_role: str | None = "codex_operator") -> TarteelSpeechReview:
    return TarteelSpeechReview(
        review_id="codex-review-1",
        campaign="generic",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        raw_asr_sha256="b" * 64,
        transcript_sha256="c" * 64,
        locale="en-US",
        intervals=[
            TarteelSpeechInterval(
                span_id="span-1",
                source_start_us=0,
                source_end_us=1_000_000,
                kind="dialogue",
                caption_decision="captioned",
                observed_text="That is exciting! 🤩",
                review_note="Codex checked the phrase against the source context.",
            )
        ],
        reviewer="codex",
        reviewer_role=reviewer_role,  # type: ignore[arg-type]
        reviewed_at=datetime.now(UTC),
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="codex",
            tool="clipforge-test",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )


def test_generic_codex_review_preserves_emotion_emoji_and_role() -> None:
    review = _review()
    assert review.campaign == "generic"
    assert review.reviewer_role == "codex_operator"
    assert "🤩" in review.intervals[0].observed_text


def test_sensitive_text_verification_requires_reliable_evidence() -> None:
    with pytest.raises(ValueError, match="source URL or hashed snapshot"):
        SpeechVerification(
            verification_id="verification-1",
            subject_kind="quran",
            note="Codex checked the wording.",
        )


def test_sensitive_text_verification_accepts_url_or_snapshot() -> None:
    by_url = SpeechVerification(
        verification_id="verification-url",
        subject_kind="quotation",
        source_url="https://example.test/quote",
        note="Codex checked the quotation against the cited source.",
    )
    by_snapshot = SpeechVerification(
        verification_id="verification-snapshot",
        subject_kind="quran",
        snapshot_sha256="d" * 64,
        note="Codex checked the verse against the captured local source.",
    )
    assert by_url.status == "verified"
    assert by_snapshot.snapshot_sha256 == "d" * 64


def test_codex_emotion_annotation_reaches_caption_event() -> None:
    caption = TypographyEvent(
        event_id="caption-1",
        interval=OutputInterval(output_start_us=0, output_end_us=1_000_000),
        purpose=MotionPurpose.CONCEPT,
        component_id="typography-v1",
        text="That is exciting",
        x=96,
        y=1600,
        font_size=64,
    )
    updated = apply_speech_review_emojis(_review(), [caption], time_map=_time_map())
    assert updated[0].emoji == "🤩"


def test_codex_emotion_annotation_maps_from_source_clock_after_jump_cut() -> None:
    review = _review().model_copy(
        update={
            "intervals": [
                TarteelSpeechInterval(
                    span_id="span-jump",
                    source_start_us=2_100_000,
                    source_end_us=2_900_000,
                    kind="reaction",
                    caption_decision="captioned",
                    observed_text="That is exciting! 🤩",
                    review_note="Codex checked the retained reaction.",
                )
            ]
        }
    )
    time_map = TimeMapDocument(
        time_map_id="map-jump",
        segments=[
            TimelineSegment(segment_id="seg-before", source_start_us=0, source_end_us=1_000_000),
            TimelineSegment(segment_id="seg-after", source_start_us=2_000_000, source_end_us=3_000_000),
        ],
    )
    caption = TypographyEvent(
        event_id="caption-jump",
        interval=OutputInterval(output_start_us=1_100_000, output_end_us=1_900_000),
        purpose=MotionPurpose.CONCEPT,
        component_id="typography-v1",
        text="That is exciting",
        x=96,
        y=1600,
        font_size=64,
    )
    updated = apply_speech_review_emojis(review, [caption], time_map=time_map)
    assert updated[0].emoji == "🤩"


def test_generic_review_rejects_non_codex_role_at_loader(tmp_path: Path) -> None:
    path = tmp_path / "editorial/speech-reviews/source-1/candidate-1/speech-review.json"
    path.parent.mkdir(parents=True)
    path.write_text(_review(reviewer_role="human_reviewer").model_dump_json(), encoding="utf-8")
    with pytest.raises(MediaError, match="codex_operator"):
        load_codex_speech_review(
            tmp_path,
            source_asset_id="source-1",
            candidate_id="candidate-1",
            source_sha256="a" * 64,
            raw_asr_sha256="b" * 64,
            transcript_sha256="c" * 64,
        )


def test_generic_review_loader_binds_all_lineage_hashes(tmp_path: Path) -> None:
    path = tmp_path / "editorial/speech-reviews/source-1/candidate-1/speech-review.json"
    path.parent.mkdir(parents=True)
    path.write_text(_review().model_dump_json(), encoding="utf-8")
    loaded = load_codex_speech_review(
        tmp_path,
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        raw_asr_sha256="b" * 64,
        transcript_sha256="c" * 64,
    )
    assert loaded is not None
    assert loaded[0].review_id == "codex-review-1"
    assert loaded[1] == __import__("hashlib").sha256(path.read_bytes()).hexdigest()


def test_generic_review_rejects_stale_source_hash(tmp_path: Path) -> None:
    path = tmp_path / "editorial/speech-reviews/source-1/candidate-1/speech-review.json"
    path.parent.mkdir(parents=True)
    path.write_text(_review().model_dump_json(), encoding="utf-8")
    with pytest.raises(MediaError, match="source hash"):
        load_codex_speech_review(
            tmp_path,
            source_asset_id="source-1",
            candidate_id="candidate-1",
            source_sha256="d" * 64,
            raw_asr_sha256="b" * 64,
            transcript_sha256="c" * 64,
        )
