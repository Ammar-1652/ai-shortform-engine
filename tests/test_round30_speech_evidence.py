"""Speech evidence is live only when the external file and the measured model agree.

Tiny WAV fixtures in this file are structural. They are not live speech.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.language.model_manifest import (
    bound_speech_record,
    load_speech_catalog,
    measured_whisperx_version,
    resolve_speech_audio,
    speech_evidence_grants_live,
    speech_evidence_root,
    speech_identity_matches,
    wav_signature,
)
from clipforge.language.providers import provider_for
from clipforge.schemas.language import SpeechEvidenceCatalog, SpeechEvidenceRecord

_REAL = {
    "en-US": ("en-speech.wav", "3df575324d82909d4314bf67364f4fa3cc58a9e0838b20257166b2d0bb2ab57c"),
    "fr-FR": ("fr-speech.wav", "a3e9c785cf7a4a84c6af80e944b134eab161d3459d86153249d6d8a02682e254"),
    "ja": ("ja-speech.wav", "7cefeb57a7ecdec014512b351d6e668893ee42ca8fcf052c067ee8dab5379934"),
}


def _pcm_wav(payload: bytes = b"\x00\x01" * 220) -> bytes:
    """A minimal PCM container. This is structural validation, not speech."""
    rate = 22050
    channels = 1
    bits = 16
    data_size = len(payload)
    byte_rate = rate * channels * bits // 8
    block = channels * bits // 8
    header = b"RIFF" + (36 + data_size).to_bytes(4, "little") + b"WAVE"
    fmt = (
        b"fmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + channels.to_bytes(2, "little")
        + rate.to_bytes(4, "little")
        + byte_rate.to_bytes(4, "little")
        + block.to_bytes(2, "little")
        + bits.to_bytes(2, "little")
    )
    data = b"data" + data_size.to_bytes(4, "little") + payload
    return header + fmt + data


def _record(**overrides: object) -> dict[str, object]:
    audio = _pcm_wav()
    base: dict[str, object] = {
        "schema_version": "1.0.0",
        "locale": "en-US",
        "audio_class": "tts_speech",
        "audio_filename": "clip.wav",
        "audio_sha256": hashlib.sha256(audio).hexdigest(),
        "sample_rate": 22050,
        "channels": 1,
        "duration_us": wav_signature_from(audio)[2],
        "transcript": "hello world this is a test",
        "token_count": 6,
        "whisperx_version": "3.4.5",
        "model_id": "WAV2VEC2_ASR_BASE_960H",
        "model_revision": "3.4.5",
        "checkpoint_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "device": "cpu",
        "provenance": "Structural WAV fixture. It is not live speech.",
    }
    base.update(overrides)
    return base


def wav_signature_from(audio: bytes) -> tuple[int, int, int]:
    path_holder = audio
    rate = 22050
    duration_us = (len(path_holder) - 44) * 1_000_000 // (rate * 2)
    return rate, 1, duration_us


def _write(root: Path, record: dict[str, object], audio: bytes | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    payload = audio if audio is not None else _pcm_wav()
    name = str(record.get("audio_filename") or "clip.wav")
    if "/" not in name and not name.startswith(".."):
        (root / name).write_bytes(payload)
    catalog = root / "catalog.json"
    catalog.write_text(
        json.dumps({"schema_version": "1.0.0", "records": [record]}),
        encoding="utf-8",
    )
    return catalog


def _identity(record: SpeechEvidenceRecord, *, locale: str = "en-US") -> bool:
    return speech_identity_matches(
        record,
        locale=locale,
        model_id="WAV2VEC2_ASR_BASE_960H",
        model_revision="3.4.5",
        checkpoint_sha256="a" * 64,
        manifest_sha256="b" * 64,
        whisperx_version="3.4.5",
        device="cpu",
    )


def _grants(
    locale: str,
    *,
    root: Path | None,
    catalog: Path,
    model_id: str = "WAV2VEC2_ASR_BASE_960H",
    model_revision: str = "3.4.5",
    checkpoint_sha256: str = "a" * 64,
    manifest_sha256: str = "b" * 64,
    whisperx_version: str = "3.4.5",
    device: str = "cpu",
) -> bool:
    return speech_evidence_grants_live(
        locale,
        model_id=model_id,
        model_revision=model_revision,
        checkpoint_sha256=checkpoint_sha256,
        manifest_sha256=manifest_sha256,
        whisperx_version=whisperx_version,
        device=device,
        evidence_root=root,
        catalog_path=catalog,
    )


def test_structural_wav_binding_is_not_a_provider_live_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A consistent tiny WAV can bind to its own row and still stay non-live."""
    audio = _pcm_wav()
    record = _record()
    catalog = _write(tmp_path, record, audio)
    monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", str(tmp_path))
    monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_CATALOG", str(catalog))
    bound = bound_speech_record("en-US", evidence_root=tmp_path, catalog_path=catalog)
    assert bound is not None
    assert _identity(bound) is True
    assert _grants("en-US", root=tmp_path, catalog=catalog) is False
    assert provider_for("en-US").live_status != "verified_live"


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("absent_catalog", "absent_catalog"),
        ("absent_root", "absent_root"),
        ("missing_filename", "missing_filename"),
        ("missing_file", "missing_file"),
        ("escaped_name", "escaped_name"),
        ("wrong_hash", "wrong_hash"),
        ("malformed_hash", "malformed_hash"),
        ("wrong_locale", "wrong_locale"),
        ("wrong_model", "wrong_model"),
        ("wrong_revision", "wrong_revision"),
        ("wrong_checkpoint", "wrong_checkpoint"),
        ("wrong_manifest", "wrong_manifest"),
        ("wrong_whisperx", "wrong_whisperx"),
        ("wrong_device", "wrong_device"),
        ("empty_transcript", "empty_transcript"),
        ("few_tokens", "few_tokens"),
        ("tone_class", "tone_class"),
        ("en_us_record_for_en_gb", "en_gb"),
        ("french_record_for_japanese", "ja_from_fr"),
        ("forged_manifest", "forged_manifest"),
    ],
)
def test_speech_evidence_failures_stay_non_live(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    mutate: str,
) -> None:
    del label
    monkeypatch.delenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", raising=False)
    monkeypatch.delenv("CLIPFORGE_SPEECH_EVIDENCE_CATALOG", raising=False)
    audio = _pcm_wav()
    record = _record()
    locale = "en-US"
    catalog = _write(tmp_path, record, audio)
    root: Path | None = tmp_path
    if mutate == "absent_catalog":
        catalog = tmp_path / "missing.json"
        assert load_speech_catalog(catalog) is None
    elif mutate == "absent_root":
        root = tmp_path / "missing-root"
        monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", str(root))
        assert speech_evidence_root() is None
        assert root.is_dir() is False
    elif mutate == "missing_filename":
        record["audio_filename"] = ""
        with pytest.raises(ValidationError):
            SpeechEvidenceRecord.model_validate(record)
        catalog = _write(tmp_path, record, audio)
    elif mutate == "missing_file":
        (tmp_path / "clip.wav").unlink()
        assert bound_speech_record("en-US", evidence_root=tmp_path, catalog_path=catalog) is None
    elif mutate == "escaped_name":
        record["audio_filename"] = "../clip.wav"
        with pytest.raises(ValidationError):
            SpeechEvidenceRecord.model_validate(record)
        assert resolve_speech_audio(tmp_path, "../clip.wav") is None
        catalog = _write(tmp_path, record, audio)
    elif mutate == "wrong_hash":
        record["audio_sha256"] = "c" * 64
        catalog = _write(tmp_path, record, audio)
        loaded = load_speech_catalog(catalog)
        assert loaded is not None
        assert hashlib.sha256(audio).hexdigest() != loaded.records[0].audio_sha256
        assert bound_speech_record("en-US", evidence_root=tmp_path, catalog_path=catalog) is None
    elif mutate == "malformed_hash":
        record["audio_sha256"] = "not-a-hash"
        with pytest.raises(ValidationError):
            SpeechEvidenceRecord.model_validate(record)
        catalog = _write(tmp_path, record, audio)
        assert load_speech_catalog(catalog) is None
    elif mutate == "wrong_locale":
        record["locale"] = "fr-FR"
        catalog = _write(tmp_path, record, audio)
        parsed = SpeechEvidenceRecord.model_validate(record)
        assert _identity(parsed, locale="en-US") is False
        assert bound_speech_record("en-US", evidence_root=tmp_path, catalog_path=catalog) is None
    elif mutate == "wrong_model":
        record["model_id"] = "jonatasgrosman/wav2vec2-large-xlsr-53-french"
        catalog = _write(tmp_path, record, audio)
        assert _identity(SpeechEvidenceRecord.model_validate(record)) is False
    elif mutate == "wrong_revision":
        record["model_revision"] = "deadbeef"
        catalog = _write(tmp_path, record, audio)
        assert _identity(SpeechEvidenceRecord.model_validate(record)) is False
    elif mutate == "wrong_checkpoint":
        record["checkpoint_sha256"] = "d" * 64
        catalog = _write(tmp_path, record, audio)
        assert _identity(SpeechEvidenceRecord.model_validate(record)) is False
    elif mutate == "wrong_manifest":
        record["manifest_sha256"] = "e" * 64
        catalog = _write(tmp_path, record, audio)
        assert _identity(SpeechEvidenceRecord.model_validate(record)) is False
    elif mutate == "wrong_whisperx":
        record["whisperx_version"] = "0.0.1"
        catalog = _write(tmp_path, record, audio)
        assert _identity(SpeechEvidenceRecord.model_validate(record)) is False
    elif mutate == "wrong_device":
        record["device"] = "cuda"
        catalog = _write(tmp_path, record, audio)
        assert _identity(SpeechEvidenceRecord.model_validate(record)) is False
    elif mutate == "empty_transcript":
        record["transcript"] = ""
        with pytest.raises(ValidationError):
            SpeechEvidenceRecord.model_validate(record)
        catalog = _write(tmp_path, record, audio)
    elif mutate == "few_tokens":
        record["token_count"] = 2
        with pytest.raises(ValidationError):
            SpeechEvidenceRecord.model_validate(record)
        catalog = _write(tmp_path, record, audio)
    elif mutate == "tone_class":
        for audio_class in ("sine_wave", "tone", "noise", "silence"):
            with pytest.raises(ValidationError):
                SpeechEvidenceRecord.model_validate(_record(audio_class=audio_class))
        record["audio_class"] = "sine_wave"
        catalog = _write(tmp_path, record, audio)
    elif mutate == "en_gb":
        locale = "en-GB"
        parsed = SpeechEvidenceRecord.model_validate(record)
        assert _identity(parsed, locale="en-GB") is False
        assert bound_speech_record("en-GB", evidence_root=tmp_path, catalog_path=catalog) is None
        assert provider_for("en-GB").live_status != "verified_live"
    elif mutate == "ja_from_fr":
        record["locale"] = "fr-FR"
        record["model_id"] = "jonatasgrosman/wav2vec2-large-xlsr-53-french"
        record["checkpoint_sha256"] = "d" * 64
        catalog = _write(tmp_path, record, audio)
        locale = "ja"
        parsed = SpeechEvidenceRecord.model_validate(record)
        assert _identity(parsed, locale="ja") is False
        assert bound_speech_record("ja", evidence_root=tmp_path, catalog_path=catalog) is None
    elif mutate == "forged_manifest":
        packaged = load_speech_catalog()
        assert packaged is not None
        original = next(item for item in packaged.records if item.locale == "en-US")
        record = original.model_dump()
        record["audio_filename"] = "clip.wav"
        record["audio_sha256"] = hashlib.sha256(audio).hexdigest()
        record["duration_us"] = wav_signature_from(audio)[2]
        record["provenance"] = "Structural WAV fixture. It is not live speech."
        catalog = _write(tmp_path, record, audio)
        assert record["manifest_sha256"] == original.manifest_sha256
        assert bound_speech_record("en-US", evidence_root=tmp_path, catalog_path=catalog) is not None
        monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", str(tmp_path))
        monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_CATALOG", str(catalog))
        assert (
            _grants(
                "en-US",
                root=tmp_path,
                catalog=catalog,
                model_id=original.model_id,
                model_revision=original.model_revision,
                checkpoint_sha256=original.checkpoint_sha256,
                manifest_sha256=original.manifest_sha256,
                whisperx_version=original.whisperx_version,
                device=original.device,
            )
            is False
        )
        assert provider_for("en-US").live_status != "verified_live"
        return
    assert _grants(locale, root=root, catalog=catalog) is False


