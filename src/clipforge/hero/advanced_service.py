"""Advanced Hero planning and rendering. Hero v1 artifacts stay in place."""

from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import TypeVar, cast

from pydantic import ValidationError

from clipforge import __version__
from clipforge.errors import MediaError, StorageError
from clipforge.hero.advanced_backend import AdvancedRenderBackend, RemotionAdvancedRenderBackend
from clipforge.hero.advanced_build import build_advanced_plan
from clipforge.hero.constants import KIND_HERO
from clipforge.hero.direction_service import load_direction
from clipforge.hero.motion_style import style_for_id, style_for_renderer_version
from clipforge.hero.probe import probe_hero
from clipforge.hero.reframe import (
    frame_count_for_duration,
    frame_period_tolerance_us,
    windows_follow_trajectory,
)
from clipforge.hero.selection import review_digest
from clipforge.hero.show import CurrentHero, load_current_hero
from clipforge.media.clock import us_to_seconds_str
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_to_file_uri
from clipforge.media.probe import read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.media.workspace import (
    SourceWorkspace,
    advanced_hero_lock,
    candidate_read_lock,
    ensure_within,
    hero_lock,
    prepare_read_lock,
    preview_read_lock,
    transcribe_read_lock,
    vision_read_lock,
)
from clipforge.preview.inputs import load_preview_inputs
from clipforge.preview.service import default_profile
from clipforge.review.service import effective_review
from clipforge.schemas.advanced import (
    AdvancedHeroCacheRecord,
    AdvancedHeroDraftOutput,
    AdvancedHeroDraftSetDocument,
    AdvancedHeroPlanDocument,
    AdvancedHeroProfile,
    AdvancedHeroRenderInput,
    AssetBinding,
    ReframingStrategy,
    advanced_fingerprint,
)
from clipforge.schemas.direction import DirectionDocument
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.hero import ForcedAlignmentDocument, HeroPlanDocument
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.reframe import ReframePlanDocument
from clipforge.schemas.time import TimeMapDocument
from clipforge.schemas.vision import VisualAnalysisDocument
from clipforge.storage import (
    ArtifactRow,
    Database,
    find_artifact,
    get_source_manifest,
    insert_artifact,
    insert_job,
    list_jobs,
    list_reviews,
    update_artifact,
    update_job,
)
from clipforge.transcription.io import publish_json

_ModelT = TypeVar("_ModelT")
KIND_ADVANCED = "advanced_hero_draft_set_json"
JOB_ADVANCED = "advanced_hero_render"
_PROFILE = AdvancedHeroProfile(
    reframing=ReframingStrategy(strategy_id="contain"),
    caption_algorithm_version="advanced-caption-clean-v1",
    typography_version="advanced-typography-clean-v1",
    diagram_version="advanced-diagram-grounded-v1",
    # v3 adds source-bound native Remotion illustration events.  Its recipe
    # name is part of the profile fingerprint, so v2 artifacts continue to
    # resolve under their recorded renderer behavior.
    renderer_recipe_version="advanced-hero-renderer-directed-v3",
    motion_library_version="advanced-motion-clean-v1",
)


@dataclass(frozen=True, slots=True)
class AdvancedRenderResult:
    status: str
    source_asset_id: str
    job_id: str | None
    advanced_set_id: str | None
    rendered_count: int
    manifest_path: Path | None
    manifest_sha256: str | None
    cache_hit: bool
    runtime_seconds: float


def default_advanced_profile() -> AdvancedHeroProfile:
    return _PROFILE


def select_advanced_backend(backend: AdvancedRenderBackend | None) -> AdvancedRenderBackend:
    """Production rendering uses Remotion. Tests pass a fake encoder explicitly."""
    if backend is None:
        return RemotionAdvancedRenderBackend()
    return backend


def plan_advanced_candidate(
    *,
    database: Database,
    source_asset_id: str,
    candidate_id: str,
    work_root: Path,
    broll_asset_ids: list[str] | None = None,
    sfx_asset_ids: list[str] | None = None,
    profile: AdvancedHeroProfile | None = None,
    created_by: str | None = None,
    direction: DirectionDocument | None = None,
) -> AdvancedHeroPlanDocument:
    """Write one advanced plan. Asset and approval failures happen before a render job."""
    root = work_root.resolve()
    active = profile or default_advanced_profile()
    context = _context(database, source_asset_id, candidate_id, root)
    stored_direction = direction
    direction_sha256 = ""
    if stored_direction is None:
        loaded_direction = load_direction(context.workspace, candidate_id)
        if loaded_direction is not None:
            stored_direction, direction_sha256 = loaded_direction
    elif stored_direction.direction_id:
        loaded_direction = load_direction(context.workspace, candidate_id)
        if loaded_direction is None or loaded_direction[0] != stored_direction:
            raise MediaError("direction must be validated and persisted before planning")
        direction_sha256 = loaded_direction[1]
    if stored_direction is not None and (
        stored_direction.source_asset_id != source_asset_id
        or stored_direction.candidate_id != candidate_id
        or stored_direction.source_sha256 != context.source_sha256
        or stored_direction.hero_plan_sha256 != context.hero_plan_sha256
        or stored_direction.time_map_sha256 != context.hero_plan.edit_plan.time_map_sha256
        or stored_direction.alignment_sha256 != context.alignment_sha256
        or stored_direction.visual_analysis_sha256 != context.visual_sha256
        or stored_direction.style_fingerprint != style_for_id(stored_direction.style_id).fingerprint()
    ):
        raise MediaError("direction is stale against the current promoted Hero plan")
    if stored_direction is not None:
        from clipforge.hero.direction_service import validate_source_evidence

        validate_source_evidence(
            stored_direction,
            context.alignment.words,
            context.hero_plan.edit_plan.time_map,
            {scene.scene_id for scene in context.visual.scenes},
        )
    directed_broll_ids: list[str] = []
    directed_sfx_ids: list[str] = []
    if stored_direction is not None:
        selected_option = next(
            item for item in stored_direction.options if item.option_id == stored_direction.selected_option_id
        )
        directed_broll_ids = [
            item.asset_id for item in selected_option.asset_placements if item.kind == "graphic"
        ]
        directed_sfx_ids = [item.asset_id for item in selected_option.asset_placements if item.kind == "audio"]
        if broll_asset_ids is not None and broll_asset_ids != directed_broll_ids:
            raise MediaError("B-roll ids must match the selected direction placements")
        if sfx_asset_ids is not None and sfx_asset_ids != directed_sfx_ids:
            raise MediaError("SFX ids must match the selected direction placements")
    actor = _actor(created_by)
    plan = build_advanced_plan(
        database=database,
        workspace=context.workspace,
        work_root=root,
        profile=active,
        plan_id=str(uuid.uuid4()),
        project_id=context.project_id,
        source_asset_id=source_asset_id,
        candidate_id=candidate_id,
        source_sha256=context.source_sha256,
        candidate_set_artifact_id=context.candidate_set_artifact_id,
        candidate_set_sha256=context.candidate_set_sha256,
        rough_artifact_id=context.rough_artifact_id,
        rough_manifest_sha256=context.rough_manifest_sha256,
        hero_artifact_id=context.hero_artifact_id,
        hero_set_id=context.hero_set_id,
        hero_manifest_sha256=context.hero_manifest_sha256,
        review_id=context.review_id,
        review_digest=context.review_digest,
        alignment=context.alignment,
        alignment_sha256=context.alignment_sha256,
        hero_plan=context.hero_plan,
        hero_plan_sha256=context.hero_plan_sha256,
        visual=context.visual,
        visual_sha256=context.visual_sha256,
        duration_us=context.duration_us,
        broll_asset_ids=directed_broll_ids if stored_direction is not None else list(broll_asset_ids or []),
        sfx_asset_ids=directed_sfx_ids if stored_direction is not None else list(sfx_asset_ids or []),
        actor=actor,
        tool_version=__version__,
        direction=stored_direction,
        direction_sha256=direction_sha256,
    )
    destination = context.workspace.advanced_plan_file(candidate_id)
    context.workspace.prepare_advanced_file(destination)
    publish_json(destination, plan, root, context.workspace.partial_for(destination))
    return plan


