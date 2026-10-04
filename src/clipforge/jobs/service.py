"""Inspect, recover, and resume recorded jobs. A stale run is never marked succeeded."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import ClipforgeError, ComplianceGateError, MediaError, StorageError
from clipforge.jobs.payload import JobPayloadError, assert_public_payload, public_payload
from clipforge.media import recipes
from clipforge.media.cache import cache_identity_matches, read_cache_record
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.prepare import prepare_source
from clipforge.media.workspace import SourceWorkspace
from clipforge.preview.service import render_previews
from clipforge.schemas.governance import require_rights_cleared
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import Transcript
from clipforge.storage import (
    Database,
    find_artifact,
    get_asset_license_record,
    get_job,
    get_source_asset,
    get_source_manifest,
    insert_job,
    list_all_jobs,
    list_jobs,
    update_job,
)
from clipforge.transcription.cache import read_transcript_cache
from clipforge.transcription.service import transcribe_source

STALE_AFTER = timedelta(minutes=15)
SUPPORTED = frozenset({"media_prepare", "transcribe", "rough_preview_render"})
RESUMABLE = frozenset({JobStatus.FAILED, JobStatus.BLOCKED, JobStatus.CANCELLED})


class JobError(ClipforgeError):
    """A job command cannot continue. This is not a successful result."""


Executor = Callable[[JobRecord, Path, str], str]


def list_job_text(database: Database, project_id: str | None = None) -> str:
    jobs = _jobs(database, project_id)
    if not jobs:
        return "No jobs are stored."
    lines = ["job_id\tkind\tproject_id\tsource_asset_id\tstatus\tupdated_at\tcache\terror"]
    for job in jobs:
        payload = public_payload(job.payload)
        lines.append(
            "\t".join(
                [
                    job.job_id,
                    job.kind,
                    job.project_id,
                    payload.get("source_asset_id", "-"),
                    job.status.value,
                    job.updated_at.isoformat(),
                    payload.get("cache", "-"),
                    (job.error_message or "").split("\n", 1)[0][:120],
                ]
            )
        )
    return "\n".join(lines)


def show_job(database: Database, job_id: str) -> str:
    job = _require(database, job_id)
    payload = public_payload(job.payload)
    lines = [
        f"job_id: {job.job_id}",
        f"kind: {job.kind}",
        f"project_id: {job.project_id}",
        f"status: {job.status.value}",
        f"created_at: {job.created_at.isoformat()}",
        f"updated_at: {job.updated_at.isoformat()}",
        f"error: {job.error_message or '-'}",
    ]
    for key, value in payload.items():
        lines.append(f"payload.{key}: {value}")
    return "\n".join(lines)


def verify_job(database: Database, job_id: str, work_root: Path) -> None:
    """Check the recorded job against its source and outputs. This does not write."""
    job = _require(database, job_id)
    try:
        assert_public_payload(job.payload)
    except JobPayloadError as exc:
        raise JobError(str(exc)) from exc
    if job.status is JobStatus.FAILED and not (job.error_message and job.error_message.strip()):
        raise JobError(f"job {job_id} failed without an error message")
    if job.status is JobStatus.SUCCEEDED:
        _verify_success(database, job, work_root)
        return
    source_id = job.payload.get("source_asset_id")
    if source_id:
        _revalidate(database, job, work_root)


def recover_jobs(
    database: Database,
    project_id: str | None = None,
    *,
    now: datetime | None = None,
    stale_after: timedelta = STALE_AFTER,
) -> list[str]:
    """Mark stale running jobs failed. Liveness is not inferred from a lock file."""
    moment = now or datetime.now(UTC)
    changed: list[str] = []
    with database.transaction() as connection:
        jobs = list_jobs(connection, project_id) if project_id else list_all_jobs(connection)
        for job in jobs:
            if job.status is not JobStatus.RUNNING:
                continue
            if moment - job.updated_at < stale_after:
                continue
            update_job(
                connection,
                job.model_copy(
                    update={
                        "status": JobStatus.FAILED,
                        "updated_at": moment,
                        "error_message": (
                            "stale running job recovered from updated_at. It was not marked succeeded. "
                            f"Resume it with `clipforge job resume {job.job_id}`."
                        ),
                    }
                ),
            )
            changed.append(job.job_id)
    return changed


def resume_job(
    database: Database,
    job_id: str,
    work_root: Path,
    *,
    created_by: str,
    executors: dict[str, Executor] | None = None,
) -> str:
    """Start a new attempt. The previous job row stays in history."""
    parent = _require(database, job_id)
    if parent.kind not in SUPPORTED:
        raise JobError(
            f"job kind {parent.kind} cannot be resumed. "
            "Supported kinds are media_prepare, speech, and rough_preview."
        )
    if parent.status not in RESUMABLE:
        raise JobError(
            f"job {job_id} is {parent.status.value}. Only failed, blocked, or cancelled jobs can be resumed."
        )
    _revalidate(database, parent, work_root)
    attempt = int(parent.payload.get("attempt") or "1") + 1
    before = _job_ids(database)
    table = executors or _bound_executors(database)
    try:
        child_id = table[parent.kind](parent, work_root, created_by)
    except (MediaError, StorageError, ComplianceGateError, ClipforgeError) as exc:
        raise JobError(str(exc)) from exc
    if child_id in before:
        return _record_cache_attempt(database, parent, child_id, attempt)
    _stamp(database, parent, child_id, attempt)
    return child_id


def retry_job(
    database: Database,
    job_id: str,
    work_root: Path,
    *,
    created_by: str,
    executors: dict[str, Executor] | None = None,
) -> str:
    """Retry has the same safety rules as resume."""
    return resume_job(
        database,
        job_id,
        work_root,
        created_by=created_by,
        executors=executors,
    )


def _jobs(database: Database, project_id: str | None) -> list[JobRecord]:
    with database.connect() as connection:
        if project_id:
            return list_jobs(connection, project_id)
        return list_all_jobs(connection)


def _require(database: Database, job_id: str) -> JobRecord:
    try:
        with database.connect() as connection:
            return get_job(connection, job_id)
    except StorageError as exc:
        raise JobError(str(exc)) from exc


def _job_ids(database: Database) -> set[str]:
    with database.connect() as connection:
        rows = connection.execute("SELECT job_id FROM jobs").fetchall()
    return {str(row["job_id"]) for row in rows}


def _revalidate(database: Database, job: JobRecord, work_root: Path) -> None:
    del work_root
    source_id = job.payload.get("source_asset_id")
    if not source_id:
        raise JobError(f"job {job.job_id} has no source_asset_id and cannot be reconstructed")
    recorded = job.payload.get("source_sha256")
    if not recorded:
        raise JobError(f"job {job.job_id} has no source hash and cannot be resumed safely")
    with database.connect() as connection:
        source = get_source_asset(connection, source_id)
        manifest = get_source_manifest(connection, source_id)
        license_record = get_asset_license_record(connection, source.license_record_id)
    if source.project_id != job.project_id:
        raise JobError(f"job {job.job_id} does not belong to source {source_id}")
    try:
        require_rights_cleared(license_record)
    except ComplianceGateError as exc:
        raise JobError(str(exc)) from exc
    current = sha_of_source(source.uri, manifest.content_sha256)
    if current != recorded:
        raise JobError(f"job {job.job_id} source hash changed after the attempt. Resume was refused.")


def sha_of_source(uri: str, manifest_sha: str) -> str:
    """Return the live file hash when the URI is local. Otherwise use the manifest hash."""
    if uri.startswith("file:"):
        return sha256_file(path_from_file_uri(uri))
    return manifest_sha


def _verify_success(database: Database, job: JobRecord, work_root: Path) -> None:
    source_id = job.payload.get("source_asset_id")
    if source_id:
        _revalidate(database, job, work_root)
    if job.kind == "media_prepare" and job.payload.get("analysis_proxy_sha256"):
        _verify_proxy(database, job, work_root)
    elif job.kind == "transcribe" and job.payload.get("source_sha256"):
        _verify_transcript(database, job, work_root)


def _verify_proxy(database: Database, job: JobRecord, work_root: Path) -> None:
    source_id = job.payload["source_asset_id"]
    workspace = SourceWorkspace(work_root, job.project_id, source_id)
    sidecar = workspace.metadata_file("analysis-proxy.recipe.json")
    media = workspace.proxy_file("analysis.mp4")
    record = read_cache_record(sidecar)
    if record is None:
        raise JobError(f"job {job.job_id} has no analysis proxy cache record")
    if record.source_sha256 != job.payload.get("source_sha256"):
        raise JobError(f"job {job.job_id} proxy cache source hash does not match the job")
    if record.project_id != job.project_id or record.source_asset_id != source_id:
        raise JobError(f"job {job.job_id} proxy cache lineage does not match the job")
    if record.artifact_sha256 != job.payload.get("analysis_proxy_sha256"):
        raise JobError(f"job {job.job_id} proxy hash does not match the cache record")
    if not cache_identity_matches(
        record,
        recipe_name=record.recipe_name,
        recipe_version=record.recipe_version,
        source_sha256=record.source_sha256,
        project_id=record.project_id,
        source_asset_id=record.source_asset_id,
        video_stream_index=record.video_stream_index,
        audio_stream_index=record.audio_stream_index,
        artifact_path=media,
    ):
        raise JobError(f"job {job.job_id} proxy file does not match its cache record")
    _verify_producer(database, job, recipes.KIND_PROXY)


def _verify_transcript(database: Database, job: JobRecord, work_root: Path) -> None:
    source_id = job.payload["source_asset_id"]
    workspace = SourceWorkspace(work_root, job.project_id, source_id)
    sidecar = workspace.transcript_sidecar()
    document_path = workspace.transcript_file()
    record = read_transcript_cache(sidecar)
    if record is None or document_path.is_symlink() or not document_path.is_file():
        raise JobError(f"job {job.job_id} has no transcript cache record")
    if record.project_id != job.project_id or record.source_asset_id != source_id:
        raise JobError(f"job {job.job_id} transcript lineage does not match the job")
    if record.source_sha256 != job.payload.get("source_sha256"):
        raise JobError(f"job {job.job_id} transcript source hash does not match the job")
    try:
        document = Transcript.model_validate_json(document_path.read_text(encoding="utf-8"))
        digest = sha256_file(document_path)
    except (OSError, ClipforgeError, ValueError, ValidationError) as exc:
        raise JobError(f"job {job.job_id} transcript could not be read") from exc
    if digest != record.artifact_sha256 or document.transcript_id != record.transcript_id:
        raise JobError(f"job {job.job_id} transcript does not match its sidecar")
    from clipforge.transcription.constants import KIND_TRANSCRIPT

    _verify_producer(database, job, KIND_TRANSCRIPT)


def _verify_producer(database: Database, job: JobRecord, kind: str) -> None:
    source_id = job.payload["source_asset_id"]
    with database.connect() as connection:
        row = find_artifact(connection, job.project_id, source_id, kind)
        if row is None or row.job_id is None:
            raise JobError(f"job {job.job_id} has no current {kind} artifact")
        if row.project_id != job.project_id or row.source_asset_id != source_id:
            raise JobError(f"job {job.job_id} artifact belongs to another project or source")
        try:
            producer = get_job(connection, row.job_id)
        except StorageError as exc:
            raise JobError(str(exc)) from exc
    if producer.status is not JobStatus.SUCCEEDED or producer.project_id != job.project_id:
        raise JobError(f"job {job.job_id} producer is not a succeeded job in this project")


def _bound_executors(database: Database) -> dict[str, Executor]:
    def media(parent: JobRecord, root: Path, actor: str) -> str:
        result = prepare_source(
            database=database,
            source_asset_id=parent.payload["source_asset_id"],
            work_root=root,
            created_by=actor,
        )
        return result.job_id

    def transcript(parent: JobRecord, root: Path, actor: str) -> str:
        from clipforge.paths import resolve_model_root
        from clipforge.transcription.profile import TranscriptionRequest

        result = transcribe_source(
            database=database,
            source_asset_id=parent.payload["source_asset_id"],
            work_root=root,
            model_root=resolve_model_root(None),
            request=TranscriptionRequest(allow_model_download=False),
            created_by=actor,
        )
        return result.job_id

    def preview(parent: JobRecord, root: Path, actor: str) -> str:
        result = render_previews(
            database=database,
            source_asset_id=parent.payload["source_asset_id"],
            work_root=root,
            created_by=actor,
        )
        return result.job_id

    return {
        "media_prepare": media,
        "transcribe": transcript,
        "rough_preview_render": preview,
    }


def _stamp(database: Database, parent: JobRecord, child_id: str, attempt: int) -> None:
    with database.connect() as connection:
        child = get_job(connection, child_id)
    payload = public_payload(dict(child.payload))
    payload["parent_job_id"] = parent.job_id
    payload["attempt"] = str(attempt)
    payload["operation"] = parent.kind
    assert_public_payload(payload)
    updated = child.model_copy(update={"payload": payload, "updated_at": datetime.now(UTC)})
    with database.transaction() as connection:
        update_job(connection, updated)


def _record_cache_attempt(database: Database, parent: JobRecord, reused_id: str, attempt: int) -> str:
    """A producer returned an existing job. Record a new attempt and do not rewrite it."""
    with database.connect() as connection:
        reused = get_job(connection, reused_id)
        parent_row = get_job(connection, parent.job_id)
    payload = public_payload(dict(reused.payload))
    payload["parent_job_id"] = parent.job_id
    payload["attempt"] = str(attempt)
    payload["operation"] = parent.kind
    payload["cache"] = "hit"
    payload["reused_job_id"] = reused_id
    assert_public_payload(payload)
    now = datetime.now(UTC)
    child = JobRecord(
        job_id=str(uuid.uuid4()),
        project_id=parent.project_id,
        kind=parent.kind,
        status=JobStatus.SUCCEEDED,
        created_at=now,
        updated_at=now,
        payload=payload,
    )
    with database.transaction() as connection:
        insert_job(connection, child)
    with database.connect() as connection:
        if get_job(connection, parent.job_id).model_dump(mode="json") != parent_row.model_dump(mode="json"):
            raise JobError(f"job {parent.job_id} was rewritten by the cache attempt")
        if get_job(connection, reused_id).model_dump(mode="json") != reused.model_dump(mode="json"):
            raise JobError(f"job {reused_id} was rewritten by the cache attempt")
    return child.job_id
