"""Offline Openverse normalization, rights, and network-boundary tests."""

from __future__ import annotations

import hashlib
import shutil
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from clipforge.assets.openverse import (
    FakeOpenverseProvider,
    OpenverseError,
    acquire_selection,
    evaluate_license,
    load_acquisition,
    select_media,
)
from clipforge.campaign.policy_fingerprint import current_policy_fingerprint
from clipforge.schemas.openverse import OpenverseLicenseEvidence, OpenverseMediaRecord, OpenverseSearchRequest
from clipforge.storage import Database


def _request(media_type: str = "audio") -> OpenverseSearchRequest:
    return OpenverseSearchRequest(
        media_type=media_type,
        query="soft tap",
        license_filter=["by"],
    )


def test_fake_openverse_search_normalizes_metadata_without_downloading() -> None:
    provider = FakeOpenverseProvider(
        [
            {
                "id": "audio-1",
                "title": "Soft tap",
                "creator": "Creator",
                "foreign_landing_url": "https://example.test/audio-1",
                "url": "https://cdn.example.test/audio-1.ogg",
                "license": "by",
                "license_version": "4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "attribution": "Creator, CC BY 4.0",
                "duration": 850,
                "filetype": "ogg",
                "tags": ["tap"],
            }
        ]
    )
    response = provider.search_offline(_request())
    record = response.results[0]
    assert record.duration_us == 850_000
    assert record.direct_download_url == "https://cdn.example.test/audio-1.ogg"
    state, reason = evaluate_license(record)
    assert state == "eligible_pending_verification"
    assert "verification" in reason
    selection = select_media(
        response,
        media_id="audio-1",
        policy_fingerprint="b" * 64,
    )
    assert selection.policy_status == "pending"
    evidence = OpenverseLicenseEvidence(
        media_id="audio-1",
        landing_url=record.landing_url,
        license_code="by",
        license_url=record.license_url or "https://creativecommons.org/licenses/by/4.0/",
        attribution=record.attribution,
        captured_response_sha256=response.response_sha256,
        verification_method="landing_page",
        verification_status="verified",
        checked_at="2026-10-24T00:00:00Z",
    )
    allowed = select_media(
        response,
        media_id="audio-1",
        policy_fingerprint="b" * 64,
        license_evidence=evidence,
    )
    assert allowed.policy_status == "allowed"


def test_unknown_openverse_license_is_blocked() -> None:
    record = OpenverseMediaRecord(
        media_id="image-1",
        media_type="image",
        title="Image",
        landing_url="https://example.test/image-1",
        source_response_sha256="a" * 64,
        discovered_at="2026-10-24T00:00:00Z",
    )
    state, reason = evaluate_license(record)
    assert state == "blocked"
    assert "unknown" in reason


def test_live_openverse_is_fail_closed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLIPFORGE_OPENVERSE_LIVE", raising=False)
    provider = FakeOpenverseProvider([])
    with pytest.raises(OpenverseError, match="disabled"):
        provider.search(_request())


def test_openverse_rejects_insecure_urls() -> None:
    with pytest.raises(ValidationError):
        OpenverseMediaRecord(
            media_id="image-1",
            media_type="image",
            title="Image",
            landing_url="http://example.test/image-1",
            source_response_sha256="a" * 64,
            discovered_at="2026-10-24T00:00:00Z",
        )


def test_verified_openverse_selection_acquires_hash_bound_bytes(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("clipforge.assets.openverse._validate_acquired_media", lambda _path, _kind: None)
    monkeypatch.setattr(
        "clipforge.assets.openverse.register_local_asset",
        lambda **_kwargs: SimpleNamespace(asset_id="asset-openverse", license_record_id="lic-openverse"),
    )
    provider = FakeOpenverseProvider(
        [
            {
                "id": "audio-2",
                "title": "Tap",
                "foreign_landing_url": "https://example.test/audio-2",
                "url": "https://cdn.example.test/audio-2.ogg",
                "license": "by",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "attribution": "Creator",
                "duration": 100,
                "filetype": "ogg",
            }
        ]
    )
    response = provider.search_offline(_request())
    record = response.results[0]
    evidence = OpenverseLicenseEvidence(
        media_id=record.media_id,
        landing_url=record.landing_url,
        license_code="by",
        license_url=record.license_url or "https://creativecommons.org/licenses/by/4.0/",
        attribution="Creator",
        captured_response_sha256=response.response_sha256,
        verification_method="landing_page",
        verification_status="verified",
        checked_at="2026-10-24T00:00:00Z",
        captured_evidence_path="license.txt",
        captured_evidence_sha256="0" * 64,
    )
    license_file = tmp_path / "license.txt"
    license_file.write_text("verified license capture", encoding="utf-8")
    evidence = evidence.model_copy(
        update={"captured_evidence_sha256": hashlib.sha256(license_file.read_bytes()).hexdigest()}
    )
    selection = select_media(
        response,
        media_id=record.media_id,
        policy_fingerprint=current_policy_fingerprint("test-campaign"),
        license_evidence=evidence,
        campaign_id="test-campaign",
        intended_role="sfx",
    )
    work = tmp_path / "work"
    work.mkdir()
    shutil.copy2(license_file, work / "license.txt")
    manifest = acquire_selection(
        selection,
        database=Database(tmp_path / "db.sqlite3"),
        project_id="project-1",
        source_asset_id="source-1",
        work_root=work,
        fetch_bytes=lambda _url, _cap: b"audio-bytes",
    )
    assert manifest.file_sha256
    loaded = load_acquisition(work / manifest.relative_path.replace("/media", "/manifest.json"), work_root=work)
    assert loaded == manifest
