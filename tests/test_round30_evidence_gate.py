"""Stored alignments stay live only while the current speech file and model match."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from clipforge.campaign.production import run_campaign, verify_campaign_run
from clipforge.campaign.providers import CampaignError
from clipforge.language.evidence import validate_current_alignment_evidence
from clipforge.language.model_manifest import (
    packaged_speech_catalog_path,
    sha256_file,
    speech_evidence_root,
)
from tests.test_round20_campaign import _world


def test_removed_speech_root_invalidates_campaign_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = speech_evidence_root()
    if root is None:
        pytest.skip("external speech evidence is not configured")
    world = _world(tmp_path)
    first = run_campaign(world.database, world.work)
    assert first.status == "succeeded"
    package = world.work / "deliveries" / "delivery-before" / "manifest.json"
    before = package.read_bytes()
    monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", str(tmp_path / "missing-evidence"))
    with pytest.raises(CampaignError) as blocked:
        verify_campaign_run(world.database, world.work, first.campaign_run_id)
    assert blocked.value.code == "speech_evidence_missing"
    assert package.read_bytes() == before
    again = run_campaign(world.database, world.work, force=True)
    assert again.status == "blocked"
    assert package.read_bytes() == before
    monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", str(root))
    restored = run_campaign(world.database, world.work, force=True)
    assert restored.status == "succeeded"
    assert verify_campaign_run(world.database, world.work, restored.campaign_run_id).startswith("PASS")


def test_changed_speech_bytes_are_not_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = speech_evidence_root()
    if root is None:
        pytest.skip("external speech evidence is not configured")
    path = _english_alignment(tmp_path / "align")
    copied = tmp_path / "speech"
    shutil.copytree(root, copied)
    target = copied / "en-speech.wav"
    payload = bytearray(target.read_bytes())
    payload[-1] ^= 0x01
    target.write_bytes(payload)
    monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", str(copied))
    changed = validate_current_alignment_evidence(path, source_sha256="")
    assert changed.status == "speech_evidence_changed"
    monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", str(root))
    restored = validate_current_alignment_evidence(path, source_sha256="")
    assert restored.status == "verified_live"


def test_catalog_duration_change_is_not_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _english_alignment(tmp_path / "align")
    catalog = packaged_speech_catalog_path()
    text = catalog.read_text(encoding="utf-8").replace('"duration_us": 1685260', '"duration_us": 1685261', 1)
    forged = tmp_path / "speech_evidence.json"
    forged.write_text(text, encoding="utf-8")
    monkeypatch.setattr("clipforge.language.model_manifest.packaged_speech_catalog_path", lambda: forged)
    evidence = validate_current_alignment_evidence(path, source_sha256="")
    assert evidence.status == "speech_evidence_changed"


def _english_alignment(directory: Path) -> Path:
    world = _world(directory)
    path = (
        world.work
        / "projects"
        / "project-1"
        / "sources"
        / "asset-before"
        / "hero"
        / "alignments"
        / "candidate-before"
        / "alignment.json"
    )
    assert path.is_file()
    assert validate_current_alignment_evidence(path, source_sha256="").status == "verified_live"
    return path


def test_identity_mutations_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _english_alignment(tmp_path / "align")
    original = path.read_bytes()
    cases = {
        "locale": {"locale": "ja", "normalized_language": "ja"},
        "transcript": {"transcript_sha256": "ab" * 32},
        "asr": {"asr_audio_sha256": "cd" * 32},
        "time_map": {"time_map_sha256": "ef" * 32},
        "revision": {"model_revision": "not-the-measured-revision"},
        "whisperx": {"whisperx_version": "9.9.9"},
    }
    for name, update in cases.items():
        payload = json.loads(original)
        payload.update(update)
        path.write_text(json.dumps(payload), encoding="utf-8")
        evidence = validate_current_alignment_evidence(path, source_sha256="")
        assert evidence.status != "verified_live", name
        assert evidence.blocker in {
            "stale_alignment",
            "speech_evidence_missing",
            "speech_evidence_changed",
            "model_missing",
            "alignment_not_claimed",
            "unsupported_language",
        }
    path.write_bytes(original)
    assert validate_current_alignment_evidence(path, source_sha256="").status == "verified_live"
    monkeypatch.setattr(
        "clipforge.language.model_manifest.measured_whisperx_version",
        lambda: "9.9.9",
    )
    assert validate_current_alignment_evidence(path, source_sha256="").status == "stale_alignment"


def test_alignment_digest_covers_the_speech_hash() -> None:
    root = speech_evidence_root()
    if root is None:
        pytest.skip("external speech evidence is not configured")
    audio = root / "en-speech.wav"
    digest = hashlib.sha256(audio.read_bytes()).hexdigest()
    assert digest == sha256_file(audio)