def render_advanced_drafts(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    force: bool = False,
    profile: AdvancedHeroProfile | None = None,
    backend: AdvancedRenderBackend | None = None,
    created_by: str | None = None,
    narration_artifact_id: str | None = None,
) -> AdvancedRenderResult:
    """Render stored advanced plans. A missing approval writes nothing."""
    root = work_root.resolve()
    active = profile or default_advanced_profile()
    renderer = select_advanced_backend(backend)
    rough = default_profile()
    inputs = load_preview_inputs(
        database, source_asset_id, root, profile_fingerprint=rough.fingerprint(), create_workspace=True
    )
    started = perf_counter()
    source = inputs.pair.source.source_asset_id
    with (
        prepare_read_lock(inputs.pair.workspace, busy=_busy(source, "media prepare")),
        transcribe_read_lock(inputs.pair.workspace, busy=_busy(source, "transcription")),
        vision_read_lock(inputs.pair.workspace, busy=_busy(source, "visual analysis")),
        candidate_read_lock(inputs.pair.workspace, busy=_busy(source, "candidate mining")),
        preview_read_lock(inputs.pair.workspace, busy=_busy(source, "rough preview")),
        hero_lock(inputs.pair.workspace),
        advanced_hero_lock(inputs.pair.workspace),
    ):
        _validate_workspace(inputs.pair.workspace)
        _fail_stale(database, inputs.pair.source.project_id, source)
        hero = load_current_hero(database, source_asset_id, root)
        chosen = _approved_with_plans(database, inputs.pair.workspace, hero, source_asset_id, root, active)
        if not chosen:
            return AdvancedRenderResult(
                "noop", source_asset_id, None, None, 0, None, None, False, perf_counter() - started
            )
        # Validate every plan's immutable source/style/direction bindings before
        # considering a cache hit.  A stale direction must never be hidden by an
        # otherwise healthy previous package.
        for candidate_id, plan in chosen:
            context = _context(database, source_asset_id, candidate_id, root)
            _require_plan_binding(database, plan, context)
            _require_plan_assets(database, inputs.pair.workspace, plan, root)
            _require_production_direction(plan, renderer, inputs.pair.workspace)
        if (
            narration_artifact_id is None
            and not force
            and _cache_ready(database, inputs.pair.workspace, hero, chosen, root)
        ):
            current = _current_manifest(inputs.pair.workspace)
            return AdvancedRenderResult(
                "cached",
                source_asset_id,
                None,
                hero.document.hero_set_id and _sidecar_set_id(inputs.pair.workspace),
                len(chosen),
                current,
                sha256_file(current) if current else None,
                True,
                perf_counter() - started,
            )
        narration: tuple[str, Path] | None = None
        if narration_artifact_id is not None:
            from clipforge.voice.service import require_bound_narration

            target = chosen[0][1].windows[-1].output_end_us if chosen[0][1].windows else 1
            narration = require_bound_narration(
                database,
                root,
                narration_artifact_id,
                project_id=inputs.pair.source.project_id,
                source_asset_id=source,
                target_duration_us=target,
            )
        now = datetime.now(UTC)
        job = _running_job(inputs.pair.source.project_id, source, len(chosen), now, _actor(created_by))
        if narration is not None:
            job = job.model_copy(update={"payload": {**job.payload, "narration_sha256": narration[0]}})
        with database.transaction() as connection:
            insert_job(connection, job)
        advanced_set_id = str(uuid.uuid4())
        run_dir: Path | None = None
        try:
            run_dir = inputs.pair.workspace.make_advanced_run(advanced_set_id)
            document, manifest = _render_run(
                database,
                inputs.pair.workspace,
                hero,
                chosen,
                active,
                renderer,
                advanced_set_id,
                job,
                _actor(created_by),
                now,
                root,
                run_dir,
                source_asset_id,
                narration,
            )
            digest = sha256_file(manifest)
            record = _cache_record(document, job.job_id, digest, manifest.stat().st_size)
            _commit(database, inputs.pair.workspace, job, document, manifest, record, root)
        except KeyboardInterrupt:
            _abandon(database, job, JobStatus.CANCELLED, "advanced Hero render cancelled", run_dir, root)
            raise
        except (MediaError, StorageError, OSError, ValidationError, ValueError) as exc:
            _abandon(database, job, JobStatus.FAILED, str(exc), run_dir, root)
            raise
    return AdvancedRenderResult(
        "rendered",
        source_asset_id,
        job.job_id,
        advanced_set_id,
        len(document.drafts),
        manifest,
        digest,
        False,
        perf_counter() - started,
    )


@dataclass(frozen=True, slots=True)
class _Context:
    workspace: SourceWorkspace
    project_id: str
    source_sha256: str
    candidate_set_artifact_id: str
    candidate_set_sha256: str
    rough_artifact_id: str
    rough_manifest_sha256: str
    hero_artifact_id: str
    hero_set_id: str
    hero_manifest_sha256: str
    review_id: str
    review_digest: str
    alignment: ForcedAlignmentDocument
    alignment_sha256: str
    hero_plan: HeroPlanDocument
    hero_plan_sha256: str
    visual: VisualAnalysisDocument
    visual_sha256: str
    duration_us: int


def _context(database: Database, source_asset_id: str, candidate_id: str, root: Path) -> _Context:
    rough = default_profile()
    inputs = load_preview_inputs(
        database, source_asset_id, root, profile_fingerprint=rough.fingerprint(), create_workspace=True
    )
    hero = load_current_hero(database, source_asset_id, root)
    draft = next((item for item in hero.document.drafts if item.candidate_id == candidate_id), None)
    if draft is None:
        raise MediaError(f"candidate {candidate_id} is not in the current Hero draft")
    reviews = _reviews(database, hero.project_id)
    decision = effective_review(reviews, hero.artifact_id, candidate_id, subject_kind="hero")
    if decision is None or decision.decision != "approved":
        raise MediaError("advanced Hero requires an approval of the current Hero artifact")
    if decision.artifact_id != hero.artifact_id:
        raise MediaError("advanced Hero refuses an approval of an older Hero artifact")
    alignment_path = hero.manifest_path.parent / "candidates" / candidate_id / "alignment.json"
    plan_path = hero.manifest_path.parent / "candidates" / candidate_id / "plan.json"
    alignment = _read_model(alignment_path, ForcedAlignmentDocument, "alignment")
    hero_plan = _read_model(plan_path, HeroPlanDocument, "hero plan")
    if sha256_file(alignment_path) != draft.alignment_sha256:
        raise MediaError("advanced Hero alignment hash does not match the Hero draft")
    if sha256_file(plan_path) != draft.edit_plan_sha256:
        raise MediaError("advanced Hero plan hash does not match the Hero draft")
    if any(word.alignment_quality != "forced" for word in alignment.words):
        raise MediaError("advanced Hero refuses provisional timing")
    if alignment.alignment_status == "verified_live":
        from clipforge.language.evidence import validate_current_alignment_evidence

        evidence = validate_current_alignment_evidence(
            document=alignment,
            candidate_id=candidate_id,
            source_asset_id=source_asset_id,
            source_sha256=inputs.pair.manifest.content_sha256,
        )
        if evidence.status != "verified_live":
            raise MediaError(evidence.blocker or evidence.status)
    source_sha = inputs.pair.manifest.content_sha256
    if source_sha != hero.document.source_sha256:
        raise MediaError("advanced Hero source bytes do not match the Hero draft")
    if inputs.pair.visual_sha256 != hero.document.visual_analysis_sha256:
        raise MediaError("advanced Hero visual analysis does not match the Hero draft")
    visual_path = inputs.pair.visual_path
    if sha256_file(visual_path) != inputs.pair.visual_sha256:
        raise MediaError("advanced Hero visual analysis bytes changed")
    source_path = inputs.pair.workspace.source_media_path() if False else None
    del source_path
    from clipforge.media.local_file import path_from_file_uri

    source_file = path_from_file_uri(inputs.pair.source.uri)
    if sha256_file(source_file) != source_sha:
        raise MediaError("advanced Hero source bytes changed")
    duration = hero_plan.edit_plan.time_map.to_time_map().total_output_duration()
    return _Context(
        workspace=inputs.pair.workspace,
        project_id=hero.project_id,
        source_sha256=source_sha,
        candidate_set_artifact_id=hero.document.candidate_set_artifact_id,
        candidate_set_sha256=hero.document.candidate_set_sha256,
        rough_artifact_id=hero.document.rough_preview_artifact_id,
        rough_manifest_sha256=hero.document.rough_manifest_sha256,
        hero_artifact_id=hero.artifact_id,
        hero_set_id=hero.document.hero_set_id,
        hero_manifest_sha256=hero.manifest_sha256,
        review_id=decision.review_id,
        review_digest=review_digest(decision),
        alignment=alignment,
        alignment_sha256=draft.alignment_sha256,
        hero_plan=hero_plan,
        hero_plan_sha256=draft.edit_plan_sha256,
        visual=inputs.pair.visual,
        visual_sha256=inputs.pair.visual_sha256,
        duration_us=duration,
    )


