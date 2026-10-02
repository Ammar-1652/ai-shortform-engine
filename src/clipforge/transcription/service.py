"""Transcribe one source from its canonical ASR FLAC.

The SQLite write transaction is closed before faster-whisper runs. Shared
``prepare.lock`` is acquired before exclusive ``transcribe.lock``. A failure
does not replace a transcript that was already valid.
"""

from __future__ import annotations

import importlib.metadata
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from clipforge.errors import ComplianceGateError, MediaError, StorageError
from clipforge.media import recipes
from clipforge.media.cache import cache_identity_matches
from clipforge.media.cache import read_cache_record as read_media_cache
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri, path_to_file_uri
from clipforge.media.mutation import inspect_mutation
from clipforge.media.process import MediaCancelled, ProcessRunner
from clipforge.media.validate import validate_asr_audio
from clipforge.media.workspace import (
    SourceWorkspace,
    atomic_replace,
    ensure_within,
    prepare_read_lock,
    safe_unlink,
    transcribe_lock,
)
from clipforge.schemas.governance import require_rights_cleared
from clipforge.schemas.ingest import SourceIngestManifest
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import SourceAsset, Transcript
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.transcription import TranscriptionCacheRecord
from clipforge.storage import (
    Database,
    find_artifact,
    get_asset_license_record,
    get_job,
    get_source_asset,
    get_source_manifest,
    insert_artifact,
    insert_job,
    list_jobs,
    update_artifact,
    update_job,
    update_source_manifest_stats,
)
from clipforge.transcription.backend import (
    FasterWhisperBackend,
    InferenceHandle,
    RawSegment,
    TranscriptionBackend,
)
from clipforge.transcription.cache import cache_identity_matches as transcript_cache_matches
from clipforge.transcription.cache import read_transcript_cache
from clipforge.transcription.constants import JOB_TRANSCRIBE, KIND_TRANSCRIPT, RECIPE_NAME, RECIPE_VERSION
from clipforge.transcription.document import build_transcript
from clipforge.transcription.integrity import document_sidecar_problems, producer_binding_problems
from clipforge.transcription.io import publish_json
from clipforge.transcription.models import ModelIdentity, ensure_model, resolve_cached_model
from clipforge.transcription.profile import (
    DecodingProfile,
    TranscriptionRequest,
    decoding_profile,
    normalize_request,
)
from clipforge.transcription.runtime import ResolvedRuntime, RuntimeFacts, resolve_runtime

AudioValidator = Callable[[Path, SourceIngestManifest], None]
Progress = Callable[[int], None]


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    job_id: str
    transcript_id: str
    source_asset_id: str
    project_id: str
    model_requested: str
    model_revision: str
    device: str
    compute_type: str
    language_requested: str
    detected_language: str
    language_probability: float
    segment_count: int
    word_count: int
    speech_detected: bool
    canonical_duration_us: int
    cache_hit: bool
    transcript_path: Path
    transcript_sha256: str
    inference_seconds: float | None
    model_load_seconds: float | None
    real_time_factor: float | None
    warning: str | None


def transcribe_source(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    model_root: Path,
    request: TranscriptionRequest | None = None,
    backend: TranscriptionBackend | None = None,
    runtime_facts: RuntimeFacts | None = None,
    model_identity: ModelIdentity | None = None,
    audio_validator: AudioValidator | None = None,
    created_by: str | None = None,
    progress: Progress | None = None,
) -> TranscriptResult:
    """Transcribe ``source_asset_id``. An arbitrary audio path is not accepted."""
    chosen = normalize_request(request or TranscriptionRequest())
    profile = decoding_profile(chosen.language)
    root = work_root.resolve()
    context = _preflight(
        database=database,
        source_asset_id=source_asset_id,
        root=root,
        audio_validator=audio_validator or _validate_audio,
    )
    runtime = resolve_runtime(
        requested_device=chosen.device,
        requested_compute_type=chosen.compute_type,
        facts=runtime_facts,
    )
    identity = model_identity or _identity_for(chosen, model_root)
    engine = _engine_versions()
    actor = created_by.strip()[:200] if created_by and created_by.strip() else _actor()
    active = backend if backend is not None else FasterWhisperBackend()
    with prepare_read_lock(context.workspace), transcribe_lock(context.workspace):
        return _locked(
            database=database,
            context=context,
            root=root,
            chosen=chosen,
            profile=profile,
            runtime=runtime,
            identity=identity,
            engine=engine,
            actor=actor,
            backend=active,
            audio_validator=audio_validator or _validate_audio,
            progress=progress,
            model_root=model_root,
        )


