"""Render the current candidate set into rough review MP4s.

Lock order is shared prepare, shared transcribe, shared vision, shared
candidate, then the exclusive preview lock. A busy lock fails before a job
row is inserted.
"""

from __future__ import annotations

import getpass
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import ValidationError

from clipforge import __version__
from clipforge.errors import MediaError, StorageError
from clipforge.media.disk import read_disk, require_disk_budget
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_to_file_uri
from clipforge.media.workspace import (
    atomic_replace,
    candidate_read_lock,
    ensure_within,
    prepare_read_lock,
    preview_lock,
    safe_unlink,
    transcribe_read_lock,
    vision_read_lock,
)
from clipforge.preview.backend import RemotionRoughRenderBackend, RoughRenderBackend
from clipforge.preview.captions import plan_captions
from clipforge.preview.constants import DISK_ESTIMATE_BYTES, JOB_PREVIEW, KIND_PREVIEW, TOOL_NAME
from clipforge.preview.inputs import PreviewInputs, load_preview_inputs
from clipforge.preview.integrity import artifact_path, preview_problems
from clipforge.preview.probe import probe_preview
from clipforge.preview.timing import media_trim_frame
from clipforge.schemas.editorial import CandidateClip
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.preview import (
    CandidateRoughPreview,
    RoughPreviewCacheRecord,
    RoughPreviewProfile,
    RoughPreviewRenderInput,
    RoughPreviewSetDocument,
    RoughPreviewSetSummary,
)
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import digest_time_map
from clipforge.storage import (
    Database,
    find_artifact,
    get_job,
    insert_artifact,
    insert_job,
    list_jobs,
    update_artifact,
    update_job,
)
from clipforge.timeline.framerate import FrameRate
from clipforge.transcription.io import dump_json, publish_json

_PROFILE = RoughPreviewProfile()


@dataclass(frozen=True, slots=True)
class PreviewRenderResult:
    job_id: str
    preview_set_id: str
    source_asset_id: str
    mining_id: str
    candidate_count: int
    rendered_count: int
    manifest_path: Path
    manifest_sha256: str
    cache_hit: bool
    runtime_seconds: float


def default_profile() -> RoughPreviewProfile:
    return _PROFILE


def render_previews(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    force: bool = False,
    profile: RoughPreviewProfile | None = None,
    backend: RoughRenderBackend | None = None,
    created_by: str | None = None,
    candidate_id: str | None = None,
) -> PreviewRenderResult:
    """Render every selected candidate for ``source_asset_id``."""
    root = work_root.resolve()
    active = profile or default_profile()
    renderer = backend if backend is not None else RemotionRoughRenderBackend()
    inputs = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=active.fingerprint(),
        create_workspace=True,
    )
    actor = created_by.strip()[:200] if created_by and created_by.strip() else _actor()
    started = perf_counter()
    source = inputs.pair.source.source_asset_id
    with (
        prepare_read_lock(inputs.pair.workspace, busy=_busy(source, "media prepare", "derived media")),
        transcribe_read_lock(inputs.pair.workspace, busy=_busy(source, "transcription", "transcript")),
        vision_read_lock(inputs.pair.workspace, busy=_busy(source, "visual analysis", "visual analysis")),
        candidate_read_lock(inputs.pair.workspace, busy=_busy(source, "candidate mining", "candidate set")),
        preview_lock(inputs.pair.workspace),
    ):
        inputs = load_preview_inputs(
            database,
            source_asset_id,
            root,
            profile_fingerprint=active.fingerprint(),
            create_workspace=True,
        )
        _fail_stale(database, inputs)
        if not force and _cache_ready(database, inputs, active, candidate_id):
            return _cache_result(database, inputs, started)
        if renderer.requires_browser:
            from clipforge.preview.browser import resolve_browser

            resolve_browser()
        _require_budget(root)
        now = datetime.now(UTC)
        job = _running_job(inputs, active, now)
        with database.transaction() as connection:
            insert_job(connection, job)
        preview_set_id = str(uuid.uuid4())
        run_dir: Path | None = None
        try:
            inputs = _confirm(database, source_asset_id, root, active, inputs)
            run_dir = inputs.pair.workspace.make_preview_run(preview_set_id)
            document, manifest = _render_run(
                inputs,
                active,
                renderer,
                preview_set_id,
                job,
                actor,
                now,
                root,
                run_dir,
                candidate_id,
            )
            digest = sha256_file(manifest)
            record = _cache_record(inputs, document, job.job_id, digest, manifest.stat().st_size, now)
            _commit_and_publish(database, inputs, job, document, manifest, record, actor, root)
        except KeyboardInterrupt:
            _abandon(
                database,
                inputs,
                job,
                JobStatus.CANCELLED,
                "rough preview render cancelled",
                run_dir,
                root,
            )
            raise
        except (MediaError, StorageError, OSError, ValidationError, ValueError) as exc:
            _abandon(database, inputs, job, JobStatus.FAILED, str(exc), run_dir, root)
            raise
    return _result(document, job_id=job.job_id, path=manifest, digest=digest, cache_hit=False, started=started)


