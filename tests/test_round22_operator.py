"""Operator selection, loopback board, and fail-closed catalogue checks."""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from clipforge.campaign.board import open_campaign_board, require_loopback, static_bundle_text
from clipforge.campaign.operator import (
    board_campaign,
    board_sources,
    catalogue_fingerprint,
    doctor_text,
    import_snapshot,
    resume_run,
    run_selection,
    select_sources,
    status_text,
    verify_selection,
)
from clipforge.campaign.providers import CampaignError
from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.preview.browser import resolve_browser
from clipforge.schemas.campaign_operator import CampaignImportSnapshot, CampaignSelectionDocument
from tests.helpers import stamp
from tests.test_round20_campaign import _job_count, _world

runner = CliRunner()


def test_selection_rejects_unknown_keys_paths_and_secrets() -> None:
    payload = _selection_payload()
    payload["extra"] = "no"
    with pytest.raises(ValidationError):
        CampaignSelectionDocument.model_validate(payload)
    payload.pop("extra")
    payload["reason_code"] = "bearer abc"
    with pytest.raises(ValidationError):
        CampaignSelectionDocument.model_validate(payload)
    payload["reason_code"] = "kept /home/secret"
    with pytest.raises(ValidationError):
        CampaignSelectionDocument.model_validate(payload)
    payload["reason_code"] = "ready"
    payload["source_ids"] = ["src-before-famous", "src-before-famous"]
    with pytest.raises(ValidationError):
        CampaignSelectionDocument.model_validate(payload)


def test_import_snapshot_rejects_duplicates_secrets_and_paths() -> None:
    with pytest.raises(ValidationError):
        CampaignImportSnapshot.model_validate(
            _import_fields(source_ids=["src-before-famous", "src-before-famous"])
        )
    with pytest.raises(ValidationError):
        CampaignImportSnapshot.model_validate(_import_fields(language="bearer token"))
    with pytest.raises(ValidationError):
        CampaignImportSnapshot.model_validate(_import_fields(language="/home/secret"))
    with pytest.raises(ValidationError):
        CampaignImportSnapshot.model_validate(_import_fields(remote_media_ref="file:///tmp/secret.mp4"))
    allowed = CampaignImportSnapshot.model_validate(_import_fields(remote_media_ref="https://example.com/item"))
    assert allowed.remote_media_ref == "https://example.com/item"


def test_allowed_selection_is_append_only_and_replays(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False)
    before = _snapshot(world.work, world.database.path)
    assert "whop_live: not_configured" in doctor_text()
    assert "discovery_only" in doctor_text()
    assert "deferred" in doctor_text()
    assert "alignment_not_claimed" in doctor_text()
    assert _snapshot(world.work, world.database.path) == before
    first = _select(world, ["src-before-famous"])
    assert first.status == "ready"
    assert first.reason_code == "ready"
    assert first.publishing == "deferred"
    assert first.whop_live == "not_configured"
    assert first.sources[0].rights_state == "allowed"
    assert "needs_operator_confirmation" not in first.model_dump_json()
    assert "file://" not in first.model_dump_json()
    assert "/home/" not in first.model_dump_json()
    stored = _selection_sha(world.work, first.selection_id)
    assert verify_selection(world.work, first.selection_id, database=world.database).startswith("PASS")
    assert _selection_sha(world.work, first.selection_id) == stored
    again = _select(world, ["src-before-famous"])
    assert again.selection_id == first.selection_id
    with pytest.raises(CampaignError, match="reload before saving") as stale:
        _select(world, ["src-american-secret"])
    assert stale.value.code == "stale_selection"
    second = _select(world, ["src-american-secret"], expected=stored)
    assert second.selection_id != first.selection_id
    assert (world.work / "campaigns" / "selections" / first.selection_id / "selection.json").is_file()
    assert (world.work / "campaigns" / "selections" / second.selection_id / "selection.json").is_file()