@dataclass(frozen=True, slots=True)
class _Context:
    source: SourceAsset
    manifest: SourceIngestManifest
    workspace: SourceWorkspace
    audio_path: Path
    audio_sha256: str
    media_job_id: str


def _preflight(
    *,
    database: Database,
    source_asset_id: str,
    root: Path,
    audio_validator: AudioValidator,
) -> _Context:
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
        manifest = get_source_manifest(connection, source_asset_id)
        license_record = get_asset_license_record(connection, source.license_record_id)
    if source.project_id != manifest.project_id:
        raise MediaError(
            f"source {source_asset_id} is in project {source.project_id} but its manifest is in "
            f"{manifest.project_id}. Refusing to transcribe across projects."
        )
    require_rights_cleared(license_record)
    if not manifest.transcription_eligible:
        raise MediaError("Source has no selected audio stream and is not transcription-eligible.")
    manifest = _refresh_mutation(database, source, manifest)
    workspace = SourceWorkspace(root, source.project_id, source_asset_id)
    workspace.ensure()
    audio_path, audio_sha, media_job = _require_asr(database, source, manifest, workspace, audio_validator)
    return _Context(source, manifest, workspace, audio_path, audio_sha, media_job)


def _locked(
    *,
    database: Database,
    context: _Context,
    root: Path,
    chosen: TranscriptionRequest,
    profile: DecodingProfile,
    runtime: ResolvedRuntime,
    identity: ModelIdentity | None,
    engine: tuple[str, str],
    actor: str,
    backend: TranscriptionBackend,
    audio_validator: AudioValidator,
    progress: Progress | None,
    model_root: Path,
) -> TranscriptResult:
    """Run only after both source locks are held. Re-check the ASR input here."""
    context = _revalidate(database, context, audio_validator)
    resolved = identity or _identity_for(chosen, model_root)
    if not chosen.force and _cache_ready(context, resolved, runtime, profile, engine, database):
        _fail_stale(database, context)
        return _cache_result(database, context, runtime)
    if resolved is None:
        resolved = ensure_model(chosen.model, model_root, allow_download=chosen.allow_model_download)
    context = _revalidate(database, context, audio_validator)
    if not chosen.force and _cache_ready(context, resolved, runtime, profile, engine, database):
        _fail_stale(database, context)
        return _cache_result(database, context, runtime)
    now = datetime.now(UTC)
    job = _running_job(context, resolved, runtime, profile, engine, now)
    with database.transaction() as connection:
        _fail_stale_rows(connection, context, now)
        insert_job(connection, job)
    partials: list[Path] = []
    backups: list[tuple[Path | None, Path]] = []
    try:
        handle = backend.transcribe(
            context.audio_path,
            model=resolved,
            runtime=runtime,
            profile=profile,
        )
        collected, infer_seconds = _consume(handle, context.manifest.canonical_duration_us, progress)
        finished = datetime.now(UTC)
        document = build_transcript(
            segments=collected,
            canonical_duration_us=context.manifest.canonical_duration_us,
            project_id=context.source.project_id,
            source_asset_id=context.source.source_asset_id,
            asr_audio_sha256=context.audio_sha256,
            asr_recipe_name=recipes.ASR_AUDIO_NAME,
            asr_recipe_version=recipes.ASR_AUDIO_VERSION,
            model=resolved,
            runtime=runtime,
            profile=profile,
            detected_language=handle.info.language,
            language_probability=handle.info.language_probability,
            faster_whisper_version=engine[0],
            ctranslate2_version=engine[1],
            created_at=finished,
            created_by=actor,
            job_id=job.job_id,
            tool_version=engine[0],
        )
        final = context.workspace.transcript_file()
        sidecar = context.workspace.transcript_sidecar()
        transcript_partial = context.workspace.partial_for(final)
        sidecar_partial = context.workspace.partial_for(sidecar)
        partials.extend((transcript_partial, sidecar_partial))
        backups.append((_backup(final, root), final))
        backups.append((_backup(sidecar, root), sidecar))
        digest, size = publish_json(final, document, root, transcript_partial)
        record = _cache_record(
            context,
            resolved,
            runtime,
            profile,
            engine,
            digest,
            size,
            finished,
            transcript_id=document.transcript_id,
            job_id=job.job_id,
        )
        publish_json(sidecar, record, root, sidecar_partial)
        _write_log(context, job.job_id, resolved, runtime, profile, engine, document, infer_seconds, handle)
        _persist(database, context, job, document, final, actor, finished, resolved, runtime, profile)
        _drop_backups(backups, root)
        return _result_from_document(
            document,
            job_id=job.job_id,
            path=final,
            digest=digest,
            cache_hit=False,
            inference_seconds=infer_seconds,
            model_load_seconds=handle.info.model_load_seconds,
            warning=runtime.warning,
        )
    except KeyboardInterrupt:
        _abandon(
            database,
            job,
            JobStatus.CANCELLED,
            "interrupted by SIGINT. Partial transcript was not promoted.",
            backups,
            partials,
            root,
        )
        raise MediaCancelled(
            "transcription was interrupted. The job was marked cancelled. "
            "A previous valid transcript was left in place."
        ) from None
    except (MediaError, StorageError, ComplianceGateError) as exc:
        _abandon(database, job, JobStatus.FAILED, str(exc), backups, partials, root)
        raise
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        _abandon(database, job, JobStatus.FAILED, message, backups, partials, root)
        raise MediaError(message) from exc