def test_filename_escape_and_symlink_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.wav"
    outside.write_bytes(_pcm_wav())
    assert resolve_speech_audio(tmp_path, "../outside.wav") is None
    assert resolve_speech_audio(tmp_path, "/tmp/en-speech.wav") is None
    assert resolve_speech_audio(tmp_path, "nested/clip.wav") is None
    link = tmp_path / "link.wav"
    link.symlink_to(outside)
    assert resolve_speech_audio(tmp_path, "link.wav") is None
    with pytest.raises(ValidationError):
        SpeechEvidenceRecord.model_validate(_record(audio_filename="../clip.wav"))
    with pytest.raises(ValidationError):
        SpeechEvidenceRecord.model_validate(_record(audio_filename="nested/clip.wav"))


def test_missing_align_python_does_not_pin_the_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_ALIGN_PYTHON", str(tmp_path / "missing-align-python"))
    assert measured_whisperx_version() == ""
    monkeypatch.delenv("CLIPFORGE_ALIGN_PYTHON", raising=False)
    installed = Path.home() / ".local" / "clipforge-hero-align" / "bin" / "python"
    if installed.is_file():
        assert measured_whisperx_version() == "3.4.5"
    else:
        assert measured_whisperx_version() == ""


def test_symlink_evidence_root_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", str(link))
    assert speech_evidence_root() is None
    assert provider_for("en-US").live_status != "verified_live"