def test_stale_fingerprints_and_languages_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(tmp_path, narrate=False)
    first = _select(world, ["src-before-famous"])
    before = _selection_sha(world.work, first.selection_id)
    monkeypatch.setattr(
        "clipforge.campaign.operator.catalogue_fingerprint",
        lambda campaign_id="antoine-sallis": "e" * 64,
    )
    with pytest.raises(CampaignError) as stale_catalogue:
        verify_selection(world.work, first.selection_id, database=world.database)
    assert stale_catalogue.value.code == "stale_catalogue"
    assert _selection_sha(world.work, first.selection_id) == before
    monkeypatch.undo()
    monkeypatch.setattr("clipforge.campaign.operator.policy_sha256", lambda: "f" * 64)
    with pytest.raises(CampaignError) as stale_policy:
        verify_selection(world.work, first.selection_id, database=world.database)
    assert stale_policy.value.code == "stale_policy"
    with pytest.raises(CampaignError) as language:
        _select(world, ["src-before-famous"], language="zh-CN")
    assert language.value.code == "unsupported_language"
    with pytest.raises(CampaignError) as narration:
        _select(world, ["src-before-famous"], language="ja", narration=True)
    assert narration.value.code == "unsupported_language"
    with pytest.raises(CampaignError) as british:
        _select(world, ["src-before-famous"], language="en-GB", narration=True)
    assert british.value.code == "locale_not_smoked"


def test_rights_and_path_gates_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(tmp_path, narrate=False)
    with pytest.raises(CampaignError) as duplicate:
        _select(world, ["src-before-famous", "src-before-famous"])
    assert duplicate.value.code == "duplicate_source"
    with pytest.raises(CampaignError) as unselected:
        _select(world, ["src-og-cuicide"])
    assert unselected.value.code == "not_selected"
    with pytest.raises(CampaignError) as mixed:
        _select(world, ["src-before-famous"], project_id="project-2")
    assert mixed.value.code == "mixed_project"
    prohibited = _rights_catalogue("prohibited")
    monkeypatch.setattr("clipforge.campaign.operator.inventory_sources", lambda: prohibited)
    blocked_rights = _select(world, ["src-before-famous"])
    assert blocked_rights.status == "blocked"
    assert blocked_rights.reason_code == "rights_not_allowed"
    assert blocked_rights.sources[0].rights_state == "prohibited"
    monkeypatch.setattr("clipforge.campaign.operator.inventory_sources", lambda: _rights_catalogue("unknown"))
    unknown = _select(
        world,
        ["src-before-famous"],
        expected=_selection_sha(world.work, blocked_rights.selection_id),
    )
    assert unknown.reason_code == "rights_not_allowed"
    assert unknown.sources[0].rights_state == "unknown"
    monkeypatch.undo()

    media = world.sources["src-before-famous"].media
    media.write_bytes(b"changed")
    changed = _select(world, ["src-before-famous"], expected=_selection_sha(world.work, unknown.selection_id))
    assert changed.status == "blocked"
    assert changed.reason_code == "source_changed"
    assert changed.sources[0].rights_state == "allowed"
    media.write_bytes(b"media-before")
    missing_expect = _selection_sha(world.work, changed.selection_id)
    media.unlink()
    missing = _select(world, ["src-before-famous"], expected=missing_expect)
    assert missing.reason_code == "missing_source"
    media.write_bytes(b"media-before")

    target = media.with_name("real.mp4")
    target.write_bytes(media.read_bytes())
    media.unlink()
    media.symlink_to(target)
    linked = _select(world, ["src-before-famous"], expected=_selection_sha(world.work, missing.selection_id))
    assert linked.reason_code == "symlink"
    media.unlink()
    holder = media.parent / "held"
    holder.mkdir()
    moved = holder / media.name
    moved.write_bytes(target.read_bytes())
    alias = media.parent / "alias"
    alias.symlink_to(holder, target_is_directory=True)
    parent_link = alias / media.name
    _set_uri(world, "asset-before", parent_link.as_uri())
    parent = _select(world, ["src-before-famous"], expected=_selection_sha(world.work, linked.selection_id))
    assert parent.reason_code == "symlink"
    _set_uri(world, "asset-before", "https://example.com/video.mp4")
    remote = _select(world, ["src-before-famous"], expected=_selection_sha(world.work, parent.selection_id))
    assert remote.reason_code == "remote_source"
    _set_uri(world, "asset-before", "file:///tmp/../secret.mp4")
    traversed = _select(world, ["src-before-famous"], expected=_selection_sha(world.work, remote.selection_id))
    assert traversed.reason_code == "traversal"
    _set_uri(world, "asset-before", "file://C:\\secret.mp4")
    slashed = _select(world, ["src-before-famous"], expected=_selection_sha(world.work, traversed.selection_id))
    assert slashed.reason_code == "traversal"