def _consume(
    handle: InferenceHandle, duration_us: int, progress: Progress | None
) -> tuple[list[RawSegment], float]:
    collected: list[RawSegment] = []
    last_bucket = 0
    started = time.perf_counter()
    for segment in handle.segments:
        collected.append(segment)
        last_bucket = _report(progress, segment.end_seconds, duration_us, last_bucket)
    if progress is not None and last_bucket < 100 and duration_us > 0:
        progress(100)
    return collected, time.perf_counter() - started


def _report(progress: Progress | None, end_seconds: float, duration_us: int, last_bucket: int) -> int:
    if progress is None or duration_us <= 0:
        return last_bucket
    end_us = max(0, int(end_seconds * 1_000_000))
    percent = min(100, int(end_us * 100 / duration_us))
    bucket = percent // 10 * 10
    if bucket > last_bucket and bucket > 0:
        progress(bucket)
        return bucket
    return last_bucket


def _identity_for(chosen: TranscriptionRequest, model_root: Path) -> ModelIdentity | None:
    cached = resolve_cached_model(chosen.model, model_root)
    if cached is not None:
        return cached
    if chosen.allow_model_download:
        return ensure_model(chosen.model, model_root, allow_download=True)
    return None


def _cache_ready(
    context: _Context,
    identity: ModelIdentity | None,
    runtime: ResolvedRuntime,
    profile: DecodingProfile,
    engine: tuple[str, str],
    database: Database,
) -> bool:
    if identity is None:
        return False
    record = read_transcript_cache(context.workspace.transcript_sidecar())
    if record is None:
        return False
    if not transcript_cache_matches(
        record,
        project_id=context.source.project_id,
        source_asset_id=context.source.source_asset_id,
        source_sha256=context.manifest.content_sha256,
        input_audio_sha256=context.audio_sha256,
        asr_recipe_name=recipes.ASR_AUDIO_NAME,
        asr_recipe_version=recipes.ASR_AUDIO_VERSION,
        recipe_name=RECIPE_NAME,
        recipe_version=RECIPE_VERSION,
        faster_whisper_version=engine[0],
        ctranslate2_version=engine[1],
        model=identity,
        runtime=runtime,
        profile=profile,
        transcript_path=context.workspace.transcript_file(),
    ):
        return False
    with database.connect() as connection:
        row = find_artifact(
            connection, context.source.project_id, context.source.source_asset_id, KIND_TRANSCRIPT
        )
        if row is None or row.job_id is None or row.provenance.job_id != row.job_id:
            return False
        if context.source.source_asset_id not in row.provenance.source_asset_ids:
            return False
        try:
            job = get_job(connection, row.job_id)
        except StorageError:
            return False
    if job.project_id != context.source.project_id or job.kind != JOB_TRANSCRIBE:
        return False
    if job.status is not JobStatus.SUCCEEDED:
        return False
    document = Transcript.model_validate_json(context.workspace.transcript_file().read_text(encoding="utf-8"))
    if document_sidecar_problems(document, record, context.manifest):
        return False
    problems = producer_binding_problems(
        document=document,
        record=record,
        manifest=context.manifest,
        current_asr_sha256=context.audio_sha256,
        artifact_job_id=row.job_id,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
    )
    return not problems


