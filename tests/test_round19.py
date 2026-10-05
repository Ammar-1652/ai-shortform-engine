"""Round 19 caption, readiness, narration, and secret checks. No source media is read."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clipforge.benchmark.service import readiness_report, run_benchmark
from clipforge.language.captions import assert_no_overlap, build_cues
from clipforge.language.frames import prove_captions
from clipforge.language.matrix import require_language
from clipforge.voice.provider import FakeVoiceProvider, VoiceStudioProvider
from clipforge.voice.service import generate_narration
from tests.test_round15 import _chain, _narration

_SCRIPT = "Café costs $12.50 today."


def test_captions_keep_source_text_and_do_not_claim_whisperx() -> None:
    english = build_cues(_SCRIPT, language="en-US", duration_us=2_000_000)
    assert english[0].text == _SCRIPT
    assert english[0].alignment_status == "alignment_not_claimed"
    arabic = build_cues("مرحبا", language="ar", duration_us=2_000_000)
    assert arabic[0].text == "مرحبا"
    assert arabic[0].text_direction == "rtl"
    assert arabic[0].alignment_status == "alignment_not_claimed"
    japanese = build_cues("価格は100円です。", language="ja", duration_us=2_000_000)
    assert japanese[0].text == "価格は100円です。"
    assert_no_overlap(japanese)
    with pytest.raises(ValueError, match="alignment_not_claimed"):
        build_cues("مرحبا", language="ar", duration_us=1_000_000, aligned=True)
    with pytest.raises(ValueError, match="unsupported_language"):
        require_language("zh-CN")


def test_synthetic_benchmark_is_not_a_real_source(tmp_path: Path) -> None:
    database, work = _chain(tmp_path)
    recorded = run_benchmark(database, work, "source-1", fixture_kind="real_source")
    report = readiness_report(database, work, recorded.benchmark_run_id)
    assert report.evidence_class == "real_source"
    assert report.real_source_verified == "unavailable"
    assert report.external_publishing == "external_publishing_deferred"
    assert report.voice_result == "voice_disabled"
    assert report.alignment_claim == "alignment_not_claimed"
    assert report.technical_result in {"technical_pass", "blocked", "not_run", "failed", "unavailable"}
    assert report.local_delivery_result != "local_delivery_pass"
    synthetic = run_benchmark(database, work, "source-1", fixture_kind="deterministic_synthetic", force=True)
    synthetic_report = readiness_report(database, work, synthetic.benchmark_run_id)
    assert synthetic_report.evidence_class == "synthetic_only"
    assert "synthetic_only" in synthetic.warnings


def test_changed_script_and_provider_miss_the_narration_cache(tmp_path: Path) -> None:
    database, work = _chain(tmp_path, evidence=False)
    provider = FakeVoiceProvider()
    first = generate_narration(database, work, _narration(_SCRIPT), provider)
    assert first.language == "en"
    assert first.provider_version == "0"
    assert provider.calls == 1
    again = generate_narration(database, work, _narration(_SCRIPT), provider)
    assert again.artifact_id == first.artifact_id
    assert provider.calls == 1
    changed = generate_narration(database, work, _narration("Café costs $13.50 today."), provider)
    assert changed.artifact_id != first.artifact_id
    assert provider.calls == 2
    revised = _narration(_SCRIPT)
    profile = revised.profile.model_copy(update={"provider_version": "9"})
    revised = revised.model_copy(update={"profile": profile})
    other = generate_narration(database, work, revised, provider)
    assert other.artifact_id != first.artifact_id
    assert other.provider_version == "9"
    assert provider.calls == 3


def test_disabled_voice_doctor_reports_health_without_a_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network opened")

    monkeypatch.setattr("http.client.HTTPConnection", explode)
    monkeypatch.setattr("http.client.HTTPSConnection", explode)
    provider = VoiceStudioProvider(enabled=False)
    text = provider.doctor()
    assert "health: not_called" in text
    assert "capabilities: not_called" in text
    assert provider.capabilities()["network"] == "none"


def test_voice_doctor_reads_health_and_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads = [
        json.dumps({"status": "ok", "version": "9.9.9"}).encode(),
        json.dumps(
            {
                "protocol": "voicestudio.speech.v1",
                "service_version": "9.9.9",
                "endpoints": {"capabilities": {}, "batch_transcription": {}},
            }
        ).encode(),
    ]

    class Response:
        status = 200

        def __init__(self, payload: bytes) -> None:
            self.payload = payload
            self.headers = {"Content-Type": "application/json"}

        def read(self) -> bytes:
            return self.payload

    class Connection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        def request(self, *_args: object, **_kwargs: object) -> None:
            return None

        def getresponse(self) -> Response:
            return Response(payloads.pop(0))

        def close(self) -> None:
            return None

    monkeypatch.setattr("http.client.HTTPConnection", Connection)
    provider = VoiceStudioProvider(enabled=True)
    text = provider.doctor()
    assert "health: ok" in text
    assert "service_version: 9.9.9" in text
    assert "batch_transcription" in text
    assert "://" not in text


@pytest.mark.media
def test_decoded_caption_frames_keep_unicode_inside_the_safe_area(tmp_path: Path) -> None:
    proofs = prove_captions(tmp_path)
    by_language = {proof.language: proof for proof in proofs}
    assert by_language["en-US"].text == _SCRIPT
    assert by_language["ar"].text == "مرحبا"
    assert by_language["ar"].text_direction == "rtl"
    assert by_language["ja"].text == "価格は100円です。"
    assert all(proof.alignment_status == "alignment_not_claimed" for proof in proofs)
    assert all(proof.safe_area and proof.glyphs_present for proof in proofs)
