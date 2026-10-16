"""Render Hero drafts for candidates approved on the current rough preview.

Lock order is shared prepare, shared transcribe, shared vision, shared
candidate, shared preview, then the exclusive Hero lock. A busy lock fails
before a job row is inserted. A Hero run does not replace the rough preview.
"""

from __future__ import annotations

import getpass
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import ValidationError

from clipforge import __version__
from clipforge.errors import MediaError, StorageError
from clipforge.hero.alignment import (
    ForcedAlignmentBackend,
    WhisperXAlignment,
    alignment_config_sha256,
    build_alignment,
    production_alignment_backend,
)
from clipforge.hero.backend import HeroRenderBackend, RemotionHeroRenderBackend
from clipforge.hero.captions import hero_caption_pieces
from clipforge.hero.constants import (
    DISK_ESTIMATE_BYTES,
    JOB_HERO,
    KIND_HERO,
    RECIPE_NAME,
    RECIPE_VERSION,
    TOOL_NAME,
)
from clipforge.hero.identity import alignment_identity_config, digest_candidate, hero_input_digest
from clipforge.hero.integrity import hero_problems
from clipforge.hero.plan import build_hero_plan
from clipforge.hero.probe import probe_hero
from clipforge.hero.selection import approved_candidates, review_digest
from clipforge.media.clock import seconds_text_to_us, us_to_seconds_str
from clipforge.media.disk import read_disk, require_disk_budget
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_to_file_uri
from clipforge.media.probe import read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.media.workspace import (
    SourceWorkspace,
    atomic_replace,
    candidate_read_lock,
    ensure_within,
    hero_lock,
    prepare_read_lock,
    preview_read_lock,
    safe_unlink,
    transcribe_read_lock,
    vision_read_lock,
)
from clipforge.preview.inputs import PreviewInputs, load_preview_inputs
from clipforge.preview.service import default_profile
from clipforge.preview.timing import frame_at_or_after, media_trim_frame
from clipforge.review.service import CurrentPreview, effective_review, require_current_preview
from clipforge.schemas.editorial import CandidateClip, MotionEvent
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.hero import (
    ForcedAlignmentDocument,
    HeroCacheRecord,
    HeroDraftOutput,
    HeroDraftSetDocument,
    HeroPlanDocument,
    HeroProfile,
    HeroRenderInput,
)
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.preview import CandidateRoughPreview
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import digest_time_map
from clipforge.storage import (
    Database,
    find_artifact,
    get_job,
    insert_artifact,
    insert_job,
    list_jobs,
    list_reviews,
    update_artifact,
    update_job,
)
from clipforge.storage.repository import ArtifactRow
from clipforge.timeline.framerate import FrameRate
from clipforge.transcription.io import dump_json, publish_json

_PROFILE = HeroProfile(
    renderer_recipe_version="hero-draft-renderer-v2",
    caption_style_version="hero-caption-style-v2",
    caption_font_sha256=[
        "b5d64817b6331723b5e59eaaa6db90057cbed58e9733f65687f110638192359f",
        "faa5f3656a78b2e2d450d27fe8382c778bc2b6bb5ea29c986664a6a435056ceb",
        "4e5462d2e8be880317b9f49b5b2da109ddb6a3563d91cc604b67f3535832a555",
    ],
)


@dataclass(frozen=True, slots=True)
class HeroRenderResult:
    status: str
    source_asset_id: str
    job_id: str | None
    hero_set_id: str | None
    rendered_count: int
    excluded: tuple[tuple[str, str], ...]
    manifest_path: Path | None
    manifest_sha256: str | None
    cache_hit: bool
    runtime_seconds: float


def default_hero_profile() -> HeroProfile:
    return _PROFILE


def _select_aligner(
    inputs: PreviewInputs,
    alignment_backend: ForcedAlignmentBackend | None,
    allow_model_download: bool,
    language: str | None = None,
) -> ForcedAlignmentBackend:
    if alignment_backend is not None:
        return alignment_backend
    detected = inputs.pair.transcript.detected_language
    if language and detected:
        from clipforge.language.providers import normalized_language

        requested = normalized_language(language)
        found = normalized_language(detected)
        if requested and found and requested != found:
            raise MediaError("transcript_language_mismatch")
    return production_alignment_backend(
        language or detected,
        allow_model_download=allow_model_download,
    )


def render_hero_drafts(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    force: bool = False,
    profile: HeroProfile | None = None,
    backend: HeroRenderBackend | None = None,
    alignment_backend: ForcedAlignmentBackend | None = None,
    allow_model_download: bool = False,
    created_by: str | None = None,
) -> HeroRenderResult:
    """Render approved candidates. No approval is a no-op and writes nothing."""
    root = work_root.resolve()
    active = profile or default_hero_profile()
    renderer: HeroRenderBackend = backend if backend is not None else RemotionHeroRenderBackend()
    rough = default_profile()
    inputs = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=rough.fingerprint(),
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
        preview_read_lock(inputs.pair.workspace, busy=_busy(source, "rough preview render", "rough preview")),
        hero_lock(inputs.pair.workspace),
    ):
        inputs = load_preview_inputs(
            database,
            source_asset_id,
            root,
            profile_fingerprint=rough.fingerprint(),
            create_workspace=True,
        )
        _validate_hero_workspace(inputs.pair.workspace)
        current = require_current_preview(database, source_asset_id, root)
        reviews = _reviews(database, inputs.pair.source.project_id)
        chosen, excluded = _ranked(
            approved_candidates(
                inputs.candidate_document,
                reviews,
                rough_artifact_id=current.artifact_id,
            ),
            current.document.previews,
        )
        if not chosen:
            return _noop(source_asset_id, tuple(excluded), started)
        identity = _live_identity(alignment_backend)
        if not force and _cache_ready(database, inputs, current, reviews, active, identity):
            return _cache_result(database, inputs, current, tuple(excluded), started)
        if renderer.requires_browser:
            from clipforge.preview.browser import resolve_browser

            resolve_browser()
        aligner = _select_aligner(inputs, alignment_backend, allow_model_download)
        _require_budget(root)
        _fail_stale(database, inputs)
        now = datetime.now(UTC)
        job = _running_job(inputs, current, active, aligner, len(chosen), now)
        with database.transaction() as connection:
            insert_job(connection, job)
        hero_set_id = str(uuid.uuid4())
        run_dir: Path | None = None
        try:
            current = require_current_preview(database, source_asset_id, root)
            inputs = load_preview_inputs(
                database,
                source_asset_id,
                root,
                profile_fingerprint=rough.fingerprint(),
                create_workspace=True,
            )
            run_dir = inputs.pair.workspace.make_hero_run(hero_set_id)
            document, manifest = _render_run(
                inputs,
                current.artifact_id,
                current.document.preview_set_id,
                current.manifest_sha256,
                chosen,
                active,
                aligner,
                renderer,
                hero_set_id,
                job,
                actor,
                now,
                root,
                run_dir,
                allow_model_download,
            )
            digest = sha256_file(manifest)
            record = _cache_record(document, job.job_id, digest, manifest.stat().st_size, now)
            _commit_and_publish(database, inputs, job, document, manifest, record, actor, root)
        except KeyboardInterrupt:
            _abandon(database, job, JobStatus.CANCELLED, "hero draft render cancelled", run_dir, root)
            raise
        except (MediaError, StorageError, OSError, ValidationError, ValueError) as exc:
            _abandon(database, job, JobStatus.FAILED, str(exc), run_dir, root)
            raise
    return _result(
        document,
        job_id=job.job_id,
        path=manifest,
        digest=digest,
        cache_hit=False,
        excluded=tuple(excluded),
        started=started,
        status="rendered",
    )