def _render_run(
    inputs: PreviewInputs,
    profile: RoughPreviewProfile,
    backend: RoughRenderBackend,
    preview_set_id: str,
    job: JobRecord,
    actor: str,
    now: datetime,
    root: Path,
    run_dir: Path,
    candidate_id: str | None = None,
) -> tuple[RoughPreviewSetDocument, Path]:
    browser = backend.requires_browser
    if not browser:
        _stage_media(inputs, run_dir, root)
    else:
        staging = run_dir / "staging"
        ensure_within(root, staging)
        staging.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, object]] = []
    built: list[tuple[CandidateClip, RoughPreviewRenderInput, Path, Path]] = []
    chosen = _selected(inputs, candidate_id)
    for candidate in chosen:
        directory = inputs.pair.workspace.preview_candidate_dir(preview_set_id, candidate.candidate_id)
        directory.mkdir()
        rendered = _render_input(
            inputs,
            candidate,
            profile,
            preview_set_id,
            run_dir,
            browser=browser,
        )
        input_path = directory / "render-input.json"
        partial = inputs.pair.workspace.partial_for(directory / "preview.mp4")
        publish_json(input_path, rendered, root, inputs.pair.workspace.partial_for(input_path))
        segment = candidate.time_map.segments[0]
        items.append(
            {
                "outputPath": str(partial),
                "h264Crf": profile.h264_crf,
                "input": json.loads(dump_json(rendered)),
                "watch": {
                    "candidate_id": candidate.candidate_id,
                    "source_id": inputs.pair.source.source_asset_id,
                    "source_start_us": segment.source_start_us,
                    "source_end_us": segment.source_end_us,
                    "duration_in_frames": rendered.duration_in_frames,
                    "staged_duration_us": rendered.staged_duration_us,
                    "proxy_sha256": rendered.proxy_sha256,
                    "staged_video_sha256": rendered.staged_video_sha256,
                },
            }
        )
        built.append((candidate, rendered, input_path, partial))
    if items:
        batch = run_dir / "render-batch.json"
        batch.write_text(json.dumps({"items": items}, sort_keys=True) + "\n", encoding="utf-8")
        backend.render_batch(batch, log_path=run_dir / "logs" / f"{job.job_id}.log")
    _cleanup_transients(run_dir, root)
    previews: list[CandidateRoughPreview] = []
    for rank, (candidate, rendered, input_path, partial) in enumerate(built, start=1):
        previews.append(
            _publish_one(
                inputs,
                candidate,
                rendered,
                input_path,
                partial,
                rank,
                root,
                run_dir,
            )
        )
    document = _document(inputs, profile, preview_set_id, job, actor, now, previews)
    manifest = run_dir / "manifest.json"
    publish_json(manifest, document, root, inputs.pair.workspace.partial_for(manifest))
    # Re-read so the stored document is the one we just validated on disk.
    stored = RoughPreviewSetDocument.model_validate_json(manifest.read_text(encoding="utf-8"))
    return stored, manifest


def _selected(inputs: PreviewInputs, candidate_id: str | None) -> list[CandidateClip]:
    rows = list(inputs.candidate_document.candidates)
    if candidate_id is None:
        return rows
    chosen = [item for item in rows if item.candidate_id == candidate_id]
    if not chosen:
        raise MediaError(f"candidate {candidate_id} is not in the current selected set")
    return chosen


