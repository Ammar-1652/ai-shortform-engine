from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.assets.credentials import PortalCredentials
from clipforge.assets.handoff import _inspect, create_envato_requests
from clipforge.assets.mcp_client import AssetError
from clipforge.assets.portal_bridge import (
    EnvatoPortalBridge,
    PortalLicense,
    _safe_https_url,
    extract_media_archive,
)
from clipforge.campaign.policy_fingerprint import current_policy_fingerprint
from clipforge.cli.main import app
from clipforge.schemas.assets import AssetSearchHit
from clipforge.schemas.envato_asset import EnvatoAssetRequest

runner = CliRunner()


def _zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def test_portal_url_allowlist_rejects_user_controlled_hosts() -> None:
    assert _safe_https_url("https://audio-downloads.envatousercontent.com/a.zip", label="media")
    assert _safe_https_url(
        "https://elements.envato.com/api/v1/license_certificates/x.pdf", label="license", allow_envato_api=True
    )
    with pytest.raises(AssetError, match="allowlisted"):
        _safe_https_url("https://envatousercontent.com.attacker.example/a.zip", label="media")
    with pytest.raises(AssetError, match="allowlisted"):
        _safe_https_url(
            "https://elements.envato.com.attacker.example/x.pdf", label="license", allow_envato_api=True
        )


def test_extract_media_archive_is_bounded_and_preserves_extension(tmp_path: Path) -> None:
    archive = tmp_path / "download.zip"
    content = b"RIFF" + b"audio" * 100
    _zip(archive, {"nested/Click.wav": content})

    target, size, digest = extract_media_archive(
        archive,
        tmp_path / "media",
        media_kind="audio",
        max_bytes=10_000,
    )

    assert target.name == "media.wav"
    assert target.read_bytes() == content
    assert size == len(content)
    assert digest == hashlib.sha256(content).hexdigest()


def test_extract_media_archive_rejects_ambiguous_or_traversal_members(tmp_path: Path) -> None:
    ambiguous = tmp_path / "ambiguous.zip"
    _zip(ambiguous, {"a.wav": b"a", "b.wav": b"b"})
    with pytest.raises(AssetError, match="multiple files"):
        extract_media_archive(ambiguous, tmp_path / "media", media_kind="audio", max_bytes=100)

    traversal = tmp_path / "traversal.zip"
    _zip(traversal, {"../escape.wav": b"x"})
    with pytest.raises(AssetError, match="unsafe path"):
        extract_media_archive(traversal, tmp_path / "media", media_kind="audio", max_bytes=100)


def test_portal_data_parsers_do_not_expose_signed_url_in_license_record() -> None:
    bridge = EnvatoPortalBridge(PortalCredentials("operator@example.test", "not-a-real-password"))
    bridge._domain = "https://envato.mytoolsplan.site"
    bridge._bsid = "session-cookie-value-123456"
    signed = "https://audio-downloads.envatousercontent.com/files/a.zip?signature=redacted"
    license_raw = (
        '[{"_1":2},"data",{"_3":4,"_5":6},"success",true,"license",{"_7":8,'
        '"id","license-123","itemUuid","00000000-0000-0000-0000-000000000001",'
        '"name","clipforge test","licenseType","project","createdAt","2026-10-16T00:00:00Z",'
        '"licenseFileDownloadUrl","https://elements.envato.com/api/v1/license_certificates/x.pdf",'
        '"licenseFilePending",false}]'
    )
    bridge._request = lambda url, **kwargs: license_raw.encode()  # type: ignore[method-assign]
    license_record = bridge._create_license("00000000-0000-0000-0000-000000000001", "clipforge test")
    assert isinstance(license_record, PortalLicense)
    assert license_record.certificate_url.endswith("x.pdf")
    assert signed not in repr(license_record)


