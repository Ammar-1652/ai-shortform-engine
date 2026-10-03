"""Resolve the current candidate set and the media it may render."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from clipforge.candidates.cache import read_candidate_cache
from clipforge.candidates.constants import KIND_CANDIDATE
from clipforge.candidates.inputs import EvidencePair, load_evidence_pair
from clipforge.candidates.integrity import candidate_problems
from clipforge.errors import MediaError, StorageError
from clipforge.media import recipes
from clipforge.media.cache import cache_identity_matches, read_cache_record
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import ensure_within
from clipforge.schemas.candidates import CandidateMiningDocument
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.storage import Database, find_artifact, get_job
from clipforge.transcription.io import read_text


@dataclass(frozen=True, slots=True)
class PreviewInputs:
    pair: EvidencePair
    candidate_document: CandidateMiningDocument
    candidate_path: Path
    candidate_sha256: str
    candidate_artifact_id: str
    candidate_job: JobRecord
    proxy_path: Path
    proxy_sha256: str
    asr_path: Path
    asr_sha256: str
    preview_input_sha256: str


def preview_input_digest(
    *,
    source_sha256: str,
    candidate_set_sha256: str,
    transcript_sha256: str,
    visual_analysis_sha256: str,
    analysis_proxy_sha256: str,
    asr_audio_sha256: str,
    profile_fingerprint: str,
) -> str:
    payload = {
        "analysis_proxy_sha256": analysis_proxy_sha256,
        "asr_audio_sha256": asr_audio_sha256,
        "candidate_set_sha256": candidate_set_sha256,
        "profile_fingerprint": profile_fingerprint,
        "source_sha256": source_sha256,
        "transcript_sha256": transcript_sha256,
        "visual_analysis_sha256": visual_analysis_sha256,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_preview_inputs(
    database: Database,
    source_asset_id: str,
    work_root: Path,
    *,
    profile_fingerprint: str,
    create_workspace: bool,
) -> PreviewInputs:
    """Load one consistent evidence stack. Missing pieces name the command that creates them."""
    pair = load_evidence_pair(
        database,
        source_asset_id,
        work_root,
        create_workspace=create_workspace,
    )
    proxy_path, proxy_sha = _require_derivative(
        database,
        pair,
        kind=recipes.KIND_PROXY,
        filename="analysis.mp4",
        recipe_name=recipes.ANALYSIS_PROXY_NAME,
        recipe_version=recipes.ANALYSIS_PROXY_VERSION,
        label="analysis proxy",
        command=f"clipforge media prepare {source_asset_id}",
    )
    asr_path, asr_sha = _require_derivative(
        database,
        pair,
        kind=recipes.KIND_ASR,
        filename="asr.flac",
        recipe_name=recipes.ASR_AUDIO_NAME,
        recipe_version=recipes.ASR_AUDIO_VERSION,
        label="ASR audio",
        command=f"clipforge media prepare {source_asset_id}",
    )
    document, path, digest, artifact_id, job = _require_candidates(database, pair)
    _require_ready(document)
    combined = preview_input_digest(
        source_sha256=pair.manifest.content_sha256,
        candidate_set_sha256=digest,
        transcript_sha256=pair.transcript_sha256,
        visual_analysis_sha256=pair.visual_sha256,
        analysis_proxy_sha256=proxy_sha,
        asr_audio_sha256=asr_sha,
        profile_fingerprint=profile_fingerprint,
    )
    return PreviewInputs(
        pair=pair,
        candidate_document=document,
        candidate_path=path,
        candidate_sha256=digest,
        candidate_artifact_id=artifact_id,
        candidate_job=job,
        proxy_path=proxy_path,
        proxy_sha256=proxy_sha,
        asr_path=asr_path,
        asr_sha256=asr_sha,
        preview_input_sha256=combined,
    )


def _require_derivative(
    database: Database,
    pair: EvidencePair,
    *,
    kind: str,
    filename: str,
    recipe_name: str,
    recipe_version: str,
    label: str,
    command: str,
) -> tuple[Path, str]:
    if kind == recipes.KIND_PROXY:
        path = pair.workspace.proxy_file(filename)
    else:
        path = pair.workspace.audio_file(filename)
    sidecar_name = "analysis-proxy.recipe.json" if kind == recipes.KIND_PROXY else "asr-audio.recipe.json"
    record = read_cache_record(pair.workspace.metadata_file(sidecar_name))
    if record is None or not path.is_file() or path.is_symlink():
        raise MediaError(f"{label} for source {pair.source.source_asset_id} is missing. Run `{command}`.")
    if not cache_identity_matches(
        record,
        recipe_name=recipe_name,
        recipe_version=recipe_version,
        source_sha256=pair.manifest.content_sha256,
        project_id=pair.source.project_id,
        source_asset_id=pair.source.source_asset_id,
        video_stream_index=pair.manifest.video_stream_index,
        audio_stream_index=pair.manifest.audio_stream_index,
        artifact_path=path,
    ):
        raise MediaError(f"{label} hash or recipe does not match this source. Run `{command}`.")
    with database.connect() as connection:
        row = find_artifact(connection, pair.source.project_id, pair.source.source_asset_id, kind)
        if row is None or row.job_id is None:
            raise MediaError(f"{label} has no artifact row. Run `{command}`.")
        try:
            job = get_job(connection, row.job_id)
        except StorageError as exc:
            raise MediaError(str(exc)) from exc
    if job.kind != recipes.JOB_MEDIA_PREPARE or job.status is not JobStatus.SUCCEEDED:
        raise MediaError(
            f"{label} producing job {job.job_id} is {job.kind}/{job.status.value}, "
            "expected media_prepare/succeeded. "
            f"Run `{command}`."
        )
    if job.project_id != pair.source.project_id:
        raise MediaError(f"{label} producing job is in another project")
    return path, record.artifact_sha256


def _require_candidates(
    database: Database,
    pair: EvidencePair,
) -> tuple[CandidateMiningDocument, Path, str, str, JobRecord]:
    record = read_candidate_cache(pair.workspace.candidate_sidecar())
    with database.connect() as connection:
        row = find_artifact(connection, pair.source.project_id, pair.source.source_asset_id, KIND_CANDIDATE)
        job = None
        if row is not None and row.job_id is not None:
            try:
                job = get_job(connection, row.job_id)
            except StorageError as exc:
                raise MediaError(str(exc)) from exc
    if record is None or row is None or row.job_id is None or job is None:
        raise MediaError(
            f"no current candidate set for source {pair.source.source_asset_id}. "
            f"Run `clipforge candidate mine {pair.source.source_asset_id}`."
        )
    try:
        path = path_from_file_uri(row.uri)
        expected = pair.workspace.candidate_run_dir(record.mining_id) / "candidates.json"
        ensure_within(pair.workspace.root, path)
        if path != expected or path.is_symlink() or not path.is_file():
            raise MediaError(
                "candidate artifact is not the candidates.json file inside this source's mining run"
            )
        document = CandidateMiningDocument.model_validate_json(read_text(path))
        digest = sha256_file(path)
    except (OSError, ValidationError, ValueError, MediaError) as exc:
        raise MediaError(f"current candidate set could not be read: {exc}") from exc
    problems = candidate_problems(
        document,
        record,
        candidate_path=path,
        work_root=pair.workspace.root,
        workspace=pair.workspace,
        pair=pair,
        profile=document.profile,
        artifact_job_id=row.job_id,
        artifact_uri=row.uri,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
    )
    if problems:
        raise MediaError("candidate set is not current: " + "; ".join(problems))
    if digest != record.candidate_artifact_sha256:
        raise MediaError("candidate set bytes do not match the candidate sidecar")
    return document, path, digest, row.artifact_id, job


def _require_ready(document: CandidateMiningDocument) -> None:
    if len(document.candidates) != document.summary.selected_count:
        raise MediaError("candidate summary does not match the selected candidates")
    for candidate in document.candidates:
        if candidate.status.value != "ready_for_review":
            raise MediaError(f"candidate {candidate.candidate_id} is not ready_for_review")
        if len(candidate.time_map.segments) != 1:
            raise MediaError(f"candidate {candidate.candidate_id} must have exactly one source segment")
        segment = candidate.time_map.segments[0]
        if segment.source_end_us > document.canonical_duration_us:
            raise MediaError(f"candidate {candidate.candidate_id} extends past the canonical duration")
