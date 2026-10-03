"""Load the current transcript and visual analysis for one source id.

Candidate mining does not run transcription or visual analysis, and it does not
decode the proxy or the ASR audio. It hashes those files only so the existing
integrity checks can see that the artifacts still belong to them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import ClipforgeError, MediaError, StorageError
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.mutation import inspect_mutation
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.governance import require_rights_cleared
from clipforge.schemas.ingest import SourceIngestManifest
from clipforge.schemas.jobs import JobRecord
from clipforge.schemas.media import SourceAsset, Transcript
from clipforge.schemas.transcription import TranscriptionCacheRecord
from clipforge.schemas.vision import VisualAnalysisCacheRecord, VisualAnalysisDocument
from clipforge.storage import (
    Database,
    find_artifact,
    get_asset_license_record,
    get_job,
    get_source_asset,
    get_source_manifest,
)
from clipforge.storage.repository import ArtifactRow
from clipforge.transcription.cache import read_transcript_cache
from clipforge.transcription.constants import KIND_TRANSCRIPT
from clipforge.transcription.integrity import document_sidecar_problems, producer_binding_problems
from clipforge.transcription.io import read_text
from clipforge.vision.cache import read_visual_cache
from clipforge.vision.constants import KIND_VISUAL
from clipforge.vision.integrity import visual_problems


@dataclass(frozen=True, slots=True)
class EvidencePair:
    source: SourceAsset
    manifest: SourceIngestManifest
    workspace: SourceWorkspace
    transcript: Transcript
    transcript_path: Path
    transcript_sha256: str
    transcript_record: TranscriptionCacheRecord
    transcript_job: JobRecord
    transcript_row: ArtifactRow
    visual: VisualAnalysisDocument
    visual_path: Path
    visual_sha256: str
    visual_record: VisualAnalysisCacheRecord
    visual_job: JobRecord
    visual_row: ArtifactRow
    candidate_input_sha256: str


def combined_input_sha256(transcript_sha256: str, visual_analysis_sha256: str) -> str:
    """SHA-256 of the two upstream artifact hashes. Either change moves this digest."""
    payload = {
        "transcript_sha256": transcript_sha256,
        "visual_analysis_sha256": visual_analysis_sha256,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_evidence_pair(
    database: Database,
    source_asset_id: str,
    work_root: Path,
    *,
    create_workspace: bool = False,
) -> EvidencePair:
    """Resolve the current verified pair. Missing or stale evidence is a hard failure."""
    root = work_root.resolve()
    try:
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
            manifest = get_source_manifest(connection, source_asset_id)
            license_record = get_asset_license_record(connection, source.license_record_id)
            transcript_row = find_artifact(connection, source.project_id, source_asset_id, KIND_TRANSCRIPT)
            visual_row = find_artifact(connection, source.project_id, source_asset_id, KIND_VISUAL)
    except StorageError as exc:
        raise MediaError(str(exc)) from exc
    if source.project_id != manifest.project_id:
        raise MediaError(
            f"source {source_asset_id} is in project {source.project_id} but its manifest is in "
            f"{manifest.project_id}. Refusing to mine across projects."
        )
    try:
        require_rights_cleared(license_record)
    except ClipforgeError as exc:
        raise MediaError(str(exc)) from exc
    inspect_mutation(path_from_file_uri(source.uri), manifest)
    if transcript_row is None:
        raise MediaError(
            f"no current transcript for source {source_asset_id}. "
            f"Run `clipforge transcript run {source_asset_id}`. "
            "Candidate mining does not create a transcript."
        )
    if visual_row is None:
        raise MediaError(
            f"no current visual analysis for source {source_asset_id}. "
            f"Run `clipforge vision analyze {source_asset_id}`. "
            "Candidate mining does not analyze video."
        )
    workspace = SourceWorkspace(root, source.project_id, source_asset_id)
    if create_workspace:
        workspace.ensure()
    transcript, transcript_record, transcript_job, transcript_sha = _load_transcript(
        database, workspace, manifest, transcript_row
    )
    visual, visual_record, visual_job, visual_sha = _load_visual(database, workspace, manifest, visual_row)
    _require_cross_identity(transcript, visual, manifest)
    return EvidencePair(
        source=source,
        manifest=manifest,
        workspace=workspace,
        transcript=transcript,
        transcript_path=workspace.transcript_file(),
        transcript_sha256=transcript_sha,
        transcript_record=transcript_record,
        transcript_job=transcript_job,
        transcript_row=transcript_row,
        visual=visual,
        visual_path=_artifact_path(visual_row),
        visual_sha256=visual_sha,
        visual_record=visual_record,
        visual_job=visual_job,
        visual_row=visual_row,
        candidate_input_sha256=combined_input_sha256(transcript_sha, visual_sha),
    )


def _load_transcript(
    database: Database,
    workspace: SourceWorkspace,
    manifest: SourceIngestManifest,
    row: ArtifactRow,
) -> tuple[Transcript, TranscriptionCacheRecord, JobRecord, str]:
    path = workspace.transcript_file()
    record = read_transcript_cache(workspace.transcript_sidecar())
    if record is None or not path.is_file() or path.is_symlink():
        raise MediaError(
            f"transcript file or sidecar for source {manifest.source_asset_id} is missing or unreadable. "
            f"Run `clipforge transcript run {manifest.source_asset_id}`."
        )
    asr_path = workspace.audio_file("asr.flac")
    if not asr_path.is_file() or asr_path.is_symlink():
        raise MediaError(
            f"ASR audio for source {manifest.source_asset_id} is missing. "
            f"Run `clipforge media prepare {manifest.source_asset_id}`. "
            "Candidate mining does not read or rebuild audio."
        )
    try:
        document = Transcript.model_validate_json(read_text(path))
        digest = sha256_file(path)
        asr_sha = sha256_file(asr_path)
    except (OSError, ValidationError, UnicodeError, MediaError) as exc:
        raise MediaError(f"current transcript could not be read: {exc}") from exc
    if digest != record.artifact_sha256 or path.stat().st_size != record.size_bytes:
        raise MediaError(
            "transcript bytes do not match the transcript sidecar. "
            f"Run `clipforge transcript verify {manifest.source_asset_id}`."
        )
    job = _job(database, row.job_id)
    problems = document_sidecar_problems(document, record, manifest)
    problems.extend(
        producer_binding_problems(
            document=document,
            record=record,
            manifest=manifest,
            current_asr_sha256=asr_sha,
            artifact_job_id=row.job_id,
            artifact_provenance_job_id=row.provenance.job_id,
            artifact_inputs_sha256=row.provenance.inputs_sha256,
            artifact_source_ids=tuple(row.provenance.source_asset_ids),
            job=job,
        )
    )
    if problems:
        raise MediaError("transcript evidence is not current: " + "; ".join(problems))
    if job is None:
        raise MediaError("producing transcript job is missing")
    return document, record, job, digest


def _load_visual(
    database: Database,
    workspace: SourceWorkspace,
    manifest: SourceIngestManifest,
    row: ArtifactRow,
) -> tuple[VisualAnalysisDocument, VisualAnalysisCacheRecord, JobRecord, str]:
    record = read_visual_cache(workspace.vision_sidecar())
    path = _artifact_path(row)
    if record is None or not path.is_file() or path.is_symlink():
        raise MediaError(
            f"visual analysis file or sidecar for source {manifest.source_asset_id} is missing. "
            f"Run `clipforge vision analyze {manifest.source_asset_id}`."
        )
    proxy_path = workspace.proxy_file("analysis.mp4")
    if not proxy_path.is_file() or proxy_path.is_symlink():
        raise MediaError(
            f"analysis proxy for source {manifest.source_asset_id} is missing. "
            f"Run `clipforge media prepare {manifest.source_asset_id}`. "
            "Candidate mining does not decode video."
        )
    try:
        document = VisualAnalysisDocument.model_validate_json(read_text(path))
        digest = sha256_file(path)
        proxy_sha = sha256_file(proxy_path)
    except (OSError, ValidationError, UnicodeError, MediaError) as exc:
        raise MediaError(f"current visual analysis could not be read: {exc}") from exc
    if digest != record.analysis_artifact_sha256 or path.stat().st_size != record.analysis_artifact_size:
        raise MediaError(
            "visual analysis bytes do not match the visual sidecar. "
            f"Run `clipforge vision verify {manifest.source_asset_id}`."
        )
    job = _job(database, row.job_id)
    problems = visual_problems(
        document,
        record,
        analysis_path=path,
        work_root=workspace.root,
        current_proxy_sha256=proxy_sha,
        artifact_job_id=row.job_id,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
    )
    if problems:
        raise MediaError("visual evidence is not current: " + "; ".join(problems))
    if document.canonical_duration_us != manifest.canonical_duration_us:
        raise MediaError("visual analysis duration does not match the source manifest")
    if job is None:
        raise MediaError("producing visual analysis job is missing")
    return document, record, job, digest


def _require_cross_identity(
    transcript: Transcript,
    visual: VisualAnalysisDocument,
    manifest: SourceIngestManifest,
) -> None:
    if transcript.project_id != manifest.project_id or visual.project_id != manifest.project_id:
        raise MediaError("transcript and visual analysis are not in this source's project")
    if (
        transcript.source_asset_id != manifest.source_asset_id
        or visual.source_asset_id != manifest.source_asset_id
    ):
        raise MediaError(
            "refusing to mine candidates from transcript and visual evidence for different sources"
        )
    if transcript.canonical_duration_us != manifest.canonical_duration_us:
        raise MediaError("transcript duration does not match the source manifest")
    if visual.canonical_duration_us != manifest.canonical_duration_us:
        raise MediaError("visual analysis duration does not match the source manifest")
    if visual.source_sha256 != manifest.content_sha256:
        raise MediaError("visual analysis source hash does not match the source manifest")


def _job(database: Database, job_id: str | None) -> JobRecord | None:
    if job_id is None:
        return None
    try:
        with database.connect() as connection:
            return get_job(connection, job_id)
    except StorageError:
        return None


def _artifact_path(row: ArtifactRow) -> Path:
    try:
        return path_from_file_uri(row.uri)
    except MediaError as exc:
        raise MediaError(f"visual analysis artifact URI is not usable: {exc}") from exc