def _cache_result(database: Database, context: _Context, runtime: ResolvedRuntime) -> TranscriptResult:
    path = context.workspace.transcript_file()
    document = Transcript.model_validate_json(path.read_text(encoding="utf-8"))
    with database.connect() as connection:
        row = find_artifact(
            connection, context.source.project_id, context.source.source_asset_id, KIND_TRANSCRIPT
        )
    if row is None or row.job_id is None:
        raise MediaError("transcript cache matched but the artifact row disappeared before reuse")
    digest = sha256_file(path)
    return _result_from_document(
        document,
        job_id=row.job_id,
        path=path,
        digest=digest,
        cache_hit=True,
        inference_seconds=None,
        model_load_seconds=None,
        warning=runtime.warning,
    )


def _result_from_document(
    document: Transcript,
    *,
    job_id: str,
    path: Path,
    digest: str,
    cache_hit: bool,
    inference_seconds: float | None,
    model_load_seconds: float | None,
    warning: str | None,
) -> TranscriptResult:
    duration_us = document.canonical_duration_us or 0
    factor = None
    if inference_seconds is not None and duration_us > 0:
        factor = inference_seconds / (duration_us / 1_000_000)
    return TranscriptResult(
        job_id=job_id,
        transcript_id=document.transcript_id,
        source_asset_id=document.source_asset_id,
        project_id=document.project_id,
        model_requested=document.asr_model,
        model_revision=document.model_revision or "",
        device=document.device or "",
        compute_type=document.compute_type or "",
        language_requested=document.language_requested or "",
        detected_language=document.detected_language or "",
        language_probability=document.language_probability or 0.0,
        segment_count=document.segment_count or len(document.segments),
        word_count=document.word_count or sum(len(segment.words) for segment in document.segments),
        speech_detected=bool(document.speech_detected),
        canonical_duration_us=duration_us,
        cache_hit=cache_hit,
        transcript_path=path,
        transcript_sha256=digest,
        inference_seconds=inference_seconds,
        model_load_seconds=model_load_seconds,
        real_time_factor=factor,
        warning=warning,
    )


def _running_job(
    context: _Context,
    identity: ModelIdentity,
    runtime: ResolvedRuntime,
    profile: DecodingProfile,
    engine: tuple[str, str],
    now: datetime,
) -> JobRecord:
    return JobRecord(
        job_id=str(uuid.uuid4()),
        project_id=context.source.project_id,
        kind=JOB_TRANSCRIBE,
        status=JobStatus.RUNNING,
        created_at=now,
        updated_at=now,
        payload={
            "source_asset_id": context.source.source_asset_id,
            "source_sha256": context.manifest.content_sha256,
            "asr_audio_sha256": context.audio_sha256,
            "model_requested": identity.requested,
            "model_revision": identity.revision,
            "device": runtime.device,
            "compute_type": runtime.compute_type,
            "language": profile.language,
            "recipe_version": RECIPE_VERSION,
            "cache": "miss",
        },
    )


