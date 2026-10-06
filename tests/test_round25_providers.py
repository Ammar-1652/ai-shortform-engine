"""Round 25: Whop snapshot intake and manual Envato handoff."""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from clipforge.assets.filters import search_arguments
from clipforge.assets.handoff import (
    assert_envato_registration,
    create_envato_requests,
    filters_for_provider,
    register_envato_asset,
    resume_envato_asset,
    verify_envato_asset,
)
from clipforge.assets.mcp_client import AssetError
from clipforge.assets.provider import FakeEnvatoMcpProvider
from clipforge.assets.service import search_assets
from clipforge.campaign.board import open_campaign_board, static_bundle_text
from clipforge.campaign.policy_fingerprint import current_policy_fingerprint
from clipforge.campaign.production import source_may_proceed
from clipforge.campaign.providers import CampaignError, whop_live_import
from clipforge.campaign.whop import (
    FakeWhopSnapshotConnector,
    import_from_connector,
    import_whop_snapshot,
    select_imported_sources,
    verify_whop_import,
    whop_doctor,
)
from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import require_asset
from clipforge.hero.advanced_build import _broll
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import SourceWorkspace
from clipforge.preview.browser import resolve_browser
from clipforge.schemas.envato_asset import EnvatoAssetRequest
from clipforge.schemas.project import Project
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.whop import WhopCampaignSnapshot
from clipforge.storage import Database, insert_project
from tests.helpers import stamp

runner = CliRunner()
_SPEC = {
    "name": "search_stock_video",
    "inputSchema": {
        "properties": {
            "searchTerms": {"type": "string", "minLength": 1, "maxLength": 60},
            "perPage": {"type": "integer", "minimum": 1, "maximum": 20},
            "page": {"type": "integer", "minimum": 1, "maximum": 50},
            "filters": {
                "type": "object",
                "properties": {
                    "orientation": {"type": "string", "enum": ["horizontal", "vertical"]},
                    "resolution": {"type": "string", "enum": ["1080p (Full HD)", "720p (HD)"]},
                    "categories": {"type": "string", "enum": ["Stock Footage", "Motion Graphics"]},
                },
            },
        },
        "required": ["searchTerms"],
    },
}


def test_whop_contracts_reject_secrets_paths_html_and_unknown_keys() -> None:
    payload = _snapshot()
    for bad in (
        "bearer abc",
        "cookie=session",
        "api_key=abcd",
        "password=hunter2",
        "authorization: basic",
        "/home/pakka/clip.mp4",
        "file:///tmp/clip.mp4",
        "<script>alert(1)</script>",
        "a\\b",
    ):
        broken = _snapshot()
        broken["campaigns"][0]["title"] = bad
        with pytest.raises(ValidationError):
            WhopCampaignSnapshot.model_validate(broken)
    payload["extra"] = "no"
    with pytest.raises(ValidationError):
        WhopCampaignSnapshot.model_validate(payload)


def test_whop_import_is_atomic_cached_and_not_a_license(tmp_path: Path) -> None:
    database, work = _db(tmp_path)
    before = _license_count(database)
    path = tmp_path / "snap.json"
    path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad_body = _snapshot()
    bad_body["campaigns"][0]["title"] = "bearer abc"
    bad.write_text(json.dumps(bad_body), encoding="utf-8")
    with pytest.raises(CampaignError):
        import_whop_snapshot(work, bad.read_bytes(), project_id="project-1")
    assert not (work / "campaigns" / "whop").exists()
    first = import_whop_snapshot(work, path.read_bytes(), project_id="project-1")
    second = import_whop_snapshot(work, path.read_bytes(), project_id="project-1")
    assert first.import_id == second.import_id
    assert first.whop_live == "not_configured"
    assert list((work / "campaigns" / "whop").iterdir()) == [work / "campaigns" / "whop" / first.import_id]
    changed = _snapshot()
    changed["campaigns"][0]["title"] = "Studio demo two"
    third = import_whop_snapshot(work, json.dumps(changed).encode(), project_id="project-1")
    assert third.import_id != first.import_id
    forced = import_whop_snapshot(work, path.read_bytes(), project_id="project-1", force=True)
    assert forced.import_id != first.import_id
    assert _license_count(database) == before
    assert "whop_live: not_configured" in whop_doctor()
    with pytest.raises(CampaignError) as blocked:
        whop_live_import()
    assert blocked.value.code == "not_configured"
    connector = FakeWhopSnapshotConnector()
    with pytest.raises(CampaignError) as missing:
        import_from_connector(work, connector, project_id="project-1")
    assert missing.value.code == "not_configured"


