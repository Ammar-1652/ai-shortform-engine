"""Read-only rough-preview verification. This does not render or create directories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from clipforge.errors import ClipforgeError, MediaError, StorageError
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.mutation import inspect_mutation
from clipforge.media.workspace import SourceWorkspace, ensure_within
from clipforge.preview.constants import KIND_PREVIEW
from clipforge.preview.inputs import load_preview_inputs
from clipforge.preview.integrity import preview_problems
from clipforge.preview.service import default_profile
from clipforge.schemas.governance import require_rights_cleared
from clipforge.schemas.preview import RoughPreviewCacheRecord, RoughPreviewSetDocument
from clipforge.storage import (
    Database,
    find_artifact,
    get_asset_license_record,
    get_job,
    get_source_asset,
    get_source_manifest,
)
from clipforge.transcription.io import read_text

Status = Literal["PASS", "FAIL"]


@dataclass(frozen=True, slots=True)
class VerifyLine:
    status: Status
    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class PreviewVerifyReport:
    source_asset_id: str
    lines: tuple[VerifyLine, ...]

    @property
    def status(self) -> Status:
        if any(line.status == "FAIL" for line in self.lines):
            return "FAIL"
        return "PASS"


def verify_preview(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
) -> PreviewVerifyReport:
    """Check the current preview set without creating files, locks, or renders."""
    lines: list[VerifyLine] = []
    root = work_root.resolve()
    try:
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
            manifest = get_source_manifest(connection, source_asset_id)
            license_record = get_asset_license_record(connection, source.license_record_id)
    except StorageError as exc:
        return PreviewVerifyReport(source_asset_id, (VerifyLine("FAIL", "source", str(exc)),))
    try:
        require_rights_cleared(license_record)
    except ClipforgeError as exc:
        lines.append(VerifyLine("FAIL", "rights", str(exc)))
    else:
        lines.append(VerifyLine("PASS", "rights", license_record.status.value))
    try:
        inspect_mutation(path_from_file_uri(source.uri), manifest)
    except MediaError as exc:
        lines.append(VerifyLine("FAIL", "source_mutation", str(exc)))
    else:
        lines.append(VerifyLine("PASS", "source_mutation", "referenced source still matches the stored hash"))
    fingerprint = default_profile().fingerprint()
    sidecar = SourceWorkspace(root, source.project_id, source_asset_id).preview_sidecar()
    early_record = _read_record(sidecar)
    if early_record is not None:
        fingerprint = early_record.profile_fingerprint
    try:
        inputs = load_preview_inputs(
            database,
            source_asset_id,
            root,
            profile_fingerprint=fingerprint,
            create_workspace=False,
        )
    except MediaError as exc:
        lines.append(VerifyLine("FAIL", "upstream", str(exc)))
        return PreviewVerifyReport(source_asset_id, tuple(lines))
    lines.append(VerifyLine("PASS", "upstream", f"mining {inputs.candidate_document.mining_id}"))
    record = early_record
    with database.connect() as connection:
        row = find_artifact(connection, source.project_id, source_asset_id, KIND_PREVIEW)
        job = None
        if row is not None and row.job_id is not None:
            try:
                job = get_job(connection, row.job_id)
            except StorageError as exc:
                lines.append(VerifyLine("FAIL", "producer", str(exc)))
    if record is None or row is None or row.job_id is None:
        lines.append(VerifyLine("FAIL", "preview", "rough preview set or sidecar is missing"))
        return PreviewVerifyReport(source_asset_id, tuple(lines))
    try:
        path = path_from_file_uri(row.uri)
        workspace = inputs.pair.workspace
        expected = workspace.preview_run_dir(record.preview_set_id) / "manifest.json"
        ensure_within(root, path)
        if path != expected or path.is_symlink() or not path.is_file():
            raise MediaError(
                "preview artifact is not manifest.json inside this source's preview run"
            )
        document = RoughPreviewSetDocument.model_validate_json(read_text(path))
    except (OSError, ValidationError, ValueError, MediaError) as exc:
        lines.append(VerifyLine("FAIL", "preview_document", str(exc)))
        return PreviewVerifyReport(source_asset_id, tuple(lines))
    problems = preview_problems(
        document,
        record,
        manifest_path=path,
        work_root=root,
        workspace=inputs.pair.workspace,
        inputs=inputs,
        artifact_job_id=row.job_id,
        artifact_uri=row.uri,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
    )
    if problems:
        for problem in problems:
            lines.append(VerifyLine("FAIL", "preview", problem))
    else:
        lines.append(
            VerifyLine(
                "PASS",
                "preview",
                f"preview set {document.preview_set_id} rendered {document.summary.rendered_count}",
            )
        )
    return PreviewVerifyReport(source_asset_id, tuple(lines))


def _read_record(path: Path) -> RoughPreviewCacheRecord | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return RoughPreviewCacheRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None