def align_hero_candidate(
    *,
    database: Database,
    source_asset_id: str,
    candidate_id: str,
    work_root: Path,
    alignment_backend: ForcedAlignmentBackend | None = None,
    allow_model_download: bool = False,
    created_by: str | None = None,
    language: str | None = None,
) -> ForcedAlignmentDocument:
    """Align one approved candidate. A missing approval or a stale preview fails first."""
    root = work_root.resolve()
    rough = default_profile()
    inputs = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=rough.fingerprint(),
        create_workspace=True,
    )
    actor = created_by.strip()[:200] if created_by and created_by.strip() else _actor()
    source = inputs.pair.source.source_asset_id
    with (
        prepare_read_lock(inputs.pair.workspace, busy=_busy(source, "media prepare", "derived media")),
        transcribe_read_lock(inputs.pair.workspace, busy=_busy(source, "transcription", "transcript")),
        vision_read_lock(inputs.pair.workspace, busy=_busy(source, "visual analysis", "visual analysis")),
        candidate_read_lock(inputs.pair.workspace, busy=_busy(source, "candidate mining", "candidate set")),
        preview_read_lock(inputs.pair.workspace, busy=_busy(source, "rough preview render", "rough preview")),
        hero_lock(inputs.pair.workspace),
    ):
        inputs = load_preview_inputs(
            database,
            source_asset_id,
            root,
            profile_fingerprint=rough.fingerprint(),
            create_workspace=True,
        )
        _validate_hero_workspace(inputs.pair.workspace)
        current = require_current_preview(database, source_asset_id, root)
        reviews = _reviews(database, inputs.pair.source.project_id)
        pair = _require_approved(inputs, reviews, current.artifact_id, candidate_id)
        aligner = _select_aligner(inputs, alignment_backend, allow_model_download, language)
        stored = inputs.pair.workspace.hero_alignment_file(candidate_id)
        existing = _stored_alignment(stored, inputs, pair[0], pair[1], current.artifact_id, aligner)
        if existing is not None:
            return existing
        staging = inputs.pair.workspace.hero_root() / "staging"
        inputs.pair.workspace.prepare_hero_file(staging / "asr.flac")
        _link_or_copy(inputs.asr_path, staging / "asr.flac", root)
        try:
            document = _build_one_alignment(
                inputs,
                pair[0],
                pair[1],
                current.artifact_id,
                aligner,
                staging,
                actor,
                allow_model_download,
                root,
            )
            destination = inputs.pair.workspace.hero_alignment_file(candidate_id)
            inputs.pair.workspace.prepare_hero_file(destination)
            publish_json(destination, document, root, inputs.pair.workspace.partial_for(destination))
        finally:
            _cleanup_dir(staging, root)
    return document


def plan_hero_candidate(
    *,
    database: Database,
    source_asset_id: str,
    candidate_id: str,
    work_root: Path,
    created_by: str | None = None,
) -> HeroPlanDocument:
    """Build a Hero plan from stored forced alignment. Provisional timing is refused."""
    root = work_root.resolve()
    rough = default_profile()
    inputs = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=rough.fingerprint(),
        create_workspace=False,
    )
    actor = created_by.strip()[:200] if created_by and created_by.strip() else _actor()
    current = require_current_preview(database, source_asset_id, root)
    reviews = _reviews(database, inputs.pair.source.project_id)
    candidate, review = _require_approved(inputs, reviews, current.artifact_id, candidate_id)
    path = inputs.pair.workspace.hero_alignment_file(candidate_id)
    alignment = _read_alignment(path)
    _require_fresh_alignment(alignment, inputs, candidate, review, current.artifact_id, None)
    if _raw_mentions_provisional(path):
        raise MediaError("Hero plan refuses provisional timing. Run hero align with forced alignment.")
    plan = build_hero_plan(
        plan_id=str(uuid.uuid4()),
        candidate=candidate,
        alignment=alignment,
        review=review,
        rough_artifact_id=current.artifact_id,
        profile=default_hero_profile(),
        created_by=actor,
        tool_version=__version__,
    )
    destination = inputs.pair.workspace.hero_plan_file(candidate_id)
    inputs.pair.workspace.prepare_hero_file(destination)
    publish_json(destination, plan, root, inputs.pair.workspace.partial_for(destination))
    return plan