def test_whop_jsonl_selection_and_stale_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _db(tmp_path)
    work = tmp_path / "work"
    header = _snapshot()
    extra = {
        "schema_version": "1.0.0",
        "campaign_id": "studio-other",
        "title": "Other",
        "policy_state": "prohibited",
        "sources": [
            {
                "schema_version": "1.0.0",
                "source_id": "src-other",
                "display_name": "Other",
                "rights_state": "allowed",
                "policy_state": "allowed",
                "selected": True,
            }
        ],
    }
    lines = json.dumps(header) + "\n" + json.dumps(extra) + "\n"
    attempt = import_whop_snapshot(work, lines.encode(), project_id="project-1")
    assert attempt.status == "ready"
    assert attempt.selectable_source_ids == ["src-one"]
    assert source_may_proceed("allowed")
    assert select_imported_sources(work, attempt.import_id, ["src-one"]) == ["src-one"]
    with pytest.raises(CampaignError) as rights:
        select_imported_sources(work, attempt.import_id, ["src-two"])
    assert rights.value.code == "rights_not_allowed"
    with pytest.raises(CampaignError) as policy:
        select_imported_sources(work, attempt.import_id, ["src-other"])
    assert policy.value.code == "policy_blocked"
    snapshot = work / "campaigns" / "whop" / attempt.import_id / "snapshot.json"
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(CampaignError) as stale:
        verify_whop_import(work, attempt.import_id)
    assert stale.value.code == "stale_snapshot"
    fresh = import_whop_snapshot(work, json.dumps(_snapshot()).encode(), project_id="project-1")

    def _other(_campaign_id: str) -> str:
        return "c" * 64

    monkeypatch.setattr("clipforge.campaign.whop.current_policy_fingerprint", _other)
    with pytest.raises(CampaignError) as policy_stale:
        verify_whop_import(work, fresh.import_id)
    assert policy_stale.value.code == "stale_policy"


def test_envato_filters_stay_local_and_urls_are_not_media(tmp_path: Path) -> None:
    provider = FakeEnvatoMcpProvider(
        [_SPEC],
        [
            {
                "id": "item-1",
                "title": "City night",
                "url": "https://elements.envato.com/city-night-1",
                "asset_type": "video",
                "provider": "fake",
            },
            {"title": "Untitled", "url": "https://elements.envato.com/untitled", "provider": "fake"},
        ],
    )
    filters = {"asset_type": "video", "orientation": "vertical", "genre": "ambient"}
    arguments, _report, deferred = search_arguments(_SPEC, "city", filters)
    assert arguments["perPage"] <= 5
    assert "genre" not in json.dumps(arguments.get("filters", {}))
    assert deferred["genre"] == "ambient"
    hits = search_assets(provider, query="city", filters=filters, campaign_id="studio-demo")
    supported, stored_deferred = filters_for_provider(provider, "city", filters)
    assert "genre" not in supported
    assert stored_deferred["genre"] == "ambient"
    assert hits[0].item_url == "https://elements.envato.com/city-night-1"
    assert hits[0].direct_download_url is None
    assert hits[0].duration_seconds is None
    assert hits[1].item_id is None
    assert hits[0].download_status == "manual_download_required"
    work = tmp_path / "work"
    work.mkdir()
    requests = create_envato_requests(
        work,
        query="city",
        filters=filters,
        campaign_id="studio-demo",
        provider="fake",
        provider_version="fake",
        hits=hits,
        supported_filters=supported,
        deferred_filters=stored_deferred,
        requested_duration="1",
        expected_codec="h264",
        expected_width=160,
        expected_height=90,
    )
    assert requests[0].item_page_url == hits[0].item_url
    assert requests[0].direct_download_url is None
    assert requests[0].download_status == "manual_download_required"
    assert not (tmp_path / "work" / "campaigns" / "envato-assets").exists()


