"""Local B-roll and SFX checks. Remote URLs and uncleared rights fail closed."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import SourceWorkspace, ensure_within
from clipforge.schemas.advanced import AssetBinding
from clipforge.schemas.governance import AssetLicenseRecord, AssetReference, RightsStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import Database, get_asset_license_record

_CLEARED = {RightsStatus.OWNED, RightsStatus.LICENSED, RightsStatus.CAMPAIGN_PROVIDED}


@dataclass(frozen=True, slots=True)
class AssetCatalogEntry:
    """An asset reference plus the local file hash. The file path is not stored in the plan."""

    reference: AssetReference
    relative_path: str
    file_sha256: str


def catalog_path(workspace: SourceWorkspace) -> Path:
    return workspace.advanced_asset_catalog()


def load_catalog(workspace: SourceWorkspace) -> list[AssetCatalogEntry]:
    path = catalog_path(workspace)
    if not path.is_file() or path.is_symlink():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MediaError(f"advanced asset catalog could not be read: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("assets"), list):
        raise MediaError("advanced asset catalog must be an object with an assets list")
    entries: list[AssetCatalogEntry] = []
    for item in payload["assets"]:
        if not isinstance(item, dict):
            raise MediaError("advanced asset catalog entry must be an object")
        relative = item.get("relative_path")
        digest = item.get("file_sha256")
        if not isinstance(relative, str) or not isinstance(digest, str):
            raise MediaError("advanced asset catalog entry is missing a path or hash")
        body = {key: value for key, value in item.items() if key not in {"relative_path", "file_sha256"}}
        try:
            reference = AssetReference.model_validate(body)
        except ValidationError as exc:
            raise MediaError(f"advanced asset catalog entry is not valid: {exc}") from exc
        entries.append(AssetCatalogEntry(reference, relative, digest))
    return entries


def confine_work_path(work_root: Path, relative: str, *, label: str) -> Path:
    """Reject escapes and symlinks before resolving the path."""
    if not relative or relative.startswith(("/", "\\")) or "\\" in relative or "\x00" in relative:
        raise MediaError(f"{label} path escapes the work root")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise MediaError(f"{label} path escapes the work root")
    current = work_root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise MediaError(f"{label} is a symlink")
    resolved = current.resolve()
    ensure_within(work_root, resolved)
    return resolved


def confine_file_uri(work_root: Path, uri: str, *, label: str) -> Path:
    """Apply the same lexical checks to a file URI."""
    if "\\" in uri or ".." in uri.split("/"):
        raise MediaError(f"{label} path escapes the work root")
    if not uri.startswith("file:"):
        raise MediaError(f"{label} must be a file URI under the work root")
    raw = path_from_file_uri(uri)
    try:
        relative = raw.relative_to(work_root)
    except ValueError as exc:
        raise MediaError(f"{label} path escapes the work root") from exc
    return confine_work_path(work_root, relative.as_posix(), label=label)


def require_asset(
    database: Database,
    workspace: SourceWorkspace,
    *,
    project_id: str,
    asset_id: str,
    expected_kind: str,
    work_root: Path,
) -> tuple[AssetCatalogEntry, AssetLicenseRecord, Path]:
    """Return one cleared local asset. A failure happens before any job row is inserted."""
    entry = next((item for item in load_catalog(workspace) if item.reference.asset_id == asset_id), None)
    if entry is None:
        raise MediaError(f"advanced asset {asset_id} is not in the local catalog")
    if entry.reference.project_id != project_id:
        raise MediaError(f"advanced asset {asset_id} belongs to another project")
    if entry.reference.kind.value != expected_kind:
        raise MediaError(
            f"advanced asset {asset_id} kind is {entry.reference.kind.value}, expected {expected_kind}"
        )
    if entry.reference.kind.value == "envato":
        raise MediaError("Envato assets are not searched or downloaded in this round")
    _reject_remote(entry.reference.uri, "asset uri")
    path = _local_file(workspace, entry, work_root)
    if path.is_symlink():
        raise MediaError(f"advanced asset {asset_id} is a symlink")
    if not path.is_file():
        raise MediaError(f"advanced asset {asset_id} file is missing")
    ensure_within(work_root, path)
    digest = sha256_file(path)
    if digest != entry.file_sha256:
        raise MediaError(f"advanced asset {asset_id} hash does not match the catalog")
    try:
        license_record = _license(database, entry.reference.license_record_id)
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError(f"advanced asset {asset_id} license record is missing") from exc
    if license_record.asset_id != asset_id:
        raise MediaError(f"advanced asset {asset_id} license names another asset")
    if license_record.status not in _CLEARED:
        status = license_record.status.value
        raise MediaError(f"advanced asset {asset_id} rights status is {status}. Editorial use is blocked.")
    if not license_record.evidence_uri or not license_record.evidence_uri.strip():
        raise MediaError(f"advanced asset {asset_id} license evidence is missing")
    _reject_remote(license_record.evidence_uri, "license evidence")
    return entry, license_record, path


def binding_for(entry: AssetCatalogEntry, license_record: AssetLicenseRecord) -> AssetBinding:
    kind = "audio" if entry.reference.kind.value == "audio" else "graphic"
    return AssetBinding(
        asset_id=entry.reference.asset_id,
        project_id=entry.reference.project_id,
        kind=kind,  # type: ignore[arg-type]
        sha256=entry.file_sha256,
        license_record_id=license_record.license_record_id,
        license_status=license_record.status.value,  # type: ignore[arg-type]
        provenance_sha256=_provenance_sha(entry.reference.provenance),
        display_name=entry.reference.asset_id,
    )


def _license(database: Database, license_record_id: str) -> AssetLicenseRecord:
    from clipforge.errors import StorageError

    try:
        with database.connect() as connection:
            return get_asset_license_record(connection, license_record_id)
    except StorageError as exc:
        raise MediaError(f"advanced asset license record is missing: {exc}") from exc


def _local_file(workspace: SourceWorkspace, entry: AssetCatalogEntry, work_root: Path) -> Path:
    label = f"advanced asset {entry.reference.asset_id}"
    path = confine_work_path(work_root, entry.relative_path, label=label)
    if entry.reference.uri.startswith("file:"):
        declared = confine_file_uri(work_root, entry.reference.uri, label=label)
        if declared != path:
            raise MediaError(f"{label} uri does not match the catalog path")
    del workspace
    return path


def _reject_remote(value: str, label: str) -> None:
    lowered = value.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        raise MediaError(f"{label} rejects remote URLs")


def _provenance_sha(provenance: ArtifactProvenance) -> str:
    raw = json.dumps(provenance.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