def _render_run(
    inputs: PreviewInputs,
    rough_artifact_id: str,
    rough_preview_set_id: str,
    rough_manifest_sha256: str,
    chosen: list[tuple[CandidateClip, ReviewDecision]],
    profile: HeroProfile,
    aligner: ForcedAlignmentBackend,
    renderer: HeroRenderBackend,
    hero_set_id: str,
    job: JobRecord,
    actor: str,
    now: datetime,
    root: Path,
    run_dir: Path,
    allow_model_download: bool,
) -> tuple[HeroDraftSetDocument, Path]:
    staging = run_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    if not renderer.requires_browser:
        _link_or_copy(inputs.proxy_path, staging / "analysis.mp4", root)
        _link_or_copy(inputs.asr_path, staging / "asr.flac", root)
    prepared: list[tuple[CandidateClip, ReviewDecision, ForcedAlignmentDocument, HeroPlanDocument]] = []
    for candidate, review in chosen:
        directory = inputs.pair.workspace.make_hero_candidate_dir(hero_set_id, candidate.candidate_id)
        alignment = _alignment_for_render(
            inputs,
            candidate,
            review,
            rough_artifact_id,
            aligner,
            staging,
            directory,
            actor,
            allow_model_download,
            root,
        )
        plan = build_hero_plan(
            plan_id=str(uuid.uuid4()),
            candidate=candidate,
            alignment=alignment,
            review=review,
            rough_artifact_id=rough_artifact_id,
            profile=profile,
            created_by=actor,
            tool_version=__version__,
        )
        publish_json(
            directory / "alignment.json",
            alignment,
            root,
            inputs.pair.workspace.partial_for(directory / "alignment.json"),
        )
        publish_json(
            directory / "plan.json",
            plan,
            root,
            inputs.pair.workspace.partial_for(directory / "plan.json"),
        )
        canonical_plan = inputs.pair.workspace.hero_plan_file(candidate.candidate_id)
        canonical_plan.parent.mkdir(parents=True, exist_ok=True)
        publish_json(
            canonical_plan,
            plan,
            root,
            inputs.pair.workspace.partial_for(canonical_plan),
        )
        prepared.append((candidate, review, alignment, plan))
    config = alignment_identity_config(
        model_name=aligner.model_name,
        whisperx_version=aligner.whisperx_version,
        device=aligner.device,
    )
    approvals = []
    for candidate, review, alignment, _plan in prepared:
        directory = inputs.pair.workspace.hero_candidate_dir(hero_set_id, candidate.candidate_id)
        approvals.append(
            {
                "alignment_id": alignment.alignment_id,
                "alignment_sha256": sha256_file(directory / "alignment.json"),
                "candidate_id": candidate.candidate_id,
                "candidate_sha256": digest_candidate(candidate),
                "review_digest": review_digest(review),
                "review_id": review.review_id,
                "time_map_sha256": digest_time_map(candidate.time_map),
            }
        )
    hero_digest = hero_input_digest(
        source_sha256=inputs.pair.manifest.content_sha256,
        candidate_set_artifact_id=inputs.candidate_artifact_id,
        candidate_set_sha256=inputs.candidate_sha256,
        transcript_id=inputs.pair.transcript.transcript_id,
        transcript_sha256=inputs.pair.transcript_sha256,
        visual_analysis_id=inputs.pair.visual.analysis_id,
        visual_analysis_sha256=inputs.pair.visual_sha256,
        analysis_proxy_sha256=inputs.proxy_sha256,
        asr_audio_sha256=inputs.asr_sha256,
        rough_preview_artifact_id=rough_artifact_id,
        rough_preview_set_id=rough_preview_set_id,
        rough_manifest_sha256=rough_manifest_sha256,
        profile_fingerprint=profile.fingerprint(),
        motion_library_version=profile.motion_library_version,
        renderer_recipe_version=profile.renderer_recipe_version,
        caption_algorithm_version=profile.caption_algorithm_version,
        alignment_model=aligner.model_name,
        whisperx_version=aligner.whisperx_version,
        alignment_config_sha256=config,
        approvals=approvals,
    )
    drafts: list[HeroDraftOutput] = []
    for rank, (candidate, review, alignment, plan) in enumerate(prepared, start=1):
        drafts.append(
            _render_one(
                inputs,
                candidate,
                review,
                alignment,
                plan,
                profile,
                renderer,
                hero_set_id,
                hero_digest,
                rank,
                root,
                run_dir,
                job,
            )
        )
    _cleanup_dir(staging, root)
    batch = run_dir / "render-batch.json"
    if batch.exists() and not batch.is_symlink():
        safe_unlink(root, batch)
    document = _document(
        inputs,
        profile,
        hero_set_id,
        job,
        actor,
        now,
        drafts,
        rough_artifact_id,
        rough_preview_set_id,
        rough_manifest_sha256,
        aligner,
        config,
        hero_digest,
    )
    manifest = run_dir / "manifest.json"
    publish_json(manifest, document, root, inputs.pair.workspace.partial_for(manifest))
    stored = HeroDraftSetDocument.model_validate_json(manifest.read_text(encoding="utf-8"))
    return stored, manifest