def _require_production_direction(
    plan: AdvancedHeroPlanDocument,
    renderer: AdvancedRenderBackend,
    workspace: SourceWorkspace | None = None,
) -> None:
    """Fail closed before a real Remotion render can use unsafe defaults.

    Fake backends remain available for deterministic contract tests. They do
    not claim a viewer-facing production result and therefore do not bypass
    the persisted provenance checks below.
    """
    if not renderer.requires_browser or plan.style_id == "legacy-v1":
        return
    if not plan.direction_id or not plan.direction_sha256:
        raise MediaError("clean Advanced Hero production requires a persisted source-grounded direction brief")
    if workspace is not None:
        direction_path = workspace.direction_file(plan.candidate_id)
        if direction_path.is_symlink() or not direction_path.is_file():
            raise MediaError("clean Advanced Hero production direction is missing or unsafe")
        if sha256_file(direction_path) != plan.direction_sha256:
            raise MediaError("clean Advanced Hero production direction hash is stale")
        try:
            direction = DirectionDocument.model_validate_json(direction_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            raise MediaError(f"clean Advanced Hero production direction is invalid: {exc}") from exc
        if direction.direction_id != plan.direction_id or direction.style_id != plan.style_id:
            raise MediaError("clean Advanced Hero production direction does not match the plan")
        selected = next(
            (option for option in direction.options if option.option_id == direction.selected_option_id),
            None,
        )
        if selected is None:
            raise MediaError("clean Advanced Hero production direction selection is missing")
        expected_broll = [item for item in selected.asset_placements if item.kind == "graphic"]
        expected_sfx = [item for item in selected.asset_placements if item.kind == "audio"]
        if len(plan.broll) != len(expected_broll) or any(
            event.asset_id != placement.asset_id
            or event.interval != placement.interval
            or event.broll_source_in_us != placement.source_in_us
            or event.source_evidence_ids != placement.source_evidence_ids
            or event.relevance_note != placement.relevance_note
            for event, placement in zip(plan.broll, expected_broll, strict=True)
        ):
            raise MediaError("clean Advanced Hero B-roll no longer matches reviewed direction placements")
        if len(plan.sfx) != len(expected_sfx) or any(
            event.asset_id != placement.asset_id
            or event.interval != placement.interval
            or event.sfx_source_in_us != placement.source_in_us
            or event.source_evidence_ids != placement.source_evidence_ids
            or event.purpose != placement.purpose
            or event.relevance_note != placement.relevance_note
            for event, placement in zip(plan.sfx, expected_sfx, strict=True)
        ):
            raise MediaError("clean Advanced Hero SFX no longer matches reviewed direction placements")
    for broll_event in plan.broll:
        if not broll_event.source_evidence_ids or not broll_event.relevance_note:
            raise MediaError(
                "production B-roll requires source evidence, relevance, and explicit reviewed timing"
            )
    for sfx_event in plan.sfx:
        if not sfx_event.source_evidence_ids or not sfx_event.relevance_note or sfx_event.purpose is None:
            raise MediaError(
                "production SFX requires source evidence, purpose, relevance, and explicit reviewed timing"
            )


def _render_run(
    database: Database,
    workspace: SourceWorkspace,
    hero: CurrentHero,
    chosen: list[tuple[str, AdvancedHeroPlanDocument]],
    profile: AdvancedHeroProfile,
    renderer: AdvancedRenderBackend,
    advanced_set_id: str,
    job: JobRecord,
    actor: str,
    now: datetime,
    root: Path,
    run_dir: Path,
    source_asset_id: str,
    narration: tuple[str, Path] | None = None,
) -> tuple[AdvancedHeroDraftSetDocument, Path]:
    if not isinstance(hero, CurrentHero):
        raise MediaError("current Hero draft is missing")
    rough = default_profile()
    inputs = load_preview_inputs(
        database, source_asset_id, root, profile_fingerprint=rough.fingerprint(), create_workspace=False
    )
    staging = run_dir / "staging"
    if renderer.requires_browser:
        staging.mkdir(parents=True, exist_ok=True)
    else:
        _link(inputs.proxy_path, staging / "analysis.mp4", root)
        _link(inputs.asr_path, staging / "asr.flac", root)
    items: list[dict[str, object]] = []
    prepared: list[tuple[int, str, AdvancedHeroPlanDocument, AdvancedHeroRenderInput, Path]] = []
    for rank, (candidate_id, plan) in enumerate(chosen, start=1):
        staged = {item.asset_id: _staged_name(item) for item in plan.assets}
        if narration is not None:
            _link(narration[1], staging / "narration.wav", root)
            staged["narration"] = "narration.wav"
        for binding in plan.assets:
            catalog_file = _asset_path(workspace, binding.asset_id, root)
            _link(catalog_file, staging / staged[binding.asset_id], root)
        selected_style = (
            style_for_id(plan.style_id)
            if plan.style_id != "legacy-v1"
            else style_for_renderer_version(profile.renderer_recipe_version)
        )
        render_input = AdvancedHeroRenderInput(
            candidate_id=candidate_id,
            advanced_set_id=advanced_set_id,
            duration_in_frames=frame_count_for_duration(_output_end_us(plan)),
            reframing_strategy=plan.reframing_strategy,
            reframing_config_sha256=plan.reframing_config_sha256,
            profile_fingerprint=plan.profile_fingerprint,
            style_id=selected_style.style_id,
            style_fingerprint=selected_style.fingerprint(),
            motion_style=selected_style.contract(),
            direction_id=plan.direction_id,
            direction_sha256=plan.direction_sha256,
            safe_region_id=plan.safe_region_id,
            alignment_sha256=plan.alignment_sha256,
            hero_plan_sha256=plan.hero_plan_sha256,
            advanced_plan_sha256=advanced_fingerprint(plan.model_dump(mode="json")),
            language=_alignment_locale(workspace, candidate_id),
            captions=plan.captions,
            typography=plan.typography,
            diagrams=plan.diagrams,
            motion_graphics=plan.motion_graphics,
            emphasis=plan.emphasis,
            broll=plan.broll,
            sfx=plan.sfx,
            windows=plan.windows,
            asset_names=staged,
            trajectory_sha256=_plan_trajectory_sha256(workspace, plan),
            time_map_sha256=plan.time_map_sha256,
            source_sha256=plan.source_sha256,
            output_duration_us=_output_end_us(plan),
            source_gain_db=profile.narration_duck_db if narration is not None else 0,
            narration_gain_db=0,
            audio_loudness_lufs=profile.audio_loudness_lufs,
            audio_true_peak_dbfs=profile.audio_true_peak_dbfs,
            audio_lra_lu=profile.audio_lra_lu,
            audio_mix_version=profile.audio_mix_version,
        )
        output = run_dir / "candidates" / candidate_id / "advanced.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        items.append(
            {
                "outputPath": str(output),
                "h264Crf": 18,
                "input": render_input.model_dump(mode="json"),
            }
        )
        prepared.append((rank, candidate_id, plan, render_input, output))
    batch = run_dir / "batch.json"
    if renderer.requires_browser:
        for item, (_rank, candidate_id, _plan, render_input, _output) in zip(items, prepared, strict=True):
            hero_plan = _read_model(
                hero.manifest_path.parent / "candidates" / candidate_id / "plan.json",
                HeroPlanDocument,
                "hero plan",
            )
            _stage_candidate_base(
                inputs,
                staging,
                candidate_id,
                hero_plan.edit_plan.time_map,
                render_input.duration_in_frames,
                root,
                run_dir / "logs" / f"{candidate_id}.trim.log",
            )
            batch.write_text(json_dumps({"items": [item]}), encoding="utf-8")
            renderer.render_batch(batch, log_path=run_dir / "logs" / "render.log")
    else:
        batch.write_text(json_dumps({"items": items}), encoding="utf-8")
        renderer.render_batch(batch, log_path=run_dir / "logs" / "render.log")
    for _rank, candidate_id, _plan, render_input, output in prepared:
        _normalize_audio(
            output,
            render_input,
            root,
            run_dir / "logs" / f"{candidate_id}.audio-normalize.log",
        )
    _cleanup_dir(staging, root)
    outputs: list[AdvancedHeroDraftOutput] = []
    for rank, candidate_id, plan, render_input, output in prepared:
        probed = probe_hero(output, expected_duration_us=_output_end_us(plan))
        sample_rate = _sample_rate(output)
        if sample_rate != profile.audio_sample_rate:
            raise MediaError(
                f"{output.name} sample rate is {sample_rate}, expected {profile.audio_sample_rate}"
            )
        (output.parent / "render-input.json").write_text(
            render_input.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        outputs.append(
            AdvancedHeroDraftOutput(
                candidate_id=candidate_id,
                rank=rank,
                hero_review_id=plan.hero_review_id,
                hero_review_digest=plan.hero_review_digest,
                alignment_id=plan.alignment_id,
                alignment_sha256=plan.alignment_sha256,
                hero_plan_id=plan.hero_plan_id,
                hero_plan_sha256=plan.hero_plan_sha256,
                advanced_plan_sha256=sha256_file(workspace.advanced_plan_file(candidate_id)),
                direction_id=plan.direction_id,
                direction_sha256=plan.direction_sha256,
                style_id=(
                    style_for_id(plan.style_id).style_id
                    if plan.style_id != "legacy-v1"
                    else style_for_renderer_version(profile.renderer_recipe_version).style_id
                ),
                render_input_sha256=sha256_file(output.parent / "render-input.json"),
                preview_relative_path=f"candidates/{candidate_id}/advanced.mp4",
                preview_sha256=sha256_file(output),
                preview_size_bytes=output.stat().st_size,
                output_duration_us=_output_end_us(plan),
                detected_video_codec=probed.video_codec,
                detected_pixel_format=probed.pixel_format,
                detected_audio_codec=probed.audio_codec,
                detected_audio_sample_rate=sample_rate,
                detected_duration_us=probed.duration_us,
                duration_error_us=probed.duration_error_us,
            )
        )
    identity = _input_digest(hero, profile, outputs)
    document = AdvancedHeroDraftSetDocument(
        advanced_set_id=advanced_set_id,
        project_id=hero.project_id,
        source_asset_id=source_asset_id,
        source_sha256=hero.document.source_sha256,
        candidate_set_artifact_id=hero.document.candidate_set_artifact_id,
        candidate_set_sha256=hero.document.candidate_set_sha256,
        rough_preview_artifact_id=hero.document.rough_preview_artifact_id,
        rough_manifest_sha256=hero.document.rough_manifest_sha256,
        hero_artifact_id=hero.artifact_id,
        hero_set_id=hero.document.hero_set_id,
        hero_manifest_sha256=hero.manifest_sha256,
        visual_analysis_id=hero.document.visual_analysis_id,
        visual_analysis_sha256=hero.document.visual_analysis_sha256,
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        reframing_strategy=_applied_strategy(chosen, profile),
        reframing_config_sha256=outputs[0].advanced_plan_sha256,
        advanced_input_sha256=identity,
        direction_sha256s=sorted({item.direction_sha256 for item in outputs if item.direction_sha256}),
        style_ids=sorted({item.style_id for item in outputs}),
        drafts=outputs,
        provenance=ArtifactProvenance(
            created_at=now,
            created_by=actor,
            tool="clipforge-advanced-hero",
            tool_version=__version__,
            source_asset_ids=[source_asset_id],
            job_id=job.job_id,
            inputs_sha256=identity,
        ),
    )
    manifest = run_dir / "manifest.json"
    publish_json(manifest, document, root, workspace.partial_for(manifest))
    return document, manifest


def _normalize_audio(
    output: Path,
    render_input: AdvancedHeroRenderInput,
    root: Path,
    log_path: Path,
) -> None:
    """Normalize the rendered mix without changing video frames."""
    ensure_within(root, output)
    if output.is_symlink() or not output.is_file() or output.stat().st_size < 1:
        raise MediaError("advanced output is missing before audio normalization")
    normalized = output.with_name("advanced.audio-normalized.mp4")
    ensure_within(root, normalized)
    if normalized.exists() or normalized.is_symlink():
        raise MediaError("refusing to replace an existing audio normalization output")
    filter_value = (
        f"loudnorm=I={render_input.audio_loudness_lufs}:"
        f"TP={render_input.audio_true_peak_dbfs}:LRA={render_input.audio_lra_lu},"
        # loudnorm can flush a partial AAC frame at the end of a cut.  The
        # TimeMap is the sole program clock, so pad before the deterministic
        # trim and reset timestamps rather than accepting an AV drift that
        # only appears after normalization.
        f"apad,atrim=duration={us_to_seconds_str(render_input.output_duration_us)},"
        "asetpts=PTS-STARTPTS"
    )
    ProcessRunner().run(
        [
            resolve_ffmpeg(),
            "-y",
            "-i",
            str(output),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c:v",
            "copy",
            "-af",
            filter_value,
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(normalized),
        ],
        log_path=log_path,
        check=True,
    )
    if normalized.is_symlink() or not normalized.is_file() or normalized.stat().st_size < 1:
        raise MediaError("audio normalization did not write a usable output")
    normalized.replace(output)
    _require_usable_audio(
        output,
        log_path.with_name(log_path.stem + ".measure.log"),
        target_lufs=render_input.audio_loudness_lufs,
        true_peak_limit=render_input.audio_true_peak_dbfs,
    )


def _require_usable_audio(
    output: Path,
    log_path: Path,
    *,
    target_lufs: float = -16,
    true_peak_limit: float = -1.5,
) -> None:
    result = ProcessRunner().run(
        [
            resolve_ffmpeg(),
            "-v",
            "info",
            "-i",
            str(output),
            "-map",
            "0:a:0",
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        log_path=log_path,
        check=True,
    )
    integrated = re.search(r"Integrated loudness:\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", result.stderr_tail, re.S)
    true_peak = re.search(r"True peak:\s*Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", result.stderr_tail, re.S)
    if integrated is None or true_peak is None:
        raise MediaError("advanced output audio loudness could not be measured")
    measured_lufs = float(integrated.group(1))
    measured_peak = float(true_peak.group(1))
    if measured_lufs < -55:
        raise MediaError("advanced output audio is unusably quiet")
    if abs(measured_lufs - target_lufs) > 1.5:
        raise MediaError(
            f"advanced output loudness {measured_lufs:.1f} LUFS is outside target {target_lufs:.1f} +/- 1.5 LU"
        )
    if measured_peak > true_peak_limit + 0.2:
        raise MediaError(
            f"advanced output true peak {measured_peak:.1f} dBFS exceeds limit {true_peak_limit:.1f} dBFS"
        )


def _input_digest(
    hero: CurrentHero, profile: AdvancedHeroProfile, drafts: list[AdvancedHeroDraftOutput]
) -> str:
    payload = {
        "drafts": [
            {
                "candidate_id": item.candidate_id,
                "advanced_plan_sha256": item.advanced_plan_sha256,
                "direction_sha256": item.direction_sha256,
                "style_id": item.style_id,
            }
            for item in drafts
        ],
        "hero_artifact_id": hero.artifact_id,
        "hero_manifest_sha256": hero.manifest_sha256,
        "profile": profile.fingerprint(),
        "source_sha256": hero.document.source_sha256,
        "visual_analysis_sha256": hero.document.visual_analysis_sha256,
    }
    return advanced_fingerprint(payload)


def _commit(
    database: Database,
    workspace: SourceWorkspace,
    job: JobRecord,
    document: AdvancedHeroDraftSetDocument,
    manifest: Path,
    record: AdvancedHeroCacheRecord,
    root: Path,
) -> None:
    previous = _snapshot(database, document.project_id, document.source_asset_id)
    provenance = document.provenance
    succeeded = job.model_copy(
        update={
            "status": JobStatus.SUCCEEDED,
            "updated_at": document.provenance.created_at,
            "error_message": None,
        }
    )
    with database.transaction() as connection:
        insert_artifact(
            connection,
            artifact_id=str(uuid.uuid4()),
            project_id=document.project_id,
            job_id=job.job_id,
            source_asset_id=document.source_asset_id,
            kind=KIND_ADVANCED,
            uri=path_to_file_uri(manifest),
            provenance=provenance,
        )
        update_job(connection, succeeded)
    try:
        sidecar = workspace.advanced_sidecar()
        publish_json(sidecar, record, root, workspace.partial_for(sidecar))
    except (OSError, MediaError) as exc:
        _revert(database, document, previous, job, str(exc))
        raise MediaError(
            f"advanced sidecar was not published: {exc}. The previous set remains current."
        ) from exc


def _cache_record(
    document: AdvancedHeroDraftSetDocument, job_id: str, digest: str, size: int
) -> AdvancedHeroCacheRecord:
    return AdvancedHeroCacheRecord(
        project_id=document.project_id,
        source_asset_id=document.source_asset_id,
        advanced_set_id=document.advanced_set_id,
        job_id=job_id,
        source_sha256=document.source_sha256,
        candidate_set_artifact_id=document.candidate_set_artifact_id,
        candidate_set_sha256=document.candidate_set_sha256,
        rough_preview_artifact_id=document.rough_preview_artifact_id,
        rough_manifest_sha256=document.rough_manifest_sha256,
        hero_artifact_id=document.hero_artifact_id,
        hero_set_id=document.hero_set_id,
        hero_manifest_sha256=document.hero_manifest_sha256,
        visual_analysis_id=document.visual_analysis_id,
        visual_analysis_sha256=document.visual_analysis_sha256,
        profile_fingerprint=document.profile_fingerprint,
        reframing_strategy=document.reframing_strategy,
        reframing_config_sha256=document.reframing_config_sha256,
        advanced_input_sha256=document.advanced_input_sha256,
        direction_sha256s=document.direction_sha256s,
        manifest_sha256=digest,
        manifest_size_bytes=size,
        rendered_count=len(document.drafts),
        validation_status="passed",
        created_at=document.provenance.created_at,
    )


def _approved_with_plans(
    database: Database,
    workspace: SourceWorkspace,
    hero: CurrentHero,
    source_asset_id: str,
    root: Path,
    profile: AdvancedHeroProfile,
) -> list[tuple[str, AdvancedHeroPlanDocument]]:
    del profile, source_asset_id, root, database
    found = []
    for draft in hero.document.drafts:
        path = workspace.advanced_plan_file(draft.candidate_id)
        if path.is_file() and not path.is_symlink():
            found.append((draft.candidate_id, _read_model(path, AdvancedHeroPlanDocument, "advanced plan")))
    return found


def _cache_ready(
    database: Database,
    workspace: SourceWorkspace,
    hero: CurrentHero,
    chosen: list[tuple[str, AdvancedHeroPlanDocument]],
    root: Path,
) -> bool:
    sidecar = workspace.advanced_sidecar()
    if not sidecar.is_file() or sidecar.is_symlink():
        return False
    try:
        record = AdvancedHeroCacheRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return False
    if record.hero_artifact_id != hero.artifact_id or record.hero_manifest_sha256 != hero.manifest_sha256:
        return False
    if record.source_sha256 != hero.document.source_sha256:
        return False
    if record.visual_analysis_sha256 != hero.document.visual_analysis_sha256:
        return False
    from clipforge.hero.advanced_assets import confine_work_path

    manifest = workspace.advanced_run_dir(record.advanced_set_id) / "manifest.json"
    try:
        manifest = confine_work_path(root, manifest.relative_to(root).as_posix(), label="advanced manifest")
    except (MediaError, ValueError):
        return False
    if not manifest.is_file():
        return False
    if sha256_file(manifest) != record.manifest_sha256:
        return False
    try:
        document = AdvancedHeroDraftSetDocument.model_validate_json(manifest.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return False
    if len(document.drafts) != len(chosen):
        return False
    from clipforge.hero.advanced_assets import confine_work_path

    for draft in document.drafts:
        video = manifest.parent / draft.preview_relative_path
        try:
            video = confine_work_path(root, video.relative_to(root).as_posix(), label="advanced media")
        except (MediaError, ValueError):
            return False
        if not video.is_file():
            return False
        if sha256_file(video) != draft.preview_sha256 or video.stat().st_size != draft.preview_size_bytes:
            return False
    for candidate_id, plan in chosen:
        plan_path = workspace.advanced_plan_file(candidate_id)
        matched = next((item for item in document.drafts if item.candidate_id == candidate_id), None)
        if matched is None or not plan_path.is_file() or plan_path.is_symlink():
            return False
        if sha256_file(plan_path) != matched.advanced_plan_sha256:
            return False
        if plan.reframing_strategy == "face_follow" and not _reframe_sidecar_current(workspace, plan):
            return False
        for binding in plan.assets:
            try:
                path = _asset_path(workspace, binding.asset_id, root)
            except MediaError:
                return False
            if not path.is_file() or sha256_file(path) != binding.sha256:
                return False
    with database.connect() as connection:
        row = find_artifact(connection, record.project_id, record.source_asset_id, KIND_ADVANCED)
    return row is not None and path_to_file_uri(manifest) == row.uri


def _running_job(project_id: str, source_asset_id: str, count: int, now: datetime, actor: str) -> JobRecord:
    return JobRecord(
        job_id=str(uuid.uuid4()),
        project_id=project_id,
        kind=JOB_ADVANCED,
        status=JobStatus.RUNNING,
        created_at=now,
        updated_at=now,
        payload={"source_asset_id": source_asset_id, "count": str(count), "actor": actor},
    )


def _reviews(database: Database, project_id: str) -> list[ReviewDecision]:
    with database.connect() as connection:
        return list_reviews(connection, project_id)


def _read_model(path: Path, model: type[_ModelT], label: str) -> _ModelT:
    if not path.is_file() or path.is_symlink():
        raise MediaError(f"advanced Hero {label} is missing")
    try:
        parsed = model.model_validate_json(path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
    except (OSError, ValidationError, ValueError) as exc:
        raise MediaError(f"advanced Hero {label} could not be read: {exc}") from exc
    return cast(_ModelT, parsed)


def _sample_rate(path: Path) -> int:
    payload = read_ffprobe_json(path, ProcessRunner(), None)
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise MediaError(f"{path.name} has no streams")
    for stream in streams:
        if isinstance(stream, dict) and stream.get("codec_type") == "audio":
            rate = stream.get("sample_rate")
            return int(rate) if isinstance(rate, str) and rate.isdigit() else 0
    raise MediaError(f"{path.name} has no audio stream")


def _plan_trajectory_sha256(workspace: SourceWorkspace, plan: AdvancedHeroPlanDocument) -> str:
    if plan.reframing_strategy != "face_follow":
        return ""
    return _sidecar_trajectory(workspace, plan)


def _alignment_locale(workspace: object, candidate_id: str) -> str:
    """Locale stored on the selected-clip alignment. Missing evidence is not English."""
    from clipforge.schemas.hero import ForcedAlignmentDocument

    path = workspace.hero_alignment_file(candidate_id)  # type: ignore[attr-defined]
    if not path.is_file() or path.is_symlink():
        return "missing"
    try:
        document = ForcedAlignmentDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return "missing"
    return document.locale or "missing"


def _output_end_us(plan: AdvancedHeroPlanDocument) -> int:
    if not plan.windows:
        return 1
    return max(window.output_end_us for window in plan.windows)


def _applied_strategy(
    chosen: list[tuple[str, AdvancedHeroPlanDocument]],
    profile: AdvancedHeroProfile,
) -> str:
    if not chosen:
        return profile.reframing.strategy_id
    strategy = chosen[0][1].reframing_strategy
    if any(plan.reframing_strategy != strategy for _candidate_id, plan in chosen):
        raise MediaError("advanced render refuses mixed reframing strategies")
    return strategy


def _reframe_sidecar_current(workspace: SourceWorkspace, plan: AdvancedHeroPlanDocument) -> bool:
    from clipforge.schemas.reframe import ReframePlanDocument

    path = workspace.reframe_plan_file(plan.candidate_id)
    if path.is_symlink() or not path.is_file():
        return False
    try:
        document = ReframePlanDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError):
        return False
    if document.applied_strategy != "face_follow" or document.trajectory is None:
        return False
    if (
        document.source_sha256 != plan.source_sha256
        or document.visual_analysis_sha256 != plan.visual_analysis_sha256
    ):
        return False
    duration_us = plan.windows[-1].output_end_us if plan.windows else 0
    if document.time_map_sha256 != plan.time_map_sha256:
        return False
    if not windows_follow_trajectory(document, list(plan.windows), duration_us):
        return False
    return document.trajectory_sha256 == document.trajectory.digest()


def _require_plan_binding(database: Database, plan: AdvancedHeroPlanDocument, context: _Context) -> None:
    """Fail closed when the stored plan no longer matches the current producers."""
    if plan.reframing_strategy not in {"contain", "center_crop", "face_follow", "manual_window"}:
        strategy = plan.reframing_strategy
        raise MediaError(f"advanced render does not support reframing strategy {strategy}")
    if plan.reframing_strategy == "face_follow":
        _require_face_follow(database, plan, context)
    elif plan.reframing_strategy == "manual_window":
        cursor_us = 0
        if not plan.windows:
            raise MediaError("manual_window requires reviewed crop windows")
        for window in plan.windows:
            if (
                window.strategy_id.strategy_id != "manual_window"
                or window.output_start_us != cursor_us
                or window.frame_width != context.visual.proxy_width
                or window.frame_height != context.visual.proxy_height
                or window.source_width * 16 != window.source_height * 9
            ):
                raise MediaError("manual_window trajectory has a gap, stale frame, or invalid portrait crop")
            cursor_us = window.output_end_us
        if cursor_us != context.duration_us:
            raise MediaError("manual_window trajectory must cover the full output duration without gaps")
    if plan.motion_style is not None:
        selected_style = style_for_id(plan.style_id)
        if (
            plan.style_fingerprint != selected_style.fingerprint()
            or plan.motion_style != selected_style.contract()
        ):
            raise MediaError("advanced plan is stale: motion recipe changed after planning")
    if plan.direction_id:
        loaded_direction = load_direction(context.workspace, plan.candidate_id)
        if loaded_direction is None:
            raise MediaError("advanced plan is stale: direction document is missing")
        direction, direction_sha256 = loaded_direction
        if direction.direction_id != plan.direction_id or direction_sha256 != plan.direction_sha256:
            raise MediaError("advanced plan is stale: direction changed after planning")
        if direction.style_id != plan.style_id or direction.style_fingerprint != plan.style_fingerprint:
            raise MediaError("advanced plan is stale: selected motion style changed")
        from clipforge.hero.direction_service import validate_source_evidence

        validate_source_evidence(
            direction,
            context.alignment.words,
            context.hero_plan.edit_plan.time_map,
            {scene.scene_id for scene in context.visual.scenes},
        )
    checks = (
        (plan.source_sha256 != context.source_sha256, "source"),
        (plan.candidate_set_artifact_id != context.candidate_set_artifact_id, "candidate set"),
        (plan.candidate_set_sha256 != context.candidate_set_sha256, "candidate set SHA"),
        (plan.rough_preview_artifact_id != context.rough_artifact_id, "rough preview"),
        (plan.rough_manifest_sha256 != context.rough_manifest_sha256, "rough preview manifest"),
        (plan.hero_artifact_id != context.hero_artifact_id, "Hero artifact"),
        (plan.hero_set_id != context.hero_set_id, "Hero set"),
        (plan.hero_manifest_sha256 != context.hero_manifest_sha256, "Hero manifest"),
        (plan.hero_review_id != context.review_id, "Hero approval"),
        (plan.hero_review_digest != context.review_digest, "Hero approval"),
        (plan.alignment_id != context.alignment.alignment_id, "alignment"),
        (plan.alignment_sha256 != context.alignment_sha256, "alignment"),
        (plan.hero_plan_id != context.hero_plan.plan_id, "Hero plan"),
        (plan.hero_plan_sha256 != context.hero_plan_sha256, "Hero plan"),
        (plan.visual_analysis_id != context.visual.analysis_id, "visual analysis"),
        (plan.visual_analysis_sha256 != context.visual_sha256, "visual analysis"),
        (plan.time_map_sha256 != context.hero_plan.edit_plan.time_map_sha256, "TimeMap"),
    )
    for failed, name in checks:
        if failed:
            raise MediaError(f"advanced plan is stale: {name} changed after planning")
    if plan.windows:
        end = max(window.output_end_us for window in plan.windows)
        if end != context.duration_us:
            raise MediaError("advanced plan is stale: TimeMap duration changed after planning")


def _require_face_follow(database: Database, plan: AdvancedHeroPlanDocument, context: _Context) -> None:
    from clipforge.hero.reframe import ReframeError, assert_unlinked, build_face_follow
    from clipforge.storage.repository import get_job

    stored = _stored_reframe(context.workspace, plan)
    if stored is None or not _reframe_sidecar_current(context.workspace, plan):
        raise MediaError("visual_analysis_stale")
    job_id = context.visual.provenance.job_id or ""
    succeeded = False
    if job_id:
        try:
            with database.connect() as connection:
                succeeded = get_job(connection, job_id).status.value == "succeeded"
        except StorageError:
            succeeded = False
    try:
        with database.connect() as connection:
            manifest = get_source_manifest(connection, plan.source_asset_id)
        video = next(
            (item for item in manifest.probe.video_streams if item.index == manifest.video_stream_index),
            None,
        )
        if video is None:
            raise MediaError("face_track_gap_tolerance_unavailable")
        rate = video.avg_frame_rate or video.r_frame_rate
        if rate is None:
            raise MediaError("face_track_gap_tolerance_unavailable")
        expected_gap_tolerance = frame_period_tolerance_us(rate.numerator, rate.denominator)
        if stored.gap_tolerance_us != expected_gap_tolerance:
            raise MediaError("visual_analysis_stale")
        rebuilt = build_face_follow(
            samples=list(context.visual.face_detection_samples),
            source_width=context.visual.proxy_width,
            source_height=context.visual.proxy_height,
            time_map=context.hero_plan.edit_plan.time_map,
            time_map_sha256=context.hero_plan.edit_plan.time_map_sha256,
            source_sha256=context.source_sha256,
            analysis_source_sha256=context.visual.source_sha256,
            analysis_present=bool(context.visual.face_detection_samples),
            producer_succeeded=succeeded,
            visual_analysis_id=context.visual.analysis_id,
            visual_analysis_sha256=context.visual_sha256,
            producer_job_id=job_id,
            plan_id=stored.plan_id,
            source_asset_id=stored.source_asset_id,
            created_by=stored.created_by,
            tool_version=stored.tool_version,
            profile_fingerprint=stored.profile_fingerprint,
            face_sample_interval_us=stored.face_sample_interval_us,
            gap_tolerance_us=expected_gap_tolerance,
        )
    except ReframeError as exc:
        raise MediaError(exc.code) from exc
    same_plan = rebuilt.plan_fingerprint == stored.plan_fingerprint
    same_trajectory = rebuilt.trajectory_sha256 == stored.trajectory_sha256
    if not same_plan or not same_trajectory:
        raise MediaError("visual_analysis_stale")
    side = context.workspace.reframe_plan_file(plan.candidate_id)
    try:
        assert_unlinked(side, context.workspace.root)
    except ReframeError as exc:
        raise MediaError(exc.code) from exc


def _stored_reframe(workspace: SourceWorkspace, plan: AdvancedHeroPlanDocument) -> ReframePlanDocument | None:
    path = workspace.reframe_plan_file(plan.candidate_id)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        return ReframePlanDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError):
        return None


def _sidecar_trajectory(workspace: SourceWorkspace, plan: AdvancedHeroPlanDocument) -> str:
    document = _stored_reframe(workspace, plan)
    if document is None:
        return ""
    return document.trajectory_sha256


def _require_plan_assets(
    database: Database,
    workspace: SourceWorkspace,
    plan: AdvancedHeroPlanDocument,
    root: Path,
) -> None:
    from clipforge.hero.advanced_assets import require_asset

    for binding in plan.assets:
        entry, license_record, path = require_asset(
            database,
            workspace,
            project_id=plan.project_id,
            asset_id=binding.asset_id,
            expected_kind=binding.kind,
            work_root=root,
        )
        if entry.file_sha256 != binding.sha256 or sha256_file(path) != binding.sha256:
            raise MediaError(f"advanced plan is stale: asset {binding.asset_id} hash changed after planning")
        if license_record.status.value != binding.license_status:
            raise MediaError(f"advanced plan is stale: asset {binding.asset_id} rights changed after planning")
        if license_record.license_record_id != binding.license_record_id:
            raise MediaError(f"advanced plan is stale: asset {binding.asset_id} rights changed after planning")


def _staged_name(binding: AssetBinding) -> str:
    suffix = ".wav" if binding.kind == "audio" else ".mp4"
    return f"{binding.asset_id}{suffix}"


def _asset_path(workspace: SourceWorkspace, asset_id: str, root: Path) -> Path:
    from clipforge.hero.advanced_assets import confine_work_path, load_catalog

    entry = next((item for item in load_catalog(workspace) if item.reference.asset_id == asset_id), None)
    if entry is None:
        raise MediaError(f"advanced asset {asset_id} is not in the local catalog")
    return confine_work_path(root, entry.relative_path, label=f"advanced asset {asset_id}")


def _stage_candidate_base(
    inputs: object,
    staging: Path,
    candidate_id: str,
    time_map: TimeMapDocument,
    frame_count: int,
    root: Path,
    log_path: Path,
) -> None:
    """Replace shared base names with the candidate's ordered TimeMap clip.

    The old implementation staged only ``segments[0]``.  That made any
    operator-authored jump-cut plan render one contiguous moment and encouraged
    callers to repeat it to fill a target duration.  Keep the cheap mining
    contract intact, but make the production staging path consume every
    validated segment in order. Even a one-range Hero uses ``stage_time_map``
    here so its recipe proves that picture and speech came from the same
    canonical map; the renderer must never accept two independently prepared
    files just because their durations happen to match.
    """
    from clipforge.preview.trim import stage_time_map

    for name in ("analysis.mp4", "asr.flac", "span.mp4", "span.flac", "span.recipe.json"):
        path = staging / name
        if path.is_symlink():
            raise MediaError("refusing to replace a symlinked advanced stage file")
        if path.exists():
            path.unlink()
    staged_jump_cut = stage_time_map(
        inputs.proxy_path,  # type: ignore[attr-defined]
        inputs.asr_path,  # type: ignore[attr-defined]
        staging,
        stem="span",
        time_map=time_map,
        frame_count=frame_count,
        root=root,
        log_path=log_path,
    )
    staged_video_path = staged_jump_cut.video_path
    staged_audio_path = staged_jump_cut.audio_path
    staged_video_path.rename(staging / "analysis.mp4")
    staged_audio_path.rename(staging / "asr.flac")


def _link(source: Path, destination: Path, root: Path) -> None:
    from clipforge.hero.advanced_assets import confine_work_path

    try:
        source_relative = source.relative_to(root)
    except ValueError as exc:
        raise MediaError("refusing to stage a file outside the work root") from exc
    confine_work_path(root, source_relative.as_posix(), label="staged media")
    try:
        destination_relative = destination.relative_to(root)
    except ValueError as exc:
        raise MediaError("refusing to stage a file outside the work root") from exc
    confine_work_path(root, destination_relative.parent.as_posix(), label="staged media")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    try:
        destination.hardlink_to(source)
    except OSError:
        shutil.copyfile(source, destination)


def _cleanup_dir(path: Path, root: Path) -> None:
    if not path.exists():
        return
    ensure_within(root, path)
    if path.is_symlink():
        raise MediaError(f"refusing to clean a symlink {path}")
    shutil.rmtree(path)


def _validate_workspace(workspace: SourceWorkspace) -> None:
    root = workspace.advanced_root()
    if root.is_symlink():
        raise MediaError(f"refusing to follow symlinked advanced Hero workspace {root}")


def _fail_stale(database: Database, project_id: str, source_asset_id: str) -> None:
    now = datetime.now(UTC)
    with database.transaction() as connection:
        for existing in list_jobs(connection, project_id):
            if existing.kind != JOB_ADVANCED or existing.status is not JobStatus.RUNNING:
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
                            "interrupted before completion. Partial advanced outputs were not promoted."
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
    if run_dir is not None:
        staging = run_dir / "staging"
        if staging.exists():
            _cleanup_dir(staging, root)
        manifest = run_dir / "manifest.json"
        partial = manifest.with_suffix(".json.partial")
        if partial.exists() and not manifest.exists():
            partial.unlink()
    updated = job.model_copy(
        update={"status": status, "updated_at": datetime.now(UTC), "error_message": message[:2000]}
    )
    with database.transaction() as connection:
        update_job(connection, updated)


def _snapshot(database: Database, project_id: str, source_asset_id: str) -> ArtifactRow | None:
    with database.connect() as connection:
        return find_artifact(connection, project_id, source_asset_id, KIND_ADVANCED)


def _revert(
    database: Database,
    document: AdvancedHeroDraftSetDocument,
    previous: ArtifactRow | None,
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
            update_artifact(
                connection,
                artifact_id=previous.artifact_id,
                project_id=document.project_id,
                job_id=previous.job_id,
                source_asset_id=document.source_asset_id,
                kind=KIND_ADVANCED,
                uri=previous.uri,
                provenance=previous.provenance,
            )
        connection.execute(
            "DELETE FROM artifacts WHERE project_id = ? AND source_asset_id = ? AND kind = ? AND job_id = ?",
            (document.project_id, document.source_asset_id, KIND_ADVANCED, job.job_id),
        )
        update_job(connection, failed)


def _current_manifest(workspace: SourceWorkspace) -> Path | None:
    sidecar = workspace.advanced_sidecar()
    if not sidecar.is_file():
        return None
    record = AdvancedHeroCacheRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
    return workspace.advanced_run_dir(record.advanced_set_id) / "manifest.json"


def _sidecar_set_id(workspace: SourceWorkspace) -> str | None:
    path = _current_manifest(workspace)
    return None if path is None else path.parent.name


def json_dumps(payload: dict[str, object]) -> str:
    import json

    return json.dumps(payload)


def _actor(created_by: str | None) -> str:
    if created_by and created_by.strip():
        return created_by.strip()[:200]
    return "clipforge"


def _busy(source: str, label: str) -> str:
    return f"another {label} is active for source {source}."


def format_advanced_list(database: Database, source_asset_id: str, work_root: Path) -> str:
    document = _load_current_document(database, source_asset_id, work_root)
    if document is None:
        return "No current advanced Hero drafts are stored for this source."
    lines = [f"advanced_set_id: {document.advanced_set_id}", f"hero_artifact_id: {document.hero_artifact_id}"]
    for draft in document.drafts:
        lines.append(f"{draft.rank}\t{draft.candidate_id}\t{draft.preview_sha256}")
    return "\n".join(lines)


def format_advanced_show(database: Database, source_asset_id: str, candidate_id: str, work_root: Path) -> str:
    document = _load_current_document(database, source_asset_id, work_root)
    if document is None:
        raise MediaError("no current advanced Hero draft")
    draft = next((item for item in document.drafts if item.candidate_id == candidate_id), None)
    if draft is None:
        raise MediaError(f"unknown candidate {candidate_id}")
    workspace = SourceWorkspace(work_root.resolve(), document.project_id, document.source_asset_id)
    return "\n".join(
        [
            f"candidate_id: {draft.candidate_id}",
            f"reframing: {document.reframing_strategy}",
            f"applied: {_show_applied(workspace, candidate_id, document.reframing_strategy)}",
            f"blocker: {_show_blocker(workspace, candidate_id, document.reframing_strategy)}",
            f"advanced_plan_sha256: {draft.advanced_plan_sha256}",
            f"dimensions: {draft.width}x{draft.height}",
        ]
    )


def _show_applied(workspace: SourceWorkspace, candidate_id: str, strategy: str) -> str:
    if strategy != "face_follow":
        return strategy
    path = workspace.reframe_plan_file(candidate_id)
    if path.is_symlink() or not path.is_file():
        return "contain"
    try:
        from clipforge.schemas.reframe import ReframePlanDocument

        document = ReframePlanDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError):
        return "contain"
    return document.applied_strategy


def _show_blocker(workspace: SourceWorkspace, candidate_id: str, strategy: str) -> str:
    if strategy != "face_follow":
        return "none"
    path = workspace.reframe_plan_file(candidate_id)
    if path.is_symlink():
        return "unsafe_path"
    if not path.is_file():
        return "visual_analysis_missing"
    return "none"


def verify_advanced(database: Database, source_asset_id: str, work_root: Path) -> None:
    document = _load_current_document(database, source_asset_id, work_root)
    if document is None:
        raise MediaError("no current advanced Hero draft")
    root = work_root.resolve()
    fingerprint = default_profile().fingerprint()
    loaded = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=fingerprint,
        create_workspace=False,
    )
    from clipforge.hero.advanced_assets import confine_work_path

    workspace = loaded.pair.workspace
    hero = load_current_hero(database, source_asset_id, root)
    manifest = workspace.advanced_run_dir(document.advanced_set_id) / "manifest.json"
    manifest = confine_work_path(root, manifest.relative_to(root).as_posix(), label="advanced manifest")
    if sha256_file(manifest) != _sidecar_digest(workspace):
        raise MediaError("advanced manifest hash does not match the sidecar")

    from clipforge.language.evidence import validate_current_alignment_evidence
    from clipforge.schemas.hero import ForcedAlignmentDocument

    for draft in document.drafts:
        video = manifest.parent / draft.preview_relative_path
        video = confine_work_path(root, video.relative_to(root).as_posix(), label="advanced output")
        if not video.is_file():
            raise MediaError("advanced output is missing or a symlink")
        if sha256_file(video) != draft.preview_sha256:
            raise MediaError("advanced output hash does not match the manifest")

        alignment_path = hero.manifest_path.parent / "candidates" / draft.candidate_id / "alignment.json"
        alignment_path = confine_work_path(
            root,
            alignment_path.relative_to(root).as_posix(),
            label="advanced alignment",
        )
        if alignment_path.is_symlink() or not alignment_path.is_file():
            raise MediaError("advanced alignment is missing or a symlink")
        if sha256_file(alignment_path) != draft.alignment_sha256:
            raise MediaError("advanced alignment hash does not match the draft")
        try:
            alignment = ForcedAlignmentDocument.model_validate_json(alignment_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            raise MediaError("advanced alignment is invalid") from exc
        if alignment.alignment_status == "verified_live":
            evidence = validate_current_alignment_evidence(
                document=alignment,
                candidate_id=draft.candidate_id,
                source_asset_id=source_asset_id,
                project_id=loaded.pair.source.project_id,
                source_sha256=loaded.pair.manifest.content_sha256,
                file_sha256=draft.alignment_sha256,
            )
            if evidence.status != "verified_live":
                raise MediaError(evidence.blocker or evidence.status)


def _load_current_document(
    database: Database, source_asset_id: str, work_root: Path
) -> AdvancedHeroDraftSetDocument | None:
    root = work_root.resolve()
    fingerprint = default_profile().fingerprint()
    inputs = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=fingerprint,
        create_workspace=False,
    )
    path = _current_manifest(inputs.pair.workspace)
    if path is None or not path.is_file():
        return None
    return AdvancedHeroDraftSetDocument.model_validate_json(path.read_text(encoding="utf-8"))


def _sidecar_digest(workspace: SourceWorkspace) -> str:
    raw = workspace.advanced_sidecar().read_text(encoding="utf-8")
    record = AdvancedHeroCacheRecord.model_validate_json(raw)
    return record.manifest_sha256


def advanced_media_path(database: Database, source_asset_id: str, candidate_id: str, work_root: Path) -> Path:
    root = work_root.resolve()
    document = _load_current_document(database, source_asset_id, root)
    if document is None:
        raise MediaError(f"unknown candidate {candidate_id}")
    draft = next((item for item in document.drafts if item.candidate_id == candidate_id), None)
    if draft is None:
        raise MediaError(f"unknown candidate {candidate_id}")
    inputs = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=default_profile().fingerprint(),
        create_workspace=False,
    )
    from clipforge.hero.advanced_assets import confine_work_path

    lexical = inputs.pair.workspace.advanced_run_dir(document.advanced_set_id) / draft.preview_relative_path
    path = confine_work_path(root, lexical.relative_to(root).as_posix(), label="advanced media")
    if not path.is_file():
        raise MediaError(f"unknown candidate {candidate_id}")
    return path