def _render_input(
    inputs: PreviewInputs,
    candidate: CandidateClip,
    profile: RoughPreviewProfile,
    preview_set_id: str,
    run_dir: Path,
    *,
    browser: bool,
) -> RoughPreviewRenderInput:
    segment = candidate.time_map.segments[0]
    time_map = candidate.time_map.to_time_map()
    frame_count = time_map.output_frame_count(FrameRate(profile.fps_numerator, profile.fps_denominator))
    if frame_count < 1:
        raise MediaError(f"candidate {candidate.candidate_id} has no preview frames")
    bundles = inputs.candidate_document.evidence_bundles
    bundle = next(item for item in bundles if item.candidate_id == candidate.candidate_id)
    captions = plan_captions(
        inputs.pair.transcript,
        bundle,
        time_map,
        profile=profile,
        frame_count=frame_count,
        mining_id=inputs.candidate_document.mining_id,
    )
    video_path = run_dir / "staging" / "analysis.mp4"
    audio_path = run_dir / "staging" / "asr.flac"
    trim_frame = media_trim_frame(segment.source_start_us)
    staged_video_sha = ""
    staged_audio_sha = ""
    staged_duration = 0
    if browser:
        from clipforge.preview.trim import stage_candidate_span

        staged = stage_candidate_span(
            inputs.proxy_path,
            inputs.asr_path,
            run_dir / "staging",
            stem=candidate.candidate_id,
            start_us=segment.source_start_us,
            end_us=segment.source_end_us,
            frame_count=frame_count,
            root=inputs.pair.workspace.root,
            log_path=run_dir / "logs" / f"{candidate.candidate_id}.trim.log",
        )
        video_path = staged.video_path
        audio_path = staged.audio_path
        trim_frame = 0
        staged_video_sha = staged.video_sha256
        staged_audio_sha = staged.audio_sha256
        staged_duration = staged.duration_us
    return RoughPreviewRenderInput(
        candidate_id=candidate.candidate_id,
        preview_set_id=preview_set_id,
        video_path=str(video_path),
        audio_path=str(audio_path),
        media_trim_frame=trim_frame,
        duration_in_frames=frame_count,
        captions=captions,
        source_start_us=segment.source_start_us,
        source_end_us=segment.source_end_us,
        background=profile.background,
        word_timing_source=(
            "transcript-word-times-v1" if any(cue.words for cue in captions) else "segment-only-v1"
        ),
        proxy_sha256=inputs.proxy_sha256,
        staged_video_sha256=staged_video_sha,
        staged_audio_sha256=staged_audio_sha,
        staged_duration_us=staged_duration,
    )


def _publish_one(
    inputs: PreviewInputs,
    candidate: CandidateClip,
    rendered: RoughPreviewRenderInput,
    input_path: Path,
    partial: Path,
    rank: int,
    root: Path,
    run_dir: Path,
) -> CandidateRoughPreview:
    if not partial.is_file() or partial.is_symlink():
        raise MediaError(f"renderer did not produce a preview file for {candidate.candidate_id}")
    segment = candidate.time_map.segments[0]
    duration = candidate.time_map.to_time_map().total_output_duration()
    probed = probe_preview(
        partial,
        expected_duration_us=duration,
        log_path=run_dir / "logs" / f"{candidate.candidate_id}.ffprobe.json",
    )
    final = input_path.parent / "preview.mp4"
    atomic_replace(partial, final, root)
    scores = inputs.candidate_document.score_breakdowns
    breakdown = next(item for item in scores if item.candidate_id == candidate.candidate_id)
    relative = f"candidates/{candidate.candidate_id}/preview.mp4"
    return CandidateRoughPreview(
        candidate_id=candidate.candidate_id,
        rank=rank,
        time_map_sha256=digest_time_map(candidate.time_map),
        source_start_us=segment.source_start_us,
        source_end_us=segment.source_end_us,
        output_duration_us=duration,
        output_frame_count=rendered.duration_in_frames,
        caption_count=len(rendered.captions),
        render_input_sha256=sha256_file(input_path),
        preview_relative_path=relative,
        preview_sha256=sha256_file(final),
        preview_size_bytes=final.stat().st_size,
        detected_video_codec=probed.video_codec,
        detected_pixel_format=probed.pixel_format,
        detected_audio_codec=probed.audio_codec,
        detected_duration_us=probed.duration_us,
        duration_error_us=probed.duration_error_us,
        quality_score=breakdown.quality_score,
        edit_opportunity_score=breakdown.edit_opportunity_score,
    )


