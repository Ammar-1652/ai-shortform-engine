"""Build the analysis proxy and ASR audio. The database lock is not held during ffmpeg.

Preflight (rights, mutation, HDR, disk) either raises or finishes before a job row
is marked running. The running row is committed, the connection is closed, and
only then does ffmpeg start. A second short transaction stores the artifact rows
and the final job status. A failure marks the job failed or cancelled and deletes
partial files. It does not delete the source, the log, or a previous valid output
that was not replaced.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from clipforge.errors import ComplianceGateError, MediaError, StorageError
from clipforge.media import recipes
from clipforge.media.cache import cache_identity_matches, read_cache_record, write_cache_record
from clipforge.media.clock import audio_filter_chain, proxy_filter_complex, proxy_pixel_size
from clipforge.media.disk import DiskStatus, estimate_prepare_bytes, read_disk, require_disk_budget
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri, path_to_file_uri
from clipforge.media.mutation import inspect_mutation
from clipforge.media.process import MediaCancelled, ProcessRunner
from clipforge.media.validate import validate_asr_audio, validate_proxy
from clipforge.media.workspace import SourceWorkspace, atomic_replace, prepare_lock
from clipforge.schemas.governance import require_rights_cleared
from clipforge.schemas.ingest import (
    DerivativeCacheRecord,
    HdrSignal,
    NormalizedMediaProbe,
    SourceIngestManifest,
    VideoStreamInfo,
)
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import SourceAsset
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import (
    Database,
    find_artifact,
    get_asset_license_record,
    get_source_asset,
    get_source_manifest,
    insert_artifact,
    insert_job,
    list_jobs,
    update_artifact,
    update_job,
    update_source_manifest_stats,
)


@dataclass(frozen=True, slots=True)
class PrepareResult:
    job_id: str
    source_asset_id: str
    project_id: str
    proxy_path: Path
    proxy_sha256: str
    proxy_from_cache: bool
    audio_path: Path | None
    audio_sha256: str | None
    audio_from_cache: bool | None
    storage_estimate_bytes: int
    ffmpeg_version: str


@dataclass(frozen=True, slots=True)
class _Produced:
    kind: str
    path: Path
    sha256: str
    size_bytes: int
    recipe_name: str
    recipe_version: str
    arguments: tuple[str, ...]
    from_cache: bool
    ffmpeg_version: str


def prepare_source(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    runner: ProcessRunner | None = None,
    disk_status: DiskStatus | None = None,
    created_by: str | None = None,
) -> PrepareResult:
    active = runner or ProcessRunner()
    root = work_root.resolve()
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
        manifest = get_source_manifest(connection, source_asset_id)
        license_record = get_asset_license_record(connection, source.license_record_id)
    if source.project_id != manifest.project_id:
        raise MediaError(
            f"source {source_asset_id} is in project {source.project_id} but its manifest is in "
            f"{manifest.project_id}. Refusing to prepare across projects."
        )
    require_rights_cleared(license_record)
    path = path_from_file_uri(source.uri)
    drift = inspect_mutation(path, manifest)
    if drift is not None:
        with database.transaction() as connection:
            update_source_manifest_stats(
                connection,
                source_asset_id=source_asset_id,
                project_id=source.project_id,
                size_bytes=drift.size_bytes,
                mtime_ns=drift.mtime_ns,
            )
        manifest = manifest.model_copy(update={"size_bytes": drift.size_bytes, "mtime_ns": drift.mtime_ns})
    _reject_hdr(manifest.probe)
    estimate = estimate_prepare_bytes(
        manifest.canonical_duration_us,
        has_audio=manifest.transcription_eligible,
    )
    disk = disk_status if disk_status is not None else read_disk(root)
    require_disk_budget(disk.free_bytes, disk.reserve_bytes, estimate)

    actor = created_by.strip()[:200] if created_by and created_by.strip() else _actor()
    workspace = SourceWorkspace(root, source.project_id, source_asset_id)
    workspace.ensure()
    with prepare_lock(workspace):
        return _prepare_while_locked(
            database=database,
            source=source,
            manifest=manifest,
            path=path,
            source_asset_id=source_asset_id,
            root=root,
            workspace=workspace,
            active=active,
            actor=actor,
            estimate=estimate,
        )


def _prepare_while_locked(
    *,
    database: Database,
    source: SourceAsset,
    manifest: SourceIngestManifest,
    path: Path,
    source_asset_id: str,
    root: Path,
    workspace: SourceWorkspace,
    active: ProcessRunner,
    actor: str,
    estimate: int,
) -> PrepareResult:
    """Run one prepare while this process holds the source lock.

    Stale ``running`` rows are failed only after the lock is held, so a live
    prepare in another process cannot be marked failed or have its partials removed.
    """
    workspace.clear_partials()
    ffmpeg = _resolve_ffmpeg()
    _resolve_ffprobe()
    ffmpeg_version = _version(active, ffmpeg)
    now = datetime.now(UTC)
    job = JobRecord(
        job_id=str(uuid.uuid4()),
        project_id=source.project_id,
        kind=recipes.JOB_MEDIA_PREPARE,
        status=JobStatus.RUNNING,
        created_at=now,
        updated_at=now,
        payload={
            "source_asset_id": source_asset_id,
            "source_sha256": manifest.content_sha256,
            "video_stream_index": str(manifest.video_stream_index),
            "audio_stream_index": (
                "" if manifest.audio_stream_index is None else str(manifest.audio_stream_index)
            ),
            "storage_estimate_bytes": str(estimate),
            "ffmpeg_version": ffmpeg_version,
        },
    )
    with database.transaction() as connection:
        _fail_stale_jobs(connection, source.project_id, source_asset_id, now)
        insert_job(connection, job)
    log_path = workspace.log_file(f"{job.job_id}.log")
    produced: list[_Produced] = []
    try:
        video = _selected_video(manifest.probe)
        if manifest.transcription_eligible:
            produced.append(
                _ensure_audio(
                    source_path=path,
                    manifest=manifest,
                    workspace=workspace,
                    root=root,
                    runner=active,
                    ffmpeg=ffmpeg,
                    ffmpeg_version=ffmpeg_version,
                    log_path=log_path,
                )
            )
        produced.append(
            _ensure_proxy(
                source_path=path,
                manifest=manifest,
                video=video,
                workspace=workspace,
                root=root,
                runner=active,
                ffmpeg=ffmpeg,
                ffmpeg_version=ffmpeg_version,
                log_path=log_path,
            )
        )
    except KeyboardInterrupt:
        _close_job(
            database,
            job,
            JobStatus.CANCELLED,
            "interrupted by SIGINT. Partial outputs were not promoted.",
        )
        workspace.clear_partials()
        raise MediaCancelled(
            "media preparation was interrupted. The job was marked cancelled. "
            "Partial outputs were not promoted and the source file was not changed."
        ) from None
    except MediaCancelled:
        _close_job(database, job, JobStatus.CANCELLED, "cancelled. Partial outputs were not promoted.")
        workspace.clear_partials()
        raise
    except (MediaError, StorageError, ComplianceGateError) as exc:
        _close_job(database, job, JobStatus.FAILED, str(exc))
        workspace.clear_partials()
        raise
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        _close_job(database, job, JobStatus.FAILED, message)
        workspace.clear_partials()
        raise MediaError(message) from exc

    audio = next((item for item in produced if item.kind == recipes.KIND_ASR), None)
    proxy = next(item for item in produced if item.kind == recipes.KIND_PROXY)
    finished = datetime.now(UTC)
    payload = dict(job.payload)
    payload["analysis_proxy_sha256"] = proxy.sha256
    payload["analysis_proxy_recipe"] = recipes.recipe_id(proxy.recipe_name, proxy.recipe_version)
    payload["analysis_proxy_cache"] = "hit" if proxy.from_cache else "miss"
    payload["analysis_proxy_arguments"] = json.dumps(list(proxy.arguments))
    payload["validation_status"] = "passed"
    if audio is None:
        payload["asr_audio_cache"] = "skipped"
        payload["asr_audio_sha256"] = ""
        payload["asr_audio_recipe"] = ""
    else:
        payload["asr_audio_sha256"] = audio.sha256
        payload["asr_audio_recipe"] = recipes.recipe_id(audio.recipe_name, audio.recipe_version)
        payload["asr_audio_cache"] = "hit" if audio.from_cache else "miss"
        payload["asr_audio_arguments"] = json.dumps(list(audio.arguments))
    succeeded = job.model_copy(
        update={
            "status": JobStatus.SUCCEEDED,
            "updated_at": finished,
            "error_message": None,
            "payload": payload,
        }
    )
    try:
        with database.transaction() as connection:
            for item in produced:
                _store_artifact(connection, item, manifest, job.job_id, actor, finished)
            update_job(connection, succeeded)
    except (StorageError, MediaError) as exc:
        _close_job(database, job, JobStatus.FAILED, str(exc))
        raise
    return PrepareResult(
        job_id=job.job_id,
        source_asset_id=source_asset_id,
        project_id=source.project_id,
        proxy_path=proxy.path,
        proxy_sha256=proxy.sha256,
        proxy_from_cache=proxy.from_cache,
        audio_path=None if audio is None else audio.path,
        audio_sha256=None if audio is None else audio.sha256,
        audio_from_cache=None if audio is None else audio.from_cache,
        storage_estimate_bytes=estimate,
        ffmpeg_version=ffmpeg_version,
    )


def _ensure_audio(
    *,
    source_path: Path,
    manifest: SourceIngestManifest,
    workspace: SourceWorkspace,
    root: Path,
    runner: ProcessRunner,
    ffmpeg: str,
    ffmpeg_version: str,
    log_path: Path,
) -> _Produced:
    final = workspace.audio_file("asr.flac")
    sidecar = workspace.metadata_file("asr-audio.recipe.json")
    video = _selected_video(manifest.probe)
    offset = manifest.probe.timeline.audio_offset_us
    if offset is None or manifest.audio_stream_index is None:
        raise MediaError("the source is marked transcription-eligible but has no audio offset")
    rate = video.avg_frame_rate or video.r_frame_rate
    cached = _reuse(
        final=final,
        sidecar=sidecar,
        manifest=manifest,
        recipe_name=recipes.ASR_AUDIO_NAME,
        recipe_version=recipes.ASR_AUDIO_VERSION,
        validate=lambda: validate_asr_audio(
            final,
            runner,
            canonical_duration_us=manifest.canonical_duration_us,
            rate=rate,
            log_path=log_path,
        ),
    )
    if cached is not None:
        return _from_cache(cached, recipes.KIND_ASR, final, ffmpeg_version)
    graph = audio_filter_chain(
        manifest.audio_stream_index,
        offset,
        manifest.canonical_duration_us,
        output_rate=16000,
        label="out",
        pcm_s16=True,
    )
    partial = workspace.partial_for(final)
    argv = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-nostdin",
        "-i",
        str(source_path),
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-vn",
        "-c:a",
        "flac",
        "-sample_fmt",
        "s16",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(partial),
    ]
    try:
        runner.run(argv, log_path=log_path, check=True)
        validate_asr_audio(
            partial,
            runner,
            canonical_duration_us=manifest.canonical_duration_us,
            rate=rate,
            log_path=log_path,
        )
        digest = sha256_file(partial)
        size = partial.stat().st_size
        record = _record(
            manifest,
            recipes.ASR_AUDIO_NAME,
            recipes.ASR_AUDIO_VERSION,
            digest,
            size,
            ffmpeg_version,
            argv,
        )
        atomic_replace(partial, final, root)
        write_cache_record(sidecar, record, root)
    except Exception:
        if partial.is_file():
            partial.unlink()
        raise
    return _Produced(
        kind=recipes.KIND_ASR,
        path=final,
        sha256=digest,
        size_bytes=size,
        recipe_name=recipes.ASR_AUDIO_NAME,
        recipe_version=recipes.ASR_AUDIO_VERSION,
        arguments=tuple(argv),
        from_cache=False,
        ffmpeg_version=ffmpeg_version,
    )


def _ensure_proxy(
    *,
    source_path: Path,
    manifest: SourceIngestManifest,
    video: VideoStreamInfo,
    workspace: SourceWorkspace,
    root: Path,
    runner: ProcessRunner,
    ffmpeg: str,
    ffmpeg_version: str,
    log_path: Path,
) -> _Produced:
    if video.display_width is None or video.display_height is None:
        raise MediaError("selected video has no display dimensions. Refusing to guess a proxy size.")
    output_width, output_height = proxy_pixel_size(video.display_width, video.display_height)
    final = workspace.proxy_file("analysis.mp4")
    sidecar = workspace.metadata_file("analysis-proxy.recipe.json")
    rate = video.avg_frame_rate or video.r_frame_rate
    expect_audio = manifest.audio_stream_index is not None
    offset = 0 if manifest.probe.timeline.audio_offset_us is None else manifest.probe.timeline.audio_offset_us
    cached = _reuse(
        final=final,
        sidecar=sidecar,
        manifest=manifest,
        recipe_name=recipes.ANALYSIS_PROXY_NAME,
        recipe_version=recipes.ANALYSIS_PROXY_VERSION,
        validate=lambda: validate_proxy(
            final,
            runner,
            canonical_duration_us=manifest.canonical_duration_us,
            rate=rate,
            output_width=output_width,
            output_height=output_height,
            display_width=video.display_width or output_width,
            display_height=video.display_height or output_height,
            expect_audio=expect_audio,
            log_path=log_path,
        ),
    )
    if cached is not None:
        return _from_cache(cached, recipes.KIND_PROXY, final, ffmpeg_version)
    graph = proxy_filter_complex(
        video_index=video.index,
        audio_index=manifest.audio_stream_index,
        output_width=output_width,
        output_height=output_height,
        sample_aspect=video.sample_aspect_ratio,
        rotation=video.rotation.degrees,
        offset_us=offset,
        duration_us=manifest.canonical_duration_us,
    )
    partial = workspace.partial_for(final)
    argv = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-nostdin",
        "-noautorotate",
        "-i",
        str(source_path),
        "-filter_complex",
        graph,
        "-map",
        "[v]",
    ]
    if expect_audio:
        argv.extend(
            ["-map", "[a]", "-c:a", "aac", "-b:a", recipes.PROXY_AUDIO_BITRATE, "-ac", "1", "-ar", "48000"]
        )
    else:
        argv.append("-an")
    argv.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            recipes.PROXY_PRESET,
            "-crf",
            recipes.PROXY_CRF,
            "-pix_fmt",
            "yuv420p",
            "-fps_mode",
            "passthrough",
            "-map_metadata",
            "-1",
            str(partial),
        ]
    )
    try:
        runner.run(argv, log_path=log_path, check=True)
        validate_proxy(
            partial,
            runner,
            canonical_duration_us=manifest.canonical_duration_us,
            rate=rate,
            output_width=output_width,
            output_height=output_height,
            display_width=video.display_width,
            display_height=video.display_height,
            expect_audio=expect_audio,
            log_path=log_path,
        )
        digest = sha256_file(partial)
        size = partial.stat().st_size
        record = _record(
            manifest,
            recipes.ANALYSIS_PROXY_NAME,
            recipes.ANALYSIS_PROXY_VERSION,
            digest,
            size,
            ffmpeg_version,
            argv,
        )
        atomic_replace(partial, final, root)
        write_cache_record(sidecar, record, root)
    except Exception:
        if partial.is_file():
            partial.unlink()
        raise
    return _Produced(
        kind=recipes.KIND_PROXY,
        path=final,
        sha256=digest,
        size_bytes=size,
        recipe_name=recipes.ANALYSIS_PROXY_NAME,
        recipe_version=recipes.ANALYSIS_PROXY_VERSION,
        arguments=tuple(argv),
        from_cache=False,
        ffmpeg_version=ffmpeg_version,
    )


def _reuse(
    *,
    final: Path,
    sidecar: Path,
    manifest: SourceIngestManifest,
    recipe_name: str,
    recipe_version: str,
    validate: Callable[[], object],
) -> DerivativeCacheRecord | None:
    record = read_cache_record(sidecar)
    if record is None:
        return None
    if not cache_identity_matches(
        record,
        recipe_name=recipe_name,
        recipe_version=recipe_version,
        source_sha256=manifest.content_sha256,
        project_id=manifest.project_id,
        source_asset_id=manifest.source_asset_id,
        video_stream_index=manifest.video_stream_index,
        audio_stream_index=manifest.audio_stream_index,
        artifact_path=final,
    ):
        return None
    try:
        validate()
    except (MediaError, OSError):
        return None
    return record


def _from_cache(record: DerivativeCacheRecord, kind: str, path: Path, ffmpeg_version: str) -> _Produced:
    return _Produced(
        kind=kind,
        path=path,
        sha256=record.artifact_sha256,
        size_bytes=record.size_bytes,
        recipe_name=record.recipe_name,
        recipe_version=record.recipe_version,
        arguments=tuple(record.arguments),
        from_cache=True,
        ffmpeg_version=ffmpeg_version,
    )


def _record(
    manifest: SourceIngestManifest,
    name: str,
    version: str,
    digest: str,
    size: int,
    ffmpeg_version: str,
    argv: list[str],
) -> DerivativeCacheRecord:
    return DerivativeCacheRecord(
        recipe_name=name,
        recipe_version=version,
        source_sha256=manifest.content_sha256,
        project_id=manifest.project_id,
        source_asset_id=manifest.source_asset_id,
        video_stream_index=manifest.video_stream_index,
        audio_stream_index=manifest.audio_stream_index,
        artifact_sha256=digest,
        size_bytes=size,
        ffmpeg_version=ffmpeg_version,
        arguments=argv,
        validation_status="passed",
        created_at=datetime.now(UTC),
    )


def _store_artifact(
    connection: sqlite3.Connection,
    item: _Produced,
    manifest: SourceIngestManifest,
    job_id: str,
    actor: str,
    now: datetime,
) -> None:
    provenance = ArtifactProvenance(
        created_at=now,
        created_by=actor,
        tool=recipes.recipe_id(item.recipe_name, item.recipe_version),
        tool_version=item.ffmpeg_version[:80],
        source_asset_ids=[manifest.source_asset_id],
        job_id=job_id,
        inputs_sha256=manifest.content_sha256,
    )
    existing = find_artifact(connection, manifest.project_id, manifest.source_asset_id, item.kind)
    uri = path_to_file_uri(item.path)
    if existing is None:
        insert_artifact(
            connection,
            artifact_id=str(uuid.uuid4()),
            project_id=manifest.project_id,
            job_id=job_id,
            source_asset_id=manifest.source_asset_id,
            kind=item.kind,
            uri=uri,
            provenance=provenance,
        )
        return
    update_artifact(
        connection,
        artifact_id=existing.artifact_id,
        project_id=manifest.project_id,
        job_id=job_id,
        source_asset_id=manifest.source_asset_id,
        kind=item.kind,
        uri=uri,
        provenance=provenance,
    )


def _close_job(database: Database, job: JobRecord, status: JobStatus, message: str) -> None:
    updated = job.model_copy(
        update={
            "status": status,
            "updated_at": datetime.now(UTC),
            "error_message": message[:2000],
        }
    )
    with database.transaction() as connection:
        update_job(connection, updated)


def _fail_stale_jobs(
    connection: sqlite3.Connection, project_id: str, source_asset_id: str, now: datetime
) -> None:
    for existing in list_jobs(connection, project_id):
        if existing.kind != recipes.JOB_MEDIA_PREPARE or existing.status is not JobStatus.RUNNING:
            continue
        if existing.payload.get("source_asset_id") != source_asset_id:
            continue
        update_job(
            connection,
            existing.model_copy(
                update={
                    "status": JobStatus.FAILED,
                    "updated_at": now,
                    "error_message": (
                        "interrupted before completion. The source lock was free, so this running "
                        "job had no live prepare. Partial outputs were not promoted."
                    ),
                }
            ),
        )


def _reject_hdr(probe: NormalizedMediaProbe) -> None:
    if probe.classification.hdr is HdrSignal.NONE:
        return
    video = _selected_video(probe)
    transfer = video.color.color_transfer or "unreported"
    raise MediaError(
        f"HDR source detected ({probe.classification.hdr.value}, color_transfer={transfer}). "
        "Round 2 does not convert HDR to SDR, because an arbitrary conversion would change the image. "
        "Proxy generation was not started. Use an SDR master. Full HDR support is not claimed."
    )


def _selected_video(probe: NormalizedMediaProbe) -> VideoStreamInfo:
    for stream in probe.video_streams:
        if stream.index == probe.selection.video_stream_index:
            return stream
    raise MediaError("stored probe does not contain the selected video stream")


def _resolve_ffmpeg() -> str:
    from clipforge.media.tools import resolve_ffmpeg

    return resolve_ffmpeg()


def _resolve_ffprobe() -> str:
    from clipforge.media.tools import resolve_ffprobe

    return resolve_ffprobe()


def _version(runner: ProcessRunner, executable: str) -> str:
    from clipforge.media.tools import tool_version

    return tool_version(runner, executable)


def _actor() -> str:
    import getpass

    try:
        return getpass.getuser()
    except OSError as exc:
        raise MediaError(f"could not determine the OS user for provenance: {exc}") from exc