def _render_one(
    inputs: PreviewInputs,
    candidate: CandidateClip,
    review: ReviewDecision,
    alignment: ForcedAlignmentDocument,
    plan: HeroPlanDocument,
    profile: HeroProfile,
    renderer: HeroRenderBackend,
    hero_set_id: str,
    hero_digest: str,
    rank: int,
    root: Path,
    run_dir: Path,
    job: JobRecord,
) -> HeroDraftOutput:
    del hero_digest
    directory = inputs.pair.workspace.hero_candidate_dir(hero_set_id, candidate.candidate_id)
    alignment_sha = sha256_file(directory / "alignment.json")
    plan_sha = sha256_file(directory / "plan.json")
    segment = candidate.time_map.segments[0]
    staging = run_dir / "staging"
    video_name = "analysis.mp4"
    audio_name = "asr.flac"
    trim_frame = media_trim_frame(segment.source_start_us)
    if renderer.requires_browser:
        from clipforge.preview.trim import stage_candidate_span

        staged = stage_candidate_span(
            inputs.proxy_path,
            inputs.asr_path,
            staging,
            stem=f"{candidate.candidate_id}-picture",
            start_us=segment.source_start_us,
            end_us=segment.source_end_us,
            frame_count=candidate.time_map.to_time_map().output_frame_count(
                FrameRate(profile.fps_numerator, profile.fps_denominator)
            ),
            root=root,
            log_path=run_dir / "logs" / f"{candidate.candidate_id}.trim.log",
        )
        video_name = staged.video_path.name
        # The staged pair is one canonical trim transaction. Do not render a
        # picture from ``stage_candidate_span`` beside a separately trimmed
        # audio file: a second ffmpeg recipe can start on a different sample
        # and reintroduce the reported AV drift at the first cut.
        audio_name = staged.audio_path.name
        trim_frame = 0
    rendered = _render_input(
        candidate,
        alignment,
        plan,
        profile,
        review,
        hero_set_id,
        run_dir,
        alignment_sha,
        plan_sha,
        video_name=video_name,
        audio_name=audio_name,
        trim_frame=trim_frame,
        source_width=inputs.pair.visual.proxy_width,
        source_height=inputs.pair.visual.proxy_height,
    )
    input_path = directory / "render-input.json"
    publish_json(input_path, rendered, root, inputs.pair.workspace.partial_for(input_path))
    partial = inputs.pair.workspace.partial_for(directory / "hero.mp4")
    batch = run_dir / "render-batch.json"
    batch.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "outputPath": str(partial),
                        "h264Crf": profile.h264_crf,
                        "input": json.loads(dump_json(rendered)),
                    }
                ]
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    renderer.render_batch(batch, log_path=run_dir / "logs" / f"{job.job_id}.log")
    if not partial.is_file() or partial.is_symlink():
        raise MediaError(f"renderer did not produce a Hero file for {candidate.candidate_id}")
    duration = candidate.time_map.to_time_map().total_output_duration()
    probed = probe_hero(partial, expected_duration_us=duration)
    final = directory / "hero.mp4"
    atomic_replace(partial, final, root)
    if batch.exists() and not batch.is_symlink():
        safe_unlink(root, batch)
    return HeroDraftOutput(
        candidate_id=candidate.candidate_id,
        rank=rank,
        review_id=review.review_id,
        review_digest=review_digest(review),
        time_map_sha256=digest_time_map(candidate.time_map),
        alignment_sha256=sha256_file(directory / "alignment.json"),
        edit_plan_sha256=sha256_file(directory / "plan.json"),
        render_input_sha256=sha256_file(input_path),
        preview_relative_path=f"candidates/{candidate.candidate_id}/hero.mp4",
        preview_sha256=sha256_file(final),
        preview_size_bytes=final.stat().st_size,
        output_duration_us=duration,
        output_frame_count=rendered.duration_in_frames,
        caption_count=len(rendered.captions),
        detected_video_codec=probed.video_codec,
        detected_pixel_format=probed.pixel_format,
        detected_audio_codec=probed.audio_codec,
        detected_duration_us=probed.duration_us,
        duration_error_us=probed.duration_error_us,
    )


def _render_input(
    candidate: CandidateClip,
    alignment: ForcedAlignmentDocument,
    plan: HeroPlanDocument,
    profile: HeroProfile,
    review: ReviewDecision,
    hero_set_id: str,
    run_dir: Path,
    alignment_sha256: str,
    edit_plan_sha256: str,
    *,
    video_name: str = "analysis.mp4",
    audio_name: str = "asr.flac",
    trim_frame: int | None = None,
    source_width: int,
    source_height: int,
) -> HeroRenderInput:
    if plan.edit_plan.stage != "hero":
        raise MediaError("Hero render refuses a plan whose stage is not hero")
    segment = candidate.time_map.segments[0]
    time_map = candidate.time_map.to_time_map()
    frame_count = time_map.output_frame_count(FrameRate(profile.fps_numerator, profile.fps_denominator))
    pieces = hero_caption_pieces(alignment.words)
    if not pieces:
        raise MediaError(f"candidate {candidate.candidate_id} produced no Hero captions")
    captions: list[dict[str, object]] = []
    for piece in pieces:
        captions.append(
            {
                "cue_id": piece.cue.cue_id,
                "text": piece.cue.text,
                "source_start_us": piece.source_start_us,
                "source_end_us": piece.source_end_us,
                "output_start_us": piece.cue.interval.output_start_us,
                "output_end_us": piece.cue.interval.output_end_us,
                "output_start_frame": piece.output_start_frame,
                "output_end_frame_exclusive": piece.output_end_frame_exclusive,
                "alignment_quality": "forced",
                "language": alignment.locale,
                "words": [
                    {
                        "text": word.text,
                        "output_start_frame": word.output_start_frame,
                        "output_end_frame_exclusive": word.output_end_frame_exclusive,
                    }
                    for word in piece.words
                ],
            }
        )
    events = [_motion_payload(event, frame_count) for event in plan.edit_plan.motion_events]
    return HeroRenderInput(
        candidate_id=candidate.candidate_id,
        renderer_recipe_version=profile.renderer_recipe_version,
        hero_set_id=hero_set_id,
        video_path=str(run_dir / "staging" / video_name),
        audio_path=str(run_dir / "staging" / audio_name),
        media_trim_frame=media_trim_frame(segment.source_start_us) if trim_frame is None else trim_frame,
        duration_in_frames=frame_count,
        source_width=source_width,
        source_height=source_height,
        caption_font_sha256=profile.caption_font_sha256,
        alignment_sha256=alignment_sha256,
        edit_plan_sha256=edit_plan_sha256,
        time_map_sha256=digest_time_map(candidate.time_map),
        review_id=review.review_id,
        review_digest=review_digest(review),
        profile_fingerprint=profile.fingerprint(),
        language=alignment.locale,
        captions=captions,
        motion_events=events,
    )


def _motion_payload(event: MotionEvent, frame_count: int) -> dict[str, object]:
    start = frame_at_or_after(event.interval.output_start_us, frame_count)
    end = frame_at_or_after(event.interval.output_end_us, frame_count)
    if end <= start:
        end = min(frame_count, start + 1)
    return {
        "event_id": event.event_id,
        "component_id": event.component_id,
        "purpose": event.purpose.value,
        "output_start_us": event.interval.output_start_us,
        "output_end_us": event.interval.output_end_us,
        "output_start_frame": start,
        "output_end_frame_exclusive": end,
        "library": event.payload.get("library", ""),
    }