def _document(
    inputs: PreviewInputs,
    profile: RoughPreviewProfile,
    preview_set_id: str,
    job: JobRecord,
    actor: str,
    now: datetime,
    previews: list[CandidateRoughPreview],
) -> RoughPreviewSetDocument:
    summary = RoughPreviewSetSummary(
        selected_candidate_count=len(previews),
        rendered_count=len(previews),
        total_output_duration_us=sum(item.output_duration_us for item in previews),
        total_preview_bytes=sum(item.preview_size_bytes for item in previews),
    )
    return RoughPreviewSetDocument(
        preview_set_id=preview_set_id,
        project_id=inputs.pair.source.project_id,
        source_asset_id=inputs.pair.source.source_asset_id,
        mining_id=inputs.candidate_document.mining_id,
        created_at=now,
        source_sha256=inputs.pair.manifest.content_sha256,
        candidate_set_artifact_id=inputs.candidate_artifact_id,
        candidate_set_sha256=inputs.candidate_sha256,
        transcript_id=inputs.pair.transcript.transcript_id,
        transcript_sha256=inputs.pair.transcript_sha256,
        visual_analysis_id=inputs.pair.visual.analysis_id,
        visual_analysis_sha256=inputs.pair.visual_sha256,
        analysis_proxy_sha256=inputs.proxy_sha256,
        asr_audio_sha256=inputs.asr_sha256,
        preview_input_sha256=inputs.preview_input_sha256,
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        tool_version=__version__,
        previews=previews,
        summary=summary,
        provenance=ArtifactProvenance(
            created_at=now,
            created_by=actor,
            tool=TOOL_NAME,
            tool_version=__version__,
            source_asset_ids=[inputs.pair.source.source_asset_id],
            job_id=job.job_id,
            inputs_sha256=inputs.preview_input_sha256,
        ),
    )


def _stage_media(inputs: PreviewInputs, run_dir: Path, root: Path) -> None:
    staging = run_dir / "staging"
    ensure_within(root, staging)
    _link_or_copy(inputs.proxy_path, staging / "analysis.mp4", root)
    _link_or_copy(inputs.asr_path, staging / "asr.flac", root)


def _link_or_copy(source: Path, destination: Path, root: Path) -> None:
    ensure_within(root, destination)
    if source.is_symlink() or destination.exists():
        raise MediaError(f"refusing to stage {source.name} through a symlink")
    try:
        os.link(source, destination)
    except OSError:
        # Same-filesystem hard links are preferred. A copy stays inside this run.
        destination.write_bytes(source.read_bytes())


def _cleanup_staging(run_dir: Path, root: Path) -> None:
    staging = run_dir / "staging"
    if not staging.exists():
        return
    ensure_within(root, staging)
    if staging.is_symlink():
        raise MediaError("refusing to clean a symlinked preview staging directory")
    for path in sorted(staging.iterdir()):
        if path.is_symlink() or not path.is_file():
            raise MediaError(f"refusing to clean unexpected staging path {path.name}")
        ensure_within(root, path)
        path.unlink()
    staging.rmdir()


def _cleanup_transients(run_dir: Path, root: Path) -> None:
    """Remove staged media and the batch file; neither is a persistent preview artifact."""
    _cleanup_staging(run_dir, root)
    batch = run_dir / "render-batch.json"
    ensure_within(root, batch)
    if batch.is_symlink():
        raise MediaError("refusing to clean a symlinked preview render batch")
    safe_unlink(root, batch)


def _confirm(
    database: Database,
    source_asset_id: str,
    root: Path,
    profile: RoughPreviewProfile,
    expected: PreviewInputs,
) -> PreviewInputs:
    current = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=profile.fingerprint(),
        create_workspace=True,
    )
    if current.preview_input_sha256 != expected.preview_input_sha256:
        raise MediaError("upstream evidence changed after the preview job started. Nothing was published.")
    return current


