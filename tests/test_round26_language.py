"""Round 26: truthful multilingual alignment and narration capability."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from clipforge.campaign.board import open_campaign_board, static_bundle_text
from clipforge.cli.main import app
from clipforge.language.captions import wrap_caption
from clipforge.language.registry import (
    ENGLISH_ALIGNMENT_CHECKPOINT,
    ENGLISH_ALIGNMENT_MODEL,
    ENGLISH_ALIGNMENT_REVISION,
    ENGLISH_NARRATION_ENGINE,
    ENGLISH_NARRATION_LICENSE,
    ENGLISH_NARRATION_MODEL,
    ENGLISH_NARRATION_REVISION,
    ENGLISH_NARRATION_VOICE,
    alignment_claim,
    capability_for,
)
from clipforge.language.service import (
    FakeLanguageAligner,
    LanguageError,
    UnavailableAligner,
    WhisperXFullSourceAligner,
    align_language,
    assert_narration_request,
    bind_verified_alignment,
    doctor_text,
    narrate_language,
    verify_alignment,
    verify_narration,
)
from clipforge.schemas.multilingual import MultilingualAlignedWord
from clipforge.schemas.project import Project
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import Database, insert_project
from tests.helpers import stamp

runner = CliRunner()
_A = "a" * 64
_B = "b" * 64
_C = "c" * 64


def test_capability_matrix_stays_truthful() -> None:
    text = doctor_text()
    assert "whop_live: not_configured" in text
    assert "publishing: deferred" in text
    assert "full_source_runtime: not_configured" in text
    assert "en-US alignment: whisperx evidence: verified_live" in text
    assert "ar alignment: alignment_not_claimed" in text
    assert "ja alignment: whisperx evidence: verified_live" in text
    assert "fr-FR alignment: whisperx evidence: verified_live" in text
    assert "zh-CN: unsupported_language" in text
    assert capability_for("en-GB").narration_reason == "locale_not_smoked"
    assert alignment_claim("ar") == "alignment_not_claimed"
    assert wrap_caption("あい。", language="ja", width=2) == ["あい。"]
    assert "".join(wrap_caption("説明です", language="ja", width=2)) == "説明です"


def test_fake_alignment_is_not_live_and_cache_invalidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, work = _db(tmp_path)
    first = _align(work, database, language="ar", source_sha=_A, transcript_sha=_B, words=_arabic())
    assert first.alignment_status == "available_not_smoked"
    assert first.alignment_status != "verified_live"
    assert first.words[0].text == "مرحبا"
    assert first.provider_id == "fake"
    jobs = _job_count(database)
    again = _align(work, database, language="ar", source_sha=_A, transcript_sha=_B, words=_arabic())
    assert again.alignment_id == first.alignment_id
    assert again.cache_status == "hit"
    assert _job_count(database) == jobs
    changed = _align(work, database, language="ar", source_sha=_C, transcript_sha=_B, words=_arabic())
    assert changed.alignment_id != first.alignment_id
    transcript_changed = _align(
        work, database, language="ja", source_sha=_A, transcript_sha=_C, words=_japanese()
    )
    assert transcript_changed.words[0].text == "説明12"
    assert transcript_changed.alignment_status == "available_not_smoked"
    before = _tree(work, database.path)
    assert "available_not_smoked" in verify_alignment(work, database, first.alignment_id)
    assert _tree(work, database.path) == before
    artifact = work / first.relative_path
    artifact.write_bytes(artifact.read_bytes() + b" ")
    with pytest.raises(LanguageError) as corrupt:
        verify_alignment(work, database, first.alignment_id)
    assert corrupt.value.code == "corrupt_alignment"
    artifact.write_bytes(hashlib.sha256(b"restore").digest())
    # The restored bytes are not the original artifact. Put the original back via the manifest hash check.
    with pytest.raises(LanguageError):
        verify_alignment(work, database, first.alignment_id, source_sha256=_C)
    monkeypatch.setattr("clipforge.language.service.language_capability_fingerprint", lambda: "d" * 64)
    with pytest.raises(LanguageError) as stale:
        verify_alignment(work, database, transcript_changed.alignment_id)
    assert stale.value.code == "stale_profile"
    with pytest.raises(LanguageError) as unbound:
        bind_verified_alignment(first)
    assert unbound.value.code == "alignment_not_claimed"


def test_alignment_failures_happen_before_a_job(tmp_path: Path) -> None:
    database, work = _db(tmp_path)
    with pytest.raises(LanguageError) as missing:
        _align(work, database, language="en-US", provider=UnavailableAligner())
    assert missing.value.code == "not_configured"
    with pytest.raises(LanguageError) as unsupported:
        _align(work, database, language="zh-CN")
    assert unsupported.value.code == "unsupported_language"
    with pytest.raises(LanguageError) as french:
        _align(work, database, language="fr-FR", provider=WhisperXFullSourceAligner())
    assert french.value.code == "not_configured"
    with pytest.raises(LanguageError) as runtime:
        _align(work, database, language="en-US", provider=WhisperXFullSourceAligner())
    assert runtime.value.code == "not_configured"
    assert _job_count(database) == 0
    assert not (work / "languages").exists()
    with pytest.raises(LanguageError):
        _align(work, database, language="ar", words=[("w1", "<b>مرحبا</b>")])
    with pytest.raises(LanguageError):
        _align(work, database, language="ar", words=[("w1", "bearer secret")])
    with pytest.raises(ValidationError):
        MultilingualAlignedWord(
            word_id="w1",
            text="مرحبا",
            source_start_us=0,
            source_end_us=0,
            output_start_us=0,
            output_end_us=1,
            output_start_frame=0,
            output_end_frame_exclusive=1,
            source_asset_id="source-1",
            transcript_id="transcript-1",
        )


def test_recorded_english_alignment_can_bind_and_fakes_cannot(tmp_path: Path) -> None:
    database, work = _db(tmp_path)
    fake = _align(work, database, language="en-US", provider=FakeLanguageAligner("en-US"))
    assert fake.alignment_status == "available_not_smoked"
    recorded = fake.model_copy(
        update={
            "provider_id": "whisperx",
            "provider_version": ENGLISH_ALIGNMENT_REVISION,
            "model_id": ENGLISH_ALIGNMENT_MODEL,
            "model_revision": ENGLISH_ALIGNMENT_REVISION,
            "checkpoint_sha256": ENGLISH_ALIGNMENT_CHECKPOINT,
            "runtime_version": ENGLISH_ALIGNMENT_REVISION,
            "alignment_status": "verified_live",
            "timing_quality": "forced",
        }
    )
    binding = bind_verified_alignment(recorded)
    assert binding["alignment_id"] == fake.alignment_id
    assert binding["language"] == "en-US"
    revised = recorded.model_copy(update={"model_revision": "9.9.9", "checkpoint_sha256": _C})
    with pytest.raises(LanguageError):
        bind_verified_alignment(revised)


def test_narration_capability_and_cache(tmp_path: Path) -> None:
    database, work = _db(tmp_path)
    assert assert_narration_request("en-US", False) == "narration_not_requested"
    assert assert_narration_request("en-US", True) == "verified_live"
    with pytest.raises(LanguageError) as arabic:
        assert_narration_request("ar", True)
    assert arabic.value.code == "unsupported_language"
    with pytest.raises(LanguageError) as british:
        assert_narration_request("en-GB", True)
    assert british.value.code == "locale_not_smoked"
    with pytest.raises(LanguageError) as blocked:
        _narrate(work, database, model_id="k2-fsa/icefall")
    assert blocked.value.code == "license_not_permitted"
    assert _job_count(database) == 0
    fake = _narrate(work, database, provider_id="fake")
    assert fake.status == "available_not_smoked"
    live = _narrate(work, database, provider_id="voicestudio", script="Café costs $12.50 today.")
    assert live.status == "verified_live"
    jobs = _job_count(database)
    hit = _narrate(work, database, provider_id="voicestudio", script="Café costs $12.50 today.")
    assert hit.narration_id == live.narration_id
    assert hit.cache_status == "hit"
    assert _job_count(database) == jobs
    changed = _narrate(work, database, provider_id="voicestudio", script="A different script.")
    assert changed.narration_id != live.narration_id
    before = _tree(work, database.path)
    assert verify_narration(work, live.narration_id, script_sha256=live.script_sha256).startswith("PASS")
    assert _tree(work, database.path) == before
    with pytest.raises(LanguageError) as stale:
        verify_narration(work, live.narration_id, script_sha256=_C)
    assert stale.value.code == "stale_script"


def test_board_and_cli_expose_language_facts(tmp_path: Path) -> None:
    database, work = _db(tmp_path)
    document = _align(work, database, language="ar")
    doctor = runner.invoke(app, ["language", "doctor"])
    assert doctor.exit_code == 0
    assert "alignment_not_claimed" in doctor.stdout
    assert "whop_live: not_configured" in doctor.stdout
    listed = runner.invoke(app, ["voice", "languages"])
    assert listed.exit_code == 0
    assert "verified_live" in listed.stdout
    assert "locale_not_smoked" in listed.stdout
    script = Path("src/clipforge/campaign/board_static/app.js").read_text(encoding="utf-8")
    plate = Path("apps/renderer/src/captions/CaptionPlate.tsx").read_text(encoding="utf-8")
    assert "innerHTML" not in script
    assert "eval(" not in script
    assert "https://" not in script
    assert "innerHTML" not in plate
    assert static_bundle_text() == "PASS campaign board"
    server = open_campaign_board(work_root=work, port=0, database=database)
    import threading
    import urllib.request

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = int(server.server_address[1])
        languages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/languages").read())
        alignments = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sources/source-1/alignments").read()
        )
        narration = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sources/source-1/narration").read()
        )
        body = json.dumps({"languages": languages, "alignments": alignments, "narration": narration})
        assert languages["whop_live"] == "not_configured"
        arabic = next(row for row in languages["languages"] if row["language"] == "ar")
        assert arabic["alignment_status"] == "alignment_not_claimed"
        assert alignments["alignments"][0]["alignment_id"] == document.alignment_id
        assert narration["narrations"] == []
        assert "/home/" not in body
        assert "file:" not in body
    finally:
        server.shutdown()
        server.server_close()


def _align(
    work: Path,
    database: Database,
    *,
    language: str = "ar",
    source_sha: str = _A,
    transcript_sha: str = _B,
    words: list[tuple[str, str]] | None = None,
    provider: object | None = None,
):
    try:
        return align_language(
            work,
            database,
            "source-1",
            project_id="project-1",
            language=language,
            transcript_id="transcript-1",
            transcript_sha256=transcript_sha,
            source_sha256=source_sha,
            words=_arabic() if words is None else words,
            duration_us=1_000_000,
            provider=provider if provider is not None else FakeLanguageAligner(language),
        )
    except ValidationError as exc:
        raise LanguageError("alignment was rejected", code="invalid_document") from exc


def _narrate(
    work: Path,
    database: Database,
    *,
    provider_id: str = "voicestudio",
    script: str = "Hello",
    model_id: str | None = None,
):
    return narrate_language(
        work,
        database,
        project_id="project-1",
        source_id="source-1",
        language="en-US",
        script_text=script,
        provider_id=provider_id,
        engine_id=ENGLISH_NARRATION_ENGINE,
        model_id=model_id or ENGLISH_NARRATION_MODEL,
        model_revision=ENGLISH_NARRATION_REVISION,
        voice_id=ENGLISH_NARRATION_VOICE,
        license_name=ENGLISH_NARRATION_LICENSE,
        commercial_use="allowed",
        sample_rate=24000,
        channels=1,
        duration_us=1_000_000,
        audio_sha256=_B,
    )


def _arabic() -> list[tuple[str, str]]:
    return [("w1", "مرحبا"), ("w2", "12")]


def _japanese() -> list[tuple[str, str]]:
    return [("w1", "説明12"), ("w2", "です")]


def _db(tmp_path: Path) -> tuple[Database, Path]:
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    work = tmp_path / "work"
    work.mkdir()
    with database.transaction() as connection:
        insert_project(
            connection,
            Project(
                project_id="project-1",
                name="Studio",
                created_at=stamp(),
                provenance=ArtifactProvenance(
                    created_at=stamp(),
                    created_by="tester",
                    tool="pytest",
                    tool_version="0.1.0",
                    source_asset_ids=[],
                ),
            ),
        )
    return database, work


def _job_count(database: Database) -> int:
    with database.connect() as connection:
        row = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()
    assert row is not None
    return int(row[0])


def _tree(work: Path, database: Path) -> tuple[int, int]:
    total = 0
    for path in work.rglob("*"):
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total, database.stat().st_size