def _stored_alignment(
    path: Path,
    inputs: PreviewInputs,
    candidate: CandidateClip,
    review: ReviewDecision,
    rough_artifact_id: str,
    aligner: ForcedAlignmentBackend,
) -> ForcedAlignmentDocument | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        existing = _read_alignment(path)
        _require_fresh_alignment(existing, inputs, candidate, review, rough_artifact_id, aligner)
    except (MediaError, ValidationError, ValueError, OSError):
        return None
    return existing


def _alignment_for_render(
    inputs: PreviewInputs,
    candidate: CandidateClip,
    review: ReviewDecision,
    rough_artifact_id: str,
    aligner: ForcedAlignmentBackend,
    staging: Path,
    directory: Path,
    actor: str,
    allow_model_download: bool,
    root: Path,
) -> ForcedAlignmentDocument:
    del directory
    stored = inputs.pair.workspace.hero_alignment_file(candidate.candidate_id)
    existing = _stored_alignment(stored, inputs, candidate, review, rough_artifact_id, aligner)
    if existing is not None:
        return existing
    return _build_one_alignment(
        inputs,
        candidate,
        review,
        rough_artifact_id,
        aligner,
        staging,
        actor,
        allow_model_download,
        root,
    )


def _build_one_alignment(
    inputs: PreviewInputs,
    candidate: CandidateClip,
    review: ReviewDecision,
    rough_artifact_id: str,
    aligner: ForcedAlignmentBackend,
    staging: Path,
    actor: str,
    allow_model_download: bool,
    root: Path,
) -> ForcedAlignmentDocument:
    bundles = inputs.candidate_document.evidence_bundles
    bundle = next(item for item in bundles if item.candidate_id == candidate.candidate_id)
    backend: ForcedAlignmentBackend = aligner
    if aligner.needs_staged_audio:
        if not isinstance(aligner, WhisperXAlignment):
            raise MediaError("staged Hero audio is only defined for the WhisperX adapter")
        single = len(candidate.time_map.segments) == 1
        if single:
            segment = candidate.time_map.segments[0]
            audio_path = staging / f"{candidate.candidate_id}.flac"
            _trim_asr(inputs.asr_path, audio_path, segment.source_start_us, segment.source_end_us, root)
            source_clock = False
        else:
            audio_path = inputs.asr_path
            source_clock = True
        backend = WhisperXAlignment(
            allow_model_download=allow_model_download,
            audio_path=str(audio_path),
            language_code=str(getattr(aligner, "language_code", "en")),
            model_name=aligner.model_name,
            locale=str(getattr(aligner, "locale", "en-US")),
            model_revision=str(getattr(aligner, "model_revision", "")),
            checkpoint_sha256=str(getattr(aligner, "checkpoint_sha256", "")),
            model_license=str(getattr(aligner, "model_license", "")),
            audio_is_source_clock=source_clock,
        )
    return build_alignment(
        alignment_id=str(uuid.uuid4()),
        transcript=inputs.pair.transcript,
        transcript_sha256=inputs.pair.transcript_sha256,
        candidate=candidate,
        bundle=bundle,
        review=review,
        rough_artifact_id=rough_artifact_id,
        asr_audio_sha256=inputs.asr_sha256,
        backend=backend,
        created_by=actor,
        tool_version=__version__,
        source_sha256=inputs.pair.manifest.content_sha256,
    )