def _cache_ready(
    database: Database,
    inputs: PreviewInputs,
    profile: RoughPreviewProfile,
    candidate_id: str | None = None,
) -> bool:
    from clipforge.transcription.io import read_text

    sidecar = inputs.pair.workspace.preview_sidecar()
    if not sidecar.is_file() or sidecar.is_symlink():
        return False
    try:
        record = RoughPreviewCacheRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return False
    if record.profile_fingerprint != profile.fingerprint():
        return False
    with database.connect() as connection:
        row = find_artifact(
            connection,
            inputs.pair.source.project_id,
            inputs.pair.source.source_asset_id,
            KIND_PREVIEW,
        )
        if row is None or row.job_id is None:
            return False
        try:
            job = get_job(connection, row.job_id)
        except StorageError:
            return False
    try:
        path = artifact_path(row.uri)
        expected = inputs.pair.workspace.preview_run_dir(record.preview_set_id) / "manifest.json"
        ensure_within(inputs.pair.workspace.root, path)
        if path != expected or path.is_symlink() or not path.is_file():
            return False
        document = RoughPreviewSetDocument.model_validate_json(read_text(path))
    except (OSError, ValidationError, ValueError, MediaError):
        return False
    selected = [item.candidate_id for item in inputs.candidate_document.candidates]
    rendered = [item.candidate_id for item in document.previews]
    if candidate_id is None and rendered != selected:
        return False
    if candidate_id is not None and rendered != [candidate_id]:
        return False
    return not preview_problems(
        document,
        record,
        manifest_path=path,
        work_root=inputs.pair.workspace.root,
        workspace=inputs.pair.workspace,
        inputs=inputs,
        artifact_job_id=row.job_id,
        artifact_uri=row.uri,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
    )


def _cache_result(database: Database, inputs: PreviewInputs, started: float) -> PreviewRenderResult:
    with database.connect() as connection:
        row = find_artifact(
            connection,
            inputs.pair.source.project_id,
            inputs.pair.source.source_asset_id,
            KIND_PREVIEW,
        )
    if row is None or row.job_id is None:
        raise MediaError("preview cache matched but the artifact row disappeared before reuse")
    path = artifact_path(row.uri)
    sidecar = inputs.pair.workspace.preview_sidecar()
    try:
        record = RoughPreviewCacheRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise MediaError("preview cache sidecar disappeared before reuse") from exc
    expected = inputs.pair.workspace.preview_run_dir(record.preview_set_id) / "manifest.json"
    ensure_within(inputs.pair.workspace.root, path)
    if path != expected or path.is_symlink() or not path.is_file():
        raise MediaError("preview cache manifest moved outside the expected preview run before reuse")
    document = RoughPreviewSetDocument.model_validate_json(path.read_text(encoding="utf-8"))
    return _result(
        document,
        job_id=row.job_id,
        path=path,
        digest=sha256_file(path),
        cache_hit=True,
        started=started,
    )


def _running_job(inputs: PreviewInputs, profile: RoughPreviewProfile, now: datetime) -> JobRecord:
    return JobRecord(
        job_id=str(uuid.uuid4()),
        project_id=inputs.pair.source.project_id,
        kind=JOB_PREVIEW,
        status=JobStatus.RUNNING,
        created_at=now,
        updated_at=now,
        payload={
            "source_asset_id": inputs.pair.source.source_asset_id,
            "source_sha256": inputs.pair.manifest.content_sha256,
            "mining_id": inputs.candidate_document.mining_id,
            "candidate_set_sha256": inputs.candidate_sha256,
            "transcript_id": inputs.pair.transcript.transcript_id,
            "transcript_sha256": inputs.pair.transcript_sha256,
            "visual_analysis_id": inputs.pair.visual.analysis_id,
            "visual_analysis_sha256": inputs.pair.visual_sha256,
            "analysis_proxy_sha256": inputs.proxy_sha256,
            "asr_audio_sha256": inputs.asr_sha256,
            "preview_input_sha256": inputs.preview_input_sha256,
            "profile_fingerprint": profile.fingerprint(),
            "renderer_recipe_version": profile.renderer_recipe_version,
            "caption_algorithm_version": profile.caption_algorithm_version,
            "candidate_count": str(len(inputs.candidate_document.candidates)),
            "cache": "miss",
        },
    )


