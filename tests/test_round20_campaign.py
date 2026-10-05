"""Campaign production runs, language claims, and fail-closed bindings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from clipforge.assets.service import render_block_reason
from clipforge.campaign.antoine import CAMPAIGN_ID, inventory_sources
from clipforge.campaign.production import (
    plan_campaign,
    resume_campaign,
    run_campaign,
    source_may_proceed,
    verify_campaign_run,
)
from clipforge.campaign.providers import CampaignError
from clipforge.campaign.service import doctor_text
from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.hero.alignment import FakeForcedAlignment, production_alignment_backend
from clipforge.language.captions import build_cues, wrap_caption
from clipforge.language.registry import (
    ENGLISH_NARRATION_MODEL,
    ENGLISH_NARRATION_REVISION,
    ENGLISH_NARRATION_SCRIPT,
    ENGLISH_NARRATION_SCRIPT_SHA256,
    ENGLISH_NARRATION_VOICE,
    alignment_claim,
    alignment_identity_matches,
    capability_for,
)
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_to_file_uri
from clipforge.schemas.assets import AssetSearchHit
from clipforge.schemas.campaign_run import CampaignCandidateRecord, CampaignProductionRun
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import SourceAsset
from clipforge.schemas.project import Project
from clipforge.schemas.publish import PublishFile, PublishPackageDocument
from clipforge.schemas.voice import NarrationAudioArtifact
from clipforge.storage import (
    Database,
    insert_artifact,
    insert_asset_license_record,
    insert_job,
    insert_project,
    insert_review,
    insert_source_asset,
)
from tests.helpers import license_record, provenance, stamp

runner = CliRunner()
_KINDS = (
    "analysis_proxy",
    "transcript_json",
    "visual_analysis_json",
    "rough_preview_set_json",
    "hero_draft_set_json",
)


@dataclass
class _Source:
    source_id: str
    asset_id: str
    media: Path
    delivery_id: str
    manifest: Path
    qa: Path
    transcript: Path
    narration_id: str | None
    wav: Path | None


@dataclass
class _World:
    database: Database
    work: Path
    project_id: str
    sources: dict[str, _Source]


def test_allowed_source_does_not_wait_for_confirmation() -> None:
    assert source_may_proceed("allowed")
    assert not source_may_proceed("needs_operator_confirmation")
    assert not source_may_proceed("prohibited")
    assert not source_may_proceed("unknown")
    assert not source_may_proceed("rights_unverified")
    document = plan_campaign()
    assert document.status == "partial"
    assert document.reason_code == "planned"
    assert document.publishing == "deferred"
    assert document.browser_concurrency == 1
    assert [item.rights_state for item in document.sources] == ["allowed", "allowed"]
    assert "needs_operator_confirmation" not in document.model_dump_json()
    assert document.source_ids == ["src-american-secret", "src-before-famous"]


def test_plan_rejects_duplicates_unselected_and_unknown_language(tmp_path: Path) -> None:
    with pytest.raises(CampaignError, match="duplicate") as duplicate:
        plan_campaign(source_ids=["src-before-famous", "src-before-famous"])
    assert duplicate.value.code == "duplicate_source"
    with pytest.raises(CampaignError, match="unselected") as unselected:
        plan_campaign(source_ids=["src-og-cuicide"])
    assert unselected.value.code == "not_selected"
    with pytest.raises(ValueError, match="unsupported_language"):
        plan_campaign(language="zh-CN")
    with pytest.raises(CampaignError, match="catalogue") as missing:
        plan_campaign(campaign_id="missing-campaign")
    assert missing.value.code == "missing_campaign"
    before = list(tmp_path.rglob("*"))
    plan_campaign()
    assert list(tmp_path.rglob("*")) == before


def test_prohibited_rights_fail_before_a_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rows = []
    for item in inventory_sources():
        if item.source_id == "src-before-famous":
            rows.append(item.model_copy(update={"rights_state": "prohibited"}))
        else:
            rows.append(item)
    monkeypatch.setattr("clipforge.campaign.production.inventory_sources", lambda: rows)
    planned = plan_campaign(source_ids=["src-before-famous"])
    assert planned.status == "blocked"
    assert planned.reason_code == "rights_not_allowed"
    assert planned.sources[0].rights_state == "prohibited"
    world = _world(tmp_path)
    with pytest.raises(CampaignError, match="rights") as exc:
        run_campaign(world.database, world.work, source_ids=["src-before-famous"])
    assert exc.value.code == "rights_not_allowed"
    assert list(world.work.glob("campaigns/runs/*/manifest.json")) == []


def test_language_claims_and_unicode_round_trip() -> None:
    english = capability_for("en-US")
    assert english.alignment_evidence == "verified_live"
    assert english.narration_evidence == "verified_live"
    assert alignment_claim("en-US") == "whisperx"
    assert alignment_claim("en-GB") == "whisperx"
    arabic = capability_for("ar")
    japanese = capability_for("ja")
    assert arabic.text_direction == "rtl"
    assert arabic.caption_policy == "rtl_logical_order"
    assert arabic.reason_code == "alignment_not_claimed"
    assert alignment_claim("ar") == "alignment_not_claimed"
    assert alignment_claim("ja") == "alignment_not_claimed"
    assert japanese.caption_policy == "character_wrap"
    assert japanese.narration_reason == "unsupported_language"
    assert capability_for("en-GB").narration_reason == "locale_not_smoked"
    assert not alignment_identity_matches(revision="9.9.9", checkpoint="a" * 64)
    wrapped = wrap_caption("説明です", language="ja", width=2)
    assert wrapped == ["説明", "です"]
    assert "".join(wrapped) == "説明です"
    arabic_line = wrap_caption("مرحبا", language="ar")
    assert arabic_line == ["مرحبا"]
    assert [ord(char) for char in arabic_line[0]] == [ord(char) for char in "مرحبا"]
    for language, text in (
        ("en-US", "Café"),
        ("en-US", "$12.50"),
        ("ja", "説明"),
        ("ar", "مرحبا"),
    ):
        cues = build_cues(text, language=language, duration_us=1_000_000)
        assert cues[0].text == text
        payload = json.dumps({"text": text}, ensure_ascii=False)
        assert json.loads(payload)["text"] == text
    backend = production_alignment_backend("en", allow_model_download=False)
    assert backend.allow_model_download is False
    assert not isinstance(backend, FakeForcedAlignment)
    with pytest.raises(MediaError, match="alignment_not_claimed"):
        production_alignment_backend("ja")
    with pytest.raises(MediaError, match="unsupported_language"):
        production_alignment_backend("zh-CN")
    arabic_plan = plan_campaign(language="ar", narration_enabled=True)
    assert arabic_plan.alignment_provider == "none"
    assert arabic_plan.voice_id is None
    narration = next(item for item in arabic_plan.sources if item.source_id == "src-before-famous")
    align = next(item for item in narration.stages if item.stage == "align")
    assert align.reason_code == "alignment_not_claimed"
    assert next(item for item in narration.stages if item.stage == "narration").reason_code == "planned"


def test_campaign_reuses_verified_stages_and_caches_the_second_run(tmp_path: Path) -> None:
    world = _world(tmp_path)
    calls: list[str] = []

    def probe(language: str, script: str) -> None:
        calls.append(language + script)

    first = run_campaign(world.database, world.work, narration_probe=probe)
    assert first.status == "succeeded"
    assert first.reason_code == "none"
    assert calls == []
    assert first.project_id != "unresolved"
    by_id = {item.source_id: item for item in first.sources}
    narrated = by_id["src-before-famous"]
    quiet = by_id["src-american-secret"]
    assert narrated.narration_artifact_id == "narration-before"
    assert narrated.candidates[0].narration_status == "verified_live"
    assert narrated.candidates[0].review_decision == "approved"
    assert narrated.candidates[0].score == "0.500000"
    assert narrated.candidates[0].source_start_us == 1_000
    assert narrated.cache_status == "hit"
    assert quiet.narration_artifact_id is None
    assert quiet.candidates[0].narration_status == "narration_not_requested"
    assert "file://" not in first.model_dump_json()
    assert "/home/" not in first.model_dump_json()
    assert _job_count(world.database) == 1
    deliveries = {path.parent.name for path in world.work.glob("deliveries/*/manifest.json")}
    again = run_campaign(world.database, world.work, narration_probe=probe)
    assert again.model_dump_json() == first.model_dump_json()
    assert calls == []
    assert _job_count(world.database) == 1
    assert {path.parent.name for path in world.work.glob("deliveries/*/manifest.json")} == deliveries
    forced = run_campaign(world.database, world.work, force=True, narration_probe=probe)
    assert forced.campaign_run_id != first.campaign_run_id
    assert forced.fingerprint == first.fingerprint
    assert _job_count(world.database) == 2
    assert calls == []
    shown_path = world.work / "campaigns" / "runs" / first.campaign_run_id / "manifest.json"
    shown = json.loads(shown_path.read_text(encoding="utf-8"))
    assert shown["campaign_run_id"] == first.campaign_run_id
    assert verify_campaign_run(world.database, world.work, first.campaign_run_id).startswith("PASS")


def test_disabled_narration_skips_the_provider(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False)
    calls: list[str] = []
    document = run_campaign(
        world.database,
        world.work,
        narration_enabled=False,
        narration_probe=lambda _language, _script: calls.append("called"),
    )
    assert document.status == "succeeded"
    assert document.voice_id is None
    assert calls == []
    assert all(item.narration_artifact_id is None for item in document.sources)


def test_one_failed_source_keeps_the_other(tmp_path: Path) -> None:
    world = _world(tmp_path)
    first = run_campaign(world.database, world.work)
    media = world.sources["src-american-secret"].media
    media.write_bytes(b"changed-source-bytes")
    second = run_campaign(world.database, world.work, force=True)
    by_id = {item.source_id: item for item in second.sources}
    assert by_id["src-before-famous"].status == "succeeded"
    assert by_id["src-american-secret"].status == "failed"
    assert by_id["src-american-secret"].reason_code == "source_changed"
    assert second.status == "partial"
    stored_path = world.work / "campaigns" / "runs" / first.campaign_run_id / "manifest.json"
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    assert stored["status"] == "blocked"
    assert stored["reason_code"] == "evidence_changed"


def test_resume_retries_only_the_incomplete_source(tmp_path: Path) -> None:
    world = _world(tmp_path)
    secret_qa = world.sources["src-american-secret"].qa
    original = secret_qa.read_bytes()
    secret_qa.unlink()
    blocked = run_campaign(world.database, world.work)
    assert blocked.status == "partial"
    assert _job_count(world.database) == 1
    secret_qa.write_bytes(original)
    resumed = resume_campaign(world.database, world.work, blocked.campaign_run_id)
    assert resumed.campaign_run_id == blocked.campaign_run_id
    assert resumed.status == "succeeded"
    assert _job_count(world.database) == 1
    run_path = world.work / "campaigns" / "runs" / resumed.campaign_run_id / "manifest.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload["sources"][0]["status"] = "cancelled"
    run_path.write_text(json.dumps(payload), encoding="utf-8")
    recovered = resume_campaign(world.database, world.work, resumed.campaign_run_id)
    assert recovered.status == "succeeded"
    assert recovered.campaign_run_id == resumed.campaign_run_id
    assert _job_count(world.database) == 1
    media = world.sources["src-before-famous"].media
    media.write_bytes(media.read_bytes() + b"-stale")
    stale = resume_campaign(world.database, world.work, recovered.campaign_run_id)
    by_id = {item.source_id: item for item in stale.sources}
    assert by_id["src-before-famous"].reason_code == "source_changed"
    assert by_id["src-american-secret"].status == "succeeded"
    assert stale.campaign_run_id == recovered.campaign_run_id
    assert _job_count(world.database) == 1


def test_narration_failures_and_timeout(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False)
    _write_narration(world, script="Café costs $12.50 tomorrow.", reason_name="script")
    scripted = run_campaign(world.database, world.work, source_ids=["src-before-famous"])
    assert scripted.sources[0].reason_code == "script_changed"
    _remove_narration(world)
    _write_narration(world, voice="expr-voice-2-m")
    voiced = run_campaign(world.database, world.work, source_ids=["src-before-famous"], force=True)
    assert voiced.sources[0].reason_code == "voice_changed"
    _remove_narration(world)
    _write_narration(world, revision="revision-changed")
    revised = run_campaign(world.database, world.work, source_ids=["src-before-famous"], force=True)
    assert revised.sources[0].reason_code == "model_revision_changed"
    _remove_narration(world)
    _write_narration(world, license_state="prohibited")
    licensed = run_campaign(world.database, world.work, source_ids=["src-before-famous"], force=True)
    assert licensed.sources[0].reason_code == "license_blocked"
    _remove_narration(world)
    _write_narration(world, model_id="k2-fsa/OmniVoice")
    blocked_model = run_campaign(world.database, world.work, source_ids=["src-before-famous"], force=True)
    assert blocked_model.sources[0].reason_code == "license_blocked"
    _remove_narration(world)
    _write_narration(world, empty=True)
    empty = run_campaign(world.database, world.work, source_ids=["src-before-famous"], force=True)
    assert empty.sources[0].reason_code == "zero_byte_audio"
    _remove_narration(world)

    def probe(_language: str, _script: str) -> None:
        raise CampaignError("cold start timed out", code="provider_timeout")

    timed = run_campaign(
        world.database,
        world.work,
        source_ids=["src-before-famous"],
        force=True,
        narration_probe=probe,
    )
    assert timed.sources[0].reason_code == "provider_timeout"
    assert timed.status == "blocked"


def test_security_bindings_and_stale_evidence(tmp_path: Path) -> None:
    world = _world(tmp_path)
    document = run_campaign(world.database, world.work)
    source = world.sources["src-before-famous"]
    linked = source.media.with_name("linked.mp4")
    linked.write_bytes(source.media.read_bytes())
    source.media.unlink()
    source.media.symlink_to(linked)
    with pytest.raises(CampaignError) as symlink:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert symlink.value.code == "symlink"
    source.media.unlink()
    source.media.write_bytes(linked.read_bytes())
    _set_uri(world, source.asset_id, "https://example.com/video.mp4")
    with pytest.raises(CampaignError) as remote:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert remote.value.code == "remote_source"
    _set_uri(world, source.asset_id, "file:///tmp/../outside.mp4")
    with pytest.raises(CampaignError) as traversal:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert traversal.value.code == "traversal"
    _set_uri(world, source.asset_id, "file://C:\\outside\\video.mp4")
    with pytest.raises(CampaignError) as slashed:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert slashed.value.code == "traversal"
    _set_uri(world, source.asset_id, path_to_file_uri(source.media))
    source.transcript.write_bytes(b"changed-transcript")
    with pytest.raises(CampaignError) as transcript:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert transcript.value.code == "transcript_changed"
    source.transcript.write_bytes(b"transcript-before")
    _patch_manifest(source.manifest, "alignment_sha256", "b" * 64)
    _refresh_checksum(source.manifest)
    with pytest.raises(CampaignError) as alignment:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert alignment.value.code == "alignment_changed"
    _patch_manifest(source.manifest, "alignment_sha256", "a" * 64)
    _refresh_checksum(source.manifest)
    _patch_manifest(source.manifest, "qa_set_sha256", "c" * 64)
    _refresh_checksum(source.manifest)
    with pytest.raises(CampaignError) as qa:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert qa.value.code == "qa_changed"
    original_qa = sha256_file(source.qa)
    _patch_manifest(source.manifest, "qa_set_sha256", original_qa)
    _refresh_checksum(source.manifest)
    wav = source.wav
    assert wav is not None
    wav.write_bytes(b"different-wav")
    with pytest.raises(CampaignError) as narration:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert narration.value.code == "narration_changed"
    wav.write_bytes(b"narration-before")
    source.manifest.write_bytes(source.manifest.read_bytes() + b"\n")
    with pytest.raises(CampaignError) as delivery:
        verify_campaign_run(world.database, world.work, document.campaign_run_id)
    assert delivery.value.code == "checksum_changed"


def test_documents_reject_paths_secrets_and_unknown_keys() -> None:
    planned = plan_campaign(source_ids=["src-before-famous"])
    body = planned.model_dump(mode="json")
    with pytest.raises(ValidationError):
        CampaignProductionRun.model_validate({**body, "reason_code": "kept /home/secret"})
    with pytest.raises(ValidationError):
        CampaignProductionRun.model_validate({**body, "reason_code": "bearer abc"})
    with pytest.raises(ValidationError):
        CampaignProductionRun.model_validate({**planned.model_dump(mode="json"), "extra": "no"})
    with pytest.raises(ValidationError):
        CampaignProductionRun.model_validate({**body, "campaign_run_id": "bad id"})
    with pytest.raises(ValidationError):
        CampaignCandidateRecord(
            candidate_id="cand-1",
            rank=1,
            selection_reason="<script>",
            alignment_status="whisperx",
            narration_status="verified_live",
            qa_status="pass",
            delivery_status="succeeded",
        )


def test_mixed_project_is_rejected(tmp_path: Path) -> None:
    world = _world(tmp_path, split_projects=True)
    with pytest.raises(CampaignError, match="different projects") as exc:
        run_campaign(world.database, world.work)
    assert exc.value.code == "mixed_project"
    assert list(world.work.glob("campaigns/runs/*/manifest.json")) == []


def test_blocked_envato_hit_cannot_enter_a_render() -> None:
    hit = AssetSearchHit(
        request_id="req-1",
        provider="fake",
        title="City street",
        campaign_policy_decision="blocked",
        rejection_reason="outside_media_prohibited_by_campaign_policy",
        selection_status="rejected",
        download_status="rejected",
        direct_download_url=None,
        created_at=stamp(),
    )
    assert render_block_reason(hit) == "outside_media_prohibited_by_campaign_policy"
    remote = hit.model_copy(
        update={
            "campaign_policy_decision": "allowed",
            "selection_status": "candidate",
            "download_status": "manual_download_required",
            "rejection_reason": None,
            "direct_download_url": "https://example.com/file.mp4",
            "license_evidence": "licensed",
            "sha256": "d" * 64,
        }
    )
    assert render_block_reason(remote) == "remote_url"
    missing = remote.model_copy(update={"direct_download_url": None, "license_evidence": None})
    assert render_block_reason(missing) == "missing_license_evidence"


def test_static_review_bundles_stay_local() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "clipforge"
    folders = [root / "review" / "static", root / "analytics" / "static"]
    combined = []
    for folder in folders:
        assert folder.is_dir()
        for path in sorted(folder.iterdir()):
            if path.is_file():
                combined.append(path.read_text(encoding="utf-8"))
    page = "\n".join(combined)
    for token in ("eval(", "innerHTML", "http://", "https://", "cdn.", "googletagmanager"):
        assert token not in page


def test_cli_plan_is_read_only_and_doctor_mentions_the_matrix() -> None:
    text = doctor_text()
    assert "language_matrix" in text
    assert "alignment_not_claimed" in text
    assert "external_publishing: deferred" in text
    assert "browser_concurrency: 1" in text
    planned = runner.invoke(app, ["campaign", "plan", CAMPAIGN_ID])
    assert planned.exit_code == 0
    assert "needs_operator_confirmation" not in planned.stdout
    help_text = runner.invoke(app, ["campaign", "--help"])
    assert help_text.exit_code == 0
    for name in ("plan", "run", "resume", "verify"):
        assert name in help_text.stdout
    root = runner.invoke(app, ["--help"])
    for absent in ("transcribe", "render", "upload"):
        assert absent not in root.stdout


def _world(tmp_path: Path, *, narrate: bool = True, split_projects: bool = False) -> _World:
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    work = tmp_path / "work"
    work.mkdir()
    media_root = tmp_path / "media"
    media_root.mkdir()
    project_id = "project-1"
    sources: dict[str, _Source] = {}
    with database.transaction() as connection:
        insert_project(connection, _project(project_id))
        if split_projects:
            insert_project(connection, _project("project-2"))
        for index, source_id in enumerate(("src-before-famous", "src-american-secret")):
            project = "project-2" if split_projects and index == 1 else project_id
            sources[source_id] = _insert_source(
                connection,
                work,
                media_root,
                project,
                source_id,
                narrate=narrate and source_id == "src-before-famous",
            )
    return _World(database, work, project_id, sources)


def _project(project_id: str) -> Project:
    return Project(project_id=project_id, name="Campaign", created_at=stamp(), provenance=provenance())


def _insert_source(
    connection,
    work: Path,
    media_root: Path,
    project_id: str,
    source_id: str,
    *,
    narrate: bool,
) -> _Source:
    slug = "before" if source_id.endswith("famous") else "secret"
    asset_id = f"asset-{slug}"
    media = media_root / f"{source_id}.mp4"
    media.write_bytes(f"media-{slug}".encode())
    insert_asset_license_record(connection, license_record(asset_id, f"lic-{slug}"))
    insert_source_asset(
        connection,
        SourceAsset(
            source_asset_id=asset_id,
            project_id=project_id,
            uri=path_to_file_uri(media),
            license_record_id=f"lic-{slug}",
            provenance=provenance([asset_id]),
        ),
    )
    digest = sha256_file(media)
    connection.execute(
        """
        INSERT INTO source_manifests (
            source_asset_id, project_id, content_sha256, size_bytes, mtime_ns, original_filename,
            storage_mode, transcription_eligible, video_stream_index, audio_stream_index,
            canonical_duration_us, video_origin_us, ingested_at, probe_json
        ) VALUES (?, ?, ?, ?, ?, ?, 'referenced', 1, 0, 0, 1000000, 0, ?, '{}')
        """,
        (
            asset_id,
            project_id,
            digest,
            media.stat().st_size,
            media.stat().st_mtime_ns,
            media.name,
            stamp().isoformat(),
        ),
    )
    job_id = f"job-{slug}"
    insert_job(
        connection,
        JobRecord(
            job_id=job_id,
            project_id=project_id,
            kind="fixture",
            status=JobStatus.SUCCEEDED,
            created_at=stamp(),
            updated_at=stamp(),
            payload={},
        ),
    )
    folder = work / "artifacts" / slug
    folder.mkdir(parents=True)
    ids: dict[str, str] = {}
    paths: dict[str, Path] = {}
    for kind in _KINDS:
        artifact_id = f"{kind}-{slug}"
        path = folder / f"{kind}.bin"
        payload = b"transcript-" + slug.encode() if kind == "transcript_json" else kind.encode()
        path.write_bytes(payload)
        _point(connection, project_id, job_id, asset_id, artifact_id, kind, path)
        ids[kind] = artifact_id
        paths[kind] = path
    mine_id = f"mine-{slug}"
    candidate_id = f"candidate-{slug}"
    mine = folder / "candidates.json"
    mine.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "candidate_id": candidate_id,
                        "creative_score": 0.5,
                        "time_map": {"segments": [{"source_start_us": 1000, "source_end_us": 5000}]},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _point(connection, project_id, job_id, asset_id, mine_id, "candidate_set_json", mine)
    advanced_id = f"advanced-{slug}"
    advanced = folder / "advanced.json"
    advanced.write_bytes(b"{}")
    _point(connection, project_id, job_id, asset_id, advanced_id, "advanced_hero_draft_set_json", advanced)
    qa = folder / "qa.json"
    qa.write_bytes(f"qa-{slug}".encode())
    qa_id = f"qa-{slug}"
    _point(connection, project_id, job_id, asset_id, qa_id, "qa_set_json", qa)
    review_id = f"review-{slug}"
    hero_review_id = f"hero-review-{slug}"
    insert_review(
        connection,
        ReviewDecision(
            review_id=review_id,
            project_id=project_id,
            artifact_id=ids["rough_preview_set_json"],
            candidate_id=candidate_id,
            subject_kind="candidate",
            decision="approved",
            reviewer_id="reviewer",
            created_at=stamp(),
            notes="",
        ),
    )
    insert_review(
        connection,
        ReviewDecision(
            review_id=hero_review_id,
            project_id=project_id,
            artifact_id=ids["hero_draft_set_json"],
            candidate_id=candidate_id,
            subject_kind="hero",
            decision="approved",
            reviewer_id="reviewer",
            created_at=stamp(),
            notes="",
        ),
    )
    delivery_id = f"delivery-{slug}"
    manifest = _write_package(
        work,
        delivery_id=delivery_id,
        project_id=project_id,
        asset_id=asset_id,
        candidate_id=candidate_id,
        hero_review_id=hero_review_id,
        qa_hash=sha256_file(qa),
        advanced_id=advanced_id,
        mine_id=mine_id,
        source_sha=digest,
    )
    publish_id = f"publish-{slug}"
    _point(connection, project_id, job_id, asset_id, publish_id, "publish_package_json", manifest)
    narration_id = None
    wav = None
    if narrate:
        narration_id = "narration-before"
        wav = _write_narration_files(connection, work, project_id, job_id, asset_id, narration_id)
    return _Source(
        source_id,
        asset_id,
        media,
        delivery_id,
        manifest,
        qa,
        paths["transcript_json"],
        narration_id,
        wav,
    )


def _write_package(
    work: Path,
    *,
    delivery_id: str,
    project_id: str,
    asset_id: str,
    candidate_id: str,
    hero_review_id: str,
    qa_hash: str,
    advanced_id: str,
    mine_id: str,
    source_sha: str,
) -> Path:
    package = work / "deliveries" / delivery_id
    video_dir = package / "candidates" / candidate_id
    video_dir.mkdir(parents=True)
    video = video_dir / "video.mp4"
    metadata = video_dir / "metadata.json"
    video.write_bytes(b"video-bytes")
    metadata.write_bytes(b'{"title":"clip"}\n')
    files = [
        PublishFile(
            relative_path=f"deliveries/{delivery_id}/candidates/{candidate_id}/video.mp4",
            sha256=sha256_file(video),
            size_bytes=video.stat().st_size,
            role="video",
        ),
        PublishFile(
            relative_path=f"deliveries/{delivery_id}/candidates/{candidate_id}/metadata.json",
            sha256=sha256_file(metadata),
            size_bytes=metadata.stat().st_size,
            role="metadata",
        ),
    ]
    document = PublishPackageDocument(
        delivery_id=delivery_id,
        project_id=project_id,
        source_asset_id=asset_id,
        source_sha256=source_sha,
        candidate_id=candidate_id,
        candidate_rank=1,
        candidate_set_id=mine_id,
        candidate_set_sha256="b" * 64,
        advanced_set_id=f"advanced-set-{delivery_id}",
        advanced_set_sha256="c" * 64,
        advanced_artifact_id=advanced_id,
        advanced_artifact_sha256="d" * 64,
        advanced_artifact_size_bytes=2,
        advanced_plan_id=f"plan-{delivery_id}",
        advanced_plan_sha256="e" * 64,
        alignment_id=f"align-{delivery_id}",
        alignment_sha256="a" * 64,
        qa_set_id=f"qa-doc-{delivery_id}",
        qa_set_sha256=qa_hash,
        approval_review_id=hero_review_id,
        profile_fingerprint="f" * 64,
        caption_mode="embedded_or_unavailable",
        cache_fingerprint="1" * 64,
        files=files,
        created_at=stamp(),
    )
    manifest = package / "manifest.json"
    manifest.write_text(document.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (package / "checksums.sha256").write_text(_checksum_text(package, delivery_id, files), encoding="utf-8")
    return manifest


def _checksum_text(package: Path, delivery_id: str, files: list[PublishFile]) -> str:
    entries = [("manifest.json", sha256_file(package / "manifest.json"))]
    prefix = f"deliveries/{delivery_id}/"
    for item in files:
        relative = item.relative_path[len(prefix) :]
        entries.append((relative, sha256_file(package / relative)))
    return "".join(f"{digest}  {relative}\n" for relative, digest in sorted(entries))


def _point(
    connection,
    project_id: str,
    job_id: str,
    asset_id: str,
    artifact_id: str,
    kind: str,
    path: Path,
) -> None:
    insert_artifact(
        connection,
        artifact_id=artifact_id,
        project_id=project_id,
        job_id=job_id,
        source_asset_id=asset_id,
        kind=kind,
        uri=path_to_file_uri(path),
        provenance=provenance([asset_id], job_id=job_id),
    )


def _write_narration_files(
    connection,
    work: Path,
    project_id: str,
    job_id: str,
    asset_id: str,
    artifact_id: str,
    *,
    script: str = ENGLISH_NARRATION_SCRIPT,
    voice: str = ENGLISH_NARRATION_VOICE,
    revision: str = ENGLISH_NARRATION_REVISION,
    model_id: str = ENGLISH_NARRATION_MODEL,
    license_state: str = "allowed",
    empty: bool = False,
) -> Path:
    audio = work / "voice" / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    wav = audio / f"{artifact_id}.wav"
    payload = b"" if empty else b"narration-before"
    wav.write_bytes(payload)
    document = NarrationAudioArtifact(
        artifact_id=artifact_id,
        project_id=project_id,
        source_asset_id=asset_id,
        provider_id="voicestudio",
        voice_profile_id=voice,
        engine_id="kittentts",
        model_id=model_id,
        model_revision=revision,
        script_sha256=hashlib.sha256(script.encode("utf-8")).hexdigest(),
        script_label=script,
        audio_sha256=hashlib.sha256(payload).hexdigest() if payload else "e" * 64,
        size_bytes=len(payload) if payload else 1,
        duration_us=1_000_000,
        sample_rate=24000,
        channels=1,
        codec="pcm_s16le",
        language="en-US",
        provider_version="0.5.7",
        consent_record_id="consent-1",
        license_evidence_id="evidence-1",
        model_license=license_state,  # type: ignore[arg-type]
        commercial_use=license_state,  # type: ignore[arg-type]
        cache_id="f" * 64,
        job_id=job_id,
        provenance=provenance([asset_id], job_id=job_id),
    )
    (audio / f"{artifact_id}.json").write_text(document.model_dump_json() + "\n", encoding="utf-8")
    _point(connection, project_id, job_id, asset_id, artifact_id, "narration_audio", wav)
    return wav


def _write_narration(world: _World, **kwargs: object) -> None:
    source = world.sources["src-before-famous"]
    with world.database.transaction() as connection:
        _write_narration_files(
            connection,
            world.work,
            world.project_id,
            "job-before",
            source.asset_id,
            "narration-before",
            script=str(kwargs.get("script", ENGLISH_NARRATION_SCRIPT)),
            voice=str(kwargs.get("voice", ENGLISH_NARRATION_VOICE)),
            revision=str(kwargs.get("revision", ENGLISH_NARRATION_REVISION)),
            model_id=str(kwargs.get("model_id", ENGLISH_NARRATION_MODEL)),
            license_state=str(kwargs.get("license_state", "allowed")),
            empty=bool(kwargs.get("empty", False)),
        )
    source.narration_id = "narration-before"
    source.wav = world.work / "voice" / "audio" / "narration-before.wav"


def _remove_narration(world: _World) -> None:
    audio = world.work / "voice" / "audio"
    if audio.exists():
        for path in audio.glob("narration-before.*"):
            path.unlink()
    with world.database.transaction() as connection:
        connection.execute("DELETE FROM artifacts WHERE artifact_id = ?", ("narration-before",))


def _refresh_checksum(manifest: Path) -> None:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    document = PublishPackageDocument.model_validate(payload)
    text = _checksum_text(manifest.parent, document.delivery_id, document.files)
    (manifest.parent / "checksums.sha256").write_text(text, encoding="utf-8")


def _patch_manifest(path: Path, key: str, value: str) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[key] = value
    path.write_text(json.dumps(payload), encoding="utf-8")


def _set_uri(world: _World, asset_id: str, uri: str) -> None:
    with world.database.transaction() as connection:
        connection.execute("UPDATE source_assets SET uri = ? WHERE source_asset_id = ?", (uri, asset_id))


def _job_count(database: Database) -> int:
    with database.connect() as connection:
        row = connection.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'campaign_production'").fetchone()
    assert row is not None
    return int(row[0])


def test_script_constant_matches_the_verified_sentence() -> None:
    assert ENGLISH_NARRATION_SCRIPT == "Café costs $12.50 today."
    assert hashlib.sha256(ENGLISH_NARRATION_SCRIPT.encode()).hexdigest() == ENGLISH_NARRATION_SCRIPT_SHA256