def _persist(
    database: Database,
    context: _Context,
    job: JobRecord,
    document: Transcript,
    final: Path,
    actor: str,
    finished: datetime,
    identity: ModelIdentity,
    runtime: ResolvedRuntime,
    profile: DecodingProfile,
) -> None:
    provenance = ArtifactProvenance(
        created_at=finished,
        created_by=actor,
        tool="faster-whisper",
        tool_version=(document.faster_whisper_version or "0")[:80],
        source_asset_ids=[context.source.source_asset_id],
        job_id=job.job_id,
        inputs_sha256=context.audio_sha256,
    )
    payload = dict(job.payload)
    payload["cache"] = "miss"
    payload["transcript_id"] = document.transcript_id
    payload["detected_language"] = document.detected_language or ""
    succeeded = job.model_copy(
        update={
            "status": JobStatus.SUCCEEDED,
            "updated_at": finished,
            "error_message": None,
            "payload": payload,
        }
    )
    with database.transaction() as connection:
        existing = find_artifact(
            connection, context.source.project_id, context.source.source_asset_id, KIND_TRANSCRIPT
        )
        uri = path_to_file_uri(final)
        if existing is None:
            insert_artifact(
                connection,
                artifact_id=str(uuid.uuid4()),
                project_id=context.source.project_id,
                job_id=job.job_id,
                source_asset_id=context.source.source_asset_id,
                kind=KIND_TRANSCRIPT,
                uri=uri,
                provenance=provenance,
            )
        else:
            update_artifact(
                connection,
                artifact_id=existing.artifact_id,
                project_id=context.source.project_id,
                job_id=job.job_id,
                source_asset_id=context.source.source_asset_id,
                kind=KIND_TRANSCRIPT,
                uri=uri,
                provenance=provenance,
            )
        update_job(connection, succeeded)


def _cache_record(
    context: _Context,
    identity: ModelIdentity,
    runtime: ResolvedRuntime,
    profile: DecodingProfile,
    engine: tuple[str, str],
    digest: str,
    size: int,
    created_at: datetime,
    *,
    transcript_id: str,
    job_id: str,
) -> TranscriptionCacheRecord:
    return TranscriptionCacheRecord(
        project_id=context.source.project_id,
        source_asset_id=context.source.source_asset_id,
        transcript_id=transcript_id,
        job_id=job_id,
        source_sha256=context.manifest.content_sha256,
        input_audio_sha256=context.audio_sha256,
        asr_recipe_name=recipes.ASR_AUDIO_NAME,
        asr_recipe_version=recipes.ASR_AUDIO_VERSION,
        recipe_name=RECIPE_NAME,
        recipe_version=RECIPE_VERSION,
        faster_whisper_version=engine[0],
        ctranslate2_version=engine[1],
        model_requested=identity.requested,
        model_revision=identity.revision,
        model_source=identity.source,
        device=runtime.device,
        compute_type=runtime.compute_type,
        language=profile.language,
        decoding_fingerprint=profile.fingerprint(),
        artifact_sha256=digest,
        size_bytes=size,
        validation_status="passed",
        created_at=created_at,
    )


def _revalidate(database: Database, context: _Context, audio_validator: AudioValidator) -> _Context:
    manifest = _refresh_mutation(database, context.source, context.manifest)
    audio_path, audio_sha, media_job = _require_asr(
        database, context.source, manifest, context.workspace, audio_validator
    )
    return _Context(context.source, manifest, context.workspace, audio_path, audio_sha, media_job)