def _cache_record(
    inputs: PreviewInputs,
    document: RoughPreviewSetDocument,
    job_id: str,
    digest: str,
    size: int,
    created_at: datetime,
) -> RoughPreviewCacheRecord:
    return RoughPreviewCacheRecord(
        project_id=document.project_id,
        source_asset_id=document.source_asset_id,
        preview_set_id=document.preview_set_id,
        job_id=job_id,
        mining_id=document.mining_id,
        source_sha256=document.source_sha256,
        candidate_set_artifact_id=document.candidate_set_artifact_id,
        candidate_set_sha256=document.candidate_set_sha256,
        transcript_id=document.transcript_id,
        transcript_sha256=document.transcript_sha256,
        visual_analysis_id=document.visual_analysis_id,
        visual_analysis_sha256=document.visual_analysis_sha256,
        analysis_proxy_sha256=document.analysis_proxy_sha256,
        asr_audio_sha256=document.asr_audio_sha256,
        preview_input_sha256=document.preview_input_sha256,
        profile_fingerprint=document.profile_fingerprint,
        manifest_sha256=digest,
        manifest_size_bytes=size,
        rendered_count=document.summary.rendered_count,
        validation_status="passed",
        created_at=created_at,
    )


def _commit_and_publish(
    database: Database,
    inputs: PreviewInputs,
    job: JobRecord,
    document: RoughPreviewSetDocument,
    manifest: Path,
    record: RoughPreviewCacheRecord,
    actor: str,
    root: Path,
) -> None:
    previous = _artifact_snapshot(database, inputs)
    provenance = ArtifactProvenance(
        created_at=document.created_at,
        created_by=actor,
        tool=TOOL_NAME,
        tool_version=__version__,
        source_asset_ids=[inputs.pair.source.source_asset_id],
        job_id=job.job_id,
        inputs_sha256=document.preview_input_sha256,
    )
    payload = dict(job.payload)
    payload["preview_set_id"] = document.preview_set_id
    payload["candidate_count"] = str(document.summary.rendered_count)
    succeeded = job.model_copy(
        update={
            "status": JobStatus.SUCCEEDED,
            "updated_at": document.created_at,
            "error_message": None,
            "payload": payload,
        }
    )
    with database.transaction() as connection:
        # A new preview set gets a new artifact id. Reviews stay on the set that was watched.
        insert_artifact(
            connection,
            artifact_id=str(uuid.uuid4()),
            project_id=inputs.pair.source.project_id,
            job_id=job.job_id,
            source_asset_id=inputs.pair.source.source_asset_id,
            kind=KIND_PREVIEW,
            uri=path_to_file_uri(manifest),
            provenance=provenance,
        )
        update_job(connection, succeeded)
    try:
        publish_json(
            inputs.pair.workspace.preview_sidecar(),
            record,
            root,
            inputs.pair.workspace.partial_for(inputs.pair.workspace.preview_sidecar()),
        )
    except (OSError, MediaError) as exc:
        _revert_artifact(database, inputs, previous, job, str(exc))
        raise MediaError(
            f"rough preview sidecar was not published: {exc}. The previous preview set remains current."
        ) from exc


def _artifact_snapshot(
    database: Database,
    inputs: PreviewInputs,
) -> tuple[str, str | None, str, ArtifactProvenance] | None:
    with database.connect() as connection:
        row = find_artifact(
            connection,
            inputs.pair.source.project_id,
            inputs.pair.source.source_asset_id,
            KIND_PREVIEW,
        )
    if row is None:
        return None
    return row.artifact_id, row.job_id, row.uri, row.provenance


