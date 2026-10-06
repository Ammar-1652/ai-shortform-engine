"""Round 30: multilingual alignment stays explicit about what was actually run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.campaign.production import plan_campaign, resume_campaign, run_campaign
from clipforge.errors import FrameOutOfRangeError, MediaError
from clipforge.hero.alignment import (
    FakeForcedAlignment,
    alignment_binding_sha256,
    production_alignment_backend,
)
from clipforge.language.captions import build_cues, wrap_caption
from clipforge.language.model_manifest import speech_smoke_manifest
from clipforge.language.providers import (
    alignment_cache_key,
    canonical_locale,
    license_is_allowed,
    normalized_language,
    provider_for,
)
from clipforge.language.registry import alignment_claim, alignment_identity_matches, capability_for
from clipforge.language.service import (
    FakeLanguageAligner,
    LanguageError,
    WhisperXFullSourceAligner,
    assert_narration_request,
    narrate_language,
)
from clipforge.schemas.multilingual import MultilingualAlignmentDocument
from clipforge.timeline import TimeMap
from clipforge.timeline.framerate import FrameRate
from tests.test_round20_campaign import _world
from tests.test_round26_language import _align, _db

_SHA = "a" * 64


def test_locale_normalization_and_closed_failures() -> None:
    assert canonical_locale("en-US") == "en-US"
    assert canonical_locale("en") == "en-US"
    assert canonical_locale("ja-JP") == "ja"
    assert normalized_language("en-GB") == "en"
    assert normalized_language("fr-FR") == "fr"
    assert normalized_language("es-ES") == "es"
    assert normalized_language("de-DE") == "de"
    assert normalized_language("zh-CN") == "zh"
    assert normalized_language("ar") == "ar"
    english = provider_for("en-US")
    assert english.live_status != "verified_live" or bool(speech_smoke_manifest("en-US"))
    assert english.model_id == "WAV2VEC2_ASR_BASE_960H"
    assert english.checkpoint_sha256 == capability_for("en-US").alignment_checkpoint_sha256
    japanese = provider_for("ja-JP")
    assert japanese.locale == "ja"
    assert japanese.normalized_language == "ja"
    assert japanese.live_status != "verified_live" or bool(speech_smoke_manifest("ja"))
    assert japanese.model_id.endswith("japanese")
    assert japanese.model_license == "Apache-2.0"
    assert japanese.checkpoint_sha256 == "4f6821dcd79770fcd4c11487c4ee5c040b3a7e1863425224014ba5ea8fbc1b67"
    french = provider_for("fr-FR")
    assert french.live_status != "verified_live" or bool(speech_smoke_manifest("fr-FR"))
    assert french.checkpoint_sha256 == "2fc4760bab7bf7d0d6c06e9b7f829a27a3e66eefee3733f53c88dbedf6607f2e"
    assert "VOXPOPULI" not in french.model_id
    assert provider_for("es-ES").live_status == "model_missing"
    assert provider_for("de-DE").live_status == "model_missing"
    assert provider_for("ar").live_status == "alignment_not_claimed"
    assert provider_for("ar").model_id == "none"
    assert provider_for("zh-CN").live_status == "unsupported_language"
    assert provider_for("../secrets").live_status == "unsupported_language"
    assert provider_for("https://example.invalid").live_status == "unsupported_language"
    assert alignment_claim("ja") == (
        "whisperx" if japanese.live_status == "verified_live" else "alignment_not_claimed"
    )
    assert alignment_identity_matches(
        revision=japanese.model_revision,
        checkpoint=japanese.checkpoint_sha256,
        language="ja",
    ) == (japanese.live_status == "verified_live")
    assert alignment_claim("ar") == "alignment_not_claimed"
    assert alignment_claim("en-US") == (
        "whisperx" if english.live_status == "verified_live" else "alignment_not_claimed"
    )
    assert not alignment_identity_matches(revision="9.9.9", checkpoint=_SHA, language="ja")
    assert not license_is_allowed("CC-BY-NC-4.0", "some-model")
    assert not license_is_allowed("Apache-2.0", "VOXPOPULI_ASR_BASE_10K_FR")
    japanese_backend = production_alignment_backend("ja")
    assert japanese_backend.model_name.endswith("japanese")
    assert japanese_backend.checkpoint_sha256 == japanese.checkpoint_sha256
    french_backend = production_alignment_backend("fr-FR")
    assert french_backend.language_code == "fr"
    assert french_backend.model_name.endswith("french")
    with pytest.raises(MediaError, match="alignment_not_claimed"):
        production_alignment_backend("ar")
    with pytest.raises(MediaError, match="unsupported_language"):
        production_alignment_backend("zh-CN")


def test_fake_provider_cannot_be_verified_live() -> None:
    with pytest.raises(ValidationError, match="fake alignment"):
        MultilingualAlignmentDocument.model_validate(
            {
                "alignment_id": "align-1",
                "source_asset_id": "source-1",
                "source_sha256": _SHA,
                "transcript_id": "transcript-1",
                "transcript_sha256": _SHA,
                "language": "en-US",
                "language_tag": "en-US",
                "provider_id": "fake",
                "provider_version": "fake",
                "model_id": "fake-en-US",
                "model_revision": "0",
                "checkpoint_sha256": _SHA,
                "runtime_version": "fake",
                "device": "cpu",
                "sample_rate": 16000,
                "word_count": 1,
                "alignment_status": "verified_live",
                "timing_quality": "forced",
                "artifact_sha256": _SHA,
                "producer_job_id": "job-1",
                "project_id": "project-1",
                "relative_path": "languages/alignments/align-1/artifact.json",
                "language_capability_fingerprint": _SHA,
                "identity_sha256": _SHA,
                "words": [
                    {
                        "word_id": "w1",
                        "text": "Cafe",
                        "source_start_us": 0,
                        "source_end_us": 1000,
                        "output_start_us": 0,
                        "output_end_us": 1000,
                        "output_start_frame": 0,
                        "output_end_frame_exclusive": 1,
                        "source_asset_id": "source-1",
                        "transcript_id": "transcript-1",
                    }
                ],
            }
        )


def test_cache_key_changes_when_identity_changes() -> None:
    base = {
        "checkpoint_sha256": _SHA,
        "locale": "en-US",
        "model_id": "WAV2VEC2_ASR_BASE_960H",
        "model_revision": "3.4.5",
        "normalized_language": "en",
        "provider_version": "3.4.5",
        "source_sha256": _SHA,
        "time_map_sha256": "b" * 64,
        "transcript_sha256": "c" * 64,
    }
    original = alignment_cache_key(**base)
    assert alignment_binding_sha256(**base) == original
    for key, value in (
        ("source_sha256", "d" * 64),
        ("transcript_sha256", "e" * 64),
        ("locale", "ja"),
        ("model_revision", "other"),
        ("checkpoint_sha256", "f" * 64),
        ("provider_version", "9.9.9"),
        ("time_map_sha256", "1" * 64),
    ):
        changed = dict(base)
        changed[key] = value
        assert alignment_cache_key(**changed) != original


def test_caption_text_keeps_source_characters() -> None:
    latin = wrap_caption("Café costs $12.50 today.", language="en-US", width=12)
    assert " ".join(latin) == "Café costs $12.50 today."
    assert any("$12.50" in line for line in latin)
    arabic = "السعر ١٢٫٥٠ أو 12.50."  # noqa: RUF001
    wrapped = wrap_caption(arabic, language="ar", width=40)
    assert " ".join(wrapped) == arabic
    assert wrapped[0][0] == arabic[0]
    japanese = wrap_caption("説明です。12", language="ja", width=4)
    assert "".join(japanese) == "説明です。12"
    assert " " not in "".join(japanese)
    assert all(not line.startswith("。") for line in japanese)
    cues = build_cues(arabic, language="ar", duration_us=1_000_000)
    assert cues[0].text == arabic
    assert cues[0].text_direction == "rtl"
    assert cues[0].alignment_status == "alignment_not_claimed"
    with pytest.raises(ValueError, match="alignment_not_claimed"):
        build_cues("説明", language="ja", duration_us=1_000_000, aligned=True)


def _full_source_code(locale: str) -> str:
    status = provider_for(locale).live_status
    return "not_configured" if status == "verified_live" else status


def test_unverified_languages_fail_before_a_job(tmp_path: Path) -> None:
    database, work = _db(tmp_path)
    with pytest.raises(LanguageError) as japanese:
        _align(work, database, language="ja", provider=WhisperXFullSourceAligner())
    assert japanese.value.code == _full_source_code("ja")
    with pytest.raises(LanguageError) as french:
        _align(work, database, language="fr-FR", provider=WhisperXFullSourceAligner())
    assert french.value.code == _full_source_code("fr-FR")
    with pytest.raises(LanguageError) as arabic:
        _align(work, database, language="ar", provider=WhisperXFullSourceAligner())
    assert arabic.value.code == "alignment_not_claimed"
    with pytest.raises(LanguageError) as unsupported:
        _align(work, database, language="zh-CN")
    assert unsupported.value.code == "unsupported_language"
    fake = _align(work, database, language="en-US", provider=FakeLanguageAligner("en-US"))
    assert fake.alignment_status == "available_not_smoked"
    assert fake.alignment_status != "verified_live"


def test_narration_rejects_unverified_locales_before_a_job(tmp_path: Path) -> None:
    database, work = _db(tmp_path)
    assert assert_narration_request("ja", False) == "narration_not_requested"
    for language in ("ja", "ar", "fr-FR", "es-ES", "de-DE"):
        with pytest.raises(LanguageError, match="unsupported_language"):
            assert_narration_request(language, True)
    with pytest.raises(LanguageError) as missing:
        narrate_language(
            work,
            database,
            project_id="project-1",
            source_id="source-1",
            language="en-US",
            script_text="Cafe",
            provider_id="none",
            engine_id="kittentts",
            model_id="KittenML/kitten-tts-mini-0.8",
            model_revision="c02725660cea441db4c383af69f1f26f5cd00947",
            voice_id="expr-voice-2-f",
            license_name="Apache-2.0",
            commercial_use="allowed",
            sample_rate=24000,
            channels=1,
            duration_us=1_000_000,
            audio_sha256=_SHA,
        )
    assert missing.value.code == "provider_unavailable"
    with pytest.raises(LanguageError) as unknown:
        narrate_language(
            work,
            database,
            project_id="project-1",
            source_id="source-1",
            language="en-US",
            script_text="Cafe",
            provider_id="voicestudio",
            engine_id="kittentts",
            model_id="KittenML/kitten-tts-mini-0.8",
            model_revision="c02725660cea441db4c383af69f1f26f5cd00947",
            voice_id="expr-voice-2-f",
            license_name="unknown",
            commercial_use="allowed",
            sample_rate=24000,
            channels=1,
            duration_us=1_000_000,
            audio_sha256=_SHA,
        )
    assert unknown.value.code == "model_license_unknown"


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    [(24, 1), (25, 1), (30000, 1001), (30, 1), (60, 1)],
)
def test_time_map_frame_rules(numerator: int, denominator: int) -> None:
    rate = FrameRate(numerator, denominator)
    duration = 1_000_000
    timeline = TimeMap.from_source_ranges([(0, duration)])
    count = timeline.output_frame_count(rate)
    assert count >= 1
    timeline.output_frame_to_source(count - 1, rate)
    with pytest.raises(FrameOutOfRangeError):
        timeline.output_frame_to_source(count, rate)
    jumped = TimeMap.from_source_ranges([(0, 500_000), (2_000_000, 2_500_000)])
    assert jumped.output_to_source(500_000) == 2_000_000
    assert jumped.output_to_source(jumped.total_output_duration()) == 2_500_000


def test_one_source_can_fail_its_locale_without_erasing_a_sibling(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False)
    document = run_campaign(
        world.database,
        world.work,
        narration_enabled=False,
        source_locales={"src-american-secret": "es-ES"},
    )
    by_id = {item.source_id: item for item in document.sources}
    assert by_id["src-before-famous"].status == "succeeded"
    failed = by_id["src-american-secret"]
    assert failed.status != "succeeded"
    assert failed.reason_code == provider_for("es-ES").live_status
    assert failed.requested_locale == "es-ES"
    resumed = resume_campaign(world.database, world.work, document.campaign_run_id)
    again = {item.source_id: item for item in resumed.sources}
    assert again["src-before-famous"].delivery_id == by_id["src-before-famous"].delivery_id
    assert again["src-american-secret"].reason_code == provider_for("es-ES").live_status
    assert [stage.job_id for stage in again["src-before-famous"].stages] == [
        stage.job_id for stage in by_id["src-before-famous"].stages
    ]


def test_plan_records_catalog_facts_without_a_live_claim() -> None:
    japanese = plan_campaign(language="ja", narration_enabled=False)
    assert japanese.alignment_provider == "whisperx"
    assert japanese.alignment_model is not None
    assert japanese.alignment_model.endswith("japanese")
    record = provider_for("ja")
    source = next(item for item in japanese.sources if item.source_id == "src-before-famous")
    align = next(item for item in source.stages if item.stage == "align")
    if record.live_status == "verified_live":
        assert japanese.alignment_checkpoint_sha256 == record.checkpoint_sha256
        assert align.reason_code == "planned"
    else:
        assert japanese.alignment_checkpoint_sha256 is None
        assert align.reason_code == record.live_status
    arabic = plan_campaign(language="ar", narration_enabled=False)
    assert arabic.alignment_provider == "none"
    arabic_source = next(item for item in arabic.sources if item.source_id == "src-before-famous")
    assert next(item for item in arabic_source.stages if item.stage == "align").reason_code == (
        "alignment_not_claimed"
    )


def test_worker_request_refuses_an_english_fallback() -> None:
    payload = {
        "allow_model_download": False,
        "language_code": "ja",
        "model_name": "WAV2VEC2_ASR_BASE_960H",
        "audio_path": "clip.wav",
        "source_start_us": 0,
        "source_end_us": 1_000_000,
        "words": [{"text": "説明"}],
    }
    assert "WAV2VEC2_ASR_BASE_960H" in json.dumps(payload)
    with pytest.raises(MediaError, match="alignment_not_claimed"):
        from clipforge.hero.alignment import _reject_alignment_model

        _reject_alignment_model("ja", "WAV2VEC2_ASR_BASE_960H")
    with pytest.raises(MediaError, match="model_license_unknown"):
        from clipforge.hero.alignment import _reject_alignment_model

        _reject_alignment_model("fr", "VOXPOPULI_ASR_BASE_10K_FR")


def test_character_pieces_collapse_onto_the_transcript_word() -> None:
    from clipforge.hero.alignment import _collapse_alignment_tokens
    from clipforge.schemas.media import TranscriptWord

    word = TranscriptWord(word_id="w1", text="説明", start_us=0, end_us=1_000)
    bounds = _collapse_alignment_tokens(
        [word],
        [("説", 0, 20_000), ("明", 20_000, 41_000)],
        source_offset=0,
    )
    assert bounds == [(0, 41_000)]
    with pytest.raises(MediaError, match="does not match"):
        _collapse_alignment_tokens([word], [("hello", 0, 10)], source_offset=0)


def test_fake_aligner_is_not_the_production_backend() -> None:
    backend = production_alignment_backend("en", allow_model_download=False)
    assert not isinstance(backend, FakeForcedAlignment)
    assert backend.language_code == "en"
    assert backend.model_name == "WAV2VEC2_ASR_BASE_960H"
    assert backend.locale == "en-US"