def _trim_asr(source: Path, destination: Path, start_us: int, end_us: int, root: Path) -> None:
    ensure_within(root, destination)
    if destination.exists() or destination.is_symlink():
        raise MediaError(f"refusing to replace staged alignment audio {destination.name}")
    ffmpeg = resolve_ffmpeg()
    ProcessRunner().run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-ss",
            us_to_seconds_str(start_us),
            "-t",
            us_to_seconds_str(end_us - start_us),
            "-c:a",
            "flac",
            str(destination),
        ],
        log_path=None,
        check=True,
    )
    probe = read_ffprobe_json(destination, ProcessRunner(), None)
    streams = probe.get("streams")
    audio = (
        next(
            (item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"),
            None,
        )
        if isinstance(streams, list)
        else None
    )
    duration = seconds_text_to_us(audio.get("duration")) if isinstance(audio, dict) else None
    expected = end_us - start_us
    if duration is None or abs(duration - expected) > 100_000:
        raise MediaError(
            f"staged alignment speech duration {duration} us differs from {expected} us; "
            "refusing a separately clocked Hero render"
        )


def _require_fresh_alignment(
    alignment: ForcedAlignmentDocument,
    inputs: PreviewInputs,
    candidate: CandidateClip,
    review: ReviewDecision,
    rough_artifact_id: str,
    aligner: ForcedAlignmentBackend | None,
) -> None:
    if any(word.alignment_quality != "forced" for word in alignment.words):
        raise MediaError("stored alignment is not forced. Provisional timing cannot enter a Hero plan.")
    if alignment.candidate_id != candidate.candidate_id:
        raise MediaError("stored alignment names another candidate")
    if alignment.review_id != review.review_id or alignment.review_digest != review_digest(review):
        raise MediaError("stored alignment is not bound to the current approval")
    if alignment.rough_preview_artifact_id != rough_artifact_id:
        raise MediaError("stored alignment is bound to an older rough preview")
    if alignment.transcript_sha256 != inputs.pair.transcript_sha256:
        raise MediaError("stored alignment does not match the current transcript")
    if alignment.asr_audio_sha256 != inputs.asr_sha256:
        raise MediaError("stored alignment does not match the current ASR audio")
    if alignment.time_map_sha256 != digest_time_map(candidate.time_map):
        raise MediaError("stored alignment does not match the candidate TimeMap")
    if not alignment.binding_sha256 or not alignment.locale:
        raise MediaError("stored alignment identity is incomplete")
    production = alignment.model_name != "fake-forced-align-v1"
    if production and (
        not alignment.model_revision
        or not alignment.checkpoint_sha256
        or not alignment.whisperx_version
        or not alignment.manifest_sha256
    ):
        raise MediaError("stored alignment identity is incomplete")
    from clipforge.language.evidence import validate_current_alignment_evidence

    evidence = validate_current_alignment_evidence(
        document=alignment,
        project_id=candidate.project_id,
        source_asset_id=candidate.source_asset_id,
        candidate_id=candidate.candidate_id,
        transcript_sha256=inputs.pair.transcript_sha256,
        asr_audio_sha256=inputs.asr_sha256,
        time_map_sha256=digest_time_map(candidate.time_map),
        rough_preview_artifact_id=rough_artifact_id,
        review_id=review.review_id,
        review_digest=review_digest(review),
        source_sha256=inputs.pair.manifest.content_sha256,
    )
    if evidence.blocker not in {"", "none"}:
        raise MediaError(evidence.blocker)
    if alignment.alignment_status == "verified_live" and evidence.status != "verified_live":
        raise MediaError(evidence.status)
    if aligner is not None and (
        alignment.model_name != aligner.model_name
        or alignment.whisperx_version != aligner.whisperx_version
        or alignment.device != ("cuda" if aligner.device == "cuda" else "cpu")
    ):
        raise MediaError("stored alignment was produced by a different alignment configuration")
    if aligner is not None:
        from clipforge.hero.alignment import _observed_checkpoint, _observed_manifest, _observed_revision
        from clipforge.language.providers import canonical_locale

        expected_locale = canonical_locale(str(getattr(aligner, "locale", "en-US"))) or "en-US"
        if canonical_locale(alignment.locale) != expected_locale:
            raise MediaError("stale_alignment")
        if (
            alignment.model_revision != _observed_revision(aligner)
            or alignment.checkpoint_sha256 != _observed_checkpoint(aligner)
            or alignment.manifest_sha256 != _observed_manifest(aligner)
        ):
            raise MediaError("stale_alignment")
    from clipforge.hero.alignment import expected_binding

    fresh = expected_binding(
        alignment,
        candidate=candidate,
        transcript_sha256=inputs.pair.transcript_sha256,
        asr_audio_sha256=inputs.asr_sha256,
        transcript_language=inputs.pair.transcript.detected_language or "",
        source_sha256=inputs.pair.manifest.content_sha256,
        aligner=aligner,
    )
    if fresh != alignment.binding_sha256:
        raise MediaError("stored alignment identity does not match the current provider")


def _read_alignment(path: Path) -> ForcedAlignmentDocument:
    if not path.is_file() or path.is_symlink():
        raise MediaError("no forced alignment is stored for this candidate. Run hero align first.")
    try:
        return ForcedAlignmentDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise MediaError(f"stored alignment could not be read: {exc}") from exc


def _raw_mentions_provisional(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MediaError(f"stored alignment could not be read: {exc}") from exc
    words = payload.get("words")
    if not isinstance(words, list):
        return True
    return any(not isinstance(word, dict) or word.get("alignment_quality") != "forced" for word in words)


def _require_approved(
    inputs: PreviewInputs,
    reviews: list[ReviewDecision],
    rough_artifact_id: str,
    candidate_id: str,
) -> tuple[CandidateClip, ReviewDecision]:
    candidate = next(
        (item for item in inputs.candidate_document.candidates if item.candidate_id == candidate_id),
        None,
    )
    if candidate is None:
        raise MediaError(f"unknown candidate {candidate_id}")
    decision = effective_review(reviews, rough_artifact_id, candidate_id)
    if decision is None:
        raise MediaError(f"candidate {candidate_id} has no decision for the current rough preview")
    if decision.decision == "changes_requested":
        raise MediaError(f"candidate {candidate_id} needs correction and is excluded from Hero")
    if decision.decision != "approved":
        raise MediaError(f"candidate {candidate_id} is {decision.decision} and is excluded from Hero")
    return candidate, decision


def _ranked(
    selected: tuple[list[tuple[CandidateClip, ReviewDecision]], list[tuple[str, str]]],
    previews: list[CandidateRoughPreview],
) -> tuple[list[tuple[CandidateClip, ReviewDecision]], list[tuple[str, str]]]:
    chosen, excluded = selected
    ranks: dict[str, int] = {}
    for preview in previews:
        candidate_id = getattr(preview, "candidate_id", None)
        rank = getattr(preview, "rank", None)
        if isinstance(candidate_id, str) and isinstance(rank, int):
            ranks[candidate_id] = rank
    ordered: list[tuple[CandidateClip, ReviewDecision]] = []
    for candidate, review in chosen:
        if candidate.candidate_id not in ranks:
            excluded.append((candidate.candidate_id, "missing from the current rough preview"))
            continue
        ordered.append((candidate, review))
    ordered.sort(key=lambda item: ranks[item[0].candidate_id])
    return ordered, excluded


def _document(
    inputs: PreviewInputs,
    profile: HeroProfile,
    hero_set_id: str,
    job: JobRecord,
    actor: str,
    now: datetime,
    drafts: list[HeroDraftOutput],
    rough_artifact_id: str,
    rough_preview_set_id: str,
    rough_manifest_sha256: str,
    aligner: ForcedAlignmentBackend,
    config: str,
    hero_digest: str,
) -> HeroDraftSetDocument:
    return HeroDraftSetDocument(
        hero_set_id=hero_set_id,
        project_id=inputs.pair.source.project_id,
        source_asset_id=inputs.pair.source.source_asset_id,
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
        rough_preview_artifact_id=rough_artifact_id,
        rough_preview_set_id=rough_preview_set_id,
        rough_manifest_sha256=rough_manifest_sha256,
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        renderer_recipe_version=profile.renderer_recipe_version,
        alignment_model=aligner.model_name,
        whisperx_version=aligner.whisperx_version,
        alignment_config_sha256=config,
        hero_input_sha256=hero_digest,
        drafts=drafts,
        provenance=ArtifactProvenance(
            created_at=now,
            created_by=actor,
            tool=TOOL_NAME,
            tool_version=__version__,
            source_asset_ids=[inputs.pair.source.source_asset_id],
            job_id=job.job_id,
            inputs_sha256=hero_digest,
        ),
    )


def _cache_record(
    document: HeroDraftSetDocument,
    job_id: str,
    digest: str,
    size: int,
    created_at: datetime,
) -> HeroCacheRecord:
    return HeroCacheRecord(
        project_id=document.project_id,
        source_asset_id=document.source_asset_id,
        hero_set_id=document.hero_set_id,
        job_id=job_id,
        source_sha256=document.source_sha256,
        candidate_set_artifact_id=document.candidate_set_artifact_id,
        candidate_set_sha256=document.candidate_set_sha256,
        transcript_id=document.transcript_id,
        transcript_sha256=document.transcript_sha256,
        visual_analysis_id=document.visual_analysis_id,
        visual_analysis_sha256=document.visual_analysis_sha256,
        analysis_proxy_sha256=document.analysis_proxy_sha256,
        asr_audio_sha256=document.asr_audio_sha256,
        rough_preview_artifact_id=document.rough_preview_artifact_id,
        rough_preview_set_id=document.rough_preview_set_id,
        rough_manifest_sha256=document.rough_manifest_sha256,
        hero_input_sha256=document.hero_input_sha256,
        profile_fingerprint=document.profile_fingerprint,
        renderer_recipe_version=document.renderer_recipe_version,
        alignment_model=document.alignment_model,
        whisperx_version=document.whisperx_version,
        alignment_config_sha256=document.alignment_config_sha256,
        manifest_sha256=digest,
        manifest_size_bytes=size,
        rendered_count=len(document.drafts),
        validation_status="passed",
        created_at=created_at,
    )


def _cache_ready(
    database: Database,
    inputs: PreviewInputs,
    current: CurrentPreview,
    reviews: list[ReviewDecision],
    profile: HeroProfile,
    identity: tuple[str, str, str] | None,
) -> bool:
    sidecar = inputs.pair.workspace.hero_sidecar()
    if not sidecar.is_file() or sidecar.is_symlink():
        return False
    try:
        record = HeroCacheRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return False
    if record.profile_fingerprint != profile.fingerprint():
        return False
    with database.connect() as connection:
        row = _find_hero(connection, inputs)
        if row is None or row.job_id is None:
            return False
        try:
            job = get_job(connection, row.job_id)
        except StorageError:
            return False
    try:
        from clipforge.media.local_file import path_from_file_uri

        path = path_from_file_uri(row.uri)
        expected = inputs.pair.workspace.hero_run_dir(record.hero_set_id) / "manifest.json"
        ensure_within(inputs.pair.workspace.root, path)
        if path != expected or path.is_symlink() or not path.is_file():
            return False
        document = HeroDraftSetDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError, MediaError):
        return False
    model, version, config = (None, None, None)
    if identity is not None:
        model, version, _device = identity
        config = alignment_config_sha256(model_name=model, whisperx_version=version, device=identity[2])
    rough_artifact_id = current.artifact_id
    rough_set = current.document.preview_set_id
    rough_sha = current.manifest_sha256
    return not hero_problems(
        document,
        record,
        manifest_path=path,
        work_root=inputs.pair.workspace.root,
        workspace=inputs.pair.workspace,
        inputs=inputs,
        rough_artifact_id=rough_artifact_id,
        rough_preview_set_id=rough_set,
        rough_manifest_sha256=rough_sha,
        reviews=reviews,
        artifact_job_id=row.job_id,
        artifact_uri=row.uri,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
        alignment_model=model,
        whisperx_version=version,
        alignment_config_sha256=config,
    )


def _cache_result(
    database: Database,
    inputs: PreviewInputs,
    current: CurrentPreview,
    excluded: tuple[tuple[str, str], ...],
    started: float,
) -> HeroRenderResult:
    del current
    with database.connect() as connection:
        row = _find_hero(connection, inputs)
    if row is None or row.job_id is None:
        raise MediaError("Hero cache matched but the artifact row disappeared before reuse")
    from clipforge.media.local_file import path_from_file_uri

    path = path_from_file_uri(row.uri)
    document = HeroDraftSetDocument.model_validate_json(path.read_text(encoding="utf-8"))
    return _result(
        document,
        job_id=row.job_id,
        path=path,
        digest=sha256_file(path),
        cache_hit=True,
        excluded=excluded,
        started=started,
        status="cache_hit",
    )


def _running_job(
    inputs: PreviewInputs,
    current: CurrentPreview,
    profile: HeroProfile,
    aligner: ForcedAlignmentBackend,
    count: int,
    now: datetime,
) -> JobRecord:
    return JobRecord(
        job_id=str(uuid.uuid4()),
        project_id=inputs.pair.source.project_id,
        kind=JOB_HERO,
        status=JobStatus.RUNNING,
        created_at=now,
        updated_at=now,
        payload={
            "source_asset_id": inputs.pair.source.source_asset_id,
            "source_sha256": inputs.pair.manifest.content_sha256,
            "candidate_set_sha256": inputs.candidate_sha256,
            "rough_preview_artifact_id": current.artifact_id,
            "rough_preview_set_id": current.document.preview_set_id,
            "profile_fingerprint": profile.fingerprint(),
            "renderer_recipe": f"{RECIPE_NAME} v{RECIPE_VERSION}",
            "alignment_model": aligner.model_name,
            "whisperx_version": aligner.whisperx_version,
            "approved_count": str(count),
            "cache": "miss",
        },
    )


def _commit_and_publish(
    database: Database,
    inputs: PreviewInputs,
    job: JobRecord,
    document: HeroDraftSetDocument,
    manifest: Path,
    record: HeroCacheRecord,
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
        inputs_sha256=document.hero_input_sha256,
    )
    payload = dict(job.payload)
    payload["hero_set_id"] = document.hero_set_id
    payload["rendered_count"] = str(len(document.drafts))
    succeeded = job.model_copy(
        update={
            "status": JobStatus.SUCCEEDED,
            "updated_at": document.created_at,
            "error_message": None,
            "payload": payload,
        }
    )
    with database.transaction() as connection:
        insert_artifact(
            connection,
            artifact_id=str(uuid.uuid4()),
            project_id=inputs.pair.source.project_id,
            job_id=job.job_id,
            source_asset_id=inputs.pair.source.source_asset_id,
            kind=KIND_HERO,
            uri=path_to_file_uri(manifest),
            provenance=provenance,
        )
        update_job(connection, succeeded)
    try:
        publish_json(
            inputs.pair.workspace.hero_sidecar(),
            record,
            root,
            inputs.pair.workspace.partial_for(inputs.pair.workspace.hero_sidecar()),
        )
    except (OSError, MediaError) as exc:
        _revert_artifact(database, inputs, previous, job, str(exc))
        raise MediaError(
            f"Hero sidecar was not published: {exc}. The previous Hero draft remains current."
        ) from exc


def _artifact_snapshot(
    database: Database,
    inputs: PreviewInputs,
) -> tuple[str, str | None, str, ArtifactProvenance] | None:
    with database.connect() as connection:
        row = _find_hero(connection, inputs)
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
                kind=KIND_HERO,
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
                KIND_HERO,
                job.job_id,
            ),
        )
        update_job(connection, failed)


