"""Readiness records and optional narration. The live voice engine is not required."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.benchmark.server import static_bundle_text
from clipforge.benchmark.service import BenchmarkError, readiness_report, run_benchmark, verify_run
from clipforge.schemas.benchmark import BenchmarkRun, BenchmarkStage, V1ReadinessReport
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.ingest import SourceIngestManifest
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import SourceAsset
from clipforge.schemas.project import Project
from clipforge.schemas.registry import CONTRACT_MODELS
from clipforge.schemas.voice import NarrationRequest, VoiceProviderProfile
from clipforge.storage import (
    Database,
    insert_artifact,
    insert_asset_license_record,
    insert_job,
    insert_project,
    insert_review,
    insert_source_asset,
    insert_source_manifest,
)
from clipforge.voice.audio import probe_file, wav_bytes
from clipforge.voice.provider import FakeVoiceProvider, VoiceStudioProvider
from clipforge.voice.service import VoiceError, generate_narration, verify_narration
from tests.helpers import license_record, provenance, stamp
from tests.test_media_unit import _probe

pytestmark = [pytest.mark.benchmark, pytest.mark.filterwarnings("ignore::DeprecationWarning")]
ROOT = Path(__file__).resolve().parents[1]
_KINDS = (
    "transcript_json",
    "visual_analysis_json",
    "candidate_set_json",
    "rough_preview_set_json",
    "alignment_json",
    "hero_plan_json",
    "hero_draft_set_json",
    "advanced_hero_plan_json",
    "advanced_hero_draft_set_json",
    "qa_set_json",
)


def test_benchmark_schemas_are_exported() -> None:
    for model in (BenchmarkRun, BenchmarkStage, V1ReadinessReport, NarrationRequest, VoiceProviderProfile):
        assert model in CONTRACT_MODELS
    schema_path = ROOT / "schemas" / "generated" / "BenchmarkRun.schema.json"
    generated = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "benchmark_run_id" in generated["properties"]
    assert not (ROOT / "vendor" / "VoiceStudio").exists()


def test_full_synthetic_chain_is_deterministic_and_blocks_delivery(tmp_path: Path) -> None:
    database, work = _chain(tmp_path)
    first = run_benchmark(database, work, "source-1", fixture_kind="deterministic_synthetic", created_by="ada")
    assert [stage.stage for stage in first.stages] == [
        "campaign_discovery",
        "policy_snapshot",
        "source_inventory",
        "source_acquisition",
        "language_profile",
        "ingest",
        "media_prepare",
        "transcript",
        "visual_analysis",
        "candidate_mining",
        "rough_preview",
        "candidate_review",
        "alignment",
        "hero_plan",
        "hero_render",
        "advanced_plan",
        "optional_voice_narration",
        "advanced_render",
        "qa",
        "hero_review",
        "analytics",
        "local_delivery",
        "platform_dry_run",
        "platform_submit",
    ]
    assert first.fixture_kind == "deterministic_synthetic"
    assert first.readiness == "blocked"
    assert first.selected_count == 1
    assert first.qa_result == "passed"
    assert "candidate_review" in first.cache_hits
    analytics = next(stage for stage in first.stages if stage.stage == "analytics")
    assert analytics.status == "passed"
    assert analytics.error_category == "synthetic_fixture"
    publish = next(stage for stage in first.stages if stage.stage == "local_delivery")
    assert publish.status == "blocked"
    assert "/tmp/" not in first.model_dump_json()
    assert "://" not in first.model_dump_json()
    again = run_benchmark(database, work, "source-1", fixture_kind="deterministic_synthetic", created_by="ada")
    assert again.benchmark_run_id == first.benchmark_run_id
    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM artifacts WHERE kind = 'v1_benchmark_run_json'"
        ).fetchone()
        assert count is not None and count[0] == 1
    report = readiness_report(database, work, first.benchmark_run_id)
    assert report.technical == "passed"
    assert report.editorial == "passed"
    assert report.qa == "passed"
    assert report.local_delivery == "blocked"
    assert report.platform_publishing == "not_implemented"
    assert report.real_source_verified == "unavailable"
    assert report.real_source_reason == "no authorized source supplied"
    assert report.voicestudio == "unavailable"
    assert report.overall == "blocked"
    assert "External platform publishing is not implemented" in " ".join(report.blocking_limitations)
    assert "PASS benchmark" in verify_run(database, work, first.benchmark_run_id)


def test_missing_approval_and_failed_qa_block(tmp_path: Path) -> None:
    database, work = _chain(tmp_path, hero_review=False)
    blocked = run_benchmark(database, work, "source-1", fixture_kind="deterministic_synthetic")
    assert blocked.readiness == "blocked"
    assert any(stage.stage == "hero_review" and stage.status == "blocked" for stage in blocked.stages)
    assert any("Hero" in item for item in blocked.manual_actions)
    qa = work / "qa.json"
    qa.write_text(json.dumps({"status": "fail"}), encoding="utf-8")
    forced = run_benchmark(database, work, "source-1", fixture_kind="deterministic_synthetic", force=True)
    assert any(stage.stage == "qa" and stage.status == "failed" for stage in forced.stages)


def test_sidecar_failure_leaves_no_current_benchmark(tmp_path: Path) -> None:
    database, work = _chain(tmp_path, hero_review=False)

    def fail() -> None:
        raise RuntimeError("sidecar failed")

    with pytest.raises(BenchmarkError, match="sidecar"):
        run_benchmark(
            database,
            work,
            "source-1",
            fixture_kind="deterministic_synthetic",
            sidecar_hook=fail,
        )
    assert not (work / "benchmarks" / "source-1" / "current.json").exists()
    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM artifacts WHERE kind = 'v1_benchmark_run_json'"
        ).fetchone()
        assert count is not None and count[0] == 0


def test_verify_is_read_only_and_symlink_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, work = _chain(tmp_path)
    document = run_benchmark(database, work, "source-1", fixture_kind="deterministic_synthetic")
    before = database.path.read_bytes()

    def forbid(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("read-only command opened a write transaction")

    monkeypatch.setattr(database, "transaction", forbid)
    verify_run(database, work, document.benchmark_run_id)
    readiness_report(database, work, document.benchmark_run_id)
    monkeypatch.undo()
    assert database.path.read_bytes() == before
    real = work / "benchmarks"
    moved = tmp_path / "moved-benchmarks"
    real.rename(moved)
    real.symlink_to(moved, target_is_directory=True)
    with pytest.raises(BenchmarkError, match="symlink"):
        run_benchmark(database, work, "source-1", fixture_kind="deterministic_synthetic", force=True)


def test_fake_narration_cache_rights_and_ffprobe(tmp_path: Path) -> None:
    database, work = _chain(tmp_path, evidence=False)
    provider = FakeVoiceProvider()
    request = _narration("Café 説明 $12.50")
    first = generate_narration(database, work, request, provider)
    assert provider.calls == 1
    assert first.script_sha256 == request.script_sha256
    second = generate_narration(database, work, request, provider)
    assert provider.calls == 1
    assert second.artifact_id == first.artifact_id
    audio = work / "voice" / "audio" / f"{first.artifact_id}.wav"
    rate, channels, duration_us, codec = probe_file(audio)
    assert (rate, channels, codec) == (16000, 1, "pcm_s16le")
    assert abs(duration_us - 1_000_000) <= 1_000
    assert "PASS narration" in verify_narration(database, work, first.artifact_id)
    audio.write_bytes(audio.read_bytes() + b"\x00")
    with pytest.raises(VoiceError, match="hash"):
        verify_narration(database, work, first.artifact_id)
    with pytest.raises(ValidationError, match="commercial"):
        _narration("hello", model_license="cc_by_nc")
    with pytest.raises(ValidationError, match="fail closed"):
        _narration("hello", commercial_use="unknown")
    with pytest.raises(ValidationError, match="markup"):
        _narration("<b>no</b>")
    with pytest.raises(ValidationError):
        _narration("see https://example.test/secret")
    linked = work / "voice" / "audio" / "linked.wav"
    linked.write_bytes(wav_bytes(1_000_000, 16000, 1))
    audio.unlink()
    audio.symlink_to(linked)
    with pytest.raises(VoiceError, match=r"symlink|missing|hash"):
        verify_narration(database, work, first.artifact_id)


def test_voicestudio_stays_disabled_and_rejects_remote_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network opened")

    monkeypatch.setattr("http.client.HTTPConnection", explode)
    monkeypatch.setattr("http.client.HTTPSConnection", explode)
    disabled = VoiceStudioProvider(enabled=False)
    assert "disabled" in disabled.doctor()
    assert disabled.capabilities()["network"] == "none"
    request = _narration("Café")
    with pytest.raises(VoiceError, match="disabled"):
        disabled.generate(request)
    with pytest.raises(VoiceError, match="loopback"):
        VoiceStudioProvider(url="http://example.test:3900", enabled=True).doctor()
    with pytest.raises(VoiceError, match="loopback"):
        VoiceStudioProvider(url="http://192.168.1.20:3900", enabled=True).doctor()
    secure = VoiceStudioProvider(url="https://voice.example.test", enabled=True, allow_remote=False)
    with pytest.raises(VoiceError, match="loopback"):
        secure.doctor()
    VoiceStudioProvider(url="https://voice.example.test", enabled=True, allow_remote=True)._require_endpoint()


def test_provider_timeout_and_malformed_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = VoiceStudioProvider(enabled=True, timeout_s=1)

    class Broken:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def request(self, *args: object, **kwargs: object) -> None:
            raise TimeoutError("too slow")

        def close(self) -> None:
            return None

    monkeypatch.setattr("http.client.HTTPConnection", Broken)
    with pytest.raises(VoiceError, match="timed out"):
        provider.doctor()
    fake = FakeVoiceProvider()
    with pytest.raises(VoiceError, match=r"empty|WAV"):
        fake.verify_audio(b"")
    with pytest.raises(VoiceError, match="WAV"):
        fake.verify_audio(b"not-audio")


def test_live_voicestudio_smoke_is_optional() -> None:
    if os.environ.get("CLIPFORGE_VOICESTUDIO_LIVE_SMOKE") != "1":
        pytest.skip("VoiceStudio live smoke: unavailable")
    provider = VoiceStudioProvider(
        url=os.environ.get("CLIPFORGE_VOICESTUDIO_URL", "http://127.0.0.1:3900"),
        enabled=True,
    )
    assert "answered" in provider.doctor()


def test_static_page_has_no_remote_execution() -> None:
    assert "PASS benchmark page" in static_bundle_text()
    page = (ROOT / "src" / "clipforge" / "benchmark" / "static" / "app.js").read_text(encoding="utf-8")
    assert "eval(" not in page
    assert "innerHTML" not in page
    assert "http://" not in page


def _chain(tmp_path: Path, *, hero_review: bool = True, evidence: bool = True) -> tuple[Database, Path]:
    work = tmp_path / "work"
    work.mkdir()
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    now = datetime.now(UTC)
    media = work / "source.bin"
    media.write_bytes(b"source-bytes")
    evidence_path = work / "evidence.json"
    evidence_path.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    project = Project(project_id="project-1", name="Bench", created_at=now, provenance=provenance())
    source = SourceAsset(
        source_asset_id="source-1",
        project_id="project-1",
        uri=media.resolve().as_uri(),
        license_record_id="lic-1",
        provenance=provenance(["source-1"]),
    )
    stat = media.stat()
    manifest = SourceIngestManifest(
        source_asset_id="source-1",
        project_id="project-1",
        content_sha256="11" * 32,
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        original_filename=media.name,
        transcription_eligible=False,
        video_stream_index=0,
        audio_stream_index=None,
        canonical_duration_us=2_000_000,
        video_origin_us=0,
        ingested_at=now,
        probe=_probe(),
    )
    job = JobRecord(
        job_id="job-1",
        project_id="project-1",
        kind="media_prepare",
        status=JobStatus.SUCCEEDED,
        created_at=now,
        updated_at=now,
        payload={"source_asset_id": "source-1"},
    )
    with database.transaction() as connection:
        insert_project(connection, project)
        insert_asset_license_record(connection, license_record(asset_id="source-1"))
        insert_source_asset(connection, source)
        insert_source_manifest(connection, manifest)
        insert_job(connection, job)
        if evidence:
            qa_path = work / "qa.json"
            qa_path.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
            for index, kind in enumerate(_KINDS, start=1):
                target = qa_path if kind == "qa_set_json" else evidence_path
                insert_artifact(
                    connection,
                    artifact_id=f"artifact-{index}",
                    project_id="project-1",
                    job_id="job-1",
                    source_asset_id="source-1",
                    kind=kind,
                    uri=target.resolve().as_uri(),
                    provenance=provenance(["source-1"], "job-1"),
                )
            insert_review(connection, _review("review-candidate", "candidate", "cand-1"))
            if hero_review:
                insert_review(connection, _review("review-hero", "hero", "cand-1"))
    return database, work


def _review(review_id: str, subject: str, candidate_id: str) -> ReviewDecision:
    return ReviewDecision(
        review_id=review_id,
        project_id="project-1",
        artifact_id="artifact-1",
        candidate_id=candidate_id,
        subject_kind=subject,  # type: ignore[arg-type]
        decision="approved",
        reviewer_id="ada",
        created_at=stamp(),
        notes="kept",
        automated=False,
    )


def _narration(
    script: str,
    *,
    model_license: str = "allowed",
    commercial_use: str = "allowed",
) -> NarrationRequest:
    digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
    profile = VoiceProviderProfile(
        provider_id="fake",
        provider_version="0",
        engine_id="fake-engine",
        model_id="studio-voice",
        model_revision="rev-1",
        language="en",
        voice_profile_id="voice-1",
        voice_type="preset",
        consent_record_id="consent-1",
        commercial_use=commercial_use,  # type: ignore[arg-type]
        model_license=model_license,  # type: ignore[arg-type]
        license_evidence_id="evidence-1",
        clone_permission=False,
        provenance=provenance(["source-1"]),
    )
    return NarrationRequest(
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="cand-1",
        script_text=script,
        script_sha256=digest,
        language="en",
        provider_id="fake",
        voice_profile_id="voice-1",
        sample_rate=16000,
        channels=1,
        timing_policy="preserve_duration",
        target_duration_us=1_000_000,
        output_use="commercial",
        profile=profile,
        created_by="ada",
        provenance=provenance(["source-1"]),
    )