def test_manual_registration_probe_cache_and_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database, work = _db(tmp_path)
    request = _request(work)
    media = _place_video(work, "incoming/clip.mp4", color="black")
    _place_text(work, "incoming/license.txt", "Envato license evidence for this item.")
    first = register_envato_asset(
        work,
        database,
        request.request_id,
        relative_file="incoming/clip.mp4",
        project_id="project-1",
        license_relative="incoming/license.txt",
        rights="allowed",
        source_asset_id="source-1",
    )
    assert first.acquisition_status == "verified"
    assert first.sha256 == sha256_file(media)
    assert first.probe is not None
    assert first.probe.video_codec == "h264"
    assert first.probe.width == 160
    assert first.probe.height == 90
    assert first.probe.audio_codec == "aac"
    assert first.relative_path is not None
    assert not first.relative_path.startswith("/")
    assert first.download_status == "manual_download_required"
    manifest = (work / "campaigns" / "envato-assets" / first.asset_id / "manifest.json").read_bytes()
    jobs_before = _job_count(database)
    again = register_envato_asset(
        work,
        database,
        request.request_id,
        relative_file="incoming/clip.mp4",
        project_id="project-1",
        license_relative="incoming/license.txt",
        rights="allowed",
    )
    assert again.asset_id == first.asset_id
    assert again.cache_status == "hit"
    assert _job_count(database) == jobs_before
    assert (work / "campaigns" / "envato-assets" / first.asset_id / "manifest.json").read_bytes() == manifest
    _place_video(work, "incoming/other.mp4", color="white")
    changed = register_envato_asset(
        work,
        database,
        request.request_id,
        relative_file="incoming/other.mp4",
        project_id="project-1",
        license_relative="incoming/license.txt",
        rights="allowed",
    )
    assert changed.asset_id != first.asset_id
    original = (work / first.relative_path).read_bytes()
    with pytest.raises(AssetError):
        register_envato_asset(
            work,
            database,
            request.request_id,
            relative_file="incoming/other.mp4",
            project_id="project-1",
            license_relative="incoming/license.txt",
            rights="allowed",
            asset_id=first.asset_id,
            promotion_hook=_stop("final_rename"),
        )
    assert (work / first.relative_path).read_bytes() == original
    with pytest.raises(AssetError):
        register_envato_asset(
            work,
            database,
            request.request_id,
            relative_file="incoming/clip.mp4",
            project_id="project-1",
            license_relative="incoming/license.txt",
            rights="allowed",
            asset_id="env-interrupted",
            promotion_hook=_stop("staging_write"),
        )
    partials = work / "campaigns" / "envato-assets" / "env-interrupted" / "media"
    assert not list(partials.glob("*.partial"))
    assert not list(partials.glob("*.mp4"))
    cancelled = register_envato_asset(
        work,
        database,
        request.request_id,
        relative_file="incoming/clip.mp4",
        project_id="project-1",
        license_relative="incoming/license.txt",
        rights="allowed",
        cancel=True,
        asset_id="env-paused",
    )
    assert cancelled.acquisition_status == "cancelled"
    resumed = resume_envato_asset(work, database, "env-paused")
    assert resumed.acquisition_status == "verified"
    forced = register_envato_asset(
        work,
        database,
        request.request_id,
        relative_file="incoming/clip.mp4",
        project_id="project-1",
        license_relative="incoming/license.txt",
        rights="allowed",
        force=True,
    )
    assert forced.asset_id != first.asset_id
    assert (work / first.relative_path).is_file()
    before = _tree(work, database.path)
    verified = verify_envato_asset(work, database, first.asset_id)
    assert verified.renderable is True
    assert _tree(work, database.path) == before
    (work / first.relative_path).write_bytes(original + b"changed")
    stale = verify_envato_asset(work, database, first.asset_id)
    assert stale.renderable is False
    assert stale.reason_code == "stale_registration"
    (work / first.relative_path).write_bytes(original)
    monkeypatch.setattr(
        "clipforge.assets.handoff.current_policy_fingerprint",
        lambda _campaign_id: "d" * 64,
    )
    assert verify_envato_asset(work, database, resumed.asset_id).reason_code == "stale_policy"