def test_cross_project_sources_are_rejected(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False, split_projects=True)
    before = _snapshot(world.work, world.database.path)
    with pytest.raises(CampaignError) as mixed:
        _select(world, ["src-before-famous", "src-american-secret"])
    assert mixed.value.code == "mixed_project"
    assert _snapshot(world.work, world.database.path) == before


def test_import_is_append_only_and_rejects_before_write(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False)
    before = list(world.work.rglob("*"))
    with pytest.raises(CampaignError) as rejected:
        import_snapshot(
            world.work,
            b'{"schema_version":"1.0.0","nope":1}',
            database=world.database,
            project_id=world.project_id,
        )
    assert rejected.value.code == "invalid_document"
    assert list(world.work.rglob("*")) == before
    body = json.dumps(_import_fields(source_ids=["src-american-secret"])).encode()
    document = import_snapshot(world.work, body, database=world.database, project_id=world.project_id)
    assert document.status == "ready"
    assert document.source_ids == ["src-american-secret"]
    assert "https://" not in document.model_dump_json()
    lines = "\n".join(
        [
            json.dumps(_import_fields(source_ids=["src-before-famous"])),
            json.dumps(_import_fields(source_ids=["src-american-secret"])),
        ]
    ).encode()
    merged = import_snapshot(
        world.work,
        lines,
        database=world.database,
        project_id=world.project_id,
        expected_sidecar_sha256=_selection_sha(world.work, document.selection_id),
    )
    assert merged.source_ids == ["src-american-secret", "src-before-famous"]
    withheld = json.dumps(_import_fields(source_ids=["src-before-famous"], selection_state="withheld")).encode()
    with pytest.raises(CampaignError) as held:
        import_snapshot(
            world.work,
            withheld,
            database=world.database,
            project_id=world.project_id,
            expected_sidecar_sha256=_selection_sha(world.work, merged.selection_id),
        )
    assert held.value.code == "not_selected"
    assert catalogue_fingerprint()


def test_run_uses_only_the_selection_and_cache(tmp_path: Path) -> None:
    world = _world(tmp_path)
    calls: list[str] = []
    selected = _select(world, ["src-before-famous"], narration=True)

    def probe(language: str, script: str) -> None:
        calls.append(language + script)

    first = run_selection(
        world.database,
        world.work,
        selected.selection_id,
        created_by="operator",
        narration_probe=probe,
    )
    shown = json.loads(status_text(world.work, first))
    assert shown["source_ids"] == ["src-before-famous"]
    assert shown["status"] == "succeeded"
    assert calls == []
    assert _job_count(world.database) == 1
    deliveries = {path.parent.name for path in world.work.glob("deliveries/*/manifest.json")}
    second = run_selection(
        world.database,
        world.work,
        selected.selection_id,
        created_by="operator",
        narration_probe=probe,
    )
    assert second == first
    assert calls == []
    assert _job_count(world.database) == 1
    assert {path.parent.name for path in world.work.glob("deliveries/*/manifest.json")} == deliveries
    assert json.loads(status_text(world.work, second))["fingerprint"] == shown["fingerprint"]
    server = open_campaign_board(work_root=world.work, port=0, database=world.database)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request

        port = int(server.server_address[1])
        runs = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/campaigns/antoine-sallis/runs").read()
        )
        assert runs["runs"][0]["campaign_run_id"] == first
        detail = json.loads(
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/campaign-runs/{first}/source/src-before-famous"
            ).read()
        )
        assert detail["fingerprint"] == shown["fingerprint"]
        assert detail["delivery_relative"].startswith("deliveries/")
        assert detail["readiness"] == "locally_deliverable"
        assert "/home/" not in json.dumps(detail)
        assert "file://" not in json.dumps(detail)
    finally:
        server.shutdown()
        server.server_close()


