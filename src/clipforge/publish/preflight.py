"""One delivery preflight. Plan, export, verify, benchmark, and readiness all use it."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from clipforge.errors import ClipforgeError, MediaError, StorageError
from clipforge.hero.advanced_assets import confine_file_uri, confine_work_path, require_asset
from clipforge.hero.advanced_service import JOB_ADVANCED, KIND_ADVANCED
from clipforge.hero.probe import probe_hero
from clipforge.hero.treatment_policy import evaluate_treatment_policy
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import SourceWorkspace
from clipforge.publish.errors import EXTERNAL_PUBLISHING, PublishError
from clipforge.qa.service import KIND_QA
from clipforge.review.service import effective_review
from clipforge.schemas.advanced import (
    AdvancedHeroCacheRecord,
    AdvancedHeroDraftOutput,
    AdvancedHeroDraftSetDocument,
    AdvancedHeroPlanDocument,
    AdvancedHeroRenderInput,
    advanced_fingerprint,
)
from clipforge.schemas.direction import DirectionDocument
from clipforge.schemas.governance import ReviewDecision, RightsStatus
from clipforge.schemas.hero import ForcedAlignmentDocument
from clipforge.schemas.jobs import JobStatus, QAStatus
from clipforge.schemas.publish import PublishProfile
from clipforge.schemas.qa import QACacheRecord, QASetDocument
from clipforge.schemas.treatment import TreatmentEvidenceBundle
from clipforge.schemas.voice import NarrationAudioArtifact
from clipforge.storage import (
    Database,
    find_artifact,
    get_artifact,
    get_asset_license_record,
    get_job,
    get_source_asset,
    get_source_manifest,
    list_reviews,
)
from clipforge.storage.repository import ArtifactRow
from clipforge.voice.service import _audio_path, _load

_CLEARED = {RightsStatus.OWNED, RightsStatus.LICENSED, RightsStatus.CAMPAIGN_PROVIDED}
_BLOCKED_LICENSES = {None, "unknown", "prohibited", "cc_by_nc"}
KIND_CANDIDATE = "candidate_set_json"
KIND_VISUAL = "visual_analysis_json"
KIND_HERO = "hero_draft_set_json"
KIND_ADVANCED_PLAN = "advanced_hero_plan_json"


@dataclass(frozen=True, slots=True)
class DeliveryFacts:
    """Bindings gathered before any package bytes are copied."""

    project_id: str
    source_asset_id: str
    source_sha256: str
    source_duration_us: int
    candidate_id: str
    candidate_rank: int
    candidate_set_id: str
    candidate_set_sha256: str
    advanced_set_id: str
    advanced_set_sha256: str
    advanced_artifact_id: str
    advanced_artifact_sha256: str
    advanced_artifact_size: int
    advanced_plan_id: str
    advanced_plan_sha256: str
    alignment_id: str | None
    alignment_sha256: str | None
    qa_set_id: str
    qa_set_sha256: str
    approval_review_id: str
    final_review_id: str
    hero_plan_id: str
    hero_plan_sha256: str
    profile_fingerprint: str
    policy_fingerprint: str
    rights_fingerprint: str
    delivery_manifest_sha256: str
    video_sha256: str
    video_size: int
    output_duration_us: int
    video_codec: str
    audio_codec: str
    caption_mode: str
    caption_cues: tuple[tuple[int, int, str], ...]
    narration_sha256: str | None
    narration_sample_rate: int | None
    narration_channels: int | None
    narration_duration_us: int | None
    narration_provider_id: str | None
    narration_engine_id: str | None
    narration_model_id: str | None
    narration_model_revision: str | None
    narration_script_sha256: str | None
    broll: tuple[tuple[str, str], ...]
    sfx: tuple[tuple[str, str], ...]
    typography: tuple[str, ...]
    diagrams: tuple[str, ...]
    emphasis: tuple[str, ...]
    video_path: Path
    narration_path: Path | None
    workspace: SourceWorkspace
    reframing_strategy: str = "contain"
    reframe_requested: str = "contain"
    reframe_applied: str = "contain"
    reframe_fallback: str = ""
    face_track_id: str = ""
    trajectory_sha256: str = ""
    time_map_sha256: str = ""
    reframe_blocker: str = ""
    narration_voice_id: str | None = None
    narration_model_license: str | None = None
    narration_requested: bool = False
    direction_id: str = ""
    direction_sha256: str = ""
    treatment_fingerprint: str = ""
    treatment_evidence_sha256: str = ""
    treatment_evidence_relative_path: str = ""
    treatment_audio_mix_sha256: str = ""
    style_id: str = "legacy-v1"
    style_fingerprint: str = ""
    safe_region_id: str = "portrait-safe-v1"
    # Creative dependencies are repeated here so final review and local
    # delivery cannot reuse an approval after a direction-layer dependency
    # changes. These mirror the bound Advanced Hero plan fields.
    preset_id: str = ""
    pilot_sha256: str = ""
    motion_recipe_ids: tuple[str, ...] = field(default_factory=tuple)
    motion_catalog_sha256: str = ""
    knowledge_context_id: str = ""
    knowledge_release_id: str = ""
    knowledge_context_sha256: str = ""
    knowledge_decision_trace_id: str = ""
    knowledge_decision_trace_sha256: str = ""


def preflight_delivery(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    candidate_id: str,
    *,
    destination: str = "local",
    include_narration: bool = False,
    narration_artifact_id: str | None = None,
    probe: bool = True,
    require_final: bool = True,
) -> DeliveryFacts:
    """Fail closed before a delivery job exists. ``probe`` is the ffprobe step."""
    if destination != "local":
        raise PublishError(EXTERNAL_PUBLISHING, category="unsupported_destination")
    if include_narration and not narration_artifact_id:
        raise PublishError("narration export requires a narration artifact id", category="artifact_missing")
    root = work_root.resolve()
    profile = PublishProfile()
    try:
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
            manifest = get_source_manifest(connection, source_asset_id)
            license_record = get_asset_license_record(connection, source.license_record_id)
            reviews = list_reviews(connection, source.project_id)
    except StorageError as exc:
        raise PublishError("source does not exist", category="source_changed") from exc
    if license_record.status not in _CLEARED:
        raise PublishError(
            f"source rights status is {license_record.status.value}",
            category="rights_blocked",
        )
    _confine_evidence(root, license_record.evidence_uri)
    source_path = _source_file(root, source.uri)
    live_sha = sha256_file(source_path)
    live_size = source_path.stat().st_size
    if live_sha != manifest.content_sha256 or live_size != manifest.size_bytes:
        raise PublishError("source hash does not match the stored manifest", category="source_changed")
    workspace = SourceWorkspace(root, source.project_id, source_asset_id)
    document, manifest_path, manifest_sha, manifest_size = _advanced_document(database, workspace)
    if document.source_sha256 != manifest.content_sha256:
        raise PublishError("advanced Hero source hash does not match the source", category="source_changed")
    draft = next((item for item in document.drafts if item.candidate_id == candidate_id), None)
    if draft is None:
        raise PublishError(
            "selected candidate is not in the current advanced Hero set", category="candidate_missing"
        )
    _require_current(
        database, source.project_id, source_asset_id, KIND_CANDIDATE, document.candidate_set_artifact_id
    )
    candidate_sha = _hash_named(root, database, source.project_id, source_asset_id, KIND_CANDIDATE)
    if candidate_sha != document.candidate_set_sha256:
        raise PublishError("candidate set hash changed", category="artifact_changed")
    if candidate_id not in _candidate_ids(root, database, source.project_id, source_asset_id):
        raise PublishError("candidate is not in the current candidate set", category="candidate_missing")
    _require_current(
        database,
        source.project_id,
        source_asset_id,
        KIND_VISUAL,
        document.visual_analysis_id,
        root=root,
        document_id_field="analysis_id",
    )
    visual_sha = _hash_named(root, database, source.project_id, source_asset_id, KIND_VISUAL)
    if visual_sha != document.visual_analysis_sha256:
        raise PublishError("visual analysis hash changed", category="artifact_changed")
    _require_current(database, source.project_id, source_asset_id, KIND_HERO, document.hero_artifact_id)
    plan = _plan(root, workspace, draft, document)
    _reject_plan_text(plan)
    reframe = _reframe_binding(workspace, plan, visual_sha, manifest.content_sha256)
    alignment_id, alignment_sha, cues = _alignment(
        root,
        workspace,
        draft,
        project_id=source.project_id,
        source_asset_id=source_asset_id,
        source_sha256=manifest.content_sha256,
    )
    _hero_plan(root, workspace, draft)
    video = _video(root, manifest_path, draft)
    input_path = video.parent / "render-input.json"
    if draft.editorial_arc_id:
        if input_path.is_symlink() or not input_path.is_file():
            raise PublishError("editorial render input is missing or unsafe", category="artifact_changed")
        if sha256_file(input_path) != draft.render_input_sha256:
            raise PublishError("editorial render input hash changed", category="artifact_changed")
    _reject_render_strategy(video.parent / "render-input.json", workspace, plan, reframe)
    if probe:
        try:
            probe_hero(video, expected_duration_us=draft.output_duration_us)
        except MediaError as exc:
            raise PublishError(_clean(root, exc), category="artifact_changed") from exc
    broll, sfx = _assets(database, workspace, root, plan)
    narration = _narration(
        database,
        root,
        source.project_id,
        source_asset_id,
        include_narration=include_narration,
        narration_artifact_id=narration_artifact_id,
        probe=probe,
    )
    _require_candidate_approval(database, source.project_id, source_asset_id, candidate_id, reviews)
    artifact = _advanced_artifact(database, root, source.project_id, source_asset_id, manifest_sha)
    approval_id = _approval(
        reviews,
        artifact.artifact_id,
        candidate_id,
        hero_artifact_id=document.hero_artifact_id,
    )
    qa_set_id, qa_sha = _qa(
        database,
        workspace,
        root,
        source.project_id,
        source_asset_id,
        artifact,
        draft.advanced_plan_sha256,
    )
    narration_path, narration_doc = narration
    rights_fingerprint = hashlib.sha256(license_record.status.value.encode("utf-8")).hexdigest()
    policy_fingerprint = hashlib.sha256(f"{profile.fingerprint()}:{qa_sha}".encode()).hexdigest()
    delivery_sha = _existing_delivery_sha(database, root, source.project_id, source_asset_id)
    from clipforge.review.final_gate import evidence_for_facts, require_final_approval

    draft_facts = DeliveryFacts(
        project_id=source.project_id,
        source_asset_id=source_asset_id,
        source_sha256=manifest.content_sha256,
        source_duration_us=manifest.canonical_duration_us,
        candidate_id=candidate_id,
        candidate_rank=draft.rank,
        candidate_set_id=document.candidate_set_artifact_id,
        candidate_set_sha256=document.candidate_set_sha256,
        advanced_set_id=document.advanced_set_id,
        advanced_set_sha256=manifest_sha,
        advanced_artifact_id=artifact.artifact_id,
        advanced_artifact_sha256=manifest_sha,
        advanced_artifact_size=manifest_size,
        advanced_plan_id=plan.plan_id,
        advanced_plan_sha256=draft.advanced_plan_sha256,
        direction_id=plan.direction_id,
        direction_sha256=plan.direction_sha256,
        treatment_fingerprint=plan.treatment_fingerprint,
        treatment_evidence_sha256=plan.treatment_evidence_sha256,
        treatment_evidence_relative_path=plan.treatment_evidence_relative_path,
        treatment_audio_mix_sha256=(
            advanced_fingerprint(plan.treatment_audio_mix.model_dump(mode="json"))
            if plan.treatment_audio_mix is not None
            else ""
        ),
        style_id=plan.style_id,
        style_fingerprint=plan.style_fingerprint,
        safe_region_id=plan.safe_region_id,
        preset_id=plan.preset_id,
        pilot_sha256=plan.pilot_sha256,
        motion_recipe_ids=tuple(plan.motion_recipe_ids),
        motion_catalog_sha256=plan.motion_catalog_sha256,
        knowledge_context_id=plan.knowledge_context_id,
        knowledge_release_id=plan.knowledge_release_id,
        knowledge_context_sha256=plan.knowledge_context_sha256,
        knowledge_decision_trace_id=plan.knowledge_decision_trace_id,
        knowledge_decision_trace_sha256=plan.knowledge_decision_trace_sha256,
        alignment_id=alignment_id,
        alignment_sha256=alignment_sha,
        qa_set_id=qa_set_id,
        qa_set_sha256=qa_sha,
        approval_review_id=approval_id,
        final_review_id="",
        hero_plan_id=draft.hero_plan_id,
        hero_plan_sha256=draft.hero_plan_sha256,
        profile_fingerprint=profile.fingerprint(),
        policy_fingerprint=policy_fingerprint,
        rights_fingerprint=rights_fingerprint,
        delivery_manifest_sha256=delivery_sha,
        video_sha256=draft.preview_sha256,
        video_size=draft.preview_size_bytes,
        output_duration_us=draft.output_duration_us,
        video_codec="h264",
        audio_codec="aac",
        caption_mode="authoritative" if cues else "embedded_or_unavailable",
        caption_cues=cues,
        narration_sha256=None if narration_doc is None else narration_doc.audio_sha256,
        narration_sample_rate=None if narration_doc is None else narration_doc.sample_rate,
        narration_channels=None if narration_doc is None else narration_doc.channels,
        narration_duration_us=None if narration_doc is None else narration_doc.duration_us,
        narration_provider_id=None if narration_doc is None else narration_doc.provider_id,
        narration_engine_id=None if narration_doc is None else narration_doc.engine_id,
        narration_model_id=None if narration_doc is None else narration_doc.model_id,
        narration_model_revision=None if narration_doc is None else narration_doc.model_revision,
        narration_script_sha256=None if narration_doc is None else narration_doc.script_sha256,
        narration_voice_id=None if narration_doc is None else narration_doc.voice_profile_id,
        narration_model_license=(
            None
            if narration_doc is None or narration_doc.model_license is None
            else narration_doc.model_license
        ),
        narration_requested=include_narration,
        broll=broll,
        sfx=sfx,
        typography=tuple(event.text for event in plan.typography),
        diagrams=tuple(event.payload.kind for event in plan.diagrams),
        emphasis=tuple(event.text for event in plan.emphasis),
        video_path=video,
        narration_path=narration_path,
        workspace=workspace,
        reframing_strategy=reframe.applied,
        reframe_requested=reframe.requested,
        reframe_applied=reframe.applied,
        reframe_fallback=reframe.fallback,
        face_track_id=reframe.track_id,
        trajectory_sha256=reframe.trajectory_sha256,
        time_map_sha256=reframe.time_map_sha256,
        reframe_blocker=reframe.blocker,
    )
    evidence = evidence_for_facts(draft_facts)
    final_id = ""
    if require_final:
        final_id = require_final_approval(database, root, draft_facts, reviews, evidence)
    if not final_id:
        return draft_facts
    return replace(draft_facts, final_review_id=final_id)


def cache_fingerprint(facts: DeliveryFacts) -> str:
    """Input identity. Output hashes are checked against the stored package, not this key."""
    body = {
        "advanced_artifact_sha256": facts.advanced_artifact_sha256,
        "advanced_artifact_size_bytes": facts.advanced_artifact_size,
        "advanced_set_id": facts.advanced_set_id,
        "advanced_set_sha256": facts.advanced_set_sha256,
        "alignment_sha256": facts.alignment_sha256 or "",
        "approval_review_id": facts.approval_review_id,
        "final_review_id": facts.final_review_id,
        "candidate_id": facts.candidate_id,
        "candidate_set_id": facts.candidate_set_id,
        "candidate_set_sha256": facts.candidate_set_sha256,
        "destination": "local",
        "narration_sha256": facts.narration_sha256 or "",
        "plan_sha256": facts.advanced_plan_sha256,
        "profile_fingerprint": facts.profile_fingerprint,
        "direction_id": facts.direction_id,
        "direction_sha256": facts.direction_sha256,
        "treatment_fingerprint": facts.treatment_fingerprint,
        "treatment_evidence_sha256": facts.treatment_evidence_sha256,
        "treatment_evidence_relative_path": facts.treatment_evidence_relative_path,
        "treatment_audio_mix_sha256": facts.treatment_audio_mix_sha256,
        "style_id": facts.style_id,
        "style_fingerprint": facts.style_fingerprint,
        "safe_region_id": facts.safe_region_id,
        "preset_id": facts.preset_id,
        "pilot_sha256": facts.pilot_sha256,
        "motion_recipe_ids": list(facts.motion_recipe_ids),
        "motion_catalog_sha256": facts.motion_catalog_sha256,
        "knowledge_context_id": facts.knowledge_context_id,
        "knowledge_release_id": facts.knowledge_release_id,
        "knowledge_context_sha256": facts.knowledge_context_sha256,
        "knowledge_decision_trace_id": facts.knowledge_decision_trace_id,
        "knowledge_decision_trace_sha256": facts.knowledge_decision_trace_sha256,
        "qa_set_id": facts.qa_set_id,
        "qa_set_sha256": facts.qa_set_sha256,
        "reframing_strategy": facts.reframing_strategy,
        "reframe_requested": facts.reframe_requested,
        "reframe_applied": facts.reframe_applied,
        "reframe_fallback": facts.reframe_fallback,
        "audio_policy": "advanced-audio-mix-v1|-16|-1.5|11",
        "source_sha256": facts.source_sha256,
        "time_map_sha256": facts.time_map_sha256,
        "trajectory_sha256": facts.trajectory_sha256,
        "video_sha256": facts.video_sha256,
        "video_size_bytes": facts.video_size,
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class _ReframeBinding:
    requested: str
    applied: str
    fallback: str
    track_id: str
    trajectory_sha256: str
    time_map_sha256: str
    blocker: str


def _reframe_binding(
    workspace: SourceWorkspace,
    plan: AdvancedHeroPlanDocument,
    visual_sha256: str,
    source_sha256: str,
) -> _ReframeBinding:
    """Contain needs no face evidence. face_follow must match the stored trajectory."""
    if plan.reframing_strategy in {"contain", "center_crop"}:
        stored_map = getattr(plan, "time_map_sha256", "")
        map_hash = stored_map if isinstance(stored_map, str) else ""
        return _ReframeBinding(plan.reframing_strategy, plan.reframing_strategy, "", "", "", map_hash, "")
    if plan.reframing_strategy != "face_follow":
        raise PublishError(
            f"reframing strategy {plan.reframing_strategy} is not supported",
            category="artifact_changed",
        )
    from clipforge.schemas.reframe import ReframePlanDocument

    path = workspace.reframe_plan_file(plan.candidate_id)
    if path.is_symlink():
        raise PublishError("visual analysis path is a symlink", category="unsafe_path")
    if not path.is_file():
        raise PublishError("face_follow plan is missing", category="visual_analysis_missing")
    try:
        document = ReframePlanDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PublishError("face_follow plan could not be read", category="visual_analysis_missing") from exc
    if document.requested_strategy == "face_follow" and document.applied_strategy != "face_follow":
        reason = document.fallback_reason or "face_follow_requires_one_track"
        raise PublishError(reason, category=reason)
    if document.source_sha256 != source_sha256 or document.visual_analysis_sha256 != visual_sha256:
        raise PublishError("visual analysis hash changed", category="visual_analysis_stale")
    if document.trajectory is None or document.trajectory.digest() != document.trajectory_sha256:
        raise PublishError("trajectory hash does not match", category="visual_analysis_stale")
    if document.time_map_sha256 != plan.time_map_sha256:
        raise PublishError("time map hash changed", category="time_map_stale")
    duration_us = plan.windows[-1].output_end_us if plan.windows else 0
    from clipforge.hero.reframe import windows_follow_trajectory

    if not windows_follow_trajectory(document, list(plan.windows), duration_us):
        raise PublishError("rendered crop does not match the trajectory", category="visual_analysis_stale")
    return _ReframeBinding(
        document.requested_strategy,
        document.applied_strategy,
        document.fallback_reason,
        document.face_track_id,
        document.trajectory_sha256,
        document.time_map_sha256,
        "",
    )


def _reject_render_strategy(
    path: Path,
    workspace: SourceWorkspace,
    plan: AdvancedHeroPlanDocument,
    reframe: _ReframeBinding,
) -> None:
    if path.is_symlink():
        raise PublishError("advanced render input is a symlink", category="unsafe_path")
    if not path.is_file():
        if reframe.applied == "face_follow":
            raise PublishError("advanced render input is missing", category="artifact_changed")
        return
    from pydantic import ValidationError

    from clipforge.hero.reframe import windows_follow_trajectory
    from clipforge.schemas.reframe import ReframePlanDocument

    try:
        rendered = AdvancedHeroRenderInput.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise PublishError("advanced render input could not be read", category="artifact_changed") from exc
    if rendered.reframing_strategy != plan.reframing_strategy or rendered.reframing_strategy != reframe.applied:
        raise PublishError("render used a different reframing strategy", category="stale_final_review")
    if plan.direction_id or plan.motion_style is not None:
        if (
            rendered.direction_id != plan.direction_id
            or rendered.direction_sha256 != plan.direction_sha256
            or rendered.treatment_fingerprint != plan.treatment_fingerprint
            or rendered.treatment_evidence_sha256 != plan.treatment_evidence_sha256
            or rendered.style_id != plan.style_id
            or rendered.style_fingerprint != plan.style_fingerprint
            or rendered.safe_region_id != plan.safe_region_id
        ):
            raise PublishError("motion direction changed", category="stale_final_review")
        if plan.motion_style is not None and rendered.motion_style != plan.motion_style:
            raise PublishError("motion style recipe changed", category="stale_final_review")
        if plan.treatment_evidence_sha256:
            if not plan.treatment_evidence_relative_path:
                raise PublishError("treatment evidence bundle path is missing", category="stale_final_review")
            bundle_path = confine_work_path(
                workspace.root, plan.treatment_evidence_relative_path, label="treatment evidence bundle"
            )
            if (
                bundle_path.is_symlink()
                or not bundle_path.is_file()
                or sha256_file(bundle_path) != plan.treatment_evidence_sha256
            ):
                raise PublishError(
                    "treatment evidence bundle is missing or stale", category="stale_final_review"
                )
            try:
                bundle = TreatmentEvidenceBundle.model_validate_json(bundle_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValidationError, ValueError) as exc:
                raise PublishError(
                    "treatment evidence bundle is invalid", category="stale_final_review"
                ) from exc
            if (
                bundle.direction_id != plan.direction_id
                or bundle.direction_sha256 != plan.direction_sha256
                or bundle.treatment_fingerprint != plan.treatment_fingerprint
            ):
                raise PublishError(
                    "treatment evidence bundle is bound to a different direction", category="stale_final_review"
                )
        direction_path = (
            workspace.advanced_review_direction_file(plan.candidate_id)
            if plan.hero_review_status == "pending"
            else workspace.direction_file(plan.candidate_id)
        )
        if direction_path.is_symlink() or not direction_path.is_file():
            raise PublishError("direction is missing", category="stale_final_review")
        try:
            direction = DirectionDocument.model_validate_json(direction_path.read_text(encoding="utf-8"))
            selected = next(
                item for item in direction.options if item.option_id == direction.selected_option_id
            )
            if direction.direction_recipe_version in {"direction-v3", "direction-v4"}:
                from clipforge.editorial.presets import PresetCatalog

                policy = PresetCatalog.load().find(direction.preset_id or "clean_explainer").treatment_policy
                errors = [
                    item for item in evaluate_treatment_policy(selected, policy) if item.severity == "error"
                ]
                if errors:
                    raise PublishError(
                        f"treatment policy failed: {errors[0].code}", category="stale_final_review"
                    )
        except PublishError:
            raise
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            raise PublishError("direction could not be validated", category="stale_final_review") from exc
    if reframe.applied != "face_follow":
        return
    if rendered.trajectory_sha256 != reframe.trajectory_sha256 or not rendered.trajectory_sha256:
        raise PublishError("trajectory hash does not match", category="visual_analysis_stale")
    if rendered.time_map_sha256 != reframe.time_map_sha256 or rendered.time_map_sha256 != plan.time_map_sha256:
        raise PublishError("time map hash changed", category="time_map_stale")
    if rendered.source_sha256 != plan.source_sha256:
        raise PublishError("source hash changed", category="source_changed")
    if rendered.profile_fingerprint != plan.profile_fingerprint:
        raise PublishError("profile fingerprint changed", category="artifact_changed")
    duration_us = plan.windows[-1].output_end_us if plan.windows else 0
    if rendered.output_duration_us != duration_us:
        raise PublishError("render duration does not match the time map", category="time_map_stale")
    if len(rendered.windows) != len(plan.windows):
        raise PublishError("render trajectory does not match the plan", category="visual_analysis_stale")
    for rendered_window, planned in zip(rendered.windows, plan.windows, strict=True):
        if (
            rendered_window.output_start_us != planned.output_start_us
            or rendered_window.output_end_us != planned.output_end_us
            or rendered_window.source_x != planned.source_x
            or rendered_window.source_y != planned.source_y
            or rendered_window.source_width != planned.source_width
            or rendered_window.source_height != planned.source_height
            or rendered_window.frame_width != planned.frame_width
            or rendered_window.frame_height != planned.frame_height
            or rendered_window.strategy_id.strategy_id != planned.strategy_id.strategy_id
        ):
            raise PublishError("render trajectory does not match the plan", category="visual_analysis_stale")
    side = workspace.reframe_plan_file(plan.candidate_id)
    try:
        document = ReframePlanDocument.model_validate_json(side.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise PublishError("face_follow plan could not be read", category="visual_analysis_missing") from exc
    if not windows_follow_trajectory(document, list(rendered.windows), duration_us):
        raise PublishError("render trajectory does not match the plan", category="visual_analysis_stale")


def _source_file(root: Path, uri: str) -> Path:
    lowered = uri.lower()
    if "\\" in uri or ".." in uri.split("/"):
        raise PublishError("source path escapes the work root", category="unsafe_path")
    if lowered.startswith(("http://", "https://")):
        raise PublishError("remote source URLs are rejected", category="unsafe_path")
    if not uri.startswith("file:"):
        raise PublishError("source must be a file URI inside the work root", category="unsafe_path")
    raw = path_from_file_uri(uri)
    if raw.is_symlink():
        raise PublishError("source file is a symlink", category="unsafe_path")
    resolved = raw.resolve()
    if not resolved.is_file():
        raise PublishError("source file is missing", category="source_changed")
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        # Referenced campaign media may live outside this work root.
        # Delivery re-hashes the file and does not store its path.
        return resolved
    try:
        return confine_work_path(root, relative.as_posix(), label="source")
    except MediaError as exc:
        raise PublishError(_clean(root, exc), category="unsafe_path") from exc


def _confine_evidence(root: Path, uri: str | None) -> None:
    if uri is None or not uri.strip():
        raise PublishError("rights evidence is missing", category="rights_blocked")
    lowered = uri.lower()
    if lowered.startswith(("http://", "https://")):
        raise PublishError("remote license-evidence URLs are rejected", category="rights_blocked")
    if "\\" in uri or ".." in uri.split("/"):
        raise PublishError("license evidence path escapes the work root", category="unsafe_path")
    try:
        if uri.startswith("file:"):
            confine_file_uri(root, uri, label="license evidence")
        elif uri.startswith("/"):
            raise PublishError("license evidence path is outside the work root", category="unsafe_path")
        else:
            confine_work_path(root, uri, label="license evidence")
    except MediaError as exc:
        raise PublishError(_clean(root, exc), category="unsafe_path") from exc


def _advanced_document(
    database: Database,
    workspace: SourceWorkspace,
) -> tuple[AdvancedHeroDraftSetDocument, Path, str, int]:
    sidecar = workspace.advanced_sidecar()
    if sidecar.is_symlink() or not sidecar.is_file():
        raise PublishError("current advanced Hero set is missing", category="artifact_missing")
    try:
        record = AdvancedHeroCacheRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PublishError("advanced Hero sidecar could not be read", category="artifact_missing") from exc
    manifest = workspace.advanced_run_dir(record.advanced_set_id) / "manifest.json"
    try:
        manifest = confine_work_path(
            workspace.root, manifest.relative_to(workspace.root).as_posix(), label="advanced manifest"
        )
    except MediaError as exc:
        raise PublishError(_clean(workspace.root, exc), category="unsafe_path") from exc
    if manifest.is_symlink() or not manifest.is_file():
        raise PublishError("advanced Hero manifest is missing", category="artifact_missing")
    digest = sha256_file(manifest)
    if digest != record.manifest_sha256 or manifest.stat().st_size != record.manifest_size_bytes:
        raise PublishError(
            "advanced Hero manifest hash does not match the sidecar", category="artifact_changed"
        )
    try:
        document = AdvancedHeroDraftSetDocument.model_validate_json(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PublishError("advanced Hero manifest could not be read", category="artifact_missing") from exc
    if document.advanced_set_id != record.advanced_set_id or document.project_id != record.project_id:
        raise PublishError("advanced Hero sidecar does not match the manifest", category="artifact_changed")
    if document.hero_review_status != "approved":
        raise PublishError(
            "Advanced Hero is an unapproved review draft; approve the current Hero before delivery",
            category="approval_missing",
        )
    with database.connect() as connection:
        row = find_artifact(connection, document.project_id, document.source_asset_id, KIND_ADVANCED)
        if row is None or row.job_id is None:
            raise PublishError("advanced Hero artifact is missing", category="artifact_missing")
        try:
            job = get_job(connection, row.job_id)
        except StorageError as exc:
            raise PublishError("advanced Hero producer job is missing", category="artifact_missing") from exc
    if job.kind != JOB_ADVANCED or job.status is not JobStatus.SUCCEEDED:
        raise PublishError("advanced Hero producer job did not succeed", category="artifact_changed")
    return document, manifest, digest, manifest.stat().st_size


def _advanced_artifact(
    database: Database,
    root: Path,
    project_id: str,
    source_asset_id: str,
    manifest_sha: str,
) -> ArtifactRow:
    with database.connect() as connection:
        row = find_artifact(connection, project_id, source_asset_id, KIND_ADVANCED)
    if row is None:
        raise PublishError("advanced Hero artifact is missing", category="artifact_missing")
    if row.kind != KIND_ADVANCED:
        raise PublishError("advanced Hero artifact kind is wrong", category="artifact_changed")
    path = _artifact_file(root, row)
    if sha256_file(path) != manifest_sha:
        raise PublishError("advanced Hero artifact hash changed", category="artifact_changed")
    return row


def _require_current(
    database: Database,
    project_id: str,
    source_asset_id: str,
    kind: str,
    expected_id: str,
    *,
    root: Path | None = None,
    document_id_field: str | None = None,
) -> ArtifactRow:
    with database.connect() as connection:
        row = find_artifact(connection, project_id, source_asset_id, kind)
    if row is None:
        raise PublishError(f"current {kind} is missing", category="artifact_missing")
    if row.artifact_id == expected_id:
        return row
    if root is not None and document_id_field:
        try:
            payload = json.loads(_artifact_file(root, row).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PublishError(f"current {kind} could not be read", category="artifact_changed") from exc
        if isinstance(payload, dict) and payload.get(document_id_field) == expected_id:
            return row
    raise PublishError(f"current {kind} does not match the advanced Hero set", category="artifact_changed")


def _hash_named(root: Path, database: Database, project_id: str, source_asset_id: str, kind: str) -> str:
    with database.connect() as connection:
        row = find_artifact(connection, project_id, source_asset_id, kind)
    if row is None:
        raise PublishError(f"current {kind} is missing", category="artifact_missing")
    path = _artifact_file(root, row)
    return sha256_file(path)


def _artifact_file(root: Path, row: ArtifactRow) -> Path:
    if not row.uri.startswith("file:") or "\\" in row.uri or ".." in row.uri.split("/"):
        raise PublishError("artifact URI escapes the work root", category="unsafe_path")
    raw = path_from_file_uri(row.uri)
    if raw.is_symlink():
        raise PublishError("artifact file is a symlink", category="unsafe_path")
    try:
        relative = raw.resolve().relative_to(root)
    except ValueError as exc:
        raise PublishError("artifact file is outside the work root", category="unsafe_path") from exc
    try:
        path = confine_work_path(root, relative.as_posix(), label="artifact")
    except MediaError as exc:
        raise PublishError(_clean(root, exc), category="unsafe_path") from exc
    if not path.is_file():
        raise PublishError("artifact file is missing", category="artifact_missing")
    return path


def _candidate_ids(root: Path, database: Database, project_id: str, source_asset_id: str) -> set[str]:
    with database.connect() as connection:
        row = find_artifact(connection, project_id, source_asset_id, KIND_CANDIDATE)
    if row is None:
        raise PublishError("candidate set is missing", category="candidate_missing")
    path = _artifact_file(root, row)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishError("candidate set could not be read", category="candidate_missing") from exc
    found: set[str] = set()
    if isinstance(payload, dict) and isinstance(payload.get("candidates"), list):
        for item in payload["candidates"]:
            if isinstance(item, dict) and isinstance(item.get("candidate_id"), str):
                found.add(item["candidate_id"])
    if not found:
        raise PublishError("candidate set does not name any candidates", category="candidate_missing")
    return found


def _plan(
    root: Path,
    workspace: SourceWorkspace,
    draft: AdvancedHeroDraftOutput,
    document: AdvancedHeroDraftSetDocument,
) -> AdvancedHeroPlanDocument:
    path = workspace.advanced_plan_file(draft.candidate_id)
    try:
        path = confine_work_path(root, path.relative_to(root).as_posix(), label="advanced plan")
    except MediaError as exc:
        raise PublishError(_clean(root, exc), category="unsafe_path") from exc
    if path.is_symlink() or not path.is_file():
        raise PublishError("advanced plan is missing", category="artifact_missing")
    digest = sha256_file(path)
    if digest != draft.advanced_plan_sha256:
        raise PublishError("advanced plan hash changed", category="artifact_changed")
    try:
        plan = AdvancedHeroPlanDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PublishError("advanced plan could not be read", category="artifact_missing") from exc
    if plan.candidate_id != draft.candidate_id or plan.source_asset_id != document.source_asset_id:
        raise PublishError("advanced plan does not match the selected candidate", category="artifact_changed")
    if plan.candidate_set_artifact_id != document.candidate_set_artifact_id:
        raise PublishError("advanced plan candidate set does not match", category="artifact_changed")
    if plan.visual_analysis_id != document.visual_analysis_id:
        raise PublishError("advanced plan visual analysis does not match", category="artifact_changed")
    if plan.alignment_id != draft.alignment_id or plan.alignment_sha256 != draft.alignment_sha256:
        raise PublishError("advanced plan alignment does not match", category="artifact_changed")
    if plan.profile_fingerprint != document.profile_fingerprint:
        raise PublishError("advanced plan profile does not match", category="artifact_changed")
    return plan


def _alignment(
    root: Path,
    workspace: SourceWorkspace,
    draft: AdvancedHeroDraftOutput,
    *,
    project_id: str,
    source_asset_id: str,
    source_sha256: str,
) -> tuple[str | None, str | None, tuple[tuple[int, int, str], ...]]:
    path = (
        workspace.advanced_alignment_file(draft.candidate_id)
        if draft.editorial_arc_id
        else workspace.hero_alignment_file(draft.candidate_id)
    )
    try:
        path = confine_work_path(root, path.relative_to(root).as_posix(), label="alignment")
    except MediaError as exc:
        raise PublishError(_clean(root, exc), category="unsafe_path") from exc
    if path.is_symlink() or not path.is_file():
        raise PublishError("alignment is missing", category="artifact_missing")
    digest = sha256_file(path)
    if digest != draft.alignment_sha256:
        raise PublishError("alignment hash changed", category="artifact_changed")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishError("alignment could not be read", category="artifact_missing") from exc
    if not isinstance(payload, dict) or payload.get("alignment_id") != draft.alignment_id:
        raise PublishError("alignment id does not match the advanced Hero draft", category="artifact_changed")
    cues: tuple[tuple[int, int, str], ...] = ()
    try:
        document = ForcedAlignmentDocument.model_validate(payload)
    except ValueError:
        document = None
    if (
        document is not None
        and document.alignment_id == draft.alignment_id
        and document.candidate_id == draft.candidate_id
    ):
        cues = tuple((word.output_start_us, word.output_end_us, word.text.strip()) for word in document.words)
        if document.alignment_status == "verified_live":
            from clipforge.language.evidence import validate_current_alignment_evidence

            evidence = validate_current_alignment_evidence(
                document=document,
                candidate_id=draft.candidate_id,
                source_asset_id=source_asset_id,
                project_id=project_id,
                source_sha256=source_sha256,
                file_sha256=digest,
            )
            if evidence.status != "verified_live":
                raise PublishError(
                    "alignment evidence is no longer verified",
                    category=evidence.blocker or evidence.status,
                )
    return draft.alignment_id, draft.alignment_sha256, cues


def _reject_plan_text(plan: AdvancedHeroPlanDocument) -> None:
    parts = [event.text for event in plan.typography]
    parts.extend(event.text for event in plan.emphasis)
    parts.extend(str(event.payload.kind) for event in plan.diagrams)
    blob = "\n".join(parts)
    lowered = blob.lower()
    tokens = ("/home/", "/tmp/", "/users/", "https://", "http://", "file:", "..", "\\")
    if any(token in lowered or token in blob for token in tokens):
        raise PublishError("plan text contains an unsafe path", category="unsafe_path")


def _hero_plan(root: Path, workspace: SourceWorkspace, draft: AdvancedHeroDraftOutput) -> None:
    path = workspace.hero_plan_file(draft.candidate_id)
    try:
        path = confine_work_path(root, path.relative_to(root).as_posix(), label="hero plan")
    except MediaError as exc:
        raise PublishError(_clean(root, exc), category="unsafe_path") from exc
    if path.is_symlink() or not path.is_file():
        raise PublishError("hero plan is missing", category="artifact_missing")
    if sha256_file(path) != draft.hero_plan_sha256:
        raise PublishError("hero plan hash changed", category="artifact_changed")


def _video(root: Path, manifest: Path, draft: AdvancedHeroDraftOutput) -> Path:
    if draft.detected_video_codec != "h264" or draft.detected_audio_codec != "aac":
        raise PublishError("advanced Hero codecs are not H.264 and AAC", category="artifact_changed")
    lexical = manifest.parent / draft.preview_relative_path
    try:
        path = confine_work_path(root, lexical.relative_to(root).as_posix(), label="advanced output")
    except MediaError as exc:
        raise PublishError(_clean(root, exc), category="unsafe_path") from exc
    if path.is_symlink():
        raise PublishError("advanced Hero MP4 is a symlink", category="unsafe_path")
    if not path.is_file():
        raise PublishError("advanced Hero MP4 is missing", category="artifact_missing")
    if path.stat().st_size == 0:
        raise PublishError("advanced Hero MP4 is empty", category="corrupt_media")
    if sha256_file(path) != draft.preview_sha256 or path.stat().st_size != draft.preview_size_bytes:
        raise PublishError("advanced Hero MP4 hash does not match the manifest", category="artifact_changed")
    return path


def _assets(
    database: Database,
    workspace: SourceWorkspace,
    root: Path,
    plan: AdvancedHeroPlanDocument,
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    bindings = {item.asset_id: item.sha256 for item in plan.assets}
    broll: list[tuple[str, str]] = []
    for event in plan.broll:
        digest = _one_asset(database, workspace, root, event.asset_id, "graphic", bindings)
        broll.append((event.asset_id, digest))
    sfx: list[tuple[str, str]] = []
    for mix in plan.sfx:
        digest = _one_asset(database, workspace, root, mix.asset_id, "audio", bindings)
        sfx.append((mix.asset_id, digest))
    return tuple(broll), tuple(sfx)


def _one_asset(
    database: Database,
    workspace: SourceWorkspace,
    root: Path,
    asset_id: str,
    kind: str,
    bindings: dict[str, str],
) -> str:
    if asset_id not in bindings:
        raise PublishError(f"advanced asset {asset_id} is not bound", category="artifact_missing")
    try:
        entry, _license, path = require_asset(
            database,
            workspace,
            project_id=workspace.project_id,
            asset_id=asset_id,
            expected_kind=kind,
            work_root=root,
        )
    except MediaError as exc:
        raise _asset_error(root, exc) from exc
    _confine_evidence(root, _license.evidence_uri)
    if entry.file_sha256 != bindings[asset_id] or sha256_file(path) != bindings[asset_id]:
        raise PublishError(f"advanced asset {asset_id} hash changed", category="artifact_changed")
    return entry.file_sha256


def _asset_error(root: Path, exc: MediaError) -> PublishError:
    text = str(exc).lower()
    cleaned = _clean(root, exc)
    if "rights" in text or "remote" in text:
        return PublishError(cleaned, category="rights_blocked")
    if "hash" in text:
        return PublishError(cleaned, category="artifact_changed")
    if "catalog" in text or "missing" in text:
        return PublishError(cleaned, category="artifact_missing")
    return PublishError(cleaned, category="unsafe_path")


def _narration(
    database: Database,
    root: Path,
    project_id: str,
    source_asset_id: str,
    *,
    include_narration: bool,
    narration_artifact_id: str | None,
    probe: bool,
) -> tuple[Path | None, NarrationAudioArtifact | None]:
    if not include_narration:
        return None, None
    if narration_artifact_id is None:
        raise PublishError("narration artifact is missing", category="artifact_missing")
    try:
        document = _load(root, narration_artifact_id)
    except ClipforgeError as exc:
        raise PublishError("narration artifact is missing", category="artifact_missing") from exc
    if document.project_id != project_id or document.source_asset_id != source_asset_id:
        raise PublishError("narration artifact belongs to another source", category="artifact_changed")
    if not document.script_sha256 or not document.consent_record_id:
        raise PublishError("narration consent or script hash is missing", category="rights_blocked")
    if not all((document.provider_id, document.engine_id, document.model_id, document.model_revision)):
        raise PublishError("narration provider identity is missing", category="artifact_missing")
    if document.model_license in _BLOCKED_LICENSES or document.commercial_use in _BLOCKED_LICENSES:
        raise PublishError(
            "narration model rights are not cleared for commercial output", category="rights_blocked"
        )
    if document.model_id.lower().startswith("k2-fsa/"):
        raise PublishError(
            "the default VoiceStudio model is not commercially permitted", category="rights_blocked"
        )
    path = _audio_path(root, narration_artifact_id)
    if path.is_symlink():
        raise PublishError("narration audio is a symlink", category="unsafe_path")
    if not path.is_file():
        raise PublishError("narration audio is missing", category="artifact_missing")
    try:
        path = confine_work_path(root, path.relative_to(root).as_posix(), label="narration")
    except (MediaError, ValueError) as exc:
        raise PublishError(_clean(root, exc), category="unsafe_path") from exc
    if sha256_file(path) != document.audio_sha256 or path.stat().st_size != document.size_bytes:
        raise PublishError("narration hash changed", category="artifact_changed")
    if probe:
        from clipforge.voice.service import verify_narration

        try:
            verify_narration(database, root, narration_artifact_id)
        except ClipforgeError as exc:
            raise PublishError(_clean(root, exc), category="artifact_changed") from exc
    with database.connect() as connection:
        try:
            row = get_artifact(connection, narration_artifact_id)
        except StorageError as exc:
            raise PublishError("narration artifact is missing", category="artifact_missing") from exc
    if row.kind != "narration_audio" or row.project_id != project_id or row.source_asset_id != source_asset_id:
        raise PublishError("narration artifact is not bound to this source", category="artifact_changed")
    return path, document


def _approval(
    reviews: Sequence[ReviewDecision],
    artifact_id: str,
    candidate_id: str,
    *,
    hero_artifact_id: str = "",
) -> str:
    typed = list(reviews)
    effective = effective_review(typed, artifact_id, candidate_id, subject_kind="hero")
    if effective is None and hero_artifact_id:
        effective = effective_review(typed, hero_artifact_id, candidate_id, subject_kind="hero")
    if effective is None:
        accepted = {artifact_id, hero_artifact_id}
        older = [
            item
            for item in typed
            if item.subject_kind == "hero"
            and item.candidate_id == candidate_id
            and item.artifact_id not in accepted
        ]
        if older:
            raise PublishError(
                "approval is bound to an older advanced Hero artifact", category="approval_stale"
            )
        raise PublishError("approved review is missing", category="approval_missing")
    if effective.decision == "rejected":
        raise PublishError("review decision is rejected", category="approval_rejected")
    if effective.decision == "changes_requested":
        raise PublishError("review decision is changes_requested", category="approval_changes_requested")
    if effective.decision != "approved":
        raise PublishError("review decision is not approved", category="approval_missing")
    return effective.review_id


def _require_candidate_approval(
    database: Database,
    project_id: str,
    source_asset_id: str,
    candidate_id: str,
    reviews: Sequence[ReviewDecision],
) -> None:
    from clipforge.preview.constants import KIND_PREVIEW

    with database.connect() as connection:
        row = find_artifact(connection, project_id, source_asset_id, KIND_PREVIEW)
    if row is None:
        raise PublishError("candidate approval is missing", category="missing_candidate_approval")
    effective = effective_review(list(reviews), row.artifact_id, candidate_id, subject_kind="candidate")
    if effective is None or effective.decision != "approved":
        raise PublishError("candidate approval is missing", category="missing_candidate_approval")


def _existing_delivery_sha(database: Database, root: Path, project_id: str, source_asset_id: str) -> str:
    with database.connect() as connection:
        row = find_artifact(connection, project_id, source_asset_id, "publish_package_json")
    if row is None:
        return ""
    path = path_from_file_uri(row.uri)
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise PublishError("delivery package is missing", category="stale_delivery")
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PublishError("delivery package is outside the work root", category="unsafe_path") from exc
    return sha256_file(path)


def _qa(
    database: Database,
    workspace: SourceWorkspace,
    root: Path,
    project_id: str,
    source_asset_id: str,
    artifact: ArtifactRow,
    plan_sha256: str,
) -> tuple[str, str]:
    with database.connect() as connection:
        row = find_artifact(connection, project_id, source_asset_id, KIND_QA)
        plan_row = find_artifact(connection, project_id, source_asset_id, KIND_ADVANCED_PLAN)
    if row is None:
        raise PublishError("current QA set is missing", category="qa_missing")
    path = _artifact_file(root, row)
    try:
        qa = QASetDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PublishError("QA set could not be read", category="qa_missing") from exc
    sidecar = workspace.qa_sidecar()
    if sidecar.is_symlink() or not sidecar.is_file():
        raise PublishError("QA sidecar is missing", category="qa_missing")
    try:
        record = QACacheRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PublishError("QA sidecar could not be read", category="qa_missing") from exc
    digest = sha256_file(path)
    if digest != record.manifest_sha256 or qa.qa_set_id != record.qa_set_id:
        raise PublishError("QA sidecar does not match the current QA set", category="qa_stale")
    if qa.status is not QAStatus.PASS:
        raise PublishError(f"QA status is {qa.status.value}", category="qa_failed")
    if qa.source_asset_id != source_asset_id or qa.target_artifact_id != artifact.artifact_id:
        raise PublishError("QA is not bound to the current advanced Hero artifact", category="qa_stale")
    if qa.target_artifact_kind != KIND_ADVANCED or qa.target_manifest_sha256 != record.target_manifest_sha256:
        raise PublishError("QA target manifest does not match", category="qa_stale")
    if record.target_artifact_id != artifact.artifact_id:
        raise PublishError("QA sidecar target is stale", category="qa_stale")
    advanced_manifest_sha = sha256_file(_artifact_file(root, artifact))
    if qa.target_manifest_sha256 != advanced_manifest_sha:
        raise PublishError("QA is bound to an older advanced Hero manifest", category="qa_stale")
    if plan_row is not None and plan_row.artifact_id not in qa.provenance.parent_artifact_ids:
        raise PublishError("QA is not bound to the current advanced plan", category="qa_stale")
    if plan_row is not None and sha256_file(_artifact_file(root, plan_row)) != plan_sha256:
        raise PublishError("QA plan hash changed", category="qa_stale")
    if plan_row is not None:
        try:
            plan = AdvancedHeroPlanDocument.model_validate_json(
                _artifact_file(root, plan_row).read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise PublishError(
                "advanced plan could not be read for treatment binding", category="qa_stale"
            ) from exc
        if qa.treatment_fingerprint != plan.treatment_fingerprint:
            raise PublishError("QA treatment fingerprint changed", category="qa_stale")
        if qa.treatment_evidence_sha256 != plan.treatment_evidence_sha256:
            raise PublishError("QA treatment evidence changed", category="qa_stale")
    return qa.qa_set_id, digest


def _clean(root: Path, exc: BaseException) -> str:
    return str(exc).replace(str(root), "work")