def advanced_review_board(database: Database, source_asset_id: str, work_root: Path) -> dict[str, object]:
    """Sanitized advanced review facts. No filesystem paths."""
    document = _load_current_document(database, source_asset_id, work_root)
    if document is None:
        return {"status": "empty", "drafts": [], "detail": "No current advanced Hero drafts are stored."}
    root = work_root.resolve()
    inputs = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=default_profile().fingerprint(),
        create_workspace=False,
    )
    with database.connect() as connection:
        row = find_artifact(connection, document.project_id, source_asset_id, KIND_ADVANCED)
    reviews = _reviews(database, document.project_id)
    drafts: list[dict[str, object]] = []
    artifact_id = None if row is None else row.artifact_id
    manifest_sha = _sidecar_digest(inputs.pair.workspace)
    for draft in document.drafts:
        plan = _read_model(
            inputs.pair.workspace.advanced_plan_file(draft.candidate_id),
            AdvancedHeroPlanDocument,
            "advanced plan",
        )
        drafts.append(_review_draft(document, draft, plan, artifact_id, manifest_sha, reviews))
    return {
        "status": "ready",
        "source_asset_id": source_asset_id,
        "project_id": document.project_id,
        "advanced_set_id": document.advanced_set_id,
        "artifact_id": None if row is None else row.artifact_id,
        "hero_artifact_id": document.hero_artifact_id,
        "manifest_sha256": _sidecar_digest(inputs.pair.workspace),
        "source_sha256": document.source_sha256,
        "reframing_strategy": document.reframing_strategy,
        "music_allowed": False,
        "drafts": drafts,
        **_qa_facts(database, source_asset_id, work_root),
    }