def test_default_evidence_discovery_does_not_grant_live_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / ".local" / "clipforge-speech-evidence"
    assert speech_evidence_root() is None
    root.mkdir(parents=True)
    assert speech_evidence_root() == root
    assert provider_for("en-US").live_status != "verified_live"
    # Arbitrary WAV bytes, even in the discovered directory, are not evidence.
    (root / "en-speech.wav").write_bytes(_pcm_wav())
    assert provider_for("en-US").live_status != "verified_live"


@pytest.mark.parametrize("override", ["missing", "file", "link"])
def test_explicit_invalid_evidence_root_never_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override: str
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    default = tmp_path / ".local" / "clipforge-speech-evidence"
    default.mkdir(parents=True)
    target = tmp_path / override
    if override == "file":
        target.write_text("not a directory", encoding="utf-8")
    elif override == "link":
        target.symlink_to(default, target_is_directory=True)
    monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", str(target))
    assert speech_evidence_root() is None


def test_default_symlink_evidence_root_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    real = tmp_path / "real"
    real.mkdir()
    parent = tmp_path / ".local"
    parent.mkdir()
    (parent / "clipforge-speech-evidence").symlink_to(real, target_is_directory=True)
    assert speech_evidence_root() is None


def test_wav_metadata_mismatch_stays_unbound(tmp_path: Path) -> None:
    """Structural WAV facts must match the bytes. This fixture is not live speech."""
    audio = _pcm_wav()
    matching = _record()
    catalog = _write(tmp_path, matching, audio)
    assert bound_speech_record("en-US", evidence_root=tmp_path, catalog_path=catalog) is not None
    mismatched = _record(duration_us=int(matching["duration_us"]) + 1)
    bad = _write(tmp_path, mismatched, audio)
    assert bound_speech_record("en-US", evidence_root=tmp_path, catalog_path=bad) is None
    rate = _record(sample_rate=16000)
    rate_catalog = _write(tmp_path, rate, audio)
    assert bound_speech_record("en-US", evidence_root=tmp_path, catalog_path=rate_catalog) is None
    channels = _record(channels=2)
    channel_catalog = _write(tmp_path, channels, audio)
    assert bound_speech_record("en-US", evidence_root=tmp_path, catalog_path=channel_catalog) is None