def _refresh_mutation(
    database: Database, source: SourceAsset, manifest: SourceIngestManifest
) -> SourceIngestManifest:
    path = path_from_file_uri(source.uri)
    drift = inspect_mutation(path, manifest)
    if drift is None:
        return manifest
    with database.transaction() as connection:
        update_source_manifest_stats(
            connection,
            source_asset_id=source.source_asset_id,
            project_id=source.project_id,
            size_bytes=drift.size_bytes,
            mtime_ns=drift.mtime_ns,
        )
    return manifest.model_copy(update={"size_bytes": drift.size_bytes, "mtime_ns": drift.mtime_ns})


def _require_asr(
    database: Database,
    source: SourceAsset,
    manifest: SourceIngestManifest,
    workspace: SourceWorkspace,
    audio_validator: AudioValidator,
) -> tuple[Path, str, str]:
    path = workspace.audio_file("asr.flac")
    sidecar = workspace.metadata_file("asr-audio.recipe.json")
    if not path.is_file() or not sidecar.is_file():
        raise MediaError(
            f"ASR audio for source {source.source_asset_id} is missing. "
            f"Run `clipforge media prepare {source.source_asset_id}`. "
            "Transcription does not create or rebuild ASR audio."
        )
    record = read_media_cache(sidecar)
    if record is None or not cache_identity_matches(
        record,
        recipe_name=recipes.ASR_AUDIO_NAME,
        recipe_version=recipes.ASR_AUDIO_VERSION,
        source_sha256=manifest.content_sha256,
        project_id=manifest.project_id,
        source_asset_id=manifest.source_asset_id,
        video_stream_index=manifest.video_stream_index,
        audio_stream_index=manifest.audio_stream_index,
        artifact_path=path,
    ):
        raise MediaError(
            "ASR audio hash or recipe does not match this source. "
            f"Run `clipforge media prepare {source.source_asset_id}`. "
            "Transcription will not rebuild it."
        )
    with database.connect() as connection:
        row = find_artifact(connection, source.project_id, source.source_asset_id, recipes.KIND_ASR)
        if row is None or row.job_id is None or row.provenance.job_id != row.job_id:
            raise MediaError(
                "ASR audio has no artifact row from a succeeded prepare. "
                f"Run `clipforge media prepare {source.source_asset_id}`."
            )
        if source.source_asset_id not in row.provenance.source_asset_ids or row.project_id != source.project_id:
            raise MediaError("ASR artifact row is not in this project and source")
        job = get_job(connection, row.job_id)
    if job.project_id != source.project_id or job.kind != recipes.JOB_MEDIA_PREPARE:
        raise MediaError(f"ASR audio was produced by job kind {job.kind}, not media_prepare")
    if job.status is not JobStatus.SUCCEEDED:
        raise MediaError(
            f"ASR audio producing job {job.job_id} is {job.status.value}, expected succeeded. "
            f"Run `clipforge media prepare {source.source_asset_id}`."
        )
    payload_source = job.payload.get("source_asset_id")
    if payload_source is not None and payload_source != source.source_asset_id:
        raise MediaError("ASR producing job names a different source")
    audio_validator(path, manifest)
    return path, record.artifact_sha256, job.job_id


def _validate_audio(path: Path, manifest: SourceIngestManifest) -> None:
    rate = None
    for stream in manifest.probe.video_streams:
        if stream.index == manifest.video_stream_index:
            rate = stream.avg_frame_rate or stream.r_frame_rate
            break
    validate_asr_audio(
        path,
        ProcessRunner(),
        canonical_duration_us=manifest.canonical_duration_us,
        rate=rate,
        log_path=None,
    )


def _fail_stale(database: Database, context: _Context) -> None:
    now = datetime.now(UTC)
    with database.transaction() as connection:
        _fail_stale_rows(connection, context, now)


def _fail_stale_rows(connection: sqlite3.Connection, context: _Context, now: datetime) -> None:
    for existing in list_jobs(connection, context.source.project_id):
        if existing.kind != JOB_TRANSCRIBE or existing.status is not JobStatus.RUNNING:
            continue
        if existing.payload.get("source_asset_id") != context.source.source_asset_id:
            continue
        update_job(
            connection,
            existing.model_copy(
                update={
                    "status": JobStatus.FAILED,
                    "updated_at": now,
                    "error_message": (
                        "interrupted before completion. The transcription lock was free, so no live "
                        "transcription process owned this running job. Partial outputs were not promoted."
                    ),
                }
            ),
        )