def _qa_facts(database: Database, source_asset_id: str, work_root: Path) -> dict[str, object]:
    from clipforge.qa.service import qa_public_facts

    return qa_public_facts(database, source_asset_id, work_root)


def advanced_review_card(
    database: Database, source_asset_id: str, candidate_id: str, work_root: Path
) -> dict[str, object]:
    board = advanced_review_board(database, source_asset_id, work_root)
    drafts = board.get("drafts")
    if isinstance(drafts, list):
        for draft in drafts:
            if isinstance(draft, dict) and draft.get("candidate_id") == candidate_id:
                return draft
    raise MediaError(f"unknown candidate {candidate_id}")


def _review_draft(
    document: AdvancedHeroDraftSetDocument,
    draft: AdvancedHeroDraftOutput,
    plan: AdvancedHeroPlanDocument,
    artifact_id: str | None,
    manifest_sha256: str,
    reviews: list[ReviewDecision],
) -> dict[str, object]:
    names = {item.asset_id: item for item in plan.assets}
    broll: list[dict[str, object]] = []
    for clip in plan.broll:
        binding = names.get(clip.asset_id)
        broll.append(
            {
                "asset_id": clip.asset_id,
                "display_name": None if binding is None else binding.display_name,
                "kind": None if binding is None else binding.kind,
                "rights_status": None if binding is None else binding.license_status,
                "output_start_us": clip.interval.output_start_us,
                "output_end_us": clip.interval.output_end_us,
                "source_in_us": clip.broll_source_in_us,
                "layer_name": "b-roll",
            }
        )
    sfx: list[dict[str, object]] = []
    for sound in plan.sfx:
        binding = names.get(sound.asset_id)
        sfx.append(
            {
                "asset_id": sound.asset_id,
                "display_name": None if binding is None else binding.display_name,
                "rights_status": None if binding is None else binding.license_status,
                "role": sound.role,
                "gain_db": sound.gain_db,
                "output_start_us": sound.interval.output_start_us,
                "output_end_us": sound.interval.output_end_us,
            }
        )
    typography = [
        {
            "component_id": item.component_id,
            "text": item.text,
            "purpose": item.purpose.value,
            "output_start_us": item.interval.output_start_us,
            "output_end_us": item.interval.output_end_us,
            "x": item.x,
            "y": item.y,
            "font_size": item.font_size,
            "style_id": "advanced-typography-v1",
        }
        for item in plan.typography
    ]
    diagrams = [
        {
            "component_id": item.component_id,
            "kind": item.payload.kind,
            "left_label": item.payload.left_label,
            "right_label": item.payload.right_label,
            "left_value": item.payload.left_value,
            "right_value": item.payload.right_value,
            "output_start_us": item.interval.output_start_us,
            "output_end_us": item.interval.output_end_us,
            "x": item.x,
            "y": item.y,
            "width": item.width,
            "height": item.height,
        }
        for item in plan.diagrams
    ]
    motion_graphics = [
        {
            "component_id": item.event_id,
            "template": item.template,
            "display_text": item.display_text,
            "purpose": item.purpose.value,
            "source_evidence_ids": item.source_evidence_ids,
            "output_start_us": item.interval.output_start_us,
            "output_end_us": item.interval.output_end_us,
            "x": item.x,
            "y": item.y,
            "width": item.width,
            "height": item.height,
        }
        for item in plan.motion_graphics
    ]
    emphasis = [
        {
            "text": item.text,
            "word_id": item.word_id,
            "output_start_frame": item.output_start_frame,
            "output_end_frame_exclusive": item.output_end_frame_exclusive,
            "purpose": item.purpose.value,
            "rule_id": item.rule_id,
            "component_id": item.event_id,
        }
        for item in plan.emphasis
    ]
    effective = (
        None
        if artifact_id is None
        else effective_review(reviews, artifact_id, draft.candidate_id, subject_kind="hero")
    )
    return {
        "candidate_id": draft.candidate_id,
        "rank": draft.rank,
        "source_asset_id": document.source_asset_id,
        "project_id": document.project_id,
        "advanced_set_id": document.advanced_set_id,
        "artifact_id": artifact_id,
        "artifact_kind": KIND_ADVANCED,
        "manifest_sha256": manifest_sha256,
        "source_sha256": document.source_sha256,
        "hero_set_id": document.hero_set_id,
        "hero_artifact_id": document.hero_artifact_id,
        "alignment_id": plan.alignment_id,
        "alignment_sha256": plan.alignment_sha256,
        "plan_id": plan.hero_plan_id,
        "plan_sha256": plan.hero_plan_sha256,
        "advanced_plan_sha256": draft.advanced_plan_sha256,
        "reframing_strategy": document.reframing_strategy,
        "preview_url": f"/media/advanced-hero/{draft.candidate_id}",
        "broll": broll,
        "sfx": sfx,
        "typography": typography,
        "diagrams": diagrams,
        "motion_graphics": motion_graphics,
        "emphasis": emphasis,
        "current_decision": None if effective is None else effective.decision,
        "history": [
            {
                "review_id": item.review_id,
                "decision": item.decision,
                "reviewer_id": item.reviewer_id,
                "notes": item.notes,
                "artifact_id": item.artifact_id,
                "current_artifact": item.artifact_id == artifact_id,
                "created_at": item.created_at.isoformat(),
            }
            for item in reviews
            if item.subject_kind == "hero" and item.candidate_id == draft.candidate_id
        ],
    }