def test_resume_retries_only_the_incomplete_source(tmp_path: Path) -> None:
    world = _world(tmp_path)
    selected = _select(world, ["src-before-famous", "src-american-secret"], narration=True)
    secret_qa = world.sources["src-american-secret"].qa
    original = secret_qa.read_bytes()
    secret_qa.unlink()
    run_id = run_selection(world.database, world.work, selected.selection_id, created_by="operator")
    shown = json.loads(status_text(world.work, run_id))
    by_id = {item["source_id"]: item for item in shown["sources"]}
    assert by_id["src-before-famous"]["status"] == "succeeded"
    assert by_id["src-american-secret"]["status"] != "succeeded"
    famous_delivery = by_id["src-before-famous"]["delivery_id"]
    secret_qa.write_bytes(original)
    resumed = resume_run(world.database, world.work, run_id, created_by="operator")
    assert resumed == run_id
    restored = json.loads(status_text(world.work, resumed))
    restored_by_id = {item["source_id"]: item for item in restored["sources"]}
    assert restored_by_id["src-before-famous"]["status"] == "succeeded"
    assert restored_by_id["src-before-famous"]["delivery_id"] == famous_delivery
    assert restored_by_id["src-american-secret"]["status"] == "succeeded"
    media = world.sources["src-american-secret"].media
    media.write_bytes(media.read_bytes() + b"-stale")
    again = resume_run(world.database, world.work, run_id, created_by="operator")
    assert again == run_id
    stale = json.loads(status_text(world.work, again))
    stale_by_id = {item["source_id"]: item for item in stale["sources"]}
    assert stale_by_id["src-before-famous"]["status"] == "succeeded"
    assert stale_by_id["src-before-famous"]["delivery_id"] == famous_delivery
    assert stale_by_id["src-american-secret"]["reason_code"] == "source_changed"


def test_read_only_cli_leaves_bytes_unchanged(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False)
    selected = _select(world, ["src-american-secret"])
    run_id = run_selection(world.database, world.work, selected.selection_id, created_by="operator")
    before = _snapshot(world.work, world.database.path)
    selection_hash = _selection_sha(world.work, selected.selection_id)
    base = [
        "--db",
        str(world.database.path),
        "--work-dir",
        str(world.work),
    ]
    commands = [
        ["campaign", "operator", "doctor"],
        ["campaign", "operator", "list"],
        ["campaign", "operator", "show", "antoine-sallis"],
        ["campaign", "operator", "sources", "antoine-sallis"],
        ["campaign", "operator", "verify", selected.selection_id, *base],
        ["campaign", "operator", "status", run_id, "--work-dir", str(world.work)],
    ]
    for command in commands:
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.stderr
    assert _snapshot(world.work, world.database.path) == before
    assert _selection_sha(world.work, selected.selection_id) == selection_hash
    help_text = runner.invoke(app, ["campaign", "operator", "--help"])
    assert help_text.exit_code == 0
    for name in ("doctor", "list", "show", "sources", "select", "verify", "run", "resume", "status", "import"):
        assert name in help_text.stdout
    root = runner.invoke(app, ["--help"])
    for absent in ("transcribe", "render", "upload"):
        assert absent not in root.stdout


