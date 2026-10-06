"""Round 27: credential-safe Whop discovery and filtering."""

from __future__ import annotations

import json
import threading
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.campaign.board import open_campaign_board, static_bundle_text
from clipforge.campaign.production import source_may_proceed
from clipforge.campaign.providers import CampaignError
from clipforge.campaign.whop import import_whop_snapshot, whop_doctor
from clipforge.campaign.whop_filter import filter_campaigns
from clipforge.campaign.whop_live import (
    FakeBrowserExportProvider,
    FakeWhopProvider,
    MalformedWhopProvider,
    UnavailableWhopProvider,
    cancel_discovery,
    discover_whop,
    import_discovered,
    normalize_whop_payload,
    select_whop_campaign,
    verify_discovery,
)
from clipforge.campaign.whop_mcp import public_headers
from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.language.registry import alignment_claim, capability_for
from clipforge.preview.browser import resolve_browser
from clipforge.schemas.whop_discovery import WhopLiveDiscoveryRequest

runner = CliRunner()
_RELOAD = "The campaign selection changed while this page was open; reload before saving."


def test_default_whop_stays_unconfigured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "work"
    work.mkdir()
    before = _tree(work)
    assert "whop_live: not_configured" in whop_doctor()
    assert "live_smoke: not_executed" in whop_doctor()
    assert "credentials: not stored" in whop_doctor()
    discovered = discover_whop()
    assert discovered["whop_live"] == "not_configured"
    assert discovered["campaigns"] == []
    assert _tree(work) == before
    monkeypatch.setenv("CLIPFORGE_WHOP_LIVE_SMOKE", "1")
    smoked = whop_doctor()
    assert "whop_live: provider_unavailable" in smoked
    assert "session: not opened" in smoked
    assert discover_whop()["whop_live"] == "provider_unavailable"
    assert "authorization" not in {key.lower() for key in public_headers()}
    assert capability_for("en-US").alignment_evidence == "verified_live"
    assert alignment_claim("ar") == "alignment_not_claimed"
    assert alignment_claim("ja") == "whisperx"


