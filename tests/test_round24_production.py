"""Aggregate campaign production over the existing runner."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.campaign.aggregate import (
    cancel_production,
    produce,
    production_plan,
    production_report,
    resume_production,
    verify_production,
)
from clipforge.campaign.board import open_campaign_board
from clipforge.campaign.operator import select_sources
from clipforge.campaign.providers import CampaignError
from clipforge.cli.main import app
from clipforge.errors import MediaError
from clipforge.preview.browser import resolve_browser
from tests.test_round20_campaign import _world

runner = CliRunner()


def test_produce_is_cached_isolated_and_resumable(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False)
    selected = _select(world)
    before = _snapshot(world.work, world.database.path)
    assert "narration_not_requested" in production_plan(world.database, world.work, selected.selection_id)
    assert _snapshot(world.work, world.database.path) == before
    calls: list[str] = []

    def probe(language: str, script: str) -> None:
        calls.append(language + script)

    first = produce(
        world.database,
        world.work,
        selected.selection_id,
        operator_id="operator-1",
        narration_probe=probe,
    )
    assert first.status == "succeeded"
    assert calls == []
    assert first.publishing == "deferred"
    assert "needs_operator_confirmation" not in first.model_dump_json()
    assert "/home/" not in first.model_dump_json()
    assert "file://" not in first.model_dump_json()
    assert [item.source_id for item in first.sources] == ["src-american-secret", "src-before-famous"]
    assert {item.narration_status for item in first.sources} == {"narration_not_requested"}
    assert {item.alignment_status for item in first.sources} == {"whisperx"}
    assert all(item.review_decision == "approved" for item in first.sources)
    assert all(item.qa_set_id for item in first.sources)
    relatives = [item.delivery_relative for item in first.sources]
    assert all(item is not None and item.startswith("deliveries/") for item in relatives)
    report = production_report(world.work, first.run_id)
    assert "review approved" in report
    assert "narration_not_requested" in report
    assert verify_production(world.database, world.work, first.run_id).startswith("PASS")
    pipeline_jobs = _jobs(world.database, "campaign_production")
    manifest = _manifest_bytes(world.work, first.run_id)
    second = produce(
        world.database,
        world.work,
        selected.selection_id,
        operator_id="operator-1",
        narration_probe=probe,
    )
    assert second.run_id == first.run_id
    assert calls == []
    assert _jobs(world.database, "campaign_production") == pipeline_jobs
    assert _manifest_bytes(world.work, first.run_id) == manifest
    forced = produce(
        world.database,
        world.work,
        selected.selection_id,
        operator_id="operator-1",
        force=True,
    )
    assert forced.run_id != first.run_id
    assert _manifest_path(world.work, first.run_id).is_file()


def test_one_source_failure_resume_and_change(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False)
    secret_qa = world.sources["src-american-secret"].qa
    original = secret_qa.read_bytes()
    secret_qa.unlink()
    selected = _select(world)
    partial = produce(world.database, world.work, selected.selection_id, operator_id="operator-1")
    assert partial.status == "partial"
    by_id = {item.source_id: item for item in partial.sources}
    assert by_id["src-before-famous"].status == "succeeded"
    assert by_id["src-american-secret"].status != "succeeded"
    famous_delivery = by_id["src-before-famous"].delivery_id
    secret_qa.write_bytes(original)
    resumed = resume_production(world.database, world.work, partial.run_id, operator_id="operator-1")
    assert resumed.run_id == partial.run_id
    assert resumed.status == "succeeded"
    resumed_by_id = {item.source_id: item for item in resumed.sources}
    assert resumed_by_id["src-before-famous"].delivery_id == famous_delivery
    assert resumed_by_id["src-american-secret"].status == "succeeded"
    media = world.sources["src-american-secret"].media
    media.write_bytes(media.read_bytes() + b"-changed")
    changed = produce(world.database, world.work, selected.selection_id, operator_id="operator-1")
    assert changed.run_id != resumed.run_id
    changed_by_id = {item.source_id: item for item in changed.sources}
    assert changed_by_id["src-before-famous"].status == "succeeded"
    assert changed_by_id["src-american-secret"].failure_code == "source_changed"
    with pytest.raises(CampaignError):
        verify_production(world.database, world.work, resumed.run_id)


def test_promotion_failure_keeps_the_previous_manifest(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False)
    selected = _select(world)
    first = produce(world.database, world.work, selected.selection_id, operator_id="operator-1")
    previous = _manifest_bytes(world.work, first.run_id)

    def hook(name: str) -> None:
        if name == "final_rename":
            raise CampaignError("promote failed", code="promotion_failed")

    with pytest.raises(CampaignError) as failed:
        produce(
            world.database,
            world.work,
            selected.selection_id,
            operator_id="operator-1",
            force=True,
            promotion_hook=hook,
        )
    assert failed.value.code == "promotion_failed"
    assert _manifest_bytes(world.work, first.run_id) == previous
    assert list((world.work / "campaigns" / "production").glob("*/*.partial")) == []


def test_read_only_commands_and_stale_selection(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False)
    selected = _select(world)
    produced = produce(world.database, world.work, selected.selection_id, operator_id="operator-1")
    before = _snapshot(world.work, world.database.path)
    base = ["--db", str(world.database.path), "--work-dir", str(world.work)]
    work = ["--work-dir", str(world.work)]
    commands = [
        ["campaign", "operator", "production-plan", selected.selection_id, *base],
        ["campaign", "operator", "production-show", produced.run_id, *work],
        ["campaign", "operator", "production-list", "antoine-sallis", *work],
        ["campaign", "operator", "production-verify", produced.run_id, *base],
        ["campaign", "operator", "production-report", produced.run_id, *work],
    ]
    for command in commands:
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.stderr
    assert _snapshot(world.work, world.database.path) == before
    with pytest.raises(CampaignError, match="reload before saving") as stale:
        produce(
            world.database,
            world.work,
            selected.selection_id,
            operator_id="operator-1",
            expected_selection_sha256="ab" * 32,
        )
    assert stale.value.code == "stale_selection"


def test_narration_request_and_unsupported_language(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(tmp_path)
    selected = _select(world, narration=True)
    calls: list[str] = []
    produced = produce(
        world.database,
        world.work,
        selected.selection_id,
        operator_id="operator-1",
        narration_probe=lambda _language, _script: calls.append("called"),
    )
    assert calls == []
    narrated = next(item for item in produced.sources if item.source_id == "src-before-famous")
    quiet = next(item for item in produced.sources if item.source_id == "src-american-secret")
    assert narrated.narration_status == "verified_live"
    assert narrated.narration_artifact_id
    assert quiet.narration_status == "narration_not_requested"
    monkeypatch.setattr(
        "clipforge.campaign.aggregate.capability_for",
        lambda _language: (_ for _ in ()).throw(ValueError("unsupported_language")),
    )
    with pytest.raises(CampaignError) as unsupported:
        produce(world.database, world.work, selected.selection_id, operator_id="operator-1")
    assert unsupported.value.code == "unsupported_language"


def test_cancel_and_board_routes(tmp_path: Path) -> None:
    world = _world(tmp_path, narrate=False)
    secret_qa = world.sources["src-american-secret"].qa
    secret_qa.unlink()
    selected = _select(world)
    partial = produce(world.database, world.work, selected.selection_id, operator_id="operator-1")
    cancelled = cancel_production(world.work, partial.run_id)
    by_id = {item.source_id: item for item in cancelled.sources}
    assert by_id["src-before-famous"].status == "succeeded"
    assert by_id["src-american-secret"].status == "cancelled"
    server = open_campaign_board(work_root=world.work, port=0, database=world.database)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request

        port = int(server.server_address[1])
        listed = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/campaigns/antoine-sallis/productions").read()
        )
        assert listed["productions"][0]["run_id"] == cancelled.run_id
        detail = json.loads(
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/campaign-productions/{cancelled.run_id}"
            ).read()
        )
        assert "/home/" not in json.dumps(detail)
        source = json.loads(
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/campaign-productions/{cancelled.run_id}/source/src-before-famous"
            ).read()
        )
        assert source["source_id"] == "src-before-famous"
        delivery = json.loads(
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/campaign-productions/{cancelled.run_id}/delivery"
            ).read()
        )
        assert delivery["deliveries"]
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_production_board_smoke(tmp_path: Path) -> None:
    try:
        browser = resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    world = _world(tmp_path, narrate=False)
    selected = _select(world)
    produce(world.database, world.work, selected.selection_id, operator_id="operator-1")
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
        assert "productions" in dumped.stdout
        assert "autoplay" not in dumped.stdout
    finally:
        server.shutdown()
        server.server_close()


def _select(world, *, narration: bool = False):
    return select_sources(
        world.work,
        campaign_id="antoine-sallis",
        source_ids=["src-american-secret", "src-before-famous"],
        project_id=world.project_id,
        operator_id="operator-1",
        narration_enabled=narration,
        database=world.database,
    )


def _snapshot(work: Path, database: Path) -> tuple[int, int]:
    total = 0
    for path in work.rglob("*"):
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total, database.stat().st_size


def _jobs(database, kind: str) -> int:
    with database.connect() as connection:
        row = connection.execute("SELECT COUNT(*) FROM jobs WHERE kind = ?", (kind,)).fetchone()
    assert row is not None
    return int(row[0])


def _manifest_path(work: Path, run_id: str) -> Path:
    return work / "campaigns" / "production" / run_id / "manifest.json"


def _manifest_bytes(work: Path, run_id: str) -> bytes:
    return _manifest_path(work, run_id).read_bytes()