def _fail_stale(database: Database, inputs: PreviewInputs) -> None:
    now = datetime.now(UTC)
    with database.transaction() as connection:
        for existing in list_jobs(connection, inputs.pair.source.project_id):
            if existing.kind != JOB_HERO or existing.status is not JobStatus.RUNNING:
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
                            "interrupted before completion. The Hero lock was free, so no live "
                            "Hero draft owned this running job. Partial outputs were not promoted."
                        ),
                    }
                ),
            )


def _abandon(
    database: Database,
    job: JobRecord,
    status: JobStatus,
    message: str,
    run_dir: Path | None,
    root: Path,
) -> None:
    notes: list[str] = []
    if run_dir is not None:
        try:
            _cleanup_dir(run_dir / "staging", root)
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
        return


def _cleanup_partials(run_dir: Path | None, root: Path) -> None:
    if run_dir is None or not run_dir.exists():
        return
    ensure_within(root, run_dir)
    if run_dir.is_symlink():
        raise MediaError(f"refusing to clean a symlinked Hero run {run_dir}")
    for path in sorted(run_dir.rglob("*")):
        if path.is_symlink():
            raise MediaError(f"refusing to clean symlink {path}")
        ensure_within(root, path)
        if path.is_file() and ".partial." in path.name:
            path.unlink()