def test_registration_rejects_unsafe_files_and_rights(tmp_path: Path) -> None:
    database, work = _db(tmp_path)
    request = _request(work)
    _place_video(work, "incoming/clip.mp4", color="black")
    _place_text(work, "incoming/license.txt", "Envato license evidence for this item.")
    _place_text(work, "incoming/empty.txt", "")
    cases = (
        ("incoming/../clip.mp4", "traversal"),
        ("incoming\\clip.mp4", "backslash"),
        ("/tmp/clip.mp4", "outside_root"),
        ("https://example.com/clip.mp4", "remote_url"),
        ("file:///tmp/clip.mp4", "remote_url"),
    )
    for relative, code in cases:
        with pytest.raises(AssetError) as exc:
            _register(work, database, request.request_id, relative_file=relative)
        assert exc.value.code == code
    real = work / "real"
    real.mkdir()
    _place_video(real, "linked.mp4", color="black")
    link = work / "incoming" / "linked.mp4"
    link.symlink_to(real / "linked.mp4")
    with pytest.raises(AssetError) as linked:
        _register(work, database, request.request_id, relative_file="incoming/linked.mp4")
    assert linked.value.code == "symlink"
    other = tmp_path / "linked-parent"
    other_work = other / "work"
    other_db, _ = _db(other)
    other_request = _request(other_work)
    store = other / "store"
    store.mkdir()
    _place_video(store, "clip.mp4", color="black")
    _place_text(other_work, "license-real.txt", "Envato license evidence for this item.")
    (other_work / "incoming").symlink_to(store, target_is_directory=True)
    with pytest.raises(AssetError) as parent_link:
        _register(other_work, other_db, other_request.request_id, relative_file="incoming/clip.mp4")
    assert parent_link.value.code == "symlink"
    (work / "incoming" / "clip.mp4").write_bytes(b"this is not media")
    with pytest.raises(AssetError) as corrupt:
        _register(work, database, request.request_id)
    assert corrupt.value.code == "corrupt_media"
    _place_video(work, "incoming/clip.mp4", color="black")
    _place_video(work, "incoming/mpeg.mp4", color="black", codec="mpeg4")
    with pytest.raises(AssetError) as codec:
        _register(work, database, request.request_id, relative_file="incoming/mpeg.mp4")
    assert codec.value.code == "unsupported_codec"
    with pytest.raises(AssetError) as size:
        _register(work, database, request.request_id, expect_size=1)
    assert size.value.code == "size_mismatch"
    tiny = _request(work, max_bytes=10, request_id=None)
    with pytest.raises(AssetError) as limit:
        _register(work, database, tiny.request_id)
    assert limit.value.code == "file_size_limit"
    with pytest.raises(AssetError) as empty:
        _register(work, database, request.request_id, license_relative="incoming/empty.txt")
    assert empty.value.code == "missing_license_evidence"
    with pytest.raises(AssetError) as unknown:
        _register(work, database, request.request_id, rights="unknown")
    assert unknown.value.code == "rights_not_allowed"
    with pytest.raises(AssetError) as prohibited:
        _register(work, database, request.request_id, rights="prohibited")
    assert prohibited.value.code == "rights_not_allowed"
    antoine = _request(work, campaign_id="antoine-sallis")
    with pytest.raises(AssetError) as blocked:
        _register(work, database, antoine.request_id)
    assert blocked.value.code == "policy_blocked"


def test_verified_envato_asset_binds_advanced_hero_and_stale_blocks(tmp_path: Path) -> None:
    database, work = _db(tmp_path)
    request = _request(work)
    _place_video(work, "incoming/clip.mp4", color="black")
    _place_text(work, "incoming/license.txt", "Envato license evidence for this item.")
    registration = _register(work, database, request.request_id, source_asset_id="source-1")
    workspace = SourceWorkspace(work, "project-1", "source-1")
    entry, _license, path = require_asset(
        database,
        workspace,
        project_id="project-1",
        asset_id=registration.asset_id,
        expected_kind="graphic",
        work_root=work,
    )
    assert entry.file_sha256 == registration.sha256
    events = _broll(
        database, workspace, work, "project-1", "candidate-1", 2_000_000, [registration.asset_id], []
    )
    assert events[0].asset_id == registration.asset_id
    assert _job_kinds(database) == {"envato_asset_registration"}
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(MediaError):
        require_asset(
            database,
            workspace,
            project_id="project-1",
            asset_id=registration.asset_id,
            expected_kind="graphic",
            work_root=work,
        )
    assert _job_kinds(database) == {"envato_asset_registration"}
    with pytest.raises(MediaError):
        assert_envato_registration(
            work,
            database,
            "missing-asset",
            project_id="project-1",
            file_sha256="a" * 64,
        )


