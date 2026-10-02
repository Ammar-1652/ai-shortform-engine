"""Read-only transcript verification. Does not load a model or repair files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from clipforge.errors import ClipforgeError, MediaError, StorageError
from clipforge.media import recipes
from clipforge.media.cache import cache_identity_matches, read_cache_record
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.mutation import inspect_mutation
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.governance import require_rights_cleared
from clipforge.schemas.ingest import SourceIngestManifest
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import Transcript
from clipforge.storage import (
    ArtifactRow,
    Database,
    find_artifact,
    get_asset_license_record,
    get_job,
    get_source_asset,
    get_source_manifest,
)
from clipforge.transcription.cache import read_transcript_cache
from clipforge.transcription.constants import KIND_TRANSCRIPT, RECIPE_NAME, RECIPE_VERSION
from clipforge.transcription.integrity import document_sidecar_problems, producer_binding_problems
from clipforge.transcription.io import read_text
from clipforge.transcription.models import model_is_cached

Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True, slots=True)
class VerifyLine:
    status: Status
    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class TranscriptVerifyReport:
    source_asset_id: str
    lines: tuple[VerifyLine, ...]

    @property
    def status(self) -> Status:
        if any(line.status == "FAIL" for line in self.lines):
            return "FAIL"
        if any(line.status == "WARN" for line in self.lines):
            return "WARN"
        return "PASS"


def verify_transcript(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    model_root: Path | None = None,
) -> TranscriptVerifyReport:
    """Check lineage and bytes. A missing model cache is a warning, not a failure."""
    lines: list[VerifyLine] = []
    try:
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
            manifest = get_source_manifest(connection, source_asset_id)
            license_record = get_asset_license_record(connection, source.license_record_id)
            audio_row = find_artifact(connection, source.project_id, source_asset_id, recipes.KIND_ASR)
            transcript_row = find_artifact(connection, source.project_id, source_asset_id, KIND_TRANSCRIPT)
    except StorageError as exc:
        return TranscriptVerifyReport(source_asset_id, (VerifyLine("FAIL", "source", str(exc)),))
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
    if not manifest.transcription_eligible:
        lines.append(VerifyLine("FAIL", "eligibility", "source is not transcription-eligible"))
        return TranscriptVerifyReport(source_asset_id, tuple(lines))
    workspace = SourceWorkspace(work_root.resolve(), source.project_id, source_asset_id)
    current_asr_sha256 = _check_asr(lines, database, workspace, manifest, audio_row)
    _check_transcript(lines, database, workspace, manifest, transcript_row, model_root, current_asr_sha256)
    return TranscriptVerifyReport(source_asset_id, tuple(lines))


def format_transcript_report(report: TranscriptVerifyReport) -> str:
    lines = [f"status: {report.status}", f"source_asset_id: {report.source_asset_id}"]
    for line in report.lines:
        lines.append(f"[{line.status}] {line.name}: {line.detail}")
    return "\n".join(lines)


def _check_asr(
    lines: list[VerifyLine],
    database: Database,
    workspace: SourceWorkspace,
    manifest: SourceIngestManifest,
    audio_row: ArtifactRow | None,
) -> str | None:
    path = workspace.audio_file("asr.flac")
    sidecar = workspace.metadata_file("asr-audio.recipe.json")
    record = read_cache_record(sidecar)
    if (
        record is None
        or not path.is_file()
        or not cache_identity_matches(
            record,
            recipe_name=recipes.ASR_AUDIO_NAME,
            recipe_version=recipes.ASR_AUDIO_VERSION,
            source_sha256=manifest.content_sha256,
            project_id=manifest.project_id,
            source_asset_id=manifest.source_asset_id,
            video_stream_index=manifest.video_stream_index,
            audio_stream_index=manifest.audio_stream_index,
            artifact_path=path,
        )
    ):
        lines.append(VerifyLine("FAIL", "asr_audio", "ASR file, hash, or recipe does not match this source"))
        return None
    if audio_row is None or audio_row.job_id is None:
        lines.append(VerifyLine("FAIL", "asr_audio", "ASR artifact row is missing"))
        return None
    if audio_row.provenance.job_id != audio_row.job_id:
        lines.append(VerifyLine("FAIL", "asr_audio", "ASR artifact job id does not match provenance"))
        return None
    try:
        with database.connect() as connection:
            job = get_job(connection, audio_row.job_id)
    except StorageError as exc:
        lines.append(VerifyLine("FAIL", "asr_audio", str(exc)))
        return None
    if job.kind != recipes.JOB_MEDIA_PREPARE or job.status is not JobStatus.SUCCEEDED:
        lines.append(
            VerifyLine(
                "FAIL",
                "asr_audio",
                f"producing job {job.job_id} is {job.status.value}, expected succeeded",
            )
        )
        return None
    if job.project_id != manifest.project_id:
        lines.append(VerifyLine("FAIL", "asr_audio", "producing job is in another project"))
        return None
    lines.append(VerifyLine("PASS", "asr_audio", f"sha256 {record.artifact_sha256[:12]} recipe asr-audio-v1"))
    return record.artifact_sha256


def _check_transcript(
    lines: list[VerifyLine],
    database: Database,
    workspace: SourceWorkspace,
    manifest: SourceIngestManifest,
    transcript_row: ArtifactRow | None,
    model_root: Path | None,
    current_asr_sha256: str | None,
) -> None:
    path = workspace.transcript_file()
    sidecar_path = workspace.transcript_sidecar()
    record = read_transcript_cache(sidecar_path)
    if record is None or not path.is_file():
        lines.append(VerifyLine("FAIL", "transcript", "transcript file or recipe sidecar is missing"))
        return
    if (
        record.project_id != manifest.project_id
        or record.source_asset_id != manifest.source_asset_id
        or record.source_sha256 != manifest.content_sha256
        or record.recipe_name != RECIPE_NAME
        or record.recipe_version != RECIPE_VERSION
        or record.asr_recipe_name != recipes.ASR_AUDIO_NAME
        or record.asr_recipe_version != recipes.ASR_AUDIO_VERSION
    ):
        lines.append(
            VerifyLine("FAIL", "transcript_cache", "sidecar project, source, recipe, or source hash differs")
        )
        return
    try:
        size = path.stat().st_size
        digest = sha256_file(path)
        document = Transcript.model_validate_json(read_text(path))
    except (OSError, ValidationError, UnicodeError, MediaError) as exc:
        lines.append(VerifyLine("FAIL", "transcript", str(exc)))
        return
    if size != record.size_bytes or digest != record.artifact_sha256:
        lines.append(
            VerifyLine("FAIL", "transcript_hash", "transcript size or SHA-256 does not match the sidecar")
        )
        return
    if document.project_id != manifest.project_id or document.source_asset_id != manifest.source_asset_id:
        lines.append(VerifyLine("FAIL", "transcript_lineage", "transcript names another project or source"))
        return
    problems = document_sidecar_problems(document, record, manifest)
    job: JobRecord | None = None
    if transcript_row is not None and transcript_row.job_id is not None:
        try:
            with database.connect() as connection:
                job = get_job(connection, transcript_row.job_id)
        except StorageError as exc:
            problems.append(str(exc))
    if current_asr_sha256 is None:
        problems.append(
            "current ASR audio identity is not available, so the transcript input cannot be confirmed"
        )
    else:
        problems.extend(
            producer_binding_problems(
                document=document,
                record=record,
                manifest=manifest,
                current_asr_sha256=current_asr_sha256,
                artifact_job_id=None if transcript_row is None else transcript_row.job_id,
                artifact_provenance_job_id=(
                    None if transcript_row is None else transcript_row.provenance.job_id
                ),
                artifact_inputs_sha256=(
                    None if transcript_row is None else transcript_row.provenance.inputs_sha256
                ),
                artifact_source_ids=(
                    () if transcript_row is None else tuple(transcript_row.provenance.source_asset_ids)
                ),
                job=job,
            )
        )
    if problems:
        lines.append(VerifyLine("FAIL", "transcript", "; ".join(problems)))
        return
    lines.append(
        VerifyLine(
            "PASS",
            "transcript",
            f"sha256 {digest[:12]} segments {len(document.segments)} device {document.device} "
            f"model {document.model_revision}",
        )
    )
    if model_root is not None and document.asr_model and not model_is_cached(document.asr_model, model_root):
        lines.append(
            VerifyLine(
                "WARN",
                "model_cache",
                "the model named by this transcript is not in the local cache. "
                "The artifact bytes are still valid. Verification did not download it.",
            )
        )