def test_snapshot_import_remains_compatible(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    payload = json.dumps(_legacy_snapshot()).encode()
    first = import_whop_snapshot(work, payload, project_id="project-1")
    second = import_whop_snapshot(work, payload, project_id="project-1")
    assert first.import_id == second.import_id
    assert first.whop_live == "not_configured"
    assert first.selectable_source_ids == ["src-one"]
    assert source_may_proceed("allowed")


def test_fake_providers_filter_cache_and_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "work"
    work.mkdir()
    provider = FakeWhopProvider()
    preview = discover_whop(provider)
    assert preview["whop_live"] == "public_discovery"
    assert "content_sha256" in preview["missing_fields"] or preview["campaigns"] == ["camp-city"]
    assert not (work / "campaigns").exists()
    first = import_discovered(work, provider, project_id="project-1")
    assert first.live_status == "public_discovery"
    assert first.evidence_origin == "test_double"
    assert first.live_claim == "not_claimed"
    assert first.cache_status == "miss"
    assert any(item.included and item.campaign_id == "camp-city" for item in first.decisions)
    again = import_discovered(work, provider, project_id="project-1")
    assert again.discovery_id == first.discovery_id
    assert again.cache_status == "hit"
    manifest = (work / "campaigns" / "whop-discoveries" / first.discovery_id / "manifest.json").read_bytes()
    changed = FakeWhopProvider(_prohibited_payload())
    second = import_discovered(work, changed, project_id="project-1")
    assert second.discovery_id != first.discovery_id
    assert any(item.reason_code == "category_prohibited" for item in second.decisions)
    first_manifest = work / "campaigns" / "whop-discoveries" / first.discovery_id / "manifest.json"
    assert first_manifest.read_bytes() == manifest
    evidence = select_whop_campaign(
        work,
        campaign_id="camp-city",
        import_id=first.import_id or "",
        project_id="project-1",
        source_ids=["src-city"],
        operator_id="operator-1",
    )
    assert evidence.source_ids == ["src-city"]
    with pytest.raises(CampaignError, match=_RELOAD) as stale:
        select_whop_campaign(
            work,
            campaign_id="camp-city",
            import_id=first.import_id or "",
            project_id="project-1",
            source_ids=["src-city"],
            operator_id="operator-1",
            expected_catalogue="c" * 64,
        )
    assert stale.value.code == "stale_selection"
    with pytest.raises(CampaignError, match=_RELOAD) as changed_source:
        select_whop_campaign(
            work,
            campaign_id="camp-city",
            import_id=first.import_id or "",
            project_id="project-1",
            source_ids=["src-city"],
            operator_id="operator-1",
            expected_source_hashes={"src-city": "b" * 64},
        )
    assert changed_source.value.code == "source_changed"
    unknown = import_discovered(work, FakeWhopProvider(_unknown_rights_payload()), project_id="project-1")
    with pytest.raises(CampaignError) as rights:
        select_whop_campaign(
            work,
            campaign_id="camp-unknown",
            import_id=unknown.import_id or "",
            project_id="project-1",
            source_ids=["src-unknown"],
            operator_id="operator-1",
        )
    assert rights.value.code == "rights_not_allowed"
    with pytest.raises(CampaignError) as missing:
        select_whop_campaign(
            work,
            campaign_id="camp-city",
            import_id=first.import_id or "",
            project_id="project-1",
            source_ids=["src-missing"],
            operator_id="operator-1",
        )
    assert missing.value.code == "missing_source"
    before = _tree(work)
    assert verify_discovery(work, first.discovery_id).discovery_id == first.discovery_id
    assert _tree(work) == before
    with pytest.raises(CampaignError) as unavailable:
        import_discovered(work, UnavailableWhopProvider(), project_id="project-1")
    assert unavailable.value.code == "provider_unavailable"
    for payload in (
        _bad("bearer abc"),
        _bad("cookie=session"),
        _bad("api_key=abcd"),
        _bad("password=hunter2"),
        _bad("/home/pakka/clip.mp4"),
        _bad("file:///tmp/clip.mp4"),
        _bad("../secret"),
        _bad("a\\b"),
        _bad("https://cdn.example.com/video.mp4"),
        _bad("<script>alert(1)</script>"),
    ):
        with pytest.raises(CampaignError):
            import_discovered(work, MalformedWhopProvider(payload), project_id="project-1")
    exported = import_discovered(
        work,
        FakeBrowserExportProvider(_sample_with_title("Exported rewards")),
        project_id="project-1",
    )
    assert exported.live_status == "not_configured"
    assert exported.evidence_origin == "test_double"
    assert exported.live_status != "authenticated_discovery"
    assert exported.live_claim == "not_claimed"
    poisoned = _sample_with_title("Cookie rewards")
    poisoned["cookie"] = "session=secret"
    with pytest.raises(CampaignError) as secret:
        import_discovered(work, FakeBrowserExportProvider(poisoned), project_id="project-1")
    assert secret.value.code == "secret_rejected"
    with pytest.raises(CampaignError) as stopped:
        import_discovered(
            work,
            FakeWhopProvider(_sample_with_title("Interrupted rewards")),
            project_id="project-1",
            promotion_hook=_stop("final_rename"),
        )
    assert stopped.value.code == "promotion_failed"
    kept = work / "campaigns" / "whop-discoveries" / first.discovery_id / "manifest.json"
    assert kept.read_bytes() == manifest
    assert not list(work.rglob("*.partial"))
    monkeypatch.setattr(
        "clipforge.campaign.whop.current_policy_fingerprint",
        lambda _campaign_id: "d" * 64,
    )
    with pytest.raises(CampaignError, match=_RELOAD):
        select_whop_campaign(
            work,
            campaign_id="camp-city",
            import_id=first.import_id or "",
            project_id="project-1",
            source_ids=["src-city"],
            operator_id="operator-1",
        )


def test_board_and_cli_are_read_only(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    discovered = import_discovered(work, FakeWhopProvider(), project_id="project-1")
    selected = runner.invoke(
        app,
        [
            "campaign",
            "operator",
            "whop",
            "select",
            "camp-city",
            "--import",
            discovered.import_id or "",
            "--project",
            "project-1",
            "--source",
            "src-city",
            "--work-dir",
            str(work),
        ],
    )
    assert selected.exit_code == 0, selected.stderr
    assert selected.stdout.startswith("sel-")
    before = _tree(work)
    doctor = runner.invoke(app, ["campaign", "operator", "whop", "doctor"])
    assert doctor.exit_code == 0
    assert "whop_live: not_configured" in doctor.stdout
    listed = runner.invoke(app, ["campaign", "operator", "whop", "discover"])
    assert listed.exit_code == 0
    assert "not_configured" in listed.stdout
    shown = runner.invoke(
        app,
        ["campaign", "operator", "whop", "show", "camp-city", "--work-dir", str(work)],
    )
    assert shown.exit_code == 0, shown.stderr
    assert _tree(work) == before
    script = Path("src/clipforge/campaign/board_static/app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in script
    assert "eval(" not in script
    assert "https://" not in script
    assert "autoplay" not in script
    assert static_bundle_text() == "PASS campaign board"
    server = open_campaign_board(work_root=work, port=0, database=None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = int(server.server_address[1])
        base = f"http://127.0.0.1:{port}"
        capabilities = json.loads(urllib.request.urlopen(f"{base}/api/whop/capabilities").read())
        rows = json.loads(urllib.request.urlopen(f"{base}/api/whop/discoveries").read())
        detail_url = f"{base}/api/whop/discoveries/{discovered.discovery_id}"
        detail = json.loads(urllib.request.urlopen(detail_url).read())
        campaign = json.loads(urllib.request.urlopen(f"{base}/api/campaigns/camp-city/whop").read())
        filters = json.loads(urllib.request.urlopen(f"{base}/api/campaigns/camp-city/filter-results").read())
        body = json.dumps(
            {
                "capabilities": capabilities,
                "rows": rows,
                "detail": detail,
                "campaign": campaign,
                "filters": filters,
            }
        )
        assert capabilities["live_status"] == "not_configured"
        assert capabilities["mutating_operations"] == "disabled"
        assert capabilities["credentials"] == "not_stored"
        assert rows["discoveries"][0]["discovery_id"] == discovered.discovery_id
        assert detail["live_status"] == "public_discovery"
        assert campaign["whop_live"] == "not_configured"
        assert filters["decisions"]
        assert len(str(filters["selection_fingerprint"])) == 64
        assert "/home/" not in body
        assert "bearer " not in body
        assert "cookie=" not in body
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_board_renders_whop_capability_in_chrome(tmp_path: Path) -> None:
    try:
        browser = resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    work = tmp_path / "work"
    work.mkdir()
    import_discovered(work, FakeWhopProvider(), project_id="project-1")
    server = open_campaign_board(work_root=work, port=0, database=None)
    import subprocess
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    try:
        dumped = subprocess.run(
            [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--disable-background-networking",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=8000",
                "--dump-dom",
                f"http://127.0.0.1:{port}/",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert dumped.returncode == 0, dumped.stderr
        assert "whop_provider" in dumped.stdout
        assert "not_configured" in dumped.stdout
        assert "autoplay" not in dumped.stdout
    finally:
        server.shutdown()
        server.server_close()


def test_filter_reasons_are_deterministic() -> None:
    snapshot = normalize_whop_payload(FakeWhopProvider().payload, operator_id="operator-1")
    created = datetime(2026, 10, 6, 12, tzinfo=UTC)
    active = _request(created_at=created)
    included = filter_campaigns(snapshot, active, now=created)
    assert included[0].included
    assert included[0].reason_code == "included"
    paused = snapshot.model_copy(deep=True)
    paused.campaigns[0].status = "paused"
    paused_request = _request(created_at=created, require_status="active")
    assert _one(filter_campaigns(paused, paused_request, now=created)) == "status_not_active"
    gambling = snapshot.model_copy(deep=True)
    gambling.campaigns[0].category = "gambling"
    gambling_request = _request(created_at=created, prohibited_categories=["gambling"])
    assert _one(filter_campaigns(gambling, gambling_request, now=created)) == "category_prohibited"
    narrow = _request(created_at=created, allowed_categories=["education"])
    assert _one(filter_campaigns(snapshot, narrow, now=created)) == "category_not_allowed"
    blocked = snapshot.model_copy(deep=True)
    blocked.campaigns[0].policy_state = "prohibited"
    blocked_request = _request(created_at=created, require_policy="allowed")
    assert _one(filter_campaigns(blocked, blocked_request, now=created)) == "policy_blocked"
    assert _one(filter_campaigns(snapshot, _request(created_at=created, language="ja"))) == "language_mismatch"
    assert _one(filter_campaigns(snapshot, _request(created_at=created, query="zzzz"))) == "search_mismatch"
    stale = _request(created_at=created, max_age_hours=1)
    assert _one(filter_campaigns(snapshot, stale, now=created + timedelta(hours=3))) == "stale_campaign"
    missing = snapshot.model_copy(deep=True)
    missing.campaigns[0].sources[0].availability = "missing"
    assert _one(filter_campaigns(missing, active, now=created)) == "missing_source"
    formatted = _request(created_at=created, media_format="mov")
    assert _one(filter_campaigns(snapshot, formatted, now=created)) == "format_mismatch"
    huge = _request(created_at=created, max_size_bytes=10)
    assert _one(filter_campaigns(snapshot, huge, now=created)) == "source_too_large"
    short = _request(created_at=created, min_duration_us=5_000_000)
    assert _one(filter_campaigns(snapshot, short, now=created)) == "duration_out_of_range"
    unknown = snapshot.model_copy(deep=True)
    unknown.campaigns[0].sources[0].rights_state = "unknown"
    assert _one(filter_campaigns(unknown, active, now=created)) == "rights_not_allowed"
    offline = snapshot.model_copy(deep=True)
    offline.campaigns[0].sources[0].availability = "offline"
    assert _one(filter_campaigns(offline, active, now=created)) == "source_unavailable"


def test_cancelled_and_stale_discoveries_fail_closed(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    provider = FakeWhopProvider()
    first = import_discovered(work, provider, project_id="project-1")
    directory = work / "campaigns" / "whop-discoveries" / first.discovery_id
    manifest = directory / "manifest.json"
    response = directory / "response.json"
    manifest_bytes = manifest.read_bytes()
    response_bytes = response.read_bytes()
    again = import_discovered(work, provider, project_id="project-1")
    assert again.cache_status == "hit"
    assert manifest.read_bytes() == manifest_bytes
    response.write_bytes(b'{"tampered":true}\n')
    with pytest.raises(CampaignError) as stale:
        import_discovered(work, provider, project_id="project-1")
    assert stale.value.code == "stale_discovery"
    response.write_bytes(response_bytes)
    recovered = import_discovered(work, provider, project_id="project-1")
    assert recovered.cache_status == "hit"
    cancelled = cancel_discovery(work, first.discovery_id)
    assert cancelled.status == "cancelled"
    with pytest.raises(CampaignError) as denied:
        verify_discovery(work, first.discovery_id)
    assert denied.value.code == "cancelled"
    repeated = import_discovered(work, provider, project_id="project-1")
    assert repeated.discovery_id != first.discovery_id
    assert b'"status":"cancelled"' in manifest.read_bytes().replace(b" ", b"")
    leaked = " ".join(path.read_text(encoding="utf-8", errors="replace") for path in work.rglob("*.json"))
    assert "cookie=" not in leaked
    assert "bearer " not in leaked
    assert "password=" not in leaked
    assert "api_key" not in leaked


def _request(**overrides: object) -> WhopLiveDiscoveryRequest:
    payload: dict[str, object] = {
        "request_id": "req-filter",
        "provider_id": "fake_whop",
        "provider_version": "1",
        "created_at": datetime(2026, 10, 6, 12, tzinfo=UTC),
    }
    payload.update(overrides)
    return WhopLiveDiscoveryRequest.model_validate(payload)


def _one(decisions: list[object]) -> str:
    decision = decisions[0]
    return str(decision.reason_code)


def _legacy_snapshot() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "operator_id": "operator-1",
        "exported_at": "2026-10-06T12:00:00Z",
        "campaigns": [
            {
                "schema_version": "1.0.0",
                "campaign_id": "studio-demo",
                "title": "Studio demo",
                "policy_state": "allowed",
                "sources": [
                    {
                        "schema_version": "1.0.0",
                        "source_id": "src-one",
                        "display_name": "First source",
                        "rights_state": "allowed",
                        "policy_state": "allowed",
                        "selected": True,
                    }
                ],
            }
        ],
    }


def _sample_with_title(title: str) -> dict[str, object]:
    payload = FakeWhopProvider().payload
    payload["campaigns"][0]["title"] = title
    payload["campaigns"][0]["campaign_id"] = "camp-" + title.split()[0].lower()
    return payload


def _prohibited_payload() -> dict[str, object]:
    payload = _sample_with_title("Blocked rewards")
    payload["campaigns"][0]["category"] = "gambling"
    payload["campaigns"][0]["policy_state"] = "prohibited"
    return payload


def _unknown_rights_payload() -> dict[str, object]:
    payload = _sample_with_title("Unknown rewards")
    payload["campaigns"][0]["campaign_id"] = "camp-unknown"
    payload["campaigns"][0]["sources"][0]["source_id"] = "src-unknown"
    payload["campaigns"][0]["sources"][0]["rights_state"] = "unknown"
    return payload


def _bad(title: str) -> dict[str, object]:
    payload = _sample_with_title("Bad rewards")
    payload["campaigns"][0]["title"] = title
    return payload


def _stop(stage_name: str):
    def _hook(stage: str) -> None:
        if stage == stage_name:
            raise CampaignError("promotion stopped", code="promotion_failed")

    return _hook


def _tree(work: Path) -> int:
    total = 0
    for path in work.rglob("*"):
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total
