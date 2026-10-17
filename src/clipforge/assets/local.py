"""Campaign-provided local material uses the existing Advanced Hero rights gate."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from clipforge import __version__
from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import (
    AssetCatalogEntry,
    confine_file_uri,
    confine_work_path,
    load_catalog,
)
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_to_file_uri
from clipforge.media.probe import read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.media.workspace import SourceWorkspace, advanced_hero_lock
from clipforge.schemas.governance import (
    AssetKind,
    AssetLicenseRecord,
    AssetReference,
    RightsStatus,
    require_rights_cleared,
)
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import (
    Database,
    get_project,
    get_source_asset,
    insert_asset_license_record,
    list_asset_license_records,
)

LocalAssetKind = Literal["graphic", "audio"]
_TOOL = "clipforge.assets.local"


@dataclass(frozen=True, slots=True)
class LocalAssetRegistration:
    asset_id: str
    license_record_id: str
    source_asset_id: str
    relative_path: str
    sha256: str
    kind: LocalAssetKind
    cache_status: Literal["hit", "miss"]


def _fingerprint(project_id: str, kind: str, digest: str, evidence_hash: str, tags: list[str]) -> str:
    body = json.dumps(
        ["campaign-local-v1", project_id, kind, digest, evidence_hash, tags],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def register_local_asset(
    *,
    database: Database,
    work_root: Path,
    project_id: str,
    source_asset_id: str,
    relative_file: str,
    license_relative: str,
    kind: LocalAssetKind,
    confirm_rights: bool = False,
    content_tags: list[str] | None = None,
) -> LocalAssetRegistration:
    """Hash, decode and bind a campaign asset; no download or editorial approval.

    Changed bytes, evidence or tags get a new identity. Existing catalog
    entries and license rows are never replaced. Decode runs outside SQLite
    transactions. The source Advanced Hero lock protects catalog promotion.
    """
    if not confirm_rights:
        raise MediaError("--confirm-rights is required; campaign-provided rights are an operator assertion")
    if kind not in {"graphic", "audio"}:
        raise MediaError("local asset kind must be graphic or audio")
    root = work_root.resolve()
    with database.connect() as connection:
        get_project(connection, project_id)
        source = get_source_asset(connection, source_asset_id)
    if source.project_id != project_id:
        raise MediaError(f"source {source_asset_id} belongs to another project")
    media = confine_work_path(root, relative_file, label="campaign asset")
    evidence = confine_work_path(root, license_relative, label="campaign asset evidence")
    if not media.is_file() or media.stat().st_size <= 0:
        raise MediaError("campaign asset is missing or empty")
    if not evidence.is_file() or not evidence.read_bytes().strip():
        raise MediaError("campaign asset evidence is missing or empty")
    digest = sha256_file(media)
    evidence_hash = sha256_file(evidence)
    now = datetime.now(UTC)
    reference = AssetReference(
        asset_id="pending-local-asset",
        project_id=project_id,
        uri=path_to_file_uri(media),
        kind=AssetKind(kind),
        license_record_id="pending-local-license",
        content_tags=content_tags or [],
        provenance=ArtifactProvenance(
            created_at=now,
            created_by=os.environ.get("USER", "operator").strip()[:200] or "operator",
            tool=_TOOL,
            tool_version=__version__,
            source_asset_ids=[source_asset_id],
        ),
    )
    tags = sorted(reference.content_tags)
    identity = _fingerprint(project_id, kind, digest, evidence_hash, tags)
    asset_id = f"campaign-{identity}"
    license_id = f"lic-{asset_id}"
    reference.asset_id = asset_id
    reference.license_record_id = license_id
    reference.content_tags = tags
    reference.provenance.inputs_sha256 = identity
    record = AssetLicenseRecord(
        license_record_id=license_id,
        asset_id=asset_id,
        status=RightsStatus.CAMPAIGN_PROVIDED,
        license_name="campaign-provided local asset",
        evidence_uri=path_to_file_uri(evidence),
        notes="Explicit operator rights assertion; not independent legal verification.",
        recorded_at=now,
        recorded_by=reference.provenance.created_by,
    )
    workspace = SourceWorkspace(root, project_id, source_asset_id)
    workspace.ensure()
    with advanced_hero_lock(workspace):
        confine_work_path(
            root, workspace.advanced_asset_catalog().relative_to(root).as_posix(), label="asset catalog"
        )
        entries = load_catalog(workspace)
        matches = [item for item in entries if item.reference.asset_id == asset_id]
        if len(matches) > 1:
            raise MediaError("advanced asset catalog contains duplicate asset ids")
        if matches:
            current = matches[0]
            if (
                current.relative_path != relative_file
                or current.file_sha256 != digest
                or current.reference.model_dump(exclude={"provenance"})
                != reference.model_dump(exclude={"provenance"})
                or current.reference.provenance.source_asset_ids != [source_asset_id]
                or current.reference.provenance.inputs_sha256 != identity
                or current.reference.provenance.tool != _TOOL
            ):
                raise MediaError("campaign asset conflicts with its existing catalog identity")
        _decode(media, kind)
        if sha256_file(media) != digest or sha256_file(evidence) != evidence_hash:
            raise MediaError("campaign asset or evidence changed during registration")
        # Rights first: a failed catalog promotion leaves no usable catalog
        # entry. Retrying can safely reuse the durable license row.
        with database.transaction() as connection:
            licenses = list_asset_license_records(connection, asset_id)
            if licenses:
                if len(licenses) != 1 or licenses[0].license_record_id != license_id:
                    raise MediaError("campaign asset has conflicting rights records")
                prior = licenses[0]
                require_rights_cleared(prior)
                if prior.status != record.status or prior.evidence_uri != record.evidence_uri:
                    raise MediaError("campaign asset has conflicting rights evidence")
            else:
                insert_asset_license_record(connection, record)
        if not matches:
            _publish_catalog(workspace, [*entries, AssetCatalogEntry(reference, relative_file, digest)])
    return LocalAssetRegistration(
        asset_id, license_id, source_asset_id, relative_file, digest, kind, "hit" if matches else "miss"
    )


def validate_local_asset_evidence(
    work_root: Path, entry: AssetCatalogEntry, record: AssetLicenseRecord
) -> None:
    """Rehash evidence at the shared planning/render/QA/delivery gate."""
    if entry.reference.provenance.tool != _TOOL:
        return  # Preserve legacy catalogs under their recorded recipe.
    if not record.evidence_uri:
        raise MediaError("campaign asset evidence is missing")
    evidence = confine_file_uri(work_root, record.evidence_uri, label="campaign asset evidence")
    if not evidence.is_file() or not evidence.read_bytes().strip():
        raise MediaError("campaign asset evidence is missing or empty")
    fingerprint = _fingerprint(
        entry.reference.project_id,
        entry.reference.kind.value,
        entry.file_sha256,
        sha256_file(evidence),
        sorted(entry.reference.content_tags),
    )
    if fingerprint != entry.reference.provenance.inputs_sha256:
        raise MediaError("campaign asset evidence or content tags changed after registration")
    if entry.reference.asset_id != f"campaign-{fingerprint}":
        raise MediaError("campaign asset identity does not match its registered dependencies")


def _decode(media: Path, kind: LocalAssetKind) -> None:
    runner = ProcessRunner()
    probe = read_ffprobe_json(media, runner, log_path=None)
    streams = probe.get("streams", [])
    required = "video" if kind == "graphic" else "audio"
    if not any(isinstance(item, dict) and item.get("codec_type") == required for item in streams):
        raise MediaError(f"campaign asset has no {required} stream for kind {kind}")
    runner.run(
        [
            resolve_ffmpeg(),
            "-v",
            "error",
            "-xerror",
            "-i",
            str(media),
            "-map",
            "0:v:0" if kind == "graphic" else "0:a:0",
            "-f",
            "null",
            "-",
        ],
        timeout_s=300,
    )


def _publish_catalog(workspace: SourceWorkspace, entries: list[AssetCatalogEntry]) -> None:
    catalog = workspace.advanced_asset_catalog()
    confine_work_path(workspace.root, catalog.relative_to(workspace.root).as_posix(), label="asset catalog")
    rows = [
        {
            **item.reference.model_dump(mode="json"),
            "relative_path": item.relative_path,
            "file_sha256": item.file_sha256,
        }
        for item in entries
    ]
    partial = workspace.partial_for(catalog)
    try:
        with partial.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps({"assets": rows}, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, catalog)
    finally:
        partial.unlink(missing_ok=True)
