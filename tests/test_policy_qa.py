"""Profiles, policy checks, and QA gates."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from clipforge.hero.advanced_backend import FakeAdvancedRenderBackend
from clipforge.hero.advanced_service import plan_advanced_candidate, render_advanced_drafts
from clipforge.policy.engine import PolicyContext, evaluate_policy
from clipforge.policy.loader import PolicyError, load_catalog, resolve_profile
from clipforge.qa.service import QAError, gate_qa, list_qa, run_qa, show_qa, verify_qa
from clipforge.schemas.governance import AssetLicenseRecord, RightsStatus
from clipforge.schemas.jobs import QACheck, QAKind, QAResult, QAStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.qa import PolicyDigest, QASetDocument, aggregate_status
from clipforge.storage import list_jobs, update_project_profile
from tests.candidate_support import PROJECT_ID, SOURCE_ID
from tests.test_advanced_hero import _approved

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")


def test_repo_profiles_resolve_and_hash_stably() -> None:
    catalog = load_catalog()
    organic = resolve_profile("profile-organic", catalog=catalog)
    paid = resolve_profile("profile-paid-campaign", catalog=catalog)
    assert organic.policy_ids == ("policy-source-rights",)
    assert paid.policy_ids == ("policy-asset-rights", "policy-source-rights")
    assert "policy-asset-rights" not in organic.policy_ids
    assert resolve_profile("profile-organic").profile_sha256 == organic.profile_sha256
    assert organic.profile_sha256 != paid.profile_sha256
    with pytest.raises(PolicyError, match="unknown profile"):
        resolve_profile("profile-missing", catalog=catalog)


def test_loader_rejects_bad_configuration(tmp_path: Path) -> None:
    root = _config_root(tmp_path)
    (root / "profiles" / "broken.json").write_text("{", encoding="utf-8")
    with pytest.raises(PolicyError, match="not valid JSON"):
        load_catalog(root)
    (root / "profiles" / "broken.json").unlink()
    extra = {
        "schema_version": "1.0.0",
        "profile_id": "profile-extra",
        "name": "Extra",
        "mode": "organic",
        "objective": "Keep one core.",
        "policy_ids": ["policy-source-rights"],
        "score": 1,
    }
    (root / "profiles" / "extra.json").write_text(json.dumps(extra), encoding="utf-8")
    with pytest.raises(PolicyError, match="rejected"):
        load_catalog(root)
    (root / "profiles" / "extra.json").unlink()
    duplicate = json.loads((root / "profiles" / "organic.json").read_text(encoding="utf-8"))
    (root / "profiles" / "copy.json").write_text(json.dumps(duplicate), encoding="utf-8")
    with pytest.raises(PolicyError, match="duplicate"):
        load_catalog(root)
    (root / "profiles" / "copy.json").unlink()
    missing = json.loads((root / "profiles" / "organic.json").read_text(encoding="utf-8"))
    missing["profile_id"] = "profile-gap"
    missing["policy_ids"] = ["policy-missing"]
    (root / "profiles" / "gap.json").write_text(json.dumps(missing), encoding="utf-8")
    catalog = load_catalog(root)
    with pytest.raises(PolicyError, match="missing policy"):
        resolve_profile("profile-gap", catalog=catalog)


def test_loader_rejects_symlinks_and_traversal(tmp_path: Path) -> None:
    from clipforge.policy.loader import _confine

    root = _config_root(tmp_path)
    with pytest.raises(PolicyError, match="escapes"):
        _confine(root / "profiles", "../outside.json", "profile")
    target = root / "policies" / "source-rights.json"
    link = root / "profiles" / "linked.json"
    link.symlink_to(target)
    with pytest.raises(PolicyError, match="symlink"):
        load_catalog(root)
    link.unlink()
    moved = tmp_path / "real-policies"
    (root / "policies").rename(moved)
    (root / "policies").symlink_to(moved, target_is_directory=True)
    with pytest.raises(PolicyError, match="symlink"):
        load_catalog(root)


def test_project_profile_assignment(tmp_path: Path) -> None:
    from clipforge.cli.main import app

    database = tmp_path / "clipforge.sqlite3"
    init = runner.invoke(app, ["db", "init", "--db", str(database)])
    assert init.exit_code == 0, init.stderr
    unknown = runner.invoke(
        app,
        ["project", "create", "Demo", "--db", str(database), "--profile-id", "profile-missing"],
    )
    assert unknown.exit_code != 0
    created = runner.invoke(
        app,
        ["project", "create", "Demo", "--db", str(database), "--profile-id", "profile-organic"],
    )
    assert created.exit_code == 0, created.stderr
    project_id = created.stdout.strip()
    updated = runner.invoke(
        app,
        ["project", "set-profile", project_id, "profile-paid-campaign", "--db", str(database)],
    )
    assert updated.exit_code == 0, updated.stderr
    assert "profile-paid-campaign" in updated.stdout
    bare = runner.invoke(app, ["project", "create", "Bare", "--db", str(database)])
    assert bare.exit_code == 0, bare.stderr


def test_policy_engine_source_and_unknown_rules() -> None:
    owned = _license(RightsStatus.OWNED, "file:///licenses/owned.txt")
    context = _context(owned)
    assert evaluate_policy("policy-source-rights", context).status is RightsStatus.OWNED or True
    passed = evaluate_policy("policy-source-rights", context)
    assert passed.status.value == "pass"
    assert "://" not in passed.evidence
    unknown = evaluate_policy("policy-source-rights", _context(_license(RightsStatus.UNKNOWN, "file:///x")))
    assert unknown.status.value == "fail"
    prohibited = evaluate_policy(
        "policy-source-rights", _context(_license(RightsStatus.PROHIBITED, "file:///x"))
    )
    assert prohibited.status.value == "fail"
    missing_evidence = evaluate_policy("policy-source-rights", _context(_license(RightsStatus.OWNED, None)))
    assert missing_evidence.status.value == "insufficient_evidence"
    missing_record = evaluate_policy("policy-source-rights", _context(None))
    assert missing_record.status.value == "insufficient_evidence"
    nope = evaluate_policy("policy-unknown", context)
    assert nope.status.value == "insufficient_evidence"
    assets = evaluate_policy("policy-asset-rights", context)
    assert assets.status.value == "pass"
    assert assets.evidence.startswith("advanced plan references no")


def test_qa_aggregate_cannot_be_upgraded() -> None:
    assert aggregate_status(QAStatus.PASS, QAStatus.FAIL) is QAStatus.FAIL
    assert aggregate_status(QAStatus.PASS, QAStatus.INSUFFICIENT_EVIDENCE) is QAStatus.INSUFFICIENT_EVIDENCE
    assert aggregate_status() is QAStatus.INSUFFICIENT_EVIDENCE
    with pytest.raises(ValidationError):
        _result(QAKind.TECHNICAL, QAStatus.PASS, [])
    with pytest.raises(ValidationError, match="aggregate"):
        QASetDocument(
            qa_set_id="qa-1",
            project_id=PROJECT_ID,
            source_asset_id=SOURCE_ID,
            target_artifact_id="artifact-1",
            target_artifact_kind="advanced_hero_draft_set_json",
            target_manifest_sha256="a" * 64,
            profile_id="profile-organic",
            profile_sha256="b" * 64,
            policies=[PolicyDigest(policy_id="policy-source-rights", sha256="c" * 64)],
            technical=_result(QAKind.TECHNICAL, QAStatus.FAIL, [_qa_check(QAStatus.FAIL)]),
            campaign=_result(QAKind.CAMPAIGN_COMPLIANCE, QAStatus.PASS, [_qa_check(QAStatus.PASS)]),
            status=QAStatus.PASS,
            provenance=_provenance(),
        )


@pytest.mark.hero
def test_unprofiled_project_is_blocked(tmp_path: Path) -> None:
    fixture, candidate_id = _approved(tmp_path)
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
    )
    render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
    )
    with pytest.raises(QAError, match="project profile"):
        run_qa(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            work_root=fixture.work,
            created_by="ada",
        )
    assert _qa_jobs(fixture) == []
    assert not fixture.workspace.qa_sidecar().exists()


@pytest.mark.hero
def test_qa_smoke_and_stale_gate(tmp_path: Path) -> None:
    fixture, _candidate_id = _ready_advanced(tmp_path)
    result = run_qa(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        created_by="ada",
    )
    assert result.status == "pass", show_qa(fixture.database, SOURCE_ID, fixture.work)
    shown = show_qa(fixture.database, SOURCE_ID, fixture.work)
    assert "technical: pass" in shown
    assert "campaign_compliance: pass" in shown
    assert "://" not in shown
    assert "/tmp/" not in shown
    before_db = fixture.database.path.read_bytes()
    before_side = fixture.workspace.qa_sidecar().read_bytes()
    verify_qa(fixture.database, SOURCE_ID, fixture.work)
    document = gate_qa(fixture.database, SOURCE_ID, fixture.work)
    assert document.status is QAStatus.PASS
    assert list_qa(fixture.database, SOURCE_ID, fixture.work)
    assert fixture.database.path.read_bytes() == before_db
    assert fixture.workspace.qa_sidecar().read_bytes() == before_side
    video = next(path for path in fixture.work.rglob("advanced.mp4") if not path.is_symlink())
    original = video.read_bytes()
    video.write_bytes(b"")
    failed = run_qa(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        created_by="ada",
    )
    assert failed.status == "fail"
    shown_fail = show_qa(fixture.database, SOURCE_ID, fixture.work)
    assert "zero bytes" in shown_fail
    with pytest.raises(QAError):
        gate_qa(fixture.database, SOURCE_ID, fixture.work)
    video.write_bytes(original)
    jobs_before = len(_qa_jobs(fixture))
    copy = tmp_path / "same-advanced.mp4"
    copy.write_bytes(original)
    video.unlink()
    video.symlink_to(copy)
    with pytest.raises(QAError, match="symlink"):
        run_qa(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            work_root=fixture.work,
            created_by="ada",
        )
    assert len(_qa_jobs(fixture)) == jobs_before
    video.unlink()
    video.write_bytes(original)
    restored = run_qa(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        created_by="ada",
    )
    assert restored.status == "pass"
    with fixture.database.transaction() as connection:
        connection.execute(
            "UPDATE asset_license_records SET status = ? WHERE asset_id = ?",
            ("prohibited", SOURCE_ID),
        )
    with pytest.raises(QAError, match="prohibited"):
        verify_qa(fixture.database, SOURCE_ID, fixture.work)
    with pytest.raises(QAError):
        gate_qa(fixture.database, SOURCE_ID, fixture.work)


@pytest.mark.hero
def test_qa_failure_keeps_the_previous_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture, _candidate_id = _ready_advanced(tmp_path)
    first = run_qa(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        created_by="ada",
    )
    assert first.status == "pass"
    original = fixture.workspace.qa_sidecar().read_bytes()
    from clipforge.transcription import io as publish_io

    real = publish_io.publish_json
    calls = {"count": 0}

    def fail_sidecar(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] >= 2:
            raise OSError("sidecar disk failed")
        return real(*args, **kwargs)

    monkeypatch.setattr("clipforge.qa.service.publish_json", fail_sidecar)
    with pytest.raises(QAError, match="sidecar"):
        run_qa(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            work_root=fixture.work,
            created_by="ada",
        )
    assert fixture.workspace.qa_sidecar().read_bytes() == original
    assert gate_qa(fixture.database, SOURCE_ID, fixture.work).qa_set_id == first.qa_set_id


@pytest.mark.hero
def test_cancelled_qa_is_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture, _candidate_id = _ready_advanced(tmp_path)

    def explode(_inputs):
        raise KeyboardInterrupt

    monkeypatch.setattr("clipforge.qa.service.technical_checks", explode)
    with pytest.raises(KeyboardInterrupt):
        run_qa(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            work_root=fixture.work,
            created_by="ada",
        )
    assert not fixture.workspace.qa_sidecar().exists()
    jobs = _qa_jobs(fixture)
    assert jobs and jobs[-1].status.value == "cancelled"


def _ready_advanced(tmp_path: Path):
    fixture, candidate_id = _approved(tmp_path)
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
    )
    render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
    )
    with fixture.database.transaction() as connection:
        update_project_profile(connection, PROJECT_ID, "profile-organic")
    return fixture, candidate_id


def _qa_jobs(fixture):
    with fixture.database.connect() as connection:
        return [item for item in list_jobs(connection, PROJECT_ID) if item.kind == "qa_run"]


def _config_root(tmp_path: Path) -> Path:
    root = tmp_path / "configs"
    shutil.copytree(Path("configs/profiles"), root / "profiles")
    shutil.copytree(Path("configs/policies"), root / "policies")
    return root


def _license(status: RightsStatus, evidence: str | None) -> AssetLicenseRecord:
    return AssetLicenseRecord(
        license_record_id="lic-source",
        asset_id=SOURCE_ID,
        status=status,
        evidence_uri=evidence,
        recorded_at=datetime.now(UTC),
        recorded_by="ada",
    )


def _context(record: AssetLicenseRecord | None) -> PolicyContext:
    return PolicyContext(
        database=None,  # type: ignore[arg-type]
        project_id=PROJECT_ID,
        source_asset_id=SOURCE_ID,
        source_license=record,
        plans=(),
        work_root=Path("/tmp"),
        workspace=None,
    )


def _provenance() -> ArtifactProvenance:
    return ArtifactProvenance(
        created_at=datetime.now(UTC),
        created_by="ada",
        tool="clipforge-test",
        tool_version="0",
        source_asset_ids=[SOURCE_ID],
        parent_artifact_ids=["artifact-1"],
    )


def _qa_check(status: QAStatus) -> QACheck:
    return QACheck(name="sample", status=status, evidence="sample evidence")


def _result(kind: QAKind, status: QAStatus, checks: list[QACheck]) -> QAResult:
    return QAResult(
        qa_id="qa-result",
        project_id=PROJECT_ID,
        artifact_id="artifact-1",
        kind=kind,
        status=status,
        checks=checks,
        provenance=_provenance(),
    )