def test_board_and_cli_are_read_only_without_secrets(tmp_path: Path) -> None:
    database, work = _db(tmp_path)
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps(_snapshot()), encoding="utf-8")
    imported = runner.invoke(
        app,
        [
            "campaign",
            "operator",
            "whop",
            "import",
            "--file",
            str(snapshot),
            "--project",
            "project-1",
            "--work-dir",
            str(work),
        ],
    )
    assert imported.exit_code == 0, imported.stderr
    assert "whop_live: not_configured" in imported.stdout
    doctor = runner.invoke(app, ["campaign", "operator", "whop", "doctor"])
    assert doctor.exit_code == 0
    assert "whop_live: not_configured" in doctor.stdout
    request = runner.invoke(
        app,
        [
            "assets",
            "envato",
            "request",
            "--query",
            "city",
            "--campaign",
            "studio-demo",
            "--provider",
            "dry-run",
            "--genre",
            "ambient",
            "--orientation",
            "vertical",
            "--asset-type",
            "video",
            "--work-dir",
            str(work),
        ],
    )
    assert request.exit_code == 0, request.stderr
    assert "download_status: manual_download_required" in request.stdout
    stored = json.loads(
        runner.invoke(
            app,
            ["assets", "envato", "requests", "--campaign", "studio-demo", "--work-dir", str(work)],
        ).stdout
    )
    assert stored[0]["deferred_filters"]["genre"] == "ambient"
    assert stored[0]["supported_filters"]["orientation"] == "vertical"
    assert stored[0]["item_page_url"] is None
    _place_video(work, "incoming/clip.mp4", color="black")
    _place_text(work, "incoming/license.txt", "Envato license evidence for this item.")
    # The dry-run request has no expectations. Register through the API for probe facts,
    # then exercise the listed commands against that asset.
    created = _request(work)
    _place_text(work, "incoming/license.txt", "Envato license evidence for this item.")
    registration = _register(work, database, created.request_id, source_asset_id="source-1")
    shown = runner.invoke(app, ["assets", "envato", "show", registration.asset_id, "--work-dir", str(work)])
    assert shown.exit_code == 0
    assert registration.sha256 in shown.stdout
    before = _tree(work, database.path)
    verified = runner.invoke(
        app,
        [
            "assets",
            "envato",
            "verify",
            registration.asset_id,
            "--db",
            str(database.path),
            "--work-dir",
            str(work),
        ],
    )
    assert verified.exit_code == 0, verified.stderr
    listed = runner.invoke(
        app, ["assets", "envato", "list", "--campaign", "studio-demo", "--work-dir", str(work)]
    )
    assert registration.asset_id in listed.stdout
    whop_listed = runner.invoke(app, ["campaign", "operator", "whop", "list", "--work-dir", str(work)])
    assert imported.stdout.splitlines()[0] in whop_listed.stdout
    showed = runner.invoke(
        app, ["campaign", "operator", "whop", "show", "studio-demo", "--work-dir", str(work)]
    )
    assert "snapshot_fingerprint" in showed.stdout
    checked = runner.invoke(
        app,
        ["campaign", "operator", "whop", "verify", imported.stdout.splitlines()[0], "--work-dir", str(work)],
    )
    assert checked.exit_code == 0, checked.stderr
    assert _tree(work, database.path) == before
    script = Path("src/clipforge/campaign/board_static/app.js").read_text(encoding="utf-8")
    style = Path("src/clipforge/campaign/board_static/styles.css").read_text(encoding="utf-8")
    page = Path("src/clipforge/campaign/board_static/index.html").read_text(encoding="utf-8")
    bundle = "\n".join((script, style, page))
    assert "eval(" not in bundle
    assert "innerHTML" not in bundle
    assert "https://" not in bundle
    assert "http://" not in bundle
    assert static_bundle_text() == "PASS campaign board"
    server = open_campaign_board(work_root=work, port=0, database=database)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request

        port = int(server.server_address[1])
        whop = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/campaigns/studio-demo/whop").read()
        )
        detail = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/whop-imports/{whop['import_id']}").read()
        )
        envato = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/campaigns/studio-demo/envato").read()
        )
        asset = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/envato-assets/{registration.asset_id}").read()
        )
        assets = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/campaigns/studio-demo/assets").read()
        )
        body = json.dumps({"whop": whop, "detail": detail, "envato": envato, "asset": asset, "assets": assets})
        assert whop["whop_live"] == "not_configured"
        assert whop["snapshot_fingerprint"]
        assert envato["envato"] == "discovery_only"
        assert asset["renderable"] is True
        assert asset["sha256"] == registration.sha256
        assert asset["probe"]["video_codec"] == "h264"
        assert asset["relative_path"] == registration.relative_path
        assert assets["assets"][0]["license_evidence"]
        assert "/home/" not in body
        assert "bearer " not in body.lower()
        assert "file:" not in body.lower()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_board_renders_provider_facts_in_chrome(tmp_path: Path) -> None:
    try:
        browser = resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    database, work = _db(tmp_path)
    import_whop_snapshot(work, json.dumps(_snapshot()).encode(), project_id="project-1")
    request = _request(work)
    _place_video(work, "incoming/clip.mp4", color="black")
    _place_text(work, "incoming/license.txt", "Envato license evidence for this item.")
    _register(work, database, request.request_id, source_asset_id="source-1")
    server = open_campaign_board(work_root=work, port=0, database=database)
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
        assert "whop_status" in dumped.stdout
        assert "snapshot_fingerprint" in dumped.stdout
        assert "asset_sha256" in dumped.stdout
        assert "autoplay" not in dumped.stdout
        assert "<script>alert" not in dumped.stdout
    finally:
        server.shutdown()
        server.server_close()


