import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clipforge.campaign.overlays import (
    choose_tarteel_foreground_position,
    choose_tarteel_overlay_start_us,
)
from clipforge.campaign.quran import canonicalize_quran_alignment, load_tarteel_quran_review
from clipforge.errors import MediaError
from clipforge.schemas.campaign import (
    CampaignOverlaySpec,
    QuranAudioMapping,
    QuranCanonicalSource,
    QuranCaptionReview,
    QuranVerificationPolicy,
)
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument
from clipforge.schemas.provenance import ArtifactProvenance


def test_cta_beat_prefers_a_caption_free_middle_or_latter_slot() -> None:
    start = choose_tarteel_overlay_start_us(
        50_000_000,
        3_000_000,
        [(30_000_000, 50_000_000)],
    )
    assert start == 23_000_000


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


def test_cta_position_avoids_the_most_occupied_face_region() -> None:
    left_top = choose_tarteel_foreground_position([(0.02, 0.05, 0.55, 0.35)])
    assert left_top != (60, 180)


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
    assert all(word.verification_status == "unverified" for word in corrected.words)
    assert corrected.words[0].source_word_ids == ["word-0", "word-1"]
    assert any(" ۖ" in word.text for word in corrected.words)