def _revert_artifact(
    database: Database,
    inputs: PreviewInputs,
    previous: tuple[str, str | None, str, ArtifactProvenance] | None,
    job: JobRecord,
    reason: str,
) -> None:
    failed = job.model_copy(
        update={
            "status": JobStatus.FAILED,
            "updated_at": datetime.now(UTC),
            "error_message": f"sidecar publish failed: {reason}"[:2000],
        }
    )
    with database.transaction() as connection:
        if previous is not None:
            artifact_id, job_id, uri, provenance = previous
            update_artifact(
                connection,
                artifact_id=artifact_id,
                project_id=inputs.pair.source.project_id,
                job_id=job_id,
                source_asset_id=inputs.pair.source.source_asset_id,
                kind=KIND_PREVIEW,
                uri=uri,
                provenance=provenance,
            )
        connection.execute(
            """
            DELETE FROM artifacts
            WHERE project_id = ? AND source_asset_id = ? AND kind = ? AND job_id = ?
            """,
            (
                inputs.pair.source.project_id,
                inputs.pair.source.source_asset_id,
                KIND_PREVIEW,
                job.job_id,
            ),
        )
        update_job(connection, failed)


def _fail_stale(database: Database, inputs: PreviewInputs) -> None:
    now = datetime.now(UTC)
    with database.transaction() as connection:
        for existing in list_jobs(connection, inputs.pair.source.project_id):
            if existing.kind != JOB_PREVIEW or existing.status is not JobStatus.RUNNING:
                continue
            if existing.payload.get("source_asset_id") != inputs.pair.source.source_asset_id:
                continue
            update_job(
                connection,
                existing.model_copy(
                    update={
                        "status": JobStatus.FAILED,
                        "updated_at": now,
                        "error_message": (
                            "interrupted before completion. The preview lock was free, so no live "
                            "preview render owned this running job. Partial outputs were not promoted."
                        ),
                    }
                ),
            )


def _abandon(
    database: Database,
    inputs: PreviewInputs,
    job: JobRecord,
    status: JobStatus,
    message: str,
    run_dir: Path | None,
    root: Path,
) -> None:
    del inputs
    notes: list[str] = []
    if run_dir is not None:
        try:
            _cleanup_transients(run_dir, root)
        except (OSError, MediaError) as exc:
            notes.append(str(exc))
    try:
        _cleanup_partials(run_dir, root)
    except (OSError, MediaError) as exc:
        notes.append(str(exc))
    detail = message if not notes else f"{message} Cleanup also failed: {'; '.join(notes)}"
    try:
        updated = job.model_copy(
            update={"status": status, "updated_at": datetime.now(UTC), "error_message": detail[:2000]}
        )
        with database.transaction() as connection:
            update_job(connection, updated)
    except Exception:
        # The original failure is already propagating. A second database error
        # must not replace it with a false success.
        return


def _cleanup_partials(run_dir: Path | None, root: Path) -> None:
    if run_dir is None or not run_dir.exists():
        return
    ensure_within(root, run_dir)
    if run_dir.is_symlink():
        raise MediaError(f"refusing to clean a symlinked preview run {run_dir}")
    for path in sorted(run_dir.rglob("*")):
        if path.is_symlink():
            raise MediaError(f"refusing to clean symlink {path}")
        ensure_within(root, path)
        if path.is_file() and ".partial." in path.name:
            path.unlink()


def _require_budget(root: Path) -> None:
    status = read_disk(root if root.exists() else root.parent)
    try:
        require_disk_budget(status.free_bytes, status.reserve_bytes, DISK_ESTIMATE_BYTES)
    except MediaError as exc:
        raise MediaError(f"{exc} Rough preview rendering was not started.") from exc


def _busy(source: str, holder: str, noun: str) -> str:
    return (
        f"another {holder} is already active for source {source}. "
        f"Clipforge refused to start rough preview rendering while the current {noun} can be replaced."
    )


def _result(
    document: RoughPreviewSetDocument,
    *,
    job_id: str,
    path: Path,
    digest: str,
    cache_hit: bool,
    started: float,
) -> PreviewRenderResult:
    return PreviewRenderResult(
        job_id=job_id,
        preview_set_id=document.preview_set_id,
        source_asset_id=document.source_asset_id,
        mining_id=document.mining_id,
        candidate_count=document.summary.selected_candidate_count,
        rendered_count=document.summary.rendered_count,
        manifest_path=path,
        manifest_sha256=digest,
        cache_hit=cache_hit,
        runtime_seconds=perf_counter() - started,
    )


def _actor() -> str:
    try:
        return getpass.getuser()
    except OSError as exc:
        raise MediaError(f"could not determine the OS user for provenance: {exc}") from exc
