"""Read-only visual-analysis verification. Does not load a model or decode video."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from clipforge.errors import ClipforgeError, MediaError, StorageError
from clipforge.media import recipes
from clipforge.media.cache import cache_identity_matches, read_cache_record
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.mutation import inspect_mutation
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.governance import require_rights_cleared
from clipforge.schemas.ingest import SourceIngestManifest
from clipforge.schemas.jobs import JobRecord
from clipforge.schemas.vision import VisualAnalysisDocument
from clipforge.storage import (
    ArtifactRow,
    Database,
    find_artifact,
    get_asset_license_record,
    get_job,
    get_source_asset,
    get_source_manifest,
)
from clipforge.vision.cache import read_visual_cache
from clipforge.vision.constants import KIND_VISUAL
from clipforge.vision.integrity import visual_problems
from clipforge.vision.models import face_model_is_cached

Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True, slots=True)
class VerifyLine:
    status: Status
    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class VisionVerifyReport:
    source_asset_id: str
    lines: tuple[VerifyLine, ...]

    @property
    def status(self) -> Status:
        if any(line.status == "FAIL" for line in self.lines):
            return "FAIL"
        if any(line.status == "WARN" for line in self.lines):
            return "WARN"
        return "PASS"


def verify_vision(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    model_root: Path | None = None,
) -> VisionVerifyReport:
    """Check lineage and evidence bytes. A missing face model is a warning."""
    lines: list[VerifyLine] = []
    try:
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
            manifest = get_source_manifest(connection, source_asset_id)
            license_record = get_asset_license_record(connection, source.license_record_id)
            proxy_row = find_artifact(connection, source.project_id, source_asset_id, recipes.KIND_PROXY)
            visual_row = find_artifact(connection, source.project_id, source_asset_id, KIND_VISUAL)
    except StorageError as exc:
        return VisionVerifyReport(source_asset_id, (VerifyLine("FAIL", "source", str(exc)),))
    if source.project_id != manifest.project_id:
        lines.append(VerifyLine("FAIL", "project", "source and manifest are in different projects"))
    else:
        lines.append(VerifyLine("PASS", "project", source.project_id))
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
    workspace = SourceWorkspace(work_root.resolve(), source.project_id, source_asset_id)
    current_proxy = _check_proxy(lines, database, workspace, manifest, proxy_row)
    _check_analysis(lines, workspace, visual_row, current_proxy, database)
    _check_model(lines, model_root)
    return VisionVerifyReport(source_asset_id, tuple(lines))


def _check_proxy(
    lines: list[VerifyLine],
    database: Database,
    workspace: SourceWorkspace,
    manifest: SourceIngestManifest,
    row: ArtifactRow | None,
) -> str | None:
    path = workspace.proxy_file("analysis.mp4")
    sidecar = workspace.metadata_file("analysis-proxy.recipe.json")
    record = read_cache_record(sidecar)
    if record is None or not cache_identity_matches(
        record,
        recipe_name=recipes.ANALYSIS_PROXY_NAME,
        recipe_version=recipes.ANALYSIS_PROXY_VERSION,
        source_sha256=manifest.content_sha256,
        project_id=manifest.project_id,
        source_asset_id=manifest.source_asset_id,
        video_stream_index=manifest.video_stream_index,
        audio_stream_index=manifest.audio_stream_index,
        artifact_path=path,
    ):
        lines.append(VerifyLine("FAIL", "proxy", "analysis proxy is missing or does not match this source"))
        return None
    if row is None or row.job_id is None or row.provenance.job_id != row.job_id:
        lines.append(VerifyLine("FAIL", "proxy_job", "analysis proxy artifact has no producing job"))
        return None
    try:
        job = get_job_from(database, row.job_id)
    except StorageError as exc:
        lines.append(VerifyLine("FAIL", "proxy_job", str(exc)))
        return None
    if job.kind != recipes.JOB_MEDIA_PREPARE or job.status.value != "succeeded":
        lines.append(VerifyLine("FAIL", "proxy_job", f"producing job is {job.kind}/{job.status.value}"))
        return None
    payload_source = job.payload.get("source_asset_id")
    if payload_source is not None and payload_source != manifest.source_asset_id:
        lines.append(VerifyLine("FAIL", "proxy_job", "producing job names a different source"))
        return None
    lines.append(VerifyLine("PASS", "proxy", f"sha256 {record.artifact_sha256[:12]}"))
    return record.artifact_sha256


def _check_analysis(
    lines: list[VerifyLine],
    workspace: SourceWorkspace,
    row: ArtifactRow | None,
    current_proxy: str | None,
    database: Database,
) -> None:
    record = read_visual_cache(workspace.vision_sidecar())
    if row is None or row.job_id is None or record is None:
        lines.append(VerifyLine("FAIL", "analysis", "visual analysis artifact or sidecar is missing"))
        return
    try:
        path = path_from_file_uri(row.uri)
        document = VisualAnalysisDocument.model_validate_json(path.read_text(encoding="utf-8"))
        job: JobRecord | None = get_job_from(database, row.job_id)
    except (OSError, ValidationError, ValueError, MediaError, StorageError) as exc:
        lines.append(VerifyLine("FAIL", "analysis", str(exc)))
        return
    problems = visual_problems(
        document,
        record,
        analysis_path=path,
        work_root=workspace.root,
        current_proxy_sha256=current_proxy,
        artifact_job_id=row.job_id,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
    )
    if problems:
        lines.append(VerifyLine("FAIL", "analysis", "; ".join(problems)))
        return
    lines.append(
        VerifyLine(
            "PASS",
            "analysis",
            f"{document.analysis_id} scenes {document.summary.scene_count} "
            f"faces {document.summary.face_detection_count}",
        )
    )


def _check_model(lines: list[VerifyLine], model_root: Path | None) -> None:
    if model_root is None:
        lines.append(VerifyLine("WARN", "face_model", "no model root was provided"))
        return
    if model_root.is_symlink():
        lines.append(VerifyLine("WARN", "face_model", "model root is a symlink and was not followed"))
        return
    if not face_model_is_cached(model_root):
        lines.append(VerifyLine("WARN", "face_model", "face detector model is not cached"))
        return
    lines.append(VerifyLine("PASS", "face_model", "face detector model is cached"))


def get_job_from(database: Database, job_id: str) -> JobRecord:
    with database.connect() as connection:
        return get_job(connection, job_id)