def test_board_is_loopback_read_only_and_ordered(tmp_path: Path) -> None:
    with pytest.raises(CampaignError) as refused:
        require_loopback("0.0.0.0")
    assert refused.value.code == "loopback_required"
    with pytest.raises(CampaignError):
        require_loopback("localhost")
    leaked = None
    try:
        leaked = open_campaign_board(work_root=tmp_path, host="0.0.0.0", port=0)
    except CampaignError as exc:
        assert exc.code == "loopback_required"
    finally:
        if leaked is not None:
            leaked.server_close()
    assert leaked is None
    assert static_bundle_text() == "PASS campaign board"
    world = _world(tmp_path, narrate=False)
    _copy_envato(world.work)
    before = _snapshot(world.work, world.database.path)
    server = open_campaign_board(work_root=world.work, port=0, database=world.database)
    host, port = server.server_address
    assert host == "127.0.0.1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request

        payload = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/campaigns").read())
        assert payload["whop_live"] == "not_configured"
        assert payload["publishing"] == "deferred"
        assert payload["envato"] == "discovery_only"
        detail = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/campaigns/antoine-sallis").read()
        )
        ids = [item["source_id"] for item in detail["sources"]]
        assert ids == sorted(ids)
        assert "src-before-famous" in ids
        famous = next(item for item in detail["sources"] if item["source_id"] == "src-before-famous")
        assert famous["rights_state"] == "allowed"
        assert famous["verification"] == "verified"
        assert famous["duration_us"] == 1_000_000
        assert "/home/" not in json.dumps(detail)
        assert "file://" not in json.dumps(detail)
        assert detail["envato_records"]
        assert detail["envato_records"][0]["renderable"] is False
        assert detail["envato_records"][0]["item_url"].startswith("https://")
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode("utf-8")
        assert "autoplay" not in page
        script = urllib.request.urlopen(f"http://127.0.0.1:{port}/app.js").read().decode("utf-8")
        assert "innerHTML" not in script
        assert "eval(" not in script
        assert "https://" not in script
        assert "http://" not in script
        styles = urllib.request.urlopen(f"http://127.0.0.1:{port}/styles.css").read().decode("utf-8")
        assert "https://" not in styles
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/campaigns", method="POST", data=b"{}")
        with pytest.raises(urllib.error.HTTPError) as posted:
            urllib.request.urlopen(request)
        assert posted.value.code == 405
    finally:
        server.shutdown()
        server.server_close()
    assert _snapshot(world.work, world.database.path) == before
    ordered = board_sources("antoine-sallis", world.database)
    assert [item["source_id"] for item in ordered["sources"]] == sorted(
        item["source_id"] for item in ordered["sources"]
    )
    assert board_campaign("antoine-sallis", world.work, world.database)["campaign_id"] == "antoine-sallis"


@pytest.mark.browser
def test_operator_board_escapes_text_in_chrome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        browser = resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))

    def fake(campaign_id: str, work_root: Path | None = None, database: object = None) -> dict[str, object]:
        del work_root, database
        return {
            "campaign_id": campaign_id,
            "title": "<script>alert(1)</script>",
            "policy_id": "policy",
            "policy_fingerprint": "ab",
            "language": "en-US",
            "alignment": "verified_live",
            "narration": "verified_live",
            "voicestudio": "kittentts",
            "publishing": "deferred",
            "whop_live": "not_configured",
            "envato": "discovery_only",
            "policy_rules": [
                {
                    "rule_id": "rule-1",
                    "name": "<b>policy</b>",
                    "outcome": "allowed",
                    "description": "<img src=x onerror=alert(1)>",
                }
            ],
            "sources": [
                {
                    "source_id": "src-before-famous",
                    "display_name": "<script>alert(1)</script>",
                    "notes": "<script>alert(2)</script>",
                    "rights_state": "allowed",
                    "selected": True,
                    "verification": "verified",
                    "reason_code": "ready",
                    "source_sha256": "a" * 64,
                    "duration_us": 1000000,
                    "size_bytes": 4,
                    "language": "en-US",
                    "narration": "verified_live",
                }
            ],
            "envato_records": [],
        }

    monkeypatch.setattr("clipforge.campaign.board.board_campaign", fake)
    server = open_campaign_board(work_root=tmp_path, port=0)
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
        page = dumped.stdout
        assert "antoine-sallis" in page
        assert "autoplay" not in page
        assert "<script>alert" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
        assert "&lt;b&gt;policy&lt;/b&gt;" in page
        assert "/home/" not in page
        assert "https://" not in page
    finally:
        server.shutdown()
        server.server_close()