def record_advanced_decision(
    *,
    database: Database,
    work_root: Path,
    source_asset_id: str,
    candidate_id: str,
    advanced_set_id: str,
    artifact_id: str,
    decision: str,
    reviewer_id: str,
    notes: str,
) -> str:
    """Append one review of the current advanced artifact. It does not render."""
    from clipforge.review.service import NOTES_MAX
    from clipforge.schemas.governance import ReviewDecision
    from clipforge.storage import insert_review

    reviewer = reviewer_id.strip()
    if decision not in {"approved", "rejected", "changes_requested"}:
        raise MediaError(f"decision must be approved, rejected, or changes_requested, got {decision!r}")
    if not reviewer:
        raise MediaError("reviewer_id must not be blank")
    if len(notes) > NOTES_MAX:
        raise MediaError(f"notes are longer than {NOTES_MAX} characters")
    require_advanced_binding(database, source_asset_id, work_root, advanced_set_id, artifact_id)
    document = _load_current_document(database, source_asset_id, work_root)
    if document is None:
        raise MediaError("no current advanced Hero draft")
    review = ReviewDecision(
        review_id=str(uuid.uuid4()),
        project_id=document.project_id,
        artifact_id=artifact_id,
        candidate_id=candidate_id,
        subject_kind="hero",
        decision=decision,  # type: ignore[arg-type]
        reviewer_id=reviewer,
        created_at=datetime.now(UTC),
        notes=notes,
        automated=False,
    )
    with database.transaction() as connection:
        insert_review(connection, review)
    return review.review_id


def require_advanced_binding(
    database: Database,
    source_asset_id: str,
    work_root: Path,
    advanced_set_id: str,
    artifact_id: str,
) -> None:
    """Reject a review write for a different advanced set."""
    from clipforge.review.service import HERO_STALE_MESSAGE

    document = _load_current_document(database, source_asset_id, work_root)
    if document is None or document.advanced_set_id != advanced_set_id:
        raise MediaError(HERO_STALE_MESSAGE)
    with database.connect() as connection:
        row = find_artifact(connection, document.project_id, source_asset_id, KIND_ADVANCED)
    if row is None or row.artifact_id != artifact_id:
        raise MediaError(HERO_STALE_MESSAGE)


def hero_kind() -> str:
    return KIND_HERO