def test_resolve_item_binds_mcp_page_to_portal_uuid() -> None:
    bridge = EnvatoPortalBridge(PortalCredentials("operator@example.test", "not-a-real-password"))
    bridge._domain = "https://envato.mytoolsplan.site"
    bridge._bsid = "session-cookie-value-123456"
    payload = {
        "page": {
            "data": {
                "data": {
                    "item": {
                        "id": "DUPX5FG",
                        "itemUuid": "00000000-0000-0000-0000-000000000001",
                        "title": "Click",
                        "itemType": "music",
                    }
                }
            }
        }
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    html = f"<script>window.INITIAL_HYDRATION_DATA={json.dumps(encoded)}</script>"
    bridge._request = lambda url, **kwargs: html.encode()  # type: ignore[method-assign]
    identity = bridge.resolve_item("https://elements.envato.com/click-DUPX5FG")
    assert identity.item_id == "DUPX5FG"
    assert identity.item_uuid == "00000000-0000-0000-0000-000000000001"
    assert identity.item_type == "music"


def test_fetch_item_downloads_media_and_certificate_through_bounded_writer(tmp_path: Path) -> None:
    bridge = EnvatoPortalBridge(PortalCredentials("operator@example.test", "not-a-real-password"))
    bridge._domain = "https://envato.mytoolsplan.site"
    bridge._bsid = "session-cookie-value-123456"
    license_record = PortalLicense(
        license_id="license-123",
        item_uuid="00000000-0000-0000-0000-000000000001",
        name="clipforge test",
        license_type="project",
        created_at="2026-10-16T00:00:00Z",
        certificate_url="https://elements.envato.com/api/v1/license_certificates/x.pdf",
        pending=False,
    )
    bridge._create_license = lambda *_args: license_record  # type: ignore[method-assign]
    bridge._signed_download_url = lambda *_args: "https://audio-downloads.envatousercontent.com/a.zip"  # type: ignore[method-assign]

    def write_download(url: str, destination: Path, **kwargs: object) -> tuple[int, str]:
        content = b"%PDF-1.4 certificate" if kwargs.get("expected_prefix") else b"zip-bytes"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return len(content), hashlib.sha256(content).hexdigest()

    bridge._download_to = write_download  # type: ignore[method-assign]
    result = bridge.fetch_item(
        item_uuid=license_record.item_uuid,
        item_type="music",
        project_name="clipforge test",
        media_path=tmp_path / "media.zip",
        license_path=tmp_path / "license.pdf",
    )
    assert result.media_bytes == len(b"zip-bytes")
    assert result.license_bytes == len(b"%PDF-1.4 certificate")
    assert result.media_path.read_bytes() == b"zip-bytes"
    assert result.license_path.read_bytes().startswith(b"%PDF")


def test_fetch_checks_campaign_policy_before_opening_portal_session(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    request = create_envato_requests(
        work,
        query="click",
        filters={"asset_type": "audio"},
        campaign_id="antoine-sallis",
        provider="envato_mcp",
        provider_version="3.4.7",
        hits=[
            AssetSearchHit(
                request_id="request-click",
                provider="envato_mcp",
                title="Click",
                item_url="https://elements.envato.com/click-DUPX5FG",
                asset_type="audio",
                campaign_policy_decision="blocked",
                rejection_reason="outside_media_prohibited_by_campaign_policy",
                created_at=datetime.now(UTC),
            )
        ],
        supported_filters={},
        deferred_filters={},
    )[0]
    assert request.policy_fingerprint == current_policy_fingerprint("antoine-sallis")
    result = runner.invoke(
        app,
        [
            "assets",
            "envato",
            "fetch",
            "--request",
            request.request_id,
            "--project",
            "project-1",
            "--portal-item-uuid",
            "00000000-0000-0000-0000-000000000001",
            "--work-dir",
            str(work),
        ],
    )
    assert result.exit_code == 1
    assert "outside media is prohibited" in result.output
    assert not (work / "incoming").exists()


def test_audio_asset_probe_accepts_pcm_wav_from_portal(tmp_path: Path) -> None:
    media = tmp_path / "incoming" / "sfx.wav"
    media.parent.mkdir()
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=0.25",
            "-c:a",
            "pcm_s16le",
            str(media),
        ],
        check=True,
        capture_output=True,
    )
    request = EnvatoAssetRequest(
        request_id="audio-probe",
        provider="envato_mcp",
        provider_version="3.4.7",
        query="click",
        media_kind="audio",
        intended_use="sfx",
        campaign_id="envato-bridge-test",
        policy_fingerprint=current_policy_fingerprint("envato-bridge-test"),
        created_at=datetime.now(UTC),
    )
    facts = _inspect(tmp_path, media, request)
    assert facts.audio_codec == "pcm_s16le"
    assert facts.video_codec is None
    assert facts.sample_rate == 44100