def test_real_espeak_files_match_the_catalog_when_the_root_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live status follows the external bytes. A missing file leaves the locale non-live."""
    installed = Path.home() / ".local" / "clipforge-speech-evidence"
    catalog = load_speech_catalog()
    assert catalog is not None
    if installed.is_dir() and not installed.is_symlink():
        monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", str(installed))
    if not installed.is_dir():
        assert provider_for("en-US").live_status != "verified_live"
        assert provider_for("fr-FR").live_status != "verified_live"
        assert provider_for("ja").live_status != "verified_live"
        return
    for locale, (name, digest) in _REAL.items():
        audio = installed / name
        if not audio.is_file() or audio.is_symlink():
            assert provider_for(locale).live_status != "verified_live"
            continue
        measured = hashlib.sha256(audio.read_bytes()).hexdigest()
        assert measured == digest
        signature = wav_signature(audio)
        assert signature is not None
        record = next(item for item in catalog.records if item.locale == locale)
        assert record.audio_sha256 == measured
        assert (signature[0], signature[1], signature[2]) == (
            record.sample_rate,
            record.channels,
            record.duration_us,
        )
        assert record.token_count >= 3
        assert record.transcript
        assert measured_whisperx_version() == record.whisperx_version
        assert provider_for(locale).live_status == "verified_live"
    assert provider_for("en-GB").live_status == "available_not_smoked"
    assert provider_for("es-ES").live_status == "model_missing"
    assert provider_for("de-DE").live_status == "model_missing"
    assert provider_for("ar").live_status == "alignment_not_claimed"
    assert provider_for("zh-CN").live_status == "unsupported_language"
    assert SpeechEvidenceCatalog.model_validate_json(
        (Path(__file__).parents[1] / "src/clipforge/language/speech_evidence.json").read_text(encoding="utf-8")
    )
