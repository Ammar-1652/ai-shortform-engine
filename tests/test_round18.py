"""Campaign policy, acquisition limits, language, narration, and Envato discovery."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from clipforge.assets.mcp_client import AssetError
from clipforge.assets.provider import (
    DryRunAssetDiscoveryProvider,
    EnvatoMcpDiscoveryProvider,
    FakeAssetDiscoveryProvider,
)
from clipforge.assets.service import acquire_local, search_assets, verify_asset, write_requests
from clipforge.campaign.antoine import FILES, selected_files
from clipforge.campaign.policy import caption_decision, evaluate_mode, footage_priority, language_decision
from clipforge.campaign.providers import (
    CampaignError,
    DryRunCampaignDiscoveryProvider,
    DryRunSourceProvider,
    FakeCampaignDiscoveryProvider,
    FakeSourceProvider,
    GoogleDriveSourceProvider,
    WhopCampaignProvider,
)
from clipforge.campaign.service import ingest_campaign, verify_campaign
from clipforge.errors import ClipforgeError, MediaError
from clipforge.language.matrix import capabilities, profiles, require_language, separate_translation
from clipforge.voice.plan import build_plan, render_plan, verify_plan, write_plan
from clipforge.voice.provider import FakeVoiceProvider
from tests.test_round15 import _chain


def test_only_two_sources_are_selected_and_under_200_mb() -> None:
    chosen = selected_files()
    assert len(chosen) == 2
    assert {item.drive_id for item in chosen} == {
        "12RKu2wuIgCccBpcwjhlbzEUM7lEt8vwN",
        "1IzZ6Klx6_y6stfhpa2q2Cf9qIK92eeim",
    }
    assert all(item.size_bytes < 200_000_000 for item in chosen)
    held = [item for item in FILES if not item.selected]
    assert len(held) == 3
    assert {item.download_status for item in held} == {"not_selected_for_round_18"}
    assert {item.drive_id for item in held} == {
        "1XNL03ZU4XPxeFxJMkiDeeLMnA-fqt9fu",
        "1VFb8LWdMnsJYultiTSH74trSDFW635hi",
        "1Cd7D2CR8_bMuGL9NcLDMnS2QXJ1eKxZC",
    }


def test_native_editor_is_allowed_and_black_box_is_blocked() -> None:
    assert evaluate_mode("clipforge_native_editor").decision == "allowed"
    assert evaluate_mode("external_black_box_ai_tool").decision == "blocked"
    assert evaluate_mode("human_supplied_asset", rights_evidenced=True).decision == "allowed"
    assert evaluate_mode("human_supplied_asset", external_media=True).decision == "blocked"
    assert evaluate_mode("voice_narration_provider").decision == "needs_operator_confirmation"
    assert evaluate_mode("voice_narration_provider", operator_confirmed=True).decision == "allowed"
    assert footage_priority() == "needs_operator_clarification"


def test_caption_review_and_effects() -> None:
    clean = "Antoine Sallis on credit. @antoinesallis #AntoineSallis #credit #wealth"
    assert caption_decision(clean, reviewed=True) == "allowed"
    assert caption_decision(clean, reviewed=False) == "needs_operator_confirmation"
    assert caption_decision(clean, effects=("glow",), reviewed=True) == "blocked"
    assert caption_decision(clean + " 💀", reviewed=True) == "blocked"
    assert caption_decision("Get rich quick @antoinesallis #AntoineSallis #a #b", reviewed=True) == "blocked"


def test_ingest_fetches_two_files_and_allowed_sources_need_no_confirmation(tmp_path: Path) -> None:
    # CampaignSource.rights_state is authoritative. The explicit allowed state
    # permits verification even when the operator-confirmed flag is omitted.
    unconfirmed = ingest_campaign(tmp_path / "unconfirmed", FakeSourceProvider(), operator_confirmed=False)
    assert all(
        item.rights_state == "allowed"
        for item in unconfirmed.sources
        if item.source_id in {row.source_id for row in selected_files()}
    )
    assert verify_campaign(tmp_path / "unconfirmed") == "PASS campaign inventory"

    provider = FakeSourceProvider()
    document = ingest_campaign(tmp_path, provider, operator_confirmed=True)
    acquired = [item for item in document.acquisitions if item.download_status == "acquired"]
    held = [item for item in document.acquisitions if item.download_status == "not_selected_for_round_18"]
    assert provider.calls == 2
    assert len(acquired) == 2
    assert len(held) == 3
    assert all(item.sha256 for item in acquired)
    assert verify_campaign(tmp_path) == "PASS campaign inventory"
    target = next(item for item in acquired if item.local_relative_path)
    path = tmp_path / str(target.local_relative_path)
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(CampaignError) as exc:
        verify_campaign(tmp_path)
    assert exc.value.code == "source_mutated"
    text = (tmp_path / "campaigns" / "antoine-sallis" / "inventory.json").read_text(encoding="utf-8")
    assert "bearer " not in text.lower()
    assert "token=" not in text.lower()


def test_drive_acquisition_persists_and_rechecks_probe_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = GoogleDriveSourceProvider()

    def fake_acquire(source_id: str, destination: Path) -> str:
        assert source_id in {row.source_id for row in selected_files()}
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"verified-media")
        return "acquired"

    facts = {
        "size_bytes": 14,
        "duration_us": 1_000_000,
        "width": 1920,
        "height": 1080,
        "video_codec": "h264",
        "audio_codec": "aac",
        "frame_rate": "30/1",
        "audio_sample_rate": 44100,
        "audio_channels": 2,
        "ffprobe_version": "6.1",
    }
    monkeypatch.setattr(provider, "acquire", fake_acquire)
    monkeypatch.setattr("clipforge.campaign.service._probe_facts", lambda _path: dict(facts))
    document = ingest_campaign(tmp_path, provider, operator_confirmed=False)
    acquired = [row for row in document.acquisitions if row.download_status == "acquired"]
    assert len(acquired) == 2
    assert all(row.probe_facts == facts for row in acquired)
    assert verify_campaign(tmp_path) == "PASS campaign inventory"


def test_probe_failure_removes_unverifiable_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = GoogleDriveSourceProvider()

    def fake_acquire(_source_id: str, destination: Path) -> str:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"unverified-media")
        return "acquired"

    def fail_probe(_path: Path) -> dict[str, str | int | None]:
        raise MediaError("ffprobe failed")

    monkeypatch.setattr(provider, "acquire", fake_acquire)
    monkeypatch.setattr("clipforge.campaign.service._probe_facts", fail_probe)
    with pytest.raises(CampaignError, match="probed"):
        ingest_campaign(tmp_path, provider)
    assert not list((tmp_path / "campaigns").rglob("*.mp4"))


def test_drive_provider_does_not_download_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("drive provider opened a socket")

    monkeypatch.setattr(socket, "socket", explode)
    provider = GoogleDriveSourceProvider()
    document = ingest_campaign(tmp_path, provider)
    assert all(
        item.download_status == "provider_unavailable"
        for item in document.acquisitions
        if item.source_id in {row.source_id for row in selected_files()}
    )
    assert provider.calls == 2


def test_unselected_source_is_rejected() -> None:
    with pytest.raises(CampaignError) as exc:
        FakeSourceProvider().acquire("src-sept-1", Path("ignored.mp4"))
    assert exc.value.code == "not_selected_for_round_18"
    assert DryRunSourceProvider().acquire("src-before-famous", Path("ignored.mp4")) == "planned"


def test_whop_providers_store_no_secrets() -> None:
    fake = FakeCampaignDiscoveryProvider()
    rows = fake.discover()
    assert rows[0]["campaign_id"] == "antoine-sallis"
    assert "password" not in json.dumps(rows).lower()
    assert DryRunCampaignDiscoveryProvider().discover() == []
    with pytest.raises(CampaignError) as exc:
        WhopCampaignProvider().discover()
    assert exc.value.code == "not_configured"


def test_translation_does_not_replace_source_text() -> None:
    document = separate_translation(
        source_asset_id="source-1",
        source_language="en-US",
        target_language="ar",
        source_text="Café costs €10.",
        translated_text="مرحبا بالعالم",
    )
    assert document.source_text == "Café costs €10."
    assert document.translated_text != document.source_text
    assert document.text_direction == "rtl"
    japanese = separate_translation(
        source_asset_id="source-1",
        source_language="ja",
        target_language="en-US",
        source_text="価格は100円です。",
        translated_text="The price is 100 yen.",
    )
    assert "円" in japanese.source_text
    assert language_decision("fr-FR") == "needs_operator_confirmation"
    assert language_decision("en-US") == "allowed"
    with pytest.raises(ValueError, match="unsupported_language"):
        require_language("zh-CN")
    assert any(item.language == "ar" and item.text_direction == "rtl" for item in profiles())
    whisper = [item for item in capabilities() if item.provider_id == "whisperx" and item.language == "ja"]
    assert whisper[0].supported_status == "not_claimed"


def test_envato_maps_supported_filters_and_rejects_unsupported() -> None:
    class StubClient:
        url = "https://mcp.envato.com/mcp"
        server_version = "test"

        def __init__(self) -> None:
            self.arguments: dict[str, object] = {}
            self.calls = 0

        def initialize(self) -> dict[str, object]:
            return {}

        def list_tools(self) -> list[dict[str, object]]:
            return [
                {
                    "name": "search_stock_video",
                    "inputSchema": {
                        "additionalProperties": False,
                        "properties": {
                            "searchTerms": {"type": "string", "minLength": 1, "maxLength": 60},
                            "perPage": {"type": "integer", "minimum": 1, "maximum": 20},
                            "filters": {
                                "anyOf": [
                                    {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "orientation": {
                                                "anyOf": [
                                                    {"type": "string", "enum": ["horizontal", "vertical"]},
                                                    {"type": "null"},
                                                ]
                                            },
                                            "resolution": {
                                                "anyOf": [
                                                    {
                                                        "type": "string",
                                                        "enum": [
                                                            "720p (HD)",
                                                            "1080p (Full HD)",
                                                            "2K",
                                                            "4K (UHD)",
                                                        ],
                                                    },
                                                    {"type": "null"},
                                                ]
                                            },
                                            "categories": {
                                                "anyOf": [
                                                    {"type": "string", "enum": ["Stock Footage", "Motion Graphics"]},
                                                    {"type": "null"},
                                                ]
                                            },
                                        },
                                    },
                                    {"type": "null"},
                                ]
                            },
                        },
                        "required": ["searchTerms"],
                    },
                }
            ]

        def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
            assert name == "search_stock_video"
            self.calls += 1
            self.arguments = arguments
            return {"structuredContent": {"results": []}}

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setenv("CLIPFORGE_ENVATO_MCP_ENABLED", "1")
        monkeypatch.setenv("CLIPFORGE_ENVATO_MCP_LIVE_SMOKE", "1")
        client = StubClient()
        provider = EnvatoMcpDiscoveryProvider(client)  # type: ignore[arg-type]
        supported = {
            "asset_type": "video",
            "category": "Stock Footage",
            "orientation": "vertical",
            "resolution": "1080p",
        }
        assert provider.search("office", supported) == []
        assert client.arguments == {
            "searchTerms": "office",
            "perPage": 5,
            "filters": {
                "categories": "Stock Footage",
                "orientation": "vertical",
                "resolution": "1080p (Full HD)",
            },
        }
        with pytest.raises(AssetError, match="format") as exc:
            provider.search("office", {"asset_type": "video", "format": "mp4"})
        assert exc.value.code == "unsupported_filter"
        assert client.calls == 1
    finally:
        monkeypatch.undo()


def test_envato_search_does_not_invent_urls(tmp_path: Path) -> None:
    provider = FakeAssetDiscoveryProvider(
        rows=[
            {
                "provider": "fake",
                "title": "City street",
                "asset_type": "video",
                "format": ["mp4"],
            }
        ]
    )
    hits = search_assets(provider, query="city", filters={"category": "stock"}, campaign_id="antoine-sallis")
    assert hits[0].item_url is None
    assert hits[0].item_id is None
    assert hits[0].direct_download_url is None
    assert hits[0].campaign_policy_decision == "blocked"
    assert hits[0].rejection_reason == "outside_media_prohibited_by_campaign_policy"
    assert hits[0].download_status == "rejected"
    json_path, md_path = write_requests(
        tmp_path,
        hits,
        query="city",
        filters={"category": "stock"},
        campaign_id="antoine-sallis",
    )
    body = json_path.read_text(encoding="utf-8")
    assert "https://" not in body
    markdown = md_path.read_text(encoding="utf-8")
    assert "manual" in markdown or "not provided" in markdown
    with pytest.raises(AssetError, match="outside media"):
        acquire_local(
            tmp_path,
            json_path,
            tmp_path / "clip.mp4",
            license_statement="license",
            campaign_id="antoine-sallis",
        )


def test_manual_acquire_rejects_symlink_and_outside_path(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from clipforge.schemas.assets import AssetSearchHit

    hit = AssetSearchHit(
        request_id="req-1",
        provider="fake",
        title="Local loop",
        campaign_policy_decision="pending",
        created_at=datetime.now(UTC),
    )
    request = tmp_path / "asset_download_requests.json"
    request.write_text(
        json.dumps({"requests": [{"hit": hit.model_dump(mode="json")}]}),
        encoding="utf-8",
    )
    outside = tmp_path.parent / "outside-asset.bin"
    outside.write_bytes(b"asset-bytes")
    with pytest.raises(ClipforgeError):
        acquire_local(
            tmp_path / "work",
            request,
            outside,
            license_statement="licensed for this campaign",
            campaign_id="future-campaign",
        )
    work = tmp_path / "work"
    work.mkdir()
    local = work / "loop.wav"
    local.write_bytes(b"asset-bytes")
    link = work / "linked.wav"
    link.symlink_to(local)
    with pytest.raises(AssetError):
        acquire_local(
            work,
            request,
            link,
            license_statement="licensed for this campaign",
            campaign_id="future-campaign",
        )
    acquired = acquire_local(
        work,
        request,
        local,
        license_statement="licensed for this campaign",
        campaign_id="future-campaign",
    )
    assert acquired.sha256
    assert acquired.direct_download_url is None
    assert verify_asset(work, acquired).startswith("PASS")
    local.write_bytes(b"changed")
    with pytest.raises(AssetError, match="hash changed"):
        verify_asset(work, acquired)
    assert DryRunAssetDiscoveryProvider().search("city", {"genre": "ambient"}) == []


def test_narration_stays_off_until_enabled(tmp_path: Path) -> None:
    database, work = _chain(tmp_path)
    provider = FakeVoiceProvider()
    disabled = build_plan(
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="cand-1",
        script_text="Antoine Sallis explains credit.",
        language="en-US",
        enabled=False,
        operator_reason="narration does not improve this clip",
    )
    assert disabled.enabled is False
    assert disabled.campaign_policy_decision == "needs_operator_confirmation"
    write_plan(work, disabled)
    held = render_plan(database, work, disabled, provider, script_text="Antoine Sallis explains credit.")
    assert held is disabled
    assert provider.calls == 0
    assert verify_plan(database, work, disabled) == "PASS narration disabled"
    enabled = build_plan(
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="cand-1",
        script_text="Antoine Sallis explains credit.",
        language="en-US",
        enabled=True,
        operator_reason="narration clarifies the offer",
    )
    rendered = render_plan(database, work, enabled, provider, script_text="Antoine Sallis explains credit.")
    assert provider.calls == 1
    assert rendered.generated_audio_sha256
    assert verify_plan(database, work, rendered).startswith("PASS")
    with pytest.raises(ClipforgeError, match="script changed"):
        render_plan(database, work, enabled, provider, script_text="A different script.")
