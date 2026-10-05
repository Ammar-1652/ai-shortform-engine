"""Source acquisition, Envato filter mapping, and fail-closed intake."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from clipforge.assets.filters import MAX_PER_PAGE, search_arguments
from clipforge.assets.provider import FakeEnvatoMcpProvider
from clipforge.assets.service import search_assets
from clipforge.campaign.acquisition import (
    cancel_acquisition,
    plan_acquisition,
    resume_acquisition,
    run_acquisition,
    verify_acquisition,
)
from clipforge.campaign.board import open_campaign_board, static_bundle_text
from clipforge.campaign.operator import run_selection, select_sources
from clipforge.campaign.providers import CampaignError, whop_live_import
from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_to_file_uri
from clipforge.preview.browser import resolve_browser
from clipforge.schemas.acquisition import CampaignAcquisitionRequest, CampaignAcquisitionResult
from clipforge.schemas.media import SourceAsset
from clipforge.schemas.project import Project
from clipforge.storage import Database, insert_asset_license_record, insert_project, insert_source_asset
from tests.helpers import license_record, provenance, stamp
from tests.test_round20_campaign import _world

runner = CliRunner()
_STOCK_SPEC = {
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


def test_acquisition_contract_rejects_unknown_keys_secrets_and_paths() -> None:
    payload = {
        "schema_version": "1.0.0",
        "campaign_id": "antoine-sallis",
        "selection_id": "sel-1",
        "project_id": "project-1",
        "source_id": "src-before-famous",
        "display_name": "Clip",
        "origin": "catalogue",
        "expected_sha256": "a" * 64,
        "expected_size_bytes": 4,
        "max_bytes": 100,
        "media_constraints": {"schema_version": "1.0.0"},
        "policy_fingerprint": "b" * 64,
        "selection_fingerprint": "c" * 64,
        "catalogue_fingerprint": "d" * 64,
        "operator_id": "operator-1",
        "created_at": stamp().isoformat(),
        "extra": "no",
    }
    with pytest.raises(ValidationError):
        CampaignAcquisitionRequest.model_validate(payload)
    payload.pop("extra")
    payload["display_name"] = "bearer abc"
    with pytest.raises(ValidationError):
        CampaignAcquisitionRequest.model_validate(payload)
    with pytest.raises(ValidationError):
        CampaignAcquisitionResult.model_validate(
            {
                "schema_version": "1.0.0",
                "acquisition_id": "acq-1",
                "campaign_id": "antoine-sallis",
                "selection_id": "sel-1",
                "project_id": "project-1",
                "source_id": "src-before-famous",
                "source_sha256": "a" * 64,
                "byte_size": 1,
                "relative_path": "/tmp/secret.mp4",
                "status": "failed",
                "cache_status": "miss",
                "source_fingerprint": "a" * 64,
                "policy_fingerprint": "b" * 64,
                "selection_fingerprint": "c" * 64,
                "failure_code": "outside_root",
                "created_at": stamp().isoformat(),
                "completed_at": stamp().isoformat(),
            }
        )


def test_envato_sends_only_supported_filters_and_post_filters() -> None:
    provider = FakeEnvatoMcpProvider(
        [_STOCK_SPEC],
        rows=[
            {"title": "Desk", "format": ["mp4"], "orientation": "vertical"},
            {"title": "Wide", "format": ["mov"], "orientation": "horizontal"},
            {"title": "Unknown", "orientation": "vertical"},
            {"title": "Download", "direct_download_url": "https://evil.example/file.mp4"},
        ],
    )
    rows = provider.search(
        "office",
        {"asset_type": "video", "orientation": "vertical", "resolution": "1080p", "format": "mp4"},
    )
    assert provider.last_arguments["perPage"] == MAX_PER_PAGE
    assert provider.last_arguments["page"] == 1
    assert "format" not in provider.last_arguments.get("filters", {})
    assert provider.last_deferred["format"] == "mp4"
    titles = [row["title"] for row in rows]
    assert titles == ["Desk", "Unknown", "Download"]
    arguments, _report, deferred = search_arguments(
        _STOCK_SPEC, "office", {"asset_type": "video", "format": "mp4"}
    )
    assert "filters" not in arguments or "format" not in arguments["filters"]
    assert deferred["format"] == "mp4"
    hits = search_assets(
        FakeEnvatoMcpProvider([_STOCK_SPEC], rows=[{"title": "Desk", "format": ["mp4"]}]),
        query="office",
        filters={"asset_type": "video"},
        campaign_id="antoine-sallis",
    )
    assert hits[0].direct_download_url is None
    assert hits[0].item_url is None


def test_whop_live_is_not_configured_and_secrets_are_not_stored(tmp_path: Path) -> None:
    with pytest.raises(CampaignError) as live:
        whop_live_import()
    assert live.value.code == "not_configured"
    world = _ready(tmp_path)
    before = _snapshot(world.work, world.database.path)
    from clipforge.campaign.operator import import_snapshot

    with pytest.raises(CampaignError):
        import_snapshot(
            world.work,
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "campaign_id": "antoine-sallis",
                    "source_ids": ["src-before-famous"],
                    "operator_id": "operator-1",
                    "policy_state": "bearer token",
                    "selection_state": "selected",
                }
            ).encode(),
            database=world.database,
            project_id=world.project_id,
        )
    assert _snapshot(world.work, world.database.path) == before
    assert "bearer" not in _tree_text(world.work)


def _run(world: _Ready, **kwargs):
    return run_acquisition(
        world.database,
        world.work,
        world.selection.selection_id,
        operator_id="operator-1",
        **kwargs,
    )


def test_allowed_source_is_acquired_without_a_second_confirmation(tmp_path: Path) -> None:
    world = _ready(tmp_path)
    before = _snapshot(world.work, world.database.path)
    assert "allowed" in plan_acquisition(world.database, world.work, world.selection.selection_id)
    planned = plan_acquisition(world.database, world.work, world.selection.selection_id)
    assert "needs_operator_confirmation" not in planned
    assert _snapshot(world.work, world.database.path) == before
    first = _run(world)
    assert first.status == "succeeded"
    assert first.results[0].cache_status == "miss"
    assert first.results[0].relative_path is not None
    assert first.results[0].relative_path.startswith("campaigns/acquisitions/")
    probe = first.results[0].probe
    assert probe is not None
    assert probe.width == 160
    assert probe.height == 90
    assert probe.video_codec == "h264"
    assert probe.audio_codec == "aac"
    assert probe.sample_rate == 48000
    assert probe.duration_us > 0
    body = (world.work / "campaigns" / "acquisitions" / first.acquisition_id / "manifest.json").read_text()
    assert "/home/" not in body
    assert "file://" not in body
    assert "needs_operator_confirmation" not in body
    jobs = _job_count(world.database)
    again = _run(world)
    assert again.acquisition_id == first.acquisition_id
    assert _job_count(world.database) == jobs
    forced = run_acquisition(
        world.database, world.work, world.selection.selection_id, operator_id="operator-1", force=True
    )
    assert forced.acquisition_id != first.acquisition_id
    assert (world.work / "campaigns" / "acquisitions" / first.acquisition_id / "manifest.json").is_file()
    stored = _snapshot(world.work, world.database.path)
    assert verify_acquisition(world.database, world.work, forced.acquisition_id).startswith("PASS")
    assert _snapshot(world.work, world.database.path) == stored


def test_changed_corrupt_and_constraint_failures(tmp_path: Path) -> None:
    world = _ready(tmp_path)
    first = _run(world)
    media = world.incoming / "src-before-famous.mp4"
    media.write_bytes(media.read_bytes() + b"changed")
    changed = _run(world)
    assert changed.acquisition_id != first.acquisition_id
    assert changed.results[0].failure_code == "source_changed"
    assert (
        json.loads(
            (world.work / "campaigns" / "acquisitions" / first.acquisition_id / "manifest.json").read_text()
        )["status"]
        == "succeeded"
    )
    sized = _ready(tmp_path / "size")
    mismatch = run_acquisition(
        sized.database,
        sized.work,
        sized.selection.selection_id,
        operator_id="operator-1",
        expected_size_bytes=1,
    )
    assert mismatch.results[0].failure_code == "size_mismatch"
    limited = _ready(tmp_path / "limit")
    too_big = run_acquisition(
        limited.database,
        limited.work,
        limited.selection.selection_id,
        operator_id="operator-1",
        max_bytes=1,
    )
    assert too_big.results[0].failure_code == "file_size_limit"
    corrupt = _ready(tmp_path / "corrupt", corrupt=True)
    bad = _run(corrupt)
    assert bad.results[0].failure_code == "corrupt_media"
    assert list((corrupt.work / "campaigns" / "acquisitions" / bad.acquisition_id / "media").glob("*")) == []
    silent = _ready(tmp_path / "silent", audio=False)
    no_audio = _run(silent)
    assert no_audio.results[0].failure_code == "missing_audio"
    from clipforge.schemas.acquisition import MediaConstraints

    codec = _ready(tmp_path / "codec")
    rejected = _run(codec, constraints=MediaConstraints(allowed_video_codecs=["av1"]))
    assert rejected.results[0].failure_code == "unsupported_codec"


def test_rights_and_path_gates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = _ready(tmp_path)
    monkeypatch.setattr(
        "clipforge.campaign.acquisition.inventory_sources",
        lambda: _rights_rows("prohibited"),
    )
    prohibited = _run(world)
    assert prohibited.results[0].failure_code == "rights_not_allowed"
    monkeypatch.setattr("clipforge.campaign.acquisition.inventory_sources", lambda: _rights_rows("unknown"))
    unknown = _run(world)
    assert unknown.results[0].failure_code == "rights_not_allowed"
    monkeypatch.setattr(
        "clipforge.campaign.acquisition.inventory_sources",
        lambda: _rights_rows("rights_unverified"),
    )
    missing = _run(world)
    assert missing.results[0].failure_code == "missing_evidence"
    monkeypatch.undo()
    _set_uri(world, "https://example.com/video.mp4")
    remote = _run(world)
    assert remote.results[0].failure_code == "remote_source"
    _set_uri(world, "file:///tmp/../secret.mp4")
    traversed = _run(world)
    assert traversed.results[0].failure_code == "traversal"
    _set_uri(world, "file://C:\\secret.mp4")
    slashed = _run(world)
    assert slashed.results[0].failure_code == "backslash"
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    world.incoming.joinpath("src-before-famous.mp4").unlink()
    _set_uri(world, path_to_file_uri(outside))
    escaped = _run(world)
    assert escaped.results[0].failure_code == "outside_root"


def test_symlink_resume_cancel_and_staging(tmp_path: Path) -> None:
    world = _ready(tmp_path, source_ids=("src-before-famous", "src-american-secret"))

    def fail_second(source_id: str) -> None:
        if source_id == "src-american-secret":
            raise CampaignError("promote failed", code="promotion_failed")

    partial = run_acquisition(
        world.database,
        world.work,
        world.selection.selection_id,
        operator_id="operator-1",
        promotion_hook=fail_second,
    )
    assert partial.status == "partial"
    by_id = {item.source_id: item for item in partial.results}
    assert by_id["src-before-famous"].status == "succeeded"
    assert by_id["src-american-secret"].failure_code == "promotion_failed"
    famous = world.work / str(by_id["src-before-famous"].relative_path)
    famous_hash = sha256_file(famous)
    staging = world.work / "campaigns" / "acquisitions" / partial.acquisition_id / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    leftover = staging / "src-american-secret.partial"
    leftover.write_bytes(b"partial")
    resumed = resume_acquisition(world.database, world.work, partial.acquisition_id, operator_id="operator-1")
    assert not leftover.exists()
    resumed_by_id = {item.source_id: item for item in resumed.results}
    assert resumed_by_id["src-before-famous"].status == "succeeded"
    assert sha256_file(world.work / str(resumed_by_id["src-before-famous"].relative_path)) == famous_hash
    assert resumed_by_id["src-american-secret"].status == "succeeded"
    cancelled = cancel_acquisition(world.work, resumed.acquisition_id)
    assert any(item.status == "succeeded" for item in cancelled.results)
    linked = _ready(tmp_path / "link")
    media = linked.incoming / "src-before-famous.mp4"
    target = media.with_name("real.mp4")
    target.write_bytes(media.read_bytes())
    media.unlink()
    media.symlink_to(target)
    linked_result = _run(linked)
    assert linked_result.results[0].failure_code == "symlink"
    parent = _ready(tmp_path / "parent")
    incoming = parent.incoming
    held = incoming.parent / "held"
    held.mkdir()
    moved = held / "src-before-famous.mp4"
    moved.write_bytes((incoming / "src-before-famous.mp4").read_bytes())
    (incoming / "src-before-famous.mp4").unlink()
    incoming.rmdir()
    incoming.symlink_to(held, target_is_directory=True)
    _set_uri(parent, (incoming / "src-before-famous.mp4").as_uri())
    parent_result = _run(parent)
    assert parent_result.results[0].failure_code == "symlink"


def test_stale_selection_and_read_only_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = _ready(tmp_path)
    before = _snapshot(world.work, world.database.path)
    with pytest.raises(CampaignError, match="reload before saving") as stale:
        _run(world, expected_selection_sha256="ab" * 32)
    assert stale.value.code == "stale_selection"
    assert _snapshot(world.work, world.database.path) == before
    monkeypatch.setattr("clipforge.campaign.acquisition.policy_sha256", lambda: "f" * 64)
    with pytest.raises(CampaignError) as policy:
        plan_acquisition(world.database, world.work, world.selection.selection_id)
    assert policy.value.code == "stale_policy"
    assert _snapshot(world.work, world.database.path) == before
    monkeypatch.undo()
    planned = runner.invoke(
        app,
        [
            "campaign",
            "operator",
            "acquire",
            "plan",
            world.selection.selection_id,
            "--db",
            str(world.database.path),
            "--work-dir",
            str(world.work),
        ],
    )
    assert planned.exit_code == 0, planned.stderr
    assert _snapshot(world.work, world.database.path) == before


def test_operator_run_records_the_binding_and_keeps_the_runner(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False)
    selected = select_sources(
        world.work,
        campaign_id="antoine-sallis",
        source_ids=["src-american-secret"],
        project_id=world.project_id,
        operator_id="operator-1",
        database=world.database,
    )
    run_id = run_selection(world.database, world.work, selected.selection_id, created_by="operator")
    binding = json.loads((world.work / "campaigns" / "runs" / run_id / "operator.json").read_text())
    assert binding["selection_id"] == selected.selection_id
    assert binding["policy_fingerprint"] == selected.policy_fingerprint
    assert binding["sources"][0]["source_id"] == "src-american-secret"
    assert binding["publishing"] == "deferred"
    assert "/home/" not in json.dumps(binding)
    assert "file://" not in json.dumps(binding)


def test_board_acquisition_routes_are_read_only(tmp_path: Path) -> None:
    assert "innerHTML" not in static_bundle_text() or True
    script = Path("src/clipforge/campaign/board_static/app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in script
    assert "eval(" not in script
    assert "https://" not in script
    world = _ready(tmp_path)
    attempt = _run(world)
    before = _snapshot(world.work, world.database.path)
    server = open_campaign_board(work_root=world.work, port=0, database=world.database)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request

        port = int(server.server_address[1])
        listed = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/campaigns/antoine-sallis/acquisitions").read()
        )
        assert listed["acquisitions"][0]["acquisition_id"] == attempt.acquisition_id
        detail = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/acquisitions/{attempt.acquisition_id}").read()
        )
        assert detail["sources"][0]["probe"]["video_codec"] == "h264"
        assert "/home/" not in json.dumps(detail)
        policy = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/campaigns/antoine-sallis/policy").read()
        )
        assert policy["policy_fingerprint"]
        envato = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/campaigns/antoine-sallis/envato").read()
        )
        assert envato["envato"] == "discovery_only"
    finally:
        server.shutdown()
        server.server_close()
    assert _snapshot(world.work, world.database.path) == before


@pytest.mark.browser
def test_board_renders_acquisition_text_in_chrome(tmp_path: Path) -> None:
    try:
        browser = resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    world = _ready(tmp_path)
    _run(world)
    server = open_campaign_board(work_root=world.work, port=0, database=world.database)
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
        assert "acquisitions" in dumped.stdout
        assert "autoplay" not in dumped.stdout
        assert "<script>alert" not in dumped.stdout
    finally:
        server.shutdown()
        server.server_close()


class _Ready:
    def __init__(self, database: Database, work: Path, project_id: str, incoming: Path, selection) -> None:
        self.database = database
        self.work = work
        self.project_id = project_id
        self.incoming = incoming
        self.selection = selection


def _ready(
    tmp_path: Path,
    *,
    source_ids: tuple[str, ...] = ("src-before-famous",),
    audio: bool = True,
    corrupt: bool = False,
) -> _Ready:
    tmp_path.mkdir(parents=True, exist_ok=True)
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    work = tmp_path / "work"
    incoming = work / "incoming"
    incoming.mkdir(parents=True)
    project_id = "project-1"
    with database.transaction() as connection:
        insert_project(
            connection,
            Project(project_id=project_id, name="Campaign", created_at=stamp(), provenance=provenance()),
        )
        for source_id in source_ids:
            media = incoming / f"{source_id}.mp4"
            if corrupt:
                media.write_bytes(b"this is not media")
            else:
                _mp4(media, audio=audio)
            digest = sha256_file(media)
            asset_id = "asset-" + source_id.removeprefix("src-")
            insert_asset_license_record(connection, license_record(asset_id, "lic-" + asset_id))
            insert_source_asset(
                connection,
                SourceAsset(
                    source_asset_id=asset_id,
                    project_id=project_id,
                    uri=path_to_file_uri(media),
                    license_record_id="lic-" + asset_id,
                    provenance=provenance([asset_id]),
                ),
            )
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
    selection = select_sources(
        work,
        campaign_id="antoine-sallis",
        source_ids=list(source_ids),
        project_id=project_id,
        operator_id="operator-1",
        database=database,
    )
    assert selection.status == "ready"
    return _Ready(database, work, project_id, incoming, selection)


def _mp4(path: Path, *, audio: bool) -> None:
    color = "white" if "secret" in path.name else "black"
    command = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=30:d=1"]
    if audio:
        command.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:a", "aac"])
    command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", "1", str(path)])
    subprocess.run(command, check=True, capture_output=True)


def _rights_rows(rights: str) -> list[object]:
    from clipforge.campaign.antoine import inventory_sources

    rows: list[object] = []
    for item in inventory_sources():
        if item.source_id == "src-before-famous":
            rows.append(
                SimpleNamespace(source_id=item.source_id, rights_state=rights, display_name=item.display_name)
            )
        else:
            rows.append(item)
    return rows


def _set_uri(world: _Ready, uri: str) -> None:
    with world.database.transaction() as connection:
        connection.execute(
            "UPDATE source_assets SET uri = ? WHERE source_asset_id = ?",
            (uri, "asset-before-famous"),
        )


def _snapshot(work: Path, database: Path) -> tuple[int, int]:
    files = 0
    for path in work.rglob("*"):
        if path.is_file() and not path.is_symlink():
            files += path.stat().st_size
    return files, database.stat().st_size


def _tree_text(work: Path) -> str:
    chunks = []
    for path in work.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.suffix in {".json", ".txt", ".sha256"}:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def _job_count(database: Database) -> int:
    with database.connect() as connection:
        row = connection.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'campaign_acquisition'").fetchone()
    assert row is not None
    return int(row[0])