def _select(
    world,
    source_ids: list[str],
    *,
    project_id: str | None = None,
    language: str = "en-US",
    narration: bool = False,
    expected: str | None = None,
):
    return select_sources(
        world.work,
        campaign_id="antoine-sallis",
        source_ids=source_ids,
        project_id=world.project_id if project_id is None else project_id,
        operator_id="operator-1",
        language=language,
        narration_enabled=narration,
        expected_sidecar_sha256=expected,
        database=world.database,
    )


def _rights_catalogue(rights: str) -> list[object]:
    rows: list[object] = []
    from clipforge.campaign.antoine import inventory_sources

    for item in inventory_sources():
        if item.source_id == "src-before-famous":
            rows.append(
                SimpleNamespace(
                    source_id=item.source_id,
                    download_status="planned",
                    rights_state=rights,
                    display_name=item.display_name,
                    size_bytes=item.size_bytes,
                )
            )
        else:
            rows.append(item)
    return rows


def _set_uri(world, asset_id: str, uri: str) -> None:
    with world.database.transaction() as connection:
        connection.execute("UPDATE source_assets SET uri = ? WHERE source_asset_id = ?", (uri, asset_id))


def _snapshot(work: Path, database: Path) -> tuple[int, int]:
    files = 0
    for path in work.rglob("*"):
        if path.is_file() and not path.is_symlink():
            files += path.stat().st_size
    return files, database.stat().st_size


def _selection_sha(work: Path, selection_id: str) -> str:
    path = work / "campaigns" / "selections" / selection_id / "selection.json"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _import_fields(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "campaign_id": "antoine-sallis",
        "source_ids": ["src-before-famous"],
        "language": "en-US",
        "narration_enabled": False,
        "operator_id": "operator-1",
        "policy_state": "catalogue",
        "selection_state": "selected",
    }
    payload.update(overrides)
    return payload


def _selection_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "selection_id": "sel-1",
        "campaign_id": "antoine-sallis",
        "project_id": "project-1",
        "source_ids": ["src-before-famous"],
        "sources": [
            {
                "schema_version": "1.0.0",
                "source_id": "src-before-famous",
                "source_sha256": "a" * 64,
                "rights_state": "allowed",
            }
        ],
        "language": "en-US",
        "narration_enabled": False,
        "narration_policy": "disabled",
        "operator_id": "operator-1",
        "created_at": stamp().isoformat(),
        "catalogue_fingerprint": "b" * 64,
        "policy_fingerprint": "c" * 64,
        "evidence_fingerprint": "d" * 64,
        "status": "ready",
        "reason_code": "ready",
        "provenance": {
            "schema_version": "1.0.0",
            "created_at": stamp().isoformat(),
            "created_by": "operator-1",
            "tool": "clipforge-operator",
            "tool_version": "0.1.0",
            "source_asset_ids": ["src-before-famous"],
            "parent_artifact_ids": [],
            "job_id": None,
            "inputs_sha256": "d" * 64,
        },
    }


def _copy_envato(work: Path) -> None:
    source = Path("docs/operations/assets/antoine-sallis/asset_download_requests.json")
    target = work / "assets" / "antoine-sallis" / "asset_download_requests.json"
    target.parent.mkdir(parents=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