def _cleanup_dir(directory: Path, root: Path) -> None:
    if not directory.exists():
        return
    ensure_within(root, directory)
    if directory.is_symlink():
        raise MediaError("refusing to clean a symlinked Hero staging directory")
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file():
            raise MediaError(f"refusing to clean unexpected staging path {path.name}")
        ensure_within(root, path)
        path.unlink()
    directory.rmdir()


def _link_or_copy(source: Path, destination: Path, root: Path) -> None:
    ensure_within(root, destination)
    if source.is_symlink() or destination.exists():
        raise MediaError(f"refusing to stage {source.name} through a symlink")
    try:
        os.link(source, destination)
    except OSError:
        destination.write_bytes(source.read_bytes())


def _validate_hero_workspace(workspace: SourceWorkspace) -> None:
    root = workspace.root.resolve()
    hero_root = workspace.hero_root()
    if hero_root.is_symlink():
        raise MediaError(f"refusing to follow symlinked hero workspace {hero_root}")
    if not hero_root.exists():
        return
    ensure_within(root, hero_root)
    if not hero_root.is_dir():
        raise MediaError(f"hero workspace {hero_root} exists and is not a directory")
    runs = hero_root / "runs"
    if runs.is_symlink():
        raise MediaError(f"refusing to follow symlinked hero runs directory {runs}")
    if runs.exists() and not runs.is_dir():
        raise MediaError(f"hero runs path {runs} exists and is not a directory")


def _live_identity(backend: ForcedAlignmentBackend | None) -> tuple[str, str, str] | None:
    if backend is not None:
        return backend.model_name, backend.whisperx_version, backend.device
    try:
        from clipforge.hero.alignment import _whisperx_version

        return WhisperXAlignment.model_name, _whisperx_version(), "cpu"
    except MediaError:
        return None


def _require_budget(root: Path) -> None:
    status = read_disk(root if root.exists() else root.parent)
    try:
        require_disk_budget(status.free_bytes, status.reserve_bytes, DISK_ESTIMATE_BYTES)
    except MediaError as exc:
        raise MediaError(f"{exc} Hero draft rendering was not started.") from exc


def _busy(source: str, holder: str, noun: str) -> str:
    return (
        f"another {holder} is already active for source {source}. "
        f"Clipforge refused to start a Hero draft while the current {noun} can be replaced."
    )


def _find_hero(connection: sqlite3.Connection, inputs: PreviewInputs) -> ArtifactRow | None:
    return find_artifact(
        connection,
        inputs.pair.source.project_id,
        inputs.pair.source.source_asset_id,
        KIND_HERO,
    )


def _reviews(database: Database, project_id: str) -> list[ReviewDecision]:
    with database.connect() as connection:
        return list_reviews(connection, project_id)


def _noop(
    source_asset_id: str,
    excluded: tuple[tuple[str, str], ...],
    started: float,
) -> HeroRenderResult:
    return HeroRenderResult(
        status="noop",
        source_asset_id=source_asset_id,
        job_id=None,
        hero_set_id=None,
        rendered_count=0,
        excluded=excluded,
        manifest_path=None,
        manifest_sha256=None,
        cache_hit=False,
        runtime_seconds=perf_counter() - started,
    )


def _result(
    document: HeroDraftSetDocument,
    *,
    job_id: str,
    path: Path,
    digest: str,
    cache_hit: bool,
    excluded: tuple[tuple[str, str], ...],
    started: float,
    status: str,
) -> HeroRenderResult:
    return HeroRenderResult(
        status=status,
        source_asset_id=document.source_asset_id,
        job_id=job_id,
        hero_set_id=document.hero_set_id,
        rendered_count=len(document.drafts),
        excluded=excluded,
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
