"""Derived Whop sidecar integrity and the external auth helper."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.campaign.providers import CampaignError
from clipforge.campaign.whop import import_whop_snapshot, verify_whop_import
from clipforge.campaign.whop_auth import doctor_text, launch_login_browser, logout
from clipforge.campaign.whop_bridge import serve_catalogue
from clipforge.campaign.whop_live import FakeWhopProvider, import_discovered, select_whop_campaign
from clipforge.cli.main import app

runner = CliRunner()


def _manifest(work: Path, import_id: str) -> Path:
    return work / "campaigns" / "whop" / import_id / "manifest.json"


def _rewrite(path: Path, **changes: object) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(changes)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_tampered_import_fields_fail_verification(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    payload = json.dumps(FakeWhopProvider().payload).encode()
    attempt = import_whop_snapshot(work, payload, project_id="project-1")
    path = _manifest(work, attempt.import_id)
    original = path.read_bytes()
    cases = (
        {"status": "blocked"},
        {"reason_code": "forged"},
        {"selectable_source_ids": ["src-city", "src-extra"]},
        {"selectable_source_ids": []},
        {"provider_id": "other"},
        {"provider_version": "9"},
        {"operator_id": "operator-9"},
        {"project_id": "project-9"},
        {"intake_label": "authenticated_operator_snapshot"},
    )
    for change in cases:
        _rewrite(path, **change)
        with pytest.raises(CampaignError) as failed:
            verify_whop_import(work, attempt.import_id)
        assert failed.value.code in {"stale_import", "stale_snapshot", "stale_policy"}
        path.write_bytes(original)
    assert verify_whop_import(work, attempt.import_id).import_id == attempt.import_id


def test_blocked_ready_flag_does_not_select(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    payload = FakeWhopProvider().payload
    payload["campaigns"][0]["policy_state"] = "prohibited"
    discovered = import_discovered(work, FakeWhopProvider(payload), project_id="project-1")
    assert discovered.status == "blocked"
    import_manifest = _manifest(work, discovered.import_id or "")
    _rewrite(import_manifest, status="ready", reason_code="ready")
    discovery_manifest = work / "campaigns" / "whop-discoveries" / discovered.discovery_id / "manifest.json"
    body = json.loads(discovery_manifest.read_text(encoding="utf-8"))
    body["status"] = "ready"
    body["reason_code"] = "ready"
    discovery_manifest.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(CampaignError):
        select_whop_campaign(
            work,
            campaign_id="camp-city",
            import_id=discovered.import_id or "",
            project_id="project-1",
            source_ids=["src-city"],
            operator_id="operator-1",
        )


def test_allowed_source_without_a_declared_hash_can_be_selected(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    payload = FakeWhopProvider().payload
    payload["campaigns"][0]["sources"][0]["selected"] = False
    payload["campaigns"][0]["sources"][0]["content_sha256"] = None
    payload["campaigns"][0]["sources"][0]["declared_content_sha256"] = None
    discovered = import_discovered(work, FakeWhopProvider(payload), project_id="project-1")
    evidence = select_whop_campaign(
        work,
        campaign_id="camp-city",
        import_id=discovered.import_id or "",
        project_id="project-1",
        source_ids=["src-city"],
        operator_id="operator-1",
    )
    assert evidence.source_hashes == [None]
    assert evidence.live_claim == "not_claimed"


def test_bridge_confinement_and_expiry(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps(FakeWhopProvider().payload), encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(SystemExit):
        serve_catalogue(
            "127.0.0.1",
            0,
            catalogue,
            "nonce-1",
            expires_at=10**18,
            work_root=outside,
        )
    with pytest.raises(SystemExit):
        serve_catalogue("127.0.0.1", 0, catalogue, "nonce-1", expires_at=float("inf"), work_root=tmp_path)
    linked_parent = tmp_path / "link"
    linked_parent.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(SystemExit):
        serve_catalogue(
            "127.0.0.1",
            0,
            linked_parent / "catalogue.json",
            "nonce-1",
            expires_at=1,
            work_root=tmp_path,
        )


def test_auth_doctor_is_read_only_and_hides_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_WHOP_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("CLIPFORGE_WHOP_STATE_DIR", str(tmp_path / "state"))
    before = list(tmp_path.rglob("*"))
    text = doctor_text()
    assert list(tmp_path.rglob("*")) == before
    assert "profile: missing" in text
    assert "credentials: not stored" in text
    assert "cookies: not read" in text
    assert "live_claim: not_claimed" in text
    assert str(tmp_path) not in text
    result = runner.invoke(app, ["campaign", "operator", "whop", "auth", "doctor"])
    assert result.exit_code == 0
    assert "socket: not opened" in result.stdout


def test_profile_paths_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("CLIPFORGE_WHOP_PROFILE_DIR", str(repo / "var" / "whop-profile"))
    monkeypatch.setenv("CLIPFORGE_WHOP_STATE_DIR", str(tmp_path / "state"))
    with pytest.raises(CampaignError) as rejected:
        launch_login_browser(repo / "var" / "whop-profile")
    assert rejected.value.code == "invalid_document"
    outside = tmp_path / "real"
    outside.mkdir()
    link = tmp_path / "linked-profile"
    link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("CLIPFORGE_WHOP_PROFILE_DIR", str(link))
    with pytest.raises(CampaignError):
        launch_login_browser(link)


def test_logout_does_not_kill_an_unrelated_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_WHOP_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CLIPFORGE_WHOP_PROFILE_DIR", str(tmp_path / "profile"))
    profile = tmp_path / "profile"
    profile.mkdir()
    os.chmod(profile, 0o700)
    sleeper = os.spawnlp(os.P_NOWAIT, "sleep", "sleep", "30")
    state = tmp_path / "state"
    state.mkdir()
    (state / "whop-browser.json").write_text(json.dumps({"pid": sleeper, "port": 9}), encoding="utf-8")
    try:
        assert logout(confirmed=True) == "profile: removed\ncredentials: not stored\nlive_claim: not_claimed"
        os.kill(sleeper, 0)
    finally:
        os.kill(sleeper, 15)
