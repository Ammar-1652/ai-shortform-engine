"""Campaign-provided local assets stay hash-bound and rights-gated."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clipforge.assets.local import register_local_asset
from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import load_catalog, require_asset
from clipforge.media.ingest import ingest_source
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.project import Project
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import Database, insert_project, list_asset_license_records
from tests.media_factory import synth_video


def _world(tmp_path: Path) -> tuple[Database, str, Path, str]:
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    project_id = "tarteel-project"
    now = datetime.now(UTC)
    project = Project(
        project_id=project_id,
        name="Tarteel",
        created_at=now,
        profile_id="profile-paid-campaign",
        provenance=ArtifactProvenance(
            created_at=now,
            created_by="pytest",
            tool="pytest",
            tool_version="0.1.0",
            source_asset_ids=[],
        ),
    )
    with database.transaction() as connection:
        insert_project(connection, project)
    source = synth_video(tmp_path, "source.mp4", audio=True, duration="1")
    evidence = tmp_path / "source-rights.md"
    evidence.write_text("campaign source rights", encoding="utf-8")
    ingested = ingest_source(
        database=database,
        project_id=project_id,
        source=str(source),
        rights_status="campaign_provided",
        rights_evidence=str(evidence),
        rights_name="Campaign source",
        confirm_rights=True,
        work_root=tmp_path / "work",
    )
    return database, project_id, tmp_path / "work", ingested.source_asset_id


def test_campaign_local_asset_is_hash_bound_idempotent_and_catalogued(tmp_path: Path) -> None:
    database, project_id, work, source_asset_id = _world(tmp_path)
    evidence = work / "campaigns/Tarteel/intake/rights.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("operator campaign rights assertion", encoding="utf-8")
    media = work / "campaigns/Tarteel/cta/cta.mp4"
    media.parent.mkdir(parents=True)
    shutil.copy2(tmp_path / "source.mp4", media)
    kwargs = {
        "database": database,
        "work_root": work,
        "project_id": project_id,
        "source_asset_id": source_asset_id,
        "relative_file": "campaigns/Tarteel/cta/cta.mp4",
        "license_relative": "campaigns/Tarteel/intake/rights.md",
        "kind": "graphic",
        "confirm_rights": True,
        "content_tags": ["cta", "campaign-provided"],
    }
    first = register_local_asset(**kwargs)
    second = register_local_asset(**kwargs)
    assert first.cache_status == "miss"
    assert second.cache_status == "hit"
    assert first.asset_id == second.asset_id
    workspace = SourceWorkspace(work, project_id, source_asset_id)
    catalog = load_catalog(workspace)
    assert len(catalog) == 1
    entry, rights, path = require_asset(
        database,
        workspace,
        project_id=project_id,
        asset_id=first.asset_id,
        expected_kind="graphic",
        work_root=work,
    )
    assert entry.reference.content_tags == ["campaign-provided", "cta"]
    assert rights.status.value == "campaign_provided"
    assert path == media
    with database.connect() as connection:
        assert len(list_asset_license_records(connection, first.asset_id)) == 1
    evidence.write_text("changed after registration", encoding="utf-8")
    with pytest.raises(MediaError, match="evidence or content tags changed"):
        require_asset(
            database,
            workspace,
            project_id=project_id,
            asset_id=first.asset_id,
            expected_kind="graphic",
            work_root=work,
        )


def test_campaign_local_asset_rejects_symlink_and_missing_confirmation(tmp_path: Path) -> None:
    database, project_id, work, source_asset_id = _world(tmp_path)
    evidence = work / "rights.md"
    evidence.write_text("rights", encoding="utf-8")
    media = work / "asset.mp4"
    shutil.copy2(tmp_path / "source.mp4", media)
    media_link = work / "link.mp4"
    media_link.symlink_to(media)
    with pytest.raises(MediaError, match="confirm-rights"):
        register_local_asset(
            database=database,
            work_root=work,
            project_id=project_id,
            source_asset_id=source_asset_id,
            relative_file="asset.mp4",
            license_relative="rights.md",
            kind="graphic",
        )
    with pytest.raises(MediaError, match="symlink"):
        register_local_asset(
            database=database,
            work_root=work,
            project_id=project_id,
            source_asset_id=source_asset_id,
            relative_file="link.mp4",
            license_relative="rights.md",
            kind="graphic",
            confirm_rights=True,
        )