def _snapshot() -> dict[str, object]:
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
                    },
                    {
                        "schema_version": "1.0.0",
                        "source_id": "src-two",
                        "display_name": "Second source",
                        "rights_state": "unknown",
                        "policy_state": "allowed",
                        "selected": True,
                    },
                ],
            }
        ],
    }


def _db(tmp_path: Path) -> tuple[Database, Path]:
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
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


def _request(
    work: Path,
    *,
    campaign_id: str = "studio-demo",
    max_bytes: int = 200_000_000,
    request_id: str | None = "req-city",
) -> EnvatoAssetRequest:
    now = datetime.now(UTC)
    chosen = request_id or f"req-{hashlib.sha256(str(max_bytes).encode()).hexdigest()[:8]}"
    request = EnvatoAssetRequest(
        request_id=chosen,
        provider="fake",
        provider_version="fake",
        query="city",
        supported_filters={"orientation": "vertical"},
        deferred_filters={"genre": "ambient"},
        item_page_url="https://elements.envato.com/city-night-1",
        item_id="item-1",
        media_kind="video",
        intended_use="broll",
        campaign_id=campaign_id,
        policy_fingerprint=current_policy_fingerprint(campaign_id),
        requested_resolution="160x90",
        requested_duration="1",
        expected_codec="h264",
        expected_width=160,
        expected_height=90,
        max_bytes=max_bytes,
        created_at=now,
    )
    path = work / "campaigns" / "envato-requests" / request.request_id / "request.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(request.model_dump_json() + "\n", encoding="utf-8")
    return request


def _register(work: Path, database: Database, request_id: str, **kwargs: object):
    values = {
        "relative_file": "incoming/clip.mp4",
        "project_id": "project-1",
        "license_relative": "incoming/license.txt",
        "rights": "allowed",
    }
    values.update(kwargs)
    return register_envato_asset(work, database, request_id, **values)  # type: ignore[arg-type]


def _place_video(root: Path, relative: str, *, color: str, codec: str = "libx264") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=160x90:r=30:d=1",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=stereo",
        "-shortest",
        "-c:v",
        codec,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-t",
        "1",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return path


def _place_text(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _stop(stage_name: str):
    def _hook(stage: str) -> None:
        if stage == stage_name:
            raise AssetError("promotion stopped", code="promotion_failed")

    return _hook


def _license_count(database: Database) -> int:
    with database.connect() as connection:
        row = connection.execute("SELECT COUNT(*) FROM asset_license_records").fetchone()
    assert row is not None
    return int(row[0])


def _job_count(database: Database) -> int:
    with database.connect() as connection:
        row = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()
    assert row is not None
    return int(row[0])


def _job_kinds(database: Database) -> set[str]:
    with database.connect() as connection:
        rows = connection.execute("SELECT kind FROM jobs").fetchall()
    return {str(row[0]) for row in rows}


def _tree(work: Path, database: Path) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    total = 0
    for path in sorted(work.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        payload = path.read_bytes()
        total += len(payload)
        digest.update(path.relative_to(work).as_posix().encode())
        digest.update(payload)
    return total, database.stat().st_size, digest.hexdigest()