def _abandon(
    database: Database,
    job: JobRecord,
    status: JobStatus,
    message: str,
    backups: list[tuple[Path | None, Path]],
    partials: list[Path],
    root: Path,
) -> None:
    """Restore files, then always try to close the job. Cleanup errors do not skip that close."""
    notes = _rewind(backups, partials, root)
    detail = message if not notes else f"{message} Cleanup also failed: {'; '.join(notes)}"
    try:
        _close(database, job, status, detail)
    except Exception:
        return


def _close(database: Database, job: JobRecord, status: JobStatus, message: str) -> None:
    updated = job.model_copy(
        update={"status": status, "updated_at": datetime.now(UTC), "error_message": message[:2000]}
    )
    with database.transaction() as connection:
        update_job(connection, updated)


def _engine_versions() -> tuple[str, str]:
    return _dist_version("faster-whisper"), _dist_version("ctranslate2")


def _dist_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise MediaError(f"{name} is not installed. Run uv sync. A model was not downloaded.") from exc


def _backup(path: Path, root: Path) -> Path | None:
    if not path.is_file():
        return None
    backup = path.with_name(f"{path.name}.partial.backup.{uuid.uuid4().hex}")
    ensure_within(root, path)
    ensure_within(root, backup)
    backup.write_bytes(path.read_bytes())
    return backup


def _restore(backup: Path | None, final: Path, root: Path) -> None:
    ensure_within(root, final)
    if backup is not None and backup.is_file():
        atomic_replace(backup, final, root)
        return
    if final.is_file() or final.is_symlink():
        safe_unlink(root, final)


def _rewind(backups: list[tuple[Path | None, Path]], partials: list[Path], root: Path) -> list[str]:
    """Best-effort restore. MediaError and OSError are reported, not raised."""
    notes: list[str] = []
    for backup, final in reversed(backups):
        try:
            _restore(backup, final, root)
        except (OSError, MediaError) as exc:
            notes.append(str(exc))
    for partial in partials:
        try:
            if partial.is_file():
                safe_unlink(root, partial)
        except (OSError, MediaError) as exc:
            notes.append(str(exc))
    return notes


def _drop_backups(backups: list[tuple[Path | None, Path]], root: Path) -> None:
    """Deleting a backup must not invalidate a transcript that is already committed."""
    for backup, _final in backups:
        if backup is None or not backup.is_file():
            continue
        try:
            safe_unlink(root, backup)
        except (OSError, MediaError):
            continue


def _write_log(
    context: _Context,
    job_id: str,
    identity: ModelIdentity,
    runtime: ResolvedRuntime,
    profile: DecodingProfile,
    engine: tuple[str, str],
    document: Transcript,
    infer_seconds: float,
    handle: InferenceHandle,
) -> None:
    lines = [
        f"job_id: {job_id}",
        f"source_asset_id: {context.source.source_asset_id}",
        f"model: {identity.requested}",
        f"model_revision: {identity.revision}",
        f"faster_whisper: {engine[0]}",
        f"ctranslate2: {engine[1]}",
        f"device: {runtime.device}",
        f"compute_type: {runtime.compute_type}",
        f"language_requested: {profile.language}",
        f"detected_language: {document.detected_language}",
        f"model_load_seconds: {handle.info.model_load_seconds:.3f}",
        f"inference_seconds: {infer_seconds:.3f}",
        f"segments: {document.segment_count}",
        f"words: {document.word_count}",
        "cache: miss",
    ]
    path = context.workspace.log_file(f"{job_id}.log")
    ensure_within(context.workspace.root, path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _actor() -> str:
    import getpass

    try:
        return getpass.getuser()
    except OSError as exc:
        raise MediaError(f"could not determine the OS user for provenance: {exc}") from exc
