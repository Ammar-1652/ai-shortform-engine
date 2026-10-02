"""Register a local file on an existing project. Does not build a proxy or transcribe."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from clipforge import __version__
from clipforge.errors import MediaError, StorageError
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import (
    normalize_evidence_reference,
    path_to_file_uri,
    require_local_media_file,
)
from clipforge.media.probe import probe_file
from clipforge.media.process import ProcessRunner
from clipforge.media.recipes import KIND_PROBE
from clipforge.media.workspace import SourceWorkspace, atomic_replace, ensure_within
from clipforge.schemas.governance import AssetLicenseRecord, RightsStatus
from clipforge.schemas.ingest import NormalizedMediaProbe, SourceIngestManifest
from clipforge.schemas.media import SourceAsset
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import (
    Database,
    find_source_manifest_by_hash,
    get_project,
    insert_artifact,
    insert_asset_license_record,
    insert_source_asset,
    insert_source_manifest,
)

_ASSERTION = "User assertion recorded by clipforge source ingest. This is not independent legal verification."


@dataclass(frozen=True, slots=True)
class IngestResult:
    source_asset_id: str
    project_id: str
    deduplicated: bool
    content_sha256: str
    video_stream_index: int
    audio_stream_index: int | None
    canonical_duration_us: int
    video_origin_us: int
    audio_offset_us: int | None
    transcription_eligible: bool
    storage_mode: str
    frame_timing: str
    hdr: str
    original_filename: str
    ffprobe_version: str


def ingest_source(
    *,
    database: Database,
    project_id: str,
    source: str,
    rights_status: str,
    rights_evidence: str,
    rights_name: str,
    confirm_rights: bool,
    work_root: Path,
    video_stream: int | None = None,
    audio_stream: int | None = None,
    recorded_by: str | None = None,
    runner: ProcessRunner | None = None,
) -> IngestResult:
    """Probe, hash, and store a referenced source. The file is not copied."""
    path = require_local_media_file(source)
    status = _require_asserted_rights(rights_status, confirm_rights)
    evidence = normalize_evidence_reference(rights_evidence)
    name = rights_name.strip()
    if not name:
        raise MediaError("rights name is required. Pass --rights-name. It is your label, not a legal finding.")
    if len(path.name) > 512:
        raise MediaError(f"filename is longer than 512 characters: {path.name}")
    actor = _actor(recorded_by)
    active = runner or ProcessRunner()
    root = work_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    log_path = root / "tmp" / f"probe-{uuid.uuid4().hex}.log"
    ensure_within(root, log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    raw, normalized = probe_file(
        path,
        active,
        video_override=video_stream,
        audio_override=audio_stream,
        log_path=log_path,
    )
    digest = sha256_file(path)
    stat = path.stat()
    now = datetime.now(UTC)
    try:
        with database.transaction() as connection:
            get_project(connection, project_id)
            existing = find_source_manifest_by_hash(connection, project_id, digest)
            if existing is not None:
                return _result(existing, deduplicated=True)
            source_asset_id = str(uuid.uuid4())
            license_record_id = str(uuid.uuid4())
            workspace = SourceWorkspace(root, project_id, source_asset_id)
            workspace.ensure()
            probe_path = workspace.metadata_file("ffprobe.json")
            manifest_path = workspace.metadata_file("ingest-manifest.json")
            _write_json(probe_path, raw, root)
            manifest = _manifest(
                source_asset_id=source_asset_id,
                project_id=project_id,
                digest=digest,
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                filename=path.name,
                probe=normalized,
                now=now,
            )
            _write_json(manifest_path, manifest.model_dump(mode="json"), root)
            uri = path_to_file_uri(path)
            if len(uri) > 2048:
                raise MediaError(f"source URI is longer than 2048 characters: {uri}")
            provenance = ArtifactProvenance(
                created_at=now,
                created_by=actor,
                tool="clipforge",
                tool_version=__version__,
                source_asset_ids=[source_asset_id],
                inputs_sha256=digest,
            )
            insert_asset_license_record(
                connection,
                AssetLicenseRecord(
                    license_record_id=license_record_id,
                    asset_id=source_asset_id,
                    status=status,
                    license_name=name[:300],
                    evidence_uri=evidence,
                    notes=_ASSERTION,
                    recorded_at=now,
                    recorded_by=actor,
                ),
            )
            insert_source_asset(
                connection,
                SourceAsset(
                    source_asset_id=source_asset_id,
                    project_id=project_id,
                    uri=uri,
                    license_record_id=license_record_id,
                    provenance=provenance,
                ),
            )
            insert_source_manifest(connection, manifest)
            probe_provenance = ArtifactProvenance(
                created_at=now,
                created_by=actor,
                tool="ffprobe",
                tool_version=normalized.ffprobe_version[:80],
                source_asset_ids=[source_asset_id],
                inputs_sha256=digest,
            )
            insert_artifact(
                connection,
                artifact_id=str(uuid.uuid4()),
                project_id=project_id,
                job_id=None,
                source_asset_id=source_asset_id,
                kind=KIND_PROBE,
                uri=path_to_file_uri(probe_path),
                provenance=probe_provenance,
            )
    except ValidationError as exc:
        raise MediaError(f"source metadata was rejected by the contract: {exc}") from exc
    except StorageError as exc:
        raise MediaError(str(exc)) from exc
    return _result(manifest, deduplicated=False)


def _require_asserted_rights(raw: str, confirm_rights: bool) -> RightsStatus:
    if not confirm_rights:
        raise MediaError(
            "explicit rights confirmation is required. Re-run with --confirm-rights. "
            "That flag records your assertion. It is not independent legal verification, "
            "and clipforge will not assume owned or licensed from the filename."
        )
    try:
        status = RightsStatus(raw.strip().lower())
    except ValueError as exc:
        raise MediaError(
            "rights status must be owned, licensed, or campaign_provided. "
            f"Received {raw!r}. UNKNOWN and PROHIBITED stay blocked."
        ) from exc
    if status in {RightsStatus.UNKNOWN, RightsStatus.PROHIBITED}:
        raise MediaError(
            f"rights status {status.value} cannot be ingested. "
            "UNKNOWN and PROHIBITED stay blocked. Clipforge did not assume a cleared status."
        )
    return status


def _manifest(
    *,
    source_asset_id: str,
    project_id: str,
    digest: str,
    size_bytes: int,
    mtime_ns: int,
    filename: str,
    probe: NormalizedMediaProbe,
    now: datetime,
) -> SourceIngestManifest:
    return SourceIngestManifest(
        source_asset_id=source_asset_id,
        project_id=project_id,
        content_sha256=digest,
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        original_filename=filename,
        storage_mode="referenced",
        transcription_eligible=probe.classification.transcription_eligible,
        video_stream_index=probe.selection.video_stream_index,
        audio_stream_index=probe.selection.audio_stream_index,
        canonical_duration_us=probe.timeline.canonical_duration_us,
        video_origin_us=probe.timeline.video_origin_us,
        ingested_at=now,
        probe=probe,
    )


def _result(manifest: SourceIngestManifest, *, deduplicated: bool) -> IngestResult:
    return IngestResult(
        source_asset_id=manifest.source_asset_id,
        project_id=manifest.project_id,
        deduplicated=deduplicated,
        content_sha256=manifest.content_sha256,
        video_stream_index=manifest.video_stream_index,
        audio_stream_index=manifest.audio_stream_index,
        canonical_duration_us=manifest.canonical_duration_us,
        video_origin_us=manifest.video_origin_us,
        audio_offset_us=manifest.probe.timeline.audio_offset_us,
        transcription_eligible=manifest.transcription_eligible,
        storage_mode=manifest.storage_mode,
        frame_timing=manifest.probe.classification.frame_timing.value,
        hdr=manifest.probe.classification.hdr.value,
        original_filename=manifest.original_filename,
        ffprobe_version=manifest.probe.ffprobe_version,
    )


def _write_json(path: Path, payload: object, root: Path) -> None:
    partial = path.with_name(f"{path.name}.partial.{uuid.uuid4().hex}")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    atomic_replace(partial, path, root)


def _actor(explicit: str | None) -> str:
    if explicit is not None and explicit.strip():
        return explicit.strip()[:200]
    try:
        import getpass

        return getpass.getuser()
    except OSError as exc:
        raise MediaError(f"could not determine the OS user for provenance: {exc}") from exc
