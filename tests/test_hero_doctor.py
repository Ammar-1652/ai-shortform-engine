"""Hero doctor explains the optional alignment runtime and evidence gate."""

from __future__ import annotations

from pathlib import Path

from clipforge.hero.doctor import hero_doctor


def test_hero_doctor_explains_missing_speech_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", str(tmp_path / "missing"))
    lines = hero_doctor(tmp_path)
    evidence = next(item for item in lines if item.name == "speech_evidence")
    assert evidence.status == "WARN"
    assert "CLIPFORGE_SPEECH_EVIDENCE_ROOT" in evidence.detail
