"""Campaign production runs. A verified stage is reused. Publishing stays deferred.

The runner does not call FakeForcedAlignment and does not approve a Hero.
Narration stays on the verified English KittenTTS identity. Other languages
are recorded as unavailable instead of borrowing that artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError

from clipforge.campaign.antoine import CAMPAIGN_ID, inventory_sources, selected_files
from clipforge.campaign.providers import CampaignError
from clipforge.errors import MediaError, StorageError
from clipforge.hero.advanced_assets import confine_file_uri, confine_work_path
from clipforge.language.registry import (
    ENGLISH_ALIGNMENT_CHECKPOINT,
    ENGLISH_ALIGNMENT_MODEL,
    ENGLISH_ALIGNMENT_REVISION,
    ENGLISH_NARRATION_ENGINE,
    ENGLISH_NARRATION_LICENSE,
    ENGLISH_NARRATION_MODEL,
    ENGLISH_NARRATION_REVISION,
    ENGLISH_NARRATION_SCRIPT,
    ENGLISH_NARRATION_SCRIPT_SHA256,
    ENGLISH_NARRATION_VOICE,
    alignment_claim,
    alignment_identity_matches,
    capability_for,
)
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import SourceWorkspace, mkdir_contained, reject_symlink_chain
from clipforge.publish.service import explain_package
from clipforge.review.service import effective_review
from clipforge.schemas.advanced import AdvancedHeroPlanDocument
from clipforge.schemas.campaign import CampaignSource
from clipforge.schemas.campaign_run import (
    STAGES,
    CampaignCandidateRecord,
    CampaignProductionRun,
    CampaignSourceRun,
    CampaignStageRecord,
    RunStatus,
    StageName,
    StageStatus,
)
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.hero import ForcedAlignmentDocument
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.reframe import ReframePlanDocument
from clipforge.schemas.voice import NarrationAudioArtifact
from clipforge.storage import (
    Database,
    find_artifact,
    get_artifact,
    get_job,
    insert_artifact,
    insert_job,
    list_artifacts_for_source,
    list_jobs,
    list_reviews,
    update_job,
)
from clipforge.storage.repository import ArtifactRow

KIND = "campaign_production_run_json"
BROWSER_CONCURRENCY = 1
_NARRATION_SOURCE = "src-before-famous"
_STAGE_KINDS: dict[StageName, str] = {
    "media_prepare": "analysis_proxy",
    "transcribe": "transcript_json",
    "vision": "visual_analysis_json",
    "mine": "candidate_set_json",
    "preview": "rough_preview_set_json",
    "hero_render": "hero_draft_set_json",
    "advanced": "advanced_hero_draft_set_json",
    "qa": "qa_set_json",
    "narration": "narration_audio",
    "delivery": "publish_package_json",
}
_ZERO = "0" * 64
NarrationProbe = Callable[[str, str], None]
PromotionHook = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class SourceBinding:
    """A catalogue id matched to one ingested asset. The path is not stored."""

    source_id: str
    source_asset_id: str
    project_id: str
    source_sha256: str
    rights_state: str


@dataclass(frozen=True, slots=True)
class _Bound:
    source_id: str
    binding: SourceBinding | None
    reason: str | None
    expected_sha256: str


@dataclass(frozen=True, slots=True)
class _Package:
    delivery_id: str
    candidate_id: str
    candidate_rank: int
    approval_review_id: str
    qa_set_id: str
    qa_set_sha256: str
    alignment_id: str | None
    alignment_sha256: str | None
    advanced_artifact_id: str | None
    candidate_set_id: str | None
    manifest_sha256: str
    files_sha256: str
    artifact_id: str
    job_id: str | None
    broll_status: str
    sfx_status: str


@dataclass(frozen=True, slots=True)
class _Reviews:
    ok: bool
    decision: str
    reason: str
    review_id: str | None
    hero_review_id: str | None
    preview_artifact_id: str | None
    hero_artifact_id: str | None


@dataclass(frozen=True, slots=True)
class _Narration:
    artifact_id: str | None
    audio_sha256: str | None
    reason: str
    job_id: str | None = None


def source_may_proceed(rights_state: str) -> bool:
    """An allowed CampaignSource does not wait for another confirmation."""
    return rights_state == "allowed"


def plan_campaign(
    *,
    campaign_id: str = CAMPAIGN_ID,
    source_ids: list[str] | None = None,
    language: str = "en-US",
    narration_enabled: bool = True,
) -> CampaignProductionRun:
    """Describe the run. This does not insert jobs or open a provider socket."""
    chosen = _choose(campaign_id, source_ids)
    capability = capability_for(language)
    claim = alignment_claim(language)
    live_voice = narration_enabled and capability.narration_evidence == "verified_live"
    now = datetime.now(UTC)
    fingerprint = _selection_fingerprint(
        campaign_id,
        [item.source_id for item in chosen],
        language,
        narration_enabled,
    )
    sources = [
        _empty_source(
            item.source_id,
            item.rights_state,
            narration_enabled and item.source_id == _NARRATION_SOURCE,
            claim,
        )
        for item in chosen
    ]
    status: RunStatus
    reason: str
    if any(not source_may_proceed(item.rights_state) for item in chosen):
        status, reason = "blocked", "rights_not_allowed"
    else:
        status, reason = "partial", "planned"
    return CampaignProductionRun(
        campaign_run_id=f"plan-{fingerprint[:16]}",
        project_id="unresolved",
        campaign_id=campaign_id,
        created_at=now,
        completed_at=None,
        source_ids=[item.source_id for item in chosen],
        language=capability.language,
        narration_enabled=narration_enabled,
        voice_id=ENGLISH_NARRATION_VOICE if live_voice else None,
        engine_id=ENGLISH_NARRATION_ENGINE if live_voice else None,
        model_id=ENGLISH_NARRATION_MODEL if live_voice else None,
        model_revision=ENGLISH_NARRATION_REVISION if live_voice else None,
        model_license=ENGLISH_NARRATION_LICENSE if live_voice else None,
        alignment_provider="whisperx" if claim == "whisperx" else "none",
        alignment_language=capability.language,
        alignment_model=ENGLISH_ALIGNMENT_MODEL if claim == "whisperx" else None,
        alignment_revision=ENGLISH_ALIGNMENT_REVISION if claim == "whisperx" else None,
        alignment_checkpoint_sha256=ENGLISH_ALIGNMENT_CHECKPOINT if claim == "whisperx" else None,
        fingerprint=fingerprint,
        sources=sources,
        status=status,
        reason_code=reason,
    )


def run_campaign(
    database: Database,
    work_root: Path,
    *,
    campaign_id: str = CAMPAIGN_ID,
    source_ids: list[str] | None = None,
    language: str = "en-US",
    narration_enabled: bool = True,
    force: bool = False,
    created_by: str = "campaign",
    narration_probe: NarrationProbe | None = None,
    promotion_hook: PromotionHook | None = None,
    invalidation_hook: PromotionHook | None = None,
) -> CampaignProductionRun:
    """Execute or reuse one campaign. A failed source does not erase the others."""
    planned = plan_campaign(
        campaign_id=campaign_id,
        source_ids=source_ids,
        language=language,
        narration_enabled=narration_enabled,
    )
    if planned.reason_code == "rights_not_allowed":
        raise CampaignError("campaign source rights are not allowed", code="rights_not_allowed")
    root = work_root.resolve()
    bound = [_bind_one(database, item.source_id) for item in planned.sources]
    _reject_mixed(bound)
    sources = [
        _execute_source(
            database,
            root,
            planned_source,
            item,
            narration_enabled=narration_enabled and planned_source.source_id == _NARRATION_SOURCE,
            language=language,
            narration_probe=narration_probe,
        )
        for planned_source, item in zip(planned.sources, bound, strict=True)
    ]
    document = _assemble(planned, sources, _project_of(bound))
    if not force:
        cached = _cached_run(root, document.fingerprint)
        if cached is not None and _evidence_current(database, root, cached):
            return cached
    _invalidate_stale(database, root, planned.campaign_id, invalidation_hook)
    _publish(database, root, document, created_by, replace_job=False, promotion_hook=promotion_hook)
    return document


def resume_campaign(
    database: Database,
    work_root: Path,
    campaign_run_id: str,
    *,
    created_by: str = "campaign",
    narration_probe: NarrationProbe | None = None,
    promotion_hook: PromotionHook | None = None,
) -> CampaignProductionRun:
    """Retry sources that are not fully verified. A verified source stays cached."""
    root = work_root.resolve()
    current = _read(root, campaign_run_id)
    bound = [_bind_one(database, item.source_id) for item in current.sources]
    _reject_mixed(bound)
    sources: list[CampaignSourceRun] = []
    changed = False
    for source, item in zip(current.sources, bound, strict=True):
        blocker = reframe_blocker(item, source, root)
        if (
            source.status == "succeeded"
            and _source_current(database, root, current, source, item)
            and blocker is None
        ):
            sources.append(source)
            continue
        changed = True
        sources.append(
            _execute_source(
                database,
                root,
                source,
                item,
                narration_enabled=current.narration_enabled and source.source_id == _NARRATION_SOURCE,
                language=current.language,
                narration_probe=narration_probe,
            )
        )
    if not changed:
        return current
    project_id = current.project_id if current.project_id != "unresolved" else _project_of(bound)
    document = _assemble(current, sources, project_id)
    restored = document.model_copy(
        update={"campaign_run_id": current.campaign_run_id, "created_at": current.created_at}
    )
    document = restored.model_copy(update={"fingerprint": _evidence_fingerprint(restored)})
    _publish(
        database,
        root,
        document,
        created_by,
        replace_job=True,
        promotion_hook=promotion_hook,
    )
    return document


def verify_campaign_run(database: Database, work_root: Path, campaign_run_id: str) -> str:
    """Re-check hashes. This does not render, narrate, or publish."""
    root = work_root.resolve()
    document = _read(root, campaign_run_id)
    if document.status != "succeeded":
        raise CampaignError("campaign run is not succeeded", code="not_succeeded")
    if document.alignment_provider == "whisperx":
        if not document.alignment_revision or not document.alignment_checkpoint_sha256:
            raise CampaignError("alignment identity is missing", code="alignment_missing")
        if not alignment_identity_matches(
            revision=document.alignment_revision,
            checkpoint=document.alignment_checkpoint_sha256,
        ):
            raise CampaignError("alignment model revision changed", code="model_revision_changed")
    bound = [_bind_one(database, item.source_id) for item in document.sources]
    _reject_mixed(bound)
    for source, item in zip(document.sources, bound, strict=True):
        _verify_source(database, root, document, source, item)
    return f"PASS campaign run {document.campaign_run_id}"


def show_campaign_run(work_root: Path, campaign_run_id: str) -> str:
    return _read(work_root.resolve(), campaign_run_id).model_dump_json()


def list_campaign_runs(work_root: Path) -> list[str]:
    base = work_root.resolve() / "campaigns" / "runs"
    if not base.is_dir():
        return []
    found: list[str] = []
    for manifest in sorted(base.glob("*/manifest.json")):
        if manifest.is_symlink() or not manifest.is_file():
            continue
        found.append(manifest.parent.name)
    return found


def _choose(campaign_id: str, source_ids: list[str] | None) -> list[CampaignSource]:
    if campaign_id != CAMPAIGN_ID:
        raise CampaignError("campaign is not in the local catalogue", code="missing_campaign")
    catalogue = {item.source_id: item for item in inventory_sources()}
    chosen_ids = [item.source_id for item in selected_files()] if source_ids is None else list(source_ids)
    if len(chosen_ids) != len(set(chosen_ids)):
        raise CampaignError("duplicate campaign source id", code="duplicate_source")
    chosen = []
    for source_id in sorted(chosen_ids):
        item = catalogue.get(source_id)
        if item is None:
            raise CampaignError("campaign source is not in the catalogue", code="missing_source")
        if item.download_status == "not_selected_for_round_18":
            raise CampaignError("unselected source cannot enter a campaign run", code="not_selected")
        chosen.append(item)
    if not chosen:
        raise CampaignError("campaign run has no sources", code="missing_source")
    return chosen


def _empty_source(source_id: str, rights_state: str, narration: bool, claim: str) -> CampaignSourceRun:
    blocked = not source_may_proceed(rights_state)
    stages: list[CampaignStageRecord] = []
    for stage in STAGES:
        status: StageStatus = "not_run"
        reason = "planned"
        if blocked:
            status, reason = "blocked", "rights_not_allowed"
        elif stage == "narration" and not narration:
            reason = "narration_not_requested"
        elif stage == "align" and claim != "whisperx":
            reason = "alignment_not_claimed"
        stages.append(CampaignStageRecord(stage=stage, status=status, cache_hit=False, reason_code=reason))
    return CampaignSourceRun(
        source_id=source_id,
        source_sha256=_ZERO,
        rights_state=rights_state,
        stages=stages,
        candidates=[],
        status="blocked" if blocked else "partial",
        reason_code="rights_not_allowed" if blocked else "planned",
        cache_status="miss",
    )


def _execute_source(
    database: Database,
    root: Path,
    planned: CampaignSourceRun,
    bound: _Bound,
    *,
    narration_enabled: bool,
    language: str,
    narration_probe: NarrationProbe | None,
) -> CampaignSourceRun:
    if not source_may_proceed(planned.rights_state):
        return _blocked_copy(planned, "rights_not_allowed", bound.expected_sha256)
    if bound.binding is None:
        return _blocked_copy(planned, bound.reason or "missing_source", bound.expected_sha256)
    return _observe(
        database,
        root,
        bound.binding,
        narration_enabled=narration_enabled,
        language=language,
        narration_probe=narration_probe,
    )


def _blocked_copy(planned: CampaignSourceRun, reason: str, source_sha256: str) -> CampaignSourceRun:
    status: RunStatus = "failed" if reason == "source_changed" else "blocked"
    stages = [
        item.model_copy(update={"status": status, "reason_code": reason, "cache_hit": False})
        for item in planned.stages
    ]
    return planned.model_copy(
        update={
            "stages": stages,
            "candidates": [],
            "source_sha256": source_sha256,
            "status": status,
            "reason_code": reason,
            "cache_status": "miss",
            "hero_artifact_id": None,
            "advanced_artifact_id": None,
            "qa_set_id": None,
            "qa_set_sha256": None,
            "delivery_id": None,
            "delivery_manifest_sha256": None,
            "narration_artifact_id": None,
            "narration_audio_sha256": None,
        }
    )


def _observe(
    database: Database,
    root: Path,
    binding: SourceBinding,
    *,
    narration_enabled: bool,
    language: str,
    narration_probe: NarrationProbe | None,
) -> CampaignSourceRun:
    claim = alignment_claim(language)
    narration = _narration(
        database,
        root,
        binding,
        enabled=narration_enabled,
        language=language,
        probe=narration_probe,
    )
    package, package_reason = _package(database, root, binding)
    reviews = _reviews(database, root, binding, package)
    review_decision = reviews.decision
    review_ok = reviews.ok
    stages = [
        _stage(
            database,
            root,
            binding,
            stage,
            package,
            claim=claim,
            narration=narration,
            narration_enabled=narration_enabled,
            review_ok=review_ok,
            package_reason=package_reason,
        )
        for stage in STAGES
    ]
    candidate = None
    if package is not None:
        score, start, end = _candidate_facts(database, root, binding, package.candidate_id)
        candidate = CampaignCandidateRecord(
            candidate_id=package.candidate_id,
            rank=package.candidate_rank,
            score=score,
            selection_reason="candidate bound to the current verified local delivery",
            source_start_us=start,
            source_end_us=end,
            review_id=reviews.review_id,
            review_decision=review_decision,
            preview_artifact_id=reviews.preview_artifact_id,
            hero_review_id=reviews.hero_review_id,
            hero_artifact_id=reviews.hero_artifact_id,
            advanced_artifact_id=package.advanced_artifact_id,
            caption_quality="aligned" if claim == "whisperx" and package.alignment_sha256 else "provisional",
            alignment_status=claim if package.alignment_sha256 else "alignment_not_claimed",
            narration_status=narration.reason if narration_enabled else "narration_not_requested",
            qa_status="pass" if package.qa_set_sha256 else "missing",
            delivery_status="blocked" if package_reason else "succeeded",
        )
    required = [
        item for item in stages if _stage_required(item.stage, narration_enabled=narration_enabled, claim=claim)
    ]
    status: RunStatus
    reason: str
    if package_reason:
        status, reason = "blocked", package_reason
    elif package is None:
        status, reason = "blocked", "missing_artifact"
    elif not review_ok:
        status, reason = "blocked", reviews.reason
    elif all(item.status == "succeeded" for item in required):
        status, reason = "succeeded", "none"
    elif any(item.status == "failed" for item in required):
        status, reason = "failed", next(item.reason_code for item in required if item.status == "failed")
    elif any(item.status == "blocked" for item in required):
        status, reason = "blocked", next(item.reason_code for item in required if item.status == "blocked")
    else:
        status, reason = "partial", "stage_incomplete"
    hero_id = _artifact_id(database, binding, "hero_draft_set_json")
    advanced_id = package.advanced_artifact_id if package is not None else None
    cache_status = _cache_status(stages, status)
    return CampaignSourceRun(
        source_id=binding.source_id,
        source_asset_id=binding.source_asset_id,
        source_sha256=binding.source_sha256,
        rights_state=binding.rights_state,
        stages=stages,
        candidates=[candidate] if candidate is not None else [],
        hero_artifact_id=hero_id,
        advanced_artifact_id=advanced_id,
        qa_set_id=None if package is None else package.qa_set_id,
        qa_set_sha256=None if package is None else package.qa_set_sha256,
        delivery_id=None if package is None else package.delivery_id,
        delivery_manifest_sha256=None if package is None else package.manifest_sha256,
        delivery_files_sha256=None if package is None else package.files_sha256,
        narration_artifact_id=narration.artifact_id if narration_enabled else None,
        narration_audio_sha256=narration.audio_sha256 if narration_enabled else None,
        broll_status="absent" if package is None else package.broll_status,
        sfx_status="absent" if package is None else package.sfx_status,
        cache_status=cache_status,
        status=status,
        reason_code=reason,
    )


def _stage_required(stage: StageName, *, narration_enabled: bool, claim: str) -> bool:
    if stage == "narration" and not narration_enabled:
        return False
    return not (stage == "align" and claim != "whisperx")


def _cache_status(stages: list[CampaignStageRecord], status: RunStatus) -> Literal["hit", "miss", "mixed"]:
    if status != "succeeded":
        return "miss"
    succeeded = [item for item in stages if item.status == "succeeded"]
    if succeeded and all(item.cache_hit for item in succeeded):
        return "hit"
    if any(item.cache_hit for item in succeeded):
        return "mixed"
    return "miss"


def _stage(
    database: Database,
    root: Path,
    binding: SourceBinding,
    stage: StageName,
    package: _Package | None,
    *,
    claim: str,
    narration: _Narration,
    narration_enabled: bool,
    review_ok: bool,
    package_reason: str | None,
) -> CampaignStageRecord:
    if stage == "narration" and not narration_enabled:
        return CampaignStageRecord(
            stage="narration",
            status="not_run",
            cache_hit=False,
            reason_code="narration_not_requested",
        )
    if stage == "narration":
        ok = narration.artifact_id is not None and narration.audio_sha256 is not None
        return CampaignStageRecord(
            stage="narration",
            status="succeeded" if ok else "blocked",
            job_id=narration.job_id,
            artifact_id=narration.artifact_id,
            artifact_sha256=narration.audio_sha256,
            cache_hit=ok,
            reason_code=narration.reason,
        )
    if stage == "source_verify":
        return CampaignStageRecord(
            stage="source_verify",
            status="succeeded",
            cache_hit=True,
            artifact_sha256=binding.source_sha256,
            reason_code="source_hash_matched",
        )
    if stage == "align":
        return _alignment_stage(database, root, binding, package, claim)
    if stage == "ingest":
        return CampaignStageRecord(stage="ingest", status="succeeded", cache_hit=True, reason_code="reused")
    if stage == "review":
        if package is None or not review_ok:
            return CampaignStageRecord(
                stage="review",
                status="blocked",
                cache_hit=False,
                reason_code="review_missing",
            )
        return CampaignStageRecord(
            stage="review",
            status="succeeded",
            cache_hit=True,
            reason_code="existing_human_review",
        )
    if stage == "hero_plan":
        hero = _artifact_row(database, binding, "hero_draft_set_json")
        if hero is None:
            return CampaignStageRecord(
                stage="hero_plan",
                status="blocked",
                cache_hit=False,
                reason_code="missing_artifact",
            )
        problem = _stage_producer_problem(database, hero, binding, "hero_draft_set_json")
        if problem:
            return _blocked_stage("hero_plan", problem, hero)
        return CampaignStageRecord(
            stage="hero_plan",
            status="succeeded",
            job_id=hero.job_id,
            artifact_id=hero.artifact_id,
            cache_hit=True,
            reason_code="reused",
        )
    kind = _STAGE_KINDS.get(stage)
    row = _row_for_stage(database, root, binding, stage, package) if kind is not None else None
    if stage == "delivery":
        if package_reason:
            return CampaignStageRecord(
                stage="delivery",
                status="blocked",
                cache_hit=False,
                reason_code=package_reason,
            )
        if package is None or row is None:
            return CampaignStageRecord(
                stage="delivery",
                status="blocked",
                cache_hit=False,
                reason_code="missing_artifact",
            )
        problem = _stage_producer_problem(database, row, binding, "publish_package_json")
        if problem:
            return _blocked_stage("delivery", problem, row)
        return CampaignStageRecord(
            stage="delivery",
            status="succeeded",
            job_id=row.job_id,
            artifact_id=row.artifact_id,
            artifact_sha256=package.manifest_sha256,
            cache_hit=True,
            reason_code="local_delivery",
        )
    if row is None:
        return CampaignStageRecord(
            stage=stage,
            status="blocked",
            cache_hit=False,
            reason_code="missing_artifact",
        )
    digest, reason = _hash_uri(root, row.uri)
    if digest is None:
        return CampaignStageRecord(
            stage=stage,
            status="blocked",
            job_id=row.job_id,
            artifact_id=row.artifact_id,
            cache_hit=False,
            reason_code=reason,
        )
    problem = _stage_producer_problem(database, row, binding, kind or row.kind)
    if problem:
        return _blocked_stage(stage, problem, row)
    return CampaignStageRecord(
        stage=stage,
        status="succeeded",
        job_id=row.job_id,
        artifact_id=row.artifact_id,
        artifact_sha256=digest,
        cache_hit=True,
        reason_code="reused",
    )


def _row_for_stage(
    database: Database,
    root: Path,
    binding: SourceBinding,
    stage: StageName,
    package: _Package | None,
) -> ArtifactRow | None:
    if stage == "qa" and package is not None:
        return _row_with_hash(database, root, binding, "qa_set_json", package.qa_set_sha256)
    if stage == "advanced" and package is not None and package.advanced_artifact_id:
        return _row_with_id(database, binding, package.advanced_artifact_id)
    if stage == "mine" and package is not None and package.candidate_set_id:
        return _row_with_id(database, binding, package.candidate_set_id)
    if stage == "delivery" and package is not None:
        return _row_with_id(database, binding, package.artifact_id)
    kind = _STAGE_KINDS.get(stage)
    if kind is None:
        return None
    return _artifact_row(database, binding, kind)


def _narration(
    database: Database,
    root: Path,
    binding: SourceBinding,
    *,
    enabled: bool,
    language: str,
    probe: NarrationProbe | None,
) -> _Narration:
    if not enabled:
        return _Narration(None, None, "narration_not_requested")
    capability = capability_for(language)
    if capability.narration_evidence != "verified_live":
        return _Narration(None, None, capability.narration_reason)
    accepted: list[NarrationAudioArtifact] = []
    reasons: list[str] = []
    with database.connect() as connection:
        rows = [
            row
            for row in list_artifacts_for_source(connection, binding.project_id, binding.source_asset_id)
            if row.kind == "narration_audio"
        ]
    for row in rows:
        decision = _classify_narration(database, root, binding, row)
        if isinstance(decision, NarrationAudioArtifact):
            accepted.append(decision)
        else:
            reasons.append(decision)
    if accepted:
        chosen = sorted(accepted, key=lambda item: item.artifact_id)[0]
        return _Narration(chosen.artifact_id, chosen.audio_sha256, "verified_live", chosen.provenance.job_id)
    if probe is not None and not reasons:
        try:
            probe(language, ENGLISH_NARRATION_SCRIPT)
        except CampaignError as exc:
            if exc.code == "provider_timeout":
                return _Narration(None, None, "provider_timeout")
            return _Narration(None, None, "provider_unavailable")
    for reason in (
        "narration_changed",
        "zero_byte_audio",
        "model_revision_changed",
        "voice_changed",
        "script_changed",
        "license_blocked",
        "symlink",
    ):
        if reason in reasons:
            return _Narration(None, None, reason)
    return _Narration(None, None, "provider_unavailable")


def _classify_narration(
    database: Database,
    root: Path,
    binding: SourceBinding,
    row: ArtifactRow,
) -> NarrationAudioArtifact | str:
    relative_sidecar = f"voice/audio/{row.artifact_id}.json"
    relative_wav = f"voice/audio/{row.artifact_id}.wav"
    try:
        from clipforge.hero.advanced_assets import confine_work_path

        sidecar = confine_work_path(root, relative_sidecar, label="narration")
        wav = confine_work_path(root, relative_wav, label="narration")
    except MediaError as exc:
        if "symlink" in str(exc):
            return "symlink"
        return "traversal"
    if sidecar.is_symlink() or wav.is_symlink():
        return "symlink"
    if not sidecar.is_file():
        return "provider_unavailable"
    try:
        document = NarrationAudioArtifact.model_validate_json(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError):
        return "provider_unavailable"
    blocked_license = document.model_license in {"unknown", "prohibited", "cc_by_nc"}
    if document.model_id.lower().startswith("k2-fsa/") or blocked_license:
        return "license_blocked"
    if document.commercial_use in {"unknown", "prohibited", "cc_by_nc"}:
        return "license_blocked"
    identity = (
        document.engine_id == ENGLISH_NARRATION_ENGINE
        and document.model_id == ENGLISH_NARRATION_MODEL
        and document.voice_profile_id == ENGLISH_NARRATION_VOICE
        and document.script_label == ENGLISH_NARRATION_SCRIPT
        and document.script_sha256 == ENGLISH_NARRATION_SCRIPT_SHA256
        and document.language == "en-US"
    )
    same_script = document.script_label == ENGLISH_NARRATION_SCRIPT
    if document.model_revision != ENGLISH_NARRATION_REVISION and same_script:
        return "model_revision_changed"
    if document.voice_profile_id != ENGLISH_NARRATION_VOICE and same_script:
        return "voice_changed"
    script_hash = document.script_sha256 != ENGLISH_NARRATION_SCRIPT_SHA256
    if not same_script or script_hash:
        return "script_changed"
    if document.language != "en-US":
        return "language_changed"
    if not identity:
        return "provider_unavailable"
    if document.project_id != binding.project_id or row.project_id != binding.project_id:
        return "cross_project"
    if document.source_asset_id != binding.source_asset_id or row.source_asset_id != binding.source_asset_id:
        return "cross_source"
    producer = _producer_problem(database, row.job_id, binding.project_id)
    if producer:
        return producer
    if not wav.is_file():
        return "narration_changed"
    if wav.stat().st_size == 0:
        return "zero_byte_audio"
    if sha256_file(wav) != document.audio_sha256:
        return "narration_changed"
    return document


def _bind_one(database: Database, source_id: str) -> _Bound:
    rights = {item.source_id: item.rights_state for item in inventory_sources()}
    rights_state = str(rights.get(source_id, "unknown"))
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT source_asset_id, project_id, content_sha256, original_filename
            FROM source_manifests
            WHERE original_filename = ?
            """,
            (f"{source_id}.mp4",),
        ).fetchone()
        uri = None
        if row is not None:
            found = connection.execute(
                "SELECT uri FROM source_assets WHERE source_asset_id = ?",
                (str(row["source_asset_id"]),),
            ).fetchone()
            uri = None if found is None else str(found["uri"])
    if row is None or uri is None:
        return _Bound(source_id, None, "missing_source", _ZERO)
    expected = str(row["content_sha256"])
    if not source_may_proceed(rights_state):
        return _Bound(source_id, None, "rights_not_allowed", expected)
    lowered = uri.lower()
    if lowered.startswith(("http://", "https://", "s3://", "ftp://", "ftps://")):
        return _Bound(source_id, None, "remote_source", expected)
    if "\\" in uri or ".." in uri.split("/"):
        return _Bound(source_id, None, "traversal", expected)
    if not lowered.startswith("file:"):
        return _Bound(source_id, None, "remote_source", expected)
    path = path_from_file_uri(uri)
    try:
        reject_symlink_chain(path)
    except MediaError:
        return _Bound(source_id, None, "symlink", expected)
    if not path.is_file():
        return _Bound(source_id, None, "missing_source", expected)
    digest = sha256_file(path)
    if digest != expected:
        return _Bound(source_id, None, "source_changed", digest)
    binding = SourceBinding(
        source_id=source_id,
        source_asset_id=str(row["source_asset_id"]),
        project_id=str(row["project_id"]),
        source_sha256=digest,
        rights_state=rights_state,
    )
    return _Bound(source_id, binding, None, digest)


def bind_campaign_source(database: Database, source_id: str) -> _Bound:
    """Re-check one catalogue source. This reads the manifest and does not write."""
    return _bind_one(database, source_id)


def _reject_mixed(bound: list[_Bound]) -> None:
    projects = {item.binding.project_id for item in bound if item.binding is not None}
    if len(projects) > 1:
        raise CampaignError("campaign sources belong to different projects", code="mixed_project")


def _project_of(bound: list[_Bound]) -> str:
    projects = sorted({item.binding.project_id for item in bound if item.binding is not None})
    if len(projects) == 1:
        return projects[0]
    return "unresolved"


def _package(database: Database, root: Path, binding: SourceBinding) -> tuple[_Package | None, str | None]:
    row = _artifact_row(database, binding, "publish_package_json")
    if row is None:
        return None, "delivery_missing"
    if row.project_id != binding.project_id:
        return None, "cross_project"
    if row.source_asset_id != binding.source_asset_id:
        return None, "cross_source"
    producer = _producer_problem(database, row.job_id, binding.project_id)
    manifest = path_from_file_uri(row.uri)
    document, reason = explain_package(root, manifest)
    if document is None:
        return None, reason or "delivery_missing"
    if document.project_id != binding.project_id:
        return None, "cross_project"
    if document.source_asset_id != binding.source_asset_id:
        return None, "cross_source"
    roles = {item.role for item in document.files}
    built = _Package(
        delivery_id=document.delivery_id,
        candidate_id=document.candidate_id,
        candidate_rank=document.candidate_rank,
        approval_review_id=document.approval_review_id,
        qa_set_id=document.qa_set_id,
        qa_set_sha256=document.qa_set_sha256,
        alignment_id=document.alignment_id,
        alignment_sha256=document.alignment_sha256,
        advanced_artifact_id=document.advanced_artifact_id,
        candidate_set_id=document.candidate_set_id,
        manifest_sha256=sha256_file(manifest),
        files_sha256=_files_sha256(document),
        artifact_id=row.artifact_id,
        job_id=row.job_id,
        broll_status="present" if "broll" in roles else "absent",
        sfx_status="present" if "sfx" in roles else "absent",
    )
    if reason:
        return built, reason
    if producer:
        return built, producer
    from clipforge.review.final_gate import package_blocker

    advanced_id = built.advanced_artifact_id or ""
    blocked = package_blocker(
        database,
        root,
        project_id=binding.project_id,
        candidate_id=built.candidate_id,
        advanced_artifact_id=advanced_id,
        qa_set_sha256=built.qa_set_sha256,
        source_sha256=binding.source_sha256,
        delivery_manifest_sha256=built.manifest_sha256,
    )
    return built, blocked


def _files_sha256(document: object) -> str:
    files = getattr(document, "files", [])
    lines = [f"{item.role}:{item.sha256}:{item.size_bytes}" for item in files]
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def _blocked_stage(stage: StageName, reason: str, row: ArtifactRow) -> CampaignStageRecord:
    return CampaignStageRecord(
        stage=stage,
        status="blocked",
        job_id=row.job_id,
        artifact_id=row.artifact_id,
        cache_hit=False,
        reason_code=reason,
    )


def _stage_producer_problem(
    database: Database,
    row: ArtifactRow,
    binding: SourceBinding,
    expected_kind: str,
) -> str | None:
    if row.kind != expected_kind:
        return "artifact_missing"
    if row.project_id != binding.project_id:
        return "cross_project"
    if row.source_asset_id != binding.source_asset_id:
        return "cross_source"
    return _producer_problem(database, row.job_id, binding.project_id)


def _alignment_stage(
    database: Database,
    root: Path,
    binding: SourceBinding,
    package: _Package | None,
    claim: str,
) -> CampaignStageRecord:
    if claim != "whisperx":
        return CampaignStageRecord(
            stage="align",
            status="not_run",
            cache_hit=False,
            reason_code="alignment_not_claimed",
        )
    problem, digest, job_id, alignment_id = _alignment_facts(database, root, binding, package)
    if problem or digest is None:
        return CampaignStageRecord(
            stage="align",
            status="blocked",
            job_id=job_id,
            artifact_id=alignment_id,
            artifact_sha256=digest,
            cache_hit=False,
            reason_code=problem or "alignment_missing",
        )
    return CampaignStageRecord(
        stage="align",
        status="succeeded",
        job_id=job_id,
        artifact_id=alignment_id,
        artifact_sha256=digest,
        cache_hit=True,
        reason_code="whisperx",
    )


def _alignment_facts(
    database: Database,
    root: Path,
    binding: SourceBinding,
    package: _Package | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return problem, file sha256, producer job id, and alignment id."""
    if package is None or not package.alignment_sha256 or not package.alignment_id:
        return "alignment_missing", None, None, None
    relative = (
        f"projects/{binding.project_id}/sources/{binding.source_asset_id}/hero/alignments/"
        f"{package.candidate_id}/alignment.json"
    )
    try:
        path = confine_work_path(root, relative, label="alignment")
    except MediaError as exc:
        code = "symlink" if "symlink" in str(exc) else "alignment_missing"
        return code, None, None, package.alignment_id
    if not path.is_file():
        return "alignment_missing", None, None, package.alignment_id
    digest = sha256_file(path)
    if digest != package.alignment_sha256:
        return "alignment_changed", digest, None, package.alignment_id
    try:
        parsed = ForcedAlignmentDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError):
        return "alignment_changed", digest, None, package.alignment_id
    if parsed.alignment_id != package.alignment_id:
        return "alignment_changed", digest, None, parsed.alignment_id
    if parsed.project_id != binding.project_id:
        return "cross_project", digest, None, parsed.alignment_id
    if parsed.source_asset_id != binding.source_asset_id:
        return "cross_source", digest, None, parsed.alignment_id
    if parsed.model_name != ENGLISH_ALIGNMENT_MODEL or parsed.whisperx_version != ENGLISH_ALIGNMENT_REVISION:
        return "model_revision_changed", digest, None, parsed.alignment_id
    transcript = _artifact_row(database, binding, "transcript_json")
    if transcript is None:
        return "alignment_changed", digest, None, parsed.alignment_id
    transcript_sha, transcript_reason = _hash_uri(root, transcript.uri)
    if transcript_sha is None:
        return transcript_reason, digest, None, parsed.alignment_id
    if transcript_sha != parsed.transcript_sha256:
        return "transcript_changed", digest, None, parsed.alignment_id
    hero = _artifact_row(database, binding, "hero_draft_set_json")
    job_id = parsed.provenance.job_id or (None if hero is None else hero.job_id)
    producer = _producer_problem(database, job_id, binding.project_id)
    if producer == "producer_failed":
        return "alignment_producer_failed", digest, job_id, parsed.alignment_id
    if producer == "producer_missing":
        return "alignment_producer_missing", digest, job_id, parsed.alignment_id
    if producer:
        return producer, digest, job_id, parsed.alignment_id
    return None, digest, job_id, parsed.alignment_id


def _producer_problem(database: Database, job_id: str | None, project_id: str) -> str | None:
    if not job_id:
        return "producer_missing"
    try:
        with database.connect() as connection:
            job = get_job(connection, job_id)
    except StorageError:
        return "producer_missing"
    if job.project_id != project_id:
        return "cross_project"
    if job.status is not JobStatus.SUCCEEDED:
        return "producer_failed"
    return None


def _roles(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    found: set[str] = set()
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("role"), str):
            found.add(str(item["role"]))
    return found


def _text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _sha(value: object) -> str | None:
    if isinstance(value, str) and len(value) == 64:
        return value
    return None


def _reviews(database: Database, root: Path, binding: SourceBinding, package: _Package | None) -> _Reviews:
    empty = _Reviews(False, "not_recorded", "review_missing", None, None, None, None)
    if package is None:
        return empty
    preview = _artifact_row(database, binding, "rough_preview_set_json")
    hero = _artifact_row(database, binding, "hero_draft_set_json")
    if preview is None or hero is None:
        return empty
    preview_producer = _producer_problem(database, preview.job_id, binding.project_id)
    if preview_producer:
        return _Reviews(
            False,
            "not_recorded",
            preview_producer,
            None,
            None,
            preview.artifact_id,
            hero.artifact_id,
        )
    try:
        with database.connect() as connection:
            rows = list_reviews(connection, binding.project_id)
    except StorageError:
        return _Reviews(
            False,
            "malformed_review",
            "malformed_review",
            None,
            None,
            preview.artifact_id,
            hero.artifact_id,
        )
    candidate_review = effective_review(
        rows,
        preview.artifact_id,
        package.candidate_id,
        subject_kind="candidate",
    )
    if candidate_review is None:
        named = [item for item in rows if item.candidate_id == package.candidate_id]
        wrong_subject = [
            item
            for item in named
            if item.artifact_id == preview.artifact_id and item.subject_kind != "candidate"
        ]
        stale = [item for item in named if item.subject_kind == "candidate"]
        if wrong_subject:
            code = "review_subject"
        elif stale:
            code = _review_source(database, stale[0].artifact_id, binding.source_asset_id) or "stale_review"
        else:
            code = "review_missing"
        return _Reviews(False, "not_recorded", code, None, None, preview.artifact_id, hero.artifact_id)
    problem = _review_problem(candidate_review, binding, package.candidate_id, preview.artifact_id, "candidate")
    if problem is None:
        problem = _review_source(database, candidate_review.artifact_id, binding.source_asset_id)
    if problem:
        return _Reviews(
            False,
            candidate_review.decision,
            problem,
            candidate_review.review_id,
            None,
            preview.artifact_id,
            hero.artifact_id,
        )
    latest_advanced = _artifact_row(database, binding, "advanced_hero_draft_set_json")
    if latest_advanced is None or package.advanced_artifact_id != latest_advanced.artifact_id:
        return _Reviews(
            False,
            candidate_review.decision,
            "stale_review",
            candidate_review.review_id,
            None,
            preview.artifact_id,
            hero.artifact_id,
        )
    hero_review, hero_code = _effective_hero_review(
        database,
        rows,
        binding,
        package.candidate_id,
        hero.artifact_id,
        latest_advanced.artifact_id,
    )
    hero_problem = hero_code
    if hero_problem:
        return _Reviews(
            False,
            candidate_review.decision,
            hero_problem,
            candidate_review.review_id,
            None if hero_review is None else hero_review.review_id,
            preview.artifact_id,
            hero.artifact_id,
        )
    if hero_review is None:
        return _Reviews(
            False,
            candidate_review.decision,
            "review_missing",
            candidate_review.review_id,
            None,
            preview.artifact_id,
            hero.artifact_id,
        )
    del root
    return _Reviews(
        True,
        "approved",
        "existing_human_review",
        candidate_review.review_id,
        hero_review.review_id,
        preview.artifact_id,
        hero.artifact_id,
    )


def _effective_hero_review(
    database: Database,
    rows: list[ReviewDecision],
    binding: SourceBinding,
    candidate_id: str,
    hero_artifact_id: str,
    advanced_artifact_id: str,
) -> tuple[ReviewDecision | None, str | None]:
    """Return the newest Hero decision for the current artifact, not the historical package id."""
    typed = rows
    on_hero = effective_review(typed, hero_artifact_id, candidate_id, subject_kind="hero")
    on_advanced = effective_review(typed, advanced_artifact_id, candidate_id, subject_kind="hero")
    chosen = [item for item in (on_hero, on_advanced) if item is not None]
    if chosen:
        review = max(chosen, key=lambda item: (item.created_at, item.review_id))
        problem = _review_problem(review, binding, candidate_id, review.artifact_id or "", "hero")
        if problem is None:
            problem = _review_source(database, review.artifact_id, binding.source_asset_id)
        return review, problem
    named = [
        item
        for item in typed
        if item.candidate_id == candidate_id
        and item.artifact_id in {hero_artifact_id, advanced_artifact_id}
        and item.subject_kind != "final"
    ]
    if any(item.subject_kind != "hero" for item in named):
        return None, "review_subject"
    other_candidate = [
        item
        for item in typed
        if item.subject_kind == "hero" and item.artifact_id in {hero_artifact_id, advanced_artifact_id}
    ]
    if other_candidate:
        return None, "stale_review"
    older = [item for item in typed if item.subject_kind == "hero" and item.candidate_id == candidate_id]
    if older:
        return None, _review_source(database, older[0].artifact_id, binding.source_asset_id) or "stale_review"
    return None, "review_missing"


def _review_source(database: Database, artifact_id: str | None, source_asset_id: str) -> str | None:
    if not artifact_id:
        return "artifact_missing"
    try:
        with database.connect() as connection:
            row = get_artifact(connection, artifact_id)
    except StorageError:
        return "artifact_missing"
    if row.source_asset_id != source_asset_id:
        return "cross_source"
    return None


def _review_problem(
    review: object,
    binding: SourceBinding,
    candidate_id: str,
    artifact_id: str,
    subject: str,
) -> str | None:
    kind = getattr(review, "subject_kind", "")
    decision = getattr(review, "decision", "")
    if kind != subject:
        return "review_subject"
    if getattr(review, "project_id", "") != binding.project_id:
        return "cross_project"
    if getattr(review, "candidate_id", None) != candidate_id:
        return "stale_review"
    if subject == "candidate" and getattr(review, "artifact_id", None) != artifact_id:
        return "stale_review"
    if decision == "rejected":
        return "review_rejected"
    if decision == "changes_requested":
        return "review_changes_requested"
    if decision != "approved":
        return "review_missing"
    return None


def _candidate_facts(
    database: Database,
    root: Path,
    binding: SourceBinding,
    candidate_id: str,
) -> tuple[str, int | None, int | None]:
    row = _artifact_row(database, binding, "candidate_set_json")
    if row is None:
        return "unavailable", None, None
    digest, reason = _hash_uri(root, row.uri)
    if digest is None or reason != "reused":
        return "unavailable", None, None
    try:
        payload = json.loads(path_from_file_uri(row.uri).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "unavailable", None, None
    clips = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(clips, list):
        return "unavailable", None, None
    for clip in clips:
        if not isinstance(clip, dict) or clip.get("candidate_id") != candidate_id:
            continue
        return _score_text(clip.get("creative_score")), *_span(clip.get("time_map"))
    return "unavailable", None, None


def _score_text(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "unavailable"
    if value < 0 or value > 1:
        return "unavailable"
    return f"{float(value):.6f}"


def _span(time_map: object) -> tuple[int | None, int | None]:
    if not isinstance(time_map, dict):
        return None, None
    segments = time_map.get("segments")
    if not isinstance(segments, list):
        return None, None
    starts: list[int] = []
    ends: list[int] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = segment.get("source_start_us")
        end = segment.get("source_end_us")
        if isinstance(start, int) and isinstance(end, int) and not isinstance(start, bool) and end > start:
            starts.append(start)
            ends.append(end)
    if not starts:
        return None, None
    return min(starts), max(ends)


def _artifact_row(database: Database, binding: SourceBinding, kind: str) -> ArtifactRow | None:
    with database.connect() as connection:
        return find_artifact(connection, binding.project_id, binding.source_asset_id, kind)


def _artifact_id(database: Database, binding: SourceBinding, kind: str) -> str | None:
    row = _artifact_row(database, binding, kind)
    if row is None:
        return None
    return row.artifact_id


def _row_with_id(database: Database, binding: SourceBinding, artifact_id: str) -> ArtifactRow | None:
    with database.connect() as connection:
        rows = list_artifacts_for_source(connection, binding.project_id, binding.source_asset_id)
    for row in rows:
        if row.artifact_id == artifact_id:
            return row
    return None


def _row_with_hash(
    database: Database,
    root: Path,
    binding: SourceBinding,
    kind: str,
    digest: str,
) -> ArtifactRow | None:
    with database.connect() as connection:
        rows = [
            row
            for row in list_artifacts_for_source(connection, binding.project_id, binding.source_asset_id)
            if row.kind == kind
        ]
    matches = [row for row in rows if _hash_uri(root, row.uri)[0] == digest]
    if not matches:
        return None
    return sorted(matches, key=lambda item: item.artifact_id)[0]


def _hash_uri(root: Path, uri: str) -> tuple[str | None, str]:
    if "\\" in uri or ".." in uri.split("/"):
        return None, "traversal"
    lowered = uri.lower()
    if lowered.startswith(("http://", "https://", "s3://", "ftp://")):
        return None, "remote_source"
    try:
        path = confine_file_uri(root, uri, label="artifact")
    except MediaError as exc:
        text = str(exc)
        if "symlink" in text:
            return None, "symlink"
        return None, "traversal"
    if not path.is_file():
        return None, "missing_artifact"
    return sha256_file(path), "reused"


def _contained(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _assemble(
    planned: CampaignProductionRun,
    sources: list[CampaignSourceRun],
    project_id: str,
) -> CampaignProductionRun:
    status, reason = _roll_up(sources)
    now = datetime.now(UTC)
    document = planned.model_copy(
        update={
            "campaign_run_id": str(uuid4()),
            "project_id": project_id,
            "created_at": now,
            "completed_at": now,
            "sources": sources,
            "status": status,
            "reason_code": reason,
        }
    )
    return document.model_copy(update={"fingerprint": _evidence_fingerprint(document)})


def _roll_up(sources: list[CampaignSourceRun]) -> tuple[RunStatus, str]:
    states = [item.status for item in sources]
    if states and all(item == "succeeded" for item in states):
        return "succeeded", "none"
    if any(item == "succeeded" for item in states):
        return "partial", "source_incomplete"
    if any(item == "failed" for item in states):
        return "failed", "source_failed"
    if any(item == "cancelled" for item in states):
        return "cancelled", "cancelled"
    return "blocked", sources[0].reason_code if sources else "missing_source"


def _selection_fingerprint(
    campaign_id: str,
    source_ids: list[str],
    language: str,
    narration_enabled: bool,
) -> str:
    body = {
        "campaign_id": campaign_id,
        "language": language,
        "narration_enabled": narration_enabled,
        "narration_model": ENGLISH_NARRATION_MODEL if narration_enabled else "",
        "narration_revision": ENGLISH_NARRATION_REVISION if narration_enabled else "",
        "narration_voice": ENGLISH_NARRATION_VOICE if narration_enabled else "",
        "source_ids": source_ids,
    }
    return _digest(body)


def _evidence_fingerprint(document: CampaignProductionRun) -> str:
    body = {
        "alignment_checkpoint_sha256": document.alignment_checkpoint_sha256,
        "alignment_provider": document.alignment_provider,
        "alignment_revision": document.alignment_revision,
        "campaign_id": document.campaign_id,
        "engine_id": document.engine_id,
        "language": document.language,
        "model_id": document.model_id,
        "model_revision": document.model_revision,
        "narration_enabled": document.narration_enabled,
        "sources": [
            {
                "candidates": [
                    {
                        "advanced_artifact_id": item.advanced_artifact_id,
                        "candidate_id": item.candidate_id,
                        "hero_artifact_id": item.hero_artifact_id,
                        "hero_review_id": item.hero_review_id,
                        "preview_artifact_id": item.preview_artifact_id,
                        "review_decision": item.review_decision,
                        "review_id": item.review_id,
                    }
                    for item in source.candidates
                ],
                "delivery_files_sha256": source.delivery_files_sha256,
                "delivery_id": source.delivery_id,
                "delivery_manifest_sha256": source.delivery_manifest_sha256,
                "narration_artifact_id": source.narration_artifact_id,
                "narration_audio_sha256": source.narration_audio_sha256,
                "narration_model": document.model_id if source.narration_artifact_id else None,
                "narration_revision": document.model_revision if source.narration_artifact_id else None,
                "narration_voice": document.voice_id if source.narration_artifact_id else None,
                "qa_set_id": source.qa_set_id,
                "qa_set_sha256": source.qa_set_sha256,
                "reason_code": source.reason_code,
                "source_id": source.source_id,
                "source_sha256": source.source_sha256,
                "stages": [
                    {
                        "artifact_id": stage.artifact_id,
                        "artifact_sha256": stage.artifact_sha256,
                        "cache_hit": stage.cache_hit,
                        "job_id": stage.job_id,
                        "reason_code": stage.reason_code,
                        "stage": stage.stage,
                        "status": stage.status,
                    }
                    for stage in source.stages
                ],
                "status": source.status,
            }
            for source in document.sources
        ],
        "voice_id": document.voice_id,
    }
    return _digest(body)


def _digest(body: object) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _evidence_current(database: Database, root: Path, document: CampaignProductionRun) -> bool:
    if document.status != "succeeded" or not _campaign_job_current(database, document):
        return False
    try:
        bound = [_bind_one(database, item.source_id) for item in document.sources]
        _reject_mixed(bound)
        for source, item in zip(document.sources, bound, strict=True):
            _verify_source(database, root, document, source, item)
    except CampaignError:
        return False
    return True


def _campaign_job_current(database: Database, document: CampaignProductionRun) -> bool:
    if document.project_id == "unresolved":
        return False
    with database.connect() as connection:
        job = _find_campaign_job(connection, document.project_id, document.campaign_run_id)
    return job is not None and job.status is JobStatus.SUCCEEDED


@dataclass(frozen=True, slots=True)
class ReframeFacts:
    """Reframing recorded on one campaign source. Paths are absent."""

    requested: str = "contain"
    applied: str = "contain"
    plan_id: str = "none"
    trajectory_sha256: str = "none"
    evidence_sha256: str = "none"
    status: str = "succeeded"
    cache_hit: bool = False
    blocker: str = "none"


def reframe_facts(bound: _Bound, source: CampaignSourceRun, root: Path) -> ReframeFacts:
    """Read the stored crop plan. Contain stays eligible without face evidence."""
    blocker = reframe_blocker(bound, source, root)
    candidate_id = source.candidates[0].candidate_id if source.candidates else None
    if bound.binding is None or candidate_id is None:
        return ReframeFacts(
            cache_hit=False, status="succeeded" if blocker is None else "blocked", blocker=blocker or "none"
        )
    workspace = SourceWorkspace(root, bound.binding.project_id, bound.binding.source_asset_id)
    path = workspace.advanced_plan_file(candidate_id)
    if path.is_symlink() or not path.is_file():
        return ReframeFacts()
    try:
        plan = AdvancedHeroPlanDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError):
        return ReframeFacts(status="blocked", blocker="visual_analysis_missing")
    if plan.reframing_strategy != "face_follow":
        hit = source.status == "succeeded" and source.cache_status == "hit"
        return ReframeFacts(cache_hit=hit)
    side = workspace.reframe_plan_file(candidate_id)
    if blocker is not None or side.is_symlink() or not side.is_file():
        return ReframeFacts(
            requested="face_follow",
            applied="none",
            status="blocked",
            blocker=blocker or "visual_analysis_missing",
        )
    try:
        document = ReframePlanDocument.model_validate_json(side.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError):
        return ReframeFacts(
            requested="face_follow", applied="none", status="blocked", blocker="visual_analysis_missing"
        )
    hit = source.status == "succeeded" and source.cache_status == "hit"
    return ReframeFacts(
        requested=document.requested_strategy,
        applied=document.applied_strategy,
        plan_id=document.plan_id,
        trajectory_sha256=document.trajectory_sha256 or "none",
        evidence_sha256=document.plan_fingerprint,
        status="succeeded",
        cache_hit=hit,
        blocker="none",
    )


def reframe_blocker(bound: _Bound, source: CampaignSourceRun, root: Path) -> str | None:
    """Return a blocker when an explicit face_follow plan is no longer current."""
    candidate_id = source.candidates[0].candidate_id if source.candidates else None
    if bound.binding is None or candidate_id is None:
        return None
    workspace = SourceWorkspace(root, bound.binding.project_id, bound.binding.source_asset_id)
    path = workspace.advanced_plan_file(candidate_id)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        plan = AdvancedHeroPlanDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError):
        return None
    if plan.reframing_strategy != "face_follow":
        return None
    side = workspace.reframe_plan_file(candidate_id)
    if side.is_symlink():
        return "unsafe_path"
    if not side.is_file():
        return "visual_analysis_missing"
    try:
        document = ReframePlanDocument.model_validate_json(side.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError):
        return "visual_analysis_missing"
    if (
        document.source_sha256 != plan.source_sha256
        or document.visual_analysis_sha256 != plan.visual_analysis_sha256
    ):
        return "visual_analysis_stale"
    if document.applied_strategy != "face_follow" or document.trajectory is None:
        return document.fallback_reason or "face_follow_requires_one_track"
    if document.trajectory.digest() != document.trajectory_sha256:
        return "visual_analysis_stale"
    if document.time_map_sha256 != plan.time_map_sha256:
        return "time_map_stale"
    return None


def _source_current(
    database: Database,
    root: Path,
    document: CampaignProductionRun,
    source: CampaignSourceRun,
    bound: _Bound,
) -> bool:
    try:
        _verify_source(database, root, document, source, bound)
    except CampaignError:
        return False
    return True


def _invalidate_stale(
    database: Database,
    root: Path,
    campaign_id: str,
    hook: PromotionHook | None = None,
) -> None:
    base = root / "campaigns" / "runs"
    if not base.is_dir() or base.is_symlink():
        return
    for manifest in sorted(base.glob("*/manifest.json")):
        if _symlink_between(root, manifest):
            continue
        try:
            document = CampaignProductionRun.model_validate_json(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, ValueError):
            continue
        if document.campaign_id != campaign_id or document.status != "succeeded":
            continue
        if not _evidence_current(database, root, document):
            _invalidate_run(database, root, document, hook)


def _invalidate_run(
    database: Database,
    root: Path,
    document: CampaignProductionRun,
    hook: PromotionHook | None = None,
    reason: str = "evidence_changed",
) -> None:
    """Mark a stale succeeded run blocked in the sidecar and the database together."""
    final = _final_manifest(root, document.campaign_run_id)
    if _symlink_between(root, final) or not final.is_file():
        return
    previous = final.read_bytes()
    updated = document.model_copy(update={"status": "blocked", "reason_code": reason})
    text = updated.model_dump_json() + "\n"
    try:
        CampaignProductionRun.model_validate_json(text)
        _step(hook, "cancellation")
    except (CampaignError, ValidationError, ValueError):
        return
    snapshot: JobRecord | None = None
    wrote = False
    committed = False
    try:
        with database.transaction() as connection:
            _step(hook, "database")
            snapshot = _find_campaign_job(connection, document.project_id, document.campaign_run_id)
            if snapshot is not None:
                update_job(
                    connection,
                    snapshot.model_copy(
                        update={
                            "status": JobStatus.BLOCKED,
                            "updated_at": datetime.now(UTC),
                            "error_message": reason,
                        }
                    ),
                )
            _step(hook, "database_commit")
        committed = True
        _step(hook, "sidecar")
        _write_contained(root, final, text)
        wrote = True
    except Exception:
        if wrote:
            _write_contained(root, final, previous.decode("utf-8"))
        if committed and snapshot is not None:
            with database.transaction() as connection:
                update_job(connection, snapshot)


def _publish(
    database: Database,
    root: Path,
    document: CampaignProductionRun,
    created_by: str,
    *,
    replace_job: bool,
    promotion_hook: PromotionHook | None = None,
) -> None:
    _step(promotion_hook, "cancellation")
    text = document.model_dump_json() + "\n"
    _step(promotion_hook, "manifest_validation")
    CampaignProductionRun.model_validate_json(text)
    staging = root / "campaigns" / f".partial-{document.campaign_run_id}" / "manifest.json"
    final = _final_manifest(root, document.campaign_run_id)
    previous = final.read_bytes() if final.is_file() and not _symlink_between(root, final) else None
    _step(promotion_hook, "staging_write")
    _write_contained(root, staging, text)
    _step(promotion_hook, "manifest_validation")
    CampaignProductionRun.model_validate_json(staging.read_text(encoding="utf-8"))
    if document.project_id == "unresolved":
        _step(promotion_hook, "final_rename")
        _replace_contained(root, staging, final)
        _step(promotion_hook, "sidecar_write")
        return
    source_ids = [item.source_asset_id for item in document.sources if item.source_asset_id]
    if not source_ids:
        _discard_contained(root, staging)
        return
    committed = False
    inserted = False
    snapshot: JobRecord | None = None
    try:
        with database.transaction() as connection:
            _step(promotion_hook, "database_insert")
            existing = _find_campaign_job(connection, document.project_id, document.campaign_run_id)
            _store_campaign_job(
                connection,
                document,
                created_by,
                source_ids,
                existing=existing,
                replace_job=replace_job,
            )
            if existing is None or not replace_job:
                inserted = existing is None
            else:
                snapshot = existing
            _step(promotion_hook, "artifact_insert")
            _step(promotion_hook, "database_commit")
        committed = True
        _step(promotion_hook, "final_rename")
        _replace_contained(root, staging, final)
        _step(promotion_hook, "sidecar_write")
    except Exception as exc:
        _discard_contained(root, staging)
        if committed:
            _restore_promotion(database, root, document, final, previous, snapshot, inserted)
        if isinstance(exc, CampaignError):
            raise
        raise CampaignError("campaign promotion failed", code="promotion_failed") from exc


def _store_campaign_job(
    connection: sqlite3.Connection,
    document: CampaignProductionRun,
    created_by: str,
    source_ids: list[str],
    *,
    existing: JobRecord | None,
    replace_job: bool,
) -> None:
    now = document.completed_at or document.created_at
    status = _job_status(document.status)
    error = document.reason_code if status is JobStatus.FAILED else None
    payload = {"campaign_run_id": document.campaign_run_id, "fingerprint": document.fingerprint}
    if existing is not None and replace_job:
        update_job(
            connection,
            existing.model_copy(
                update={"status": status, "updated_at": now, "error_message": error, "payload": payload}
            ),
        )
        return
    if existing is not None:
        return
    job_id = str(uuid4())
    provenance = ArtifactProvenance(
        created_at=now,
        created_by=created_by,
        tool="clipforge-campaign",
        tool_version="0.1.0",
        source_asset_ids=source_ids,
        job_id=job_id,
        inputs_sha256=document.fingerprint,
    )
    insert_job(
        connection,
        JobRecord(
            job_id=job_id,
            project_id=document.project_id,
            kind="campaign_production",
            status=status,
            created_at=document.created_at,
            updated_at=now,
            error_message=error,
            payload=payload,
        ),
    )
    final = Path("campaigns") / "runs" / document.campaign_run_id / "manifest.json"
    insert_artifact(
        connection,
        artifact_id=document.campaign_run_id,
        project_id=document.project_id,
        job_id=job_id,
        source_asset_id=source_ids[0],
        kind=KIND,
        uri=final.as_posix(),
        provenance=provenance,
    )


def _restore_promotion(
    database: Database,
    root: Path,
    document: CampaignProductionRun,
    final: Path,
    previous: bytes | None,
    snapshot: JobRecord | None,
    inserted: bool,
) -> None:
    if previous is None:
        _discard_contained(root, final)
    else:
        _write_contained(root, final, previous.decode("utf-8"))
    with database.transaction() as connection:
        if snapshot is not None:
            update_job(connection, snapshot)
            return
        if not inserted:
            return
        connection.execute(
            "DELETE FROM artifacts WHERE artifact_id = ? AND project_id = ?",
            (document.campaign_run_id, document.project_id),
        )
        failed = _find_campaign_job(connection, document.project_id, document.campaign_run_id)
        if failed is None:
            return
        update_job(
            connection,
            failed.model_copy(
                update={
                    "status": JobStatus.FAILED,
                    "updated_at": datetime.now(UTC),
                    "error_message": "promotion_failed",
                }
            ),
        )


def _step(hook: PromotionHook | None, name: str) -> None:
    if hook is not None:
        hook(name)


def _final_manifest(root: Path, campaign_run_id: str) -> Path:
    return root / "campaigns" / "runs" / campaign_run_id / "manifest.json"


def _symlink_between(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _write_contained(root: Path, path: Path, text: str) -> None:
    if _symlink_between(root, path):
        raise CampaignError("campaign path is a symlink", code="symlink")
    mkdir_contained(root, path.parent)
    partial = path.with_name(f"{path.name}.partial")
    if partial.is_symlink():
        raise CampaignError("campaign path is a symlink", code="symlink")
    partial.write_text(text, encoding="utf-8")
    os.replace(partial, path)


def _replace_contained(root: Path, source: Path, final: Path) -> None:
    if _symlink_between(root, source) or _symlink_between(root, final):
        raise CampaignError("campaign path is a symlink", code="symlink")
    mkdir_contained(root, final.parent)
    os.replace(source, final)
    parent = source.parent
    if parent.is_dir() and not parent.is_symlink() and not any(parent.iterdir()):
        parent.rmdir()


def _discard_contained(root: Path, path: Path) -> None:
    if _symlink_between(root, path):
        return
    if path.is_file():
        path.unlink()
    parent = path.parent
    if parent != root and parent.is_dir() and not parent.is_symlink() and not any(parent.iterdir()):
        parent.rmdir()


def _job_status(status: RunStatus) -> JobStatus:
    if status == "succeeded":
        return JobStatus.SUCCEEDED
    if status == "failed":
        return JobStatus.FAILED
    if status == "cancelled":
        return JobStatus.CANCELLED
    return JobStatus.BLOCKED


def _find_campaign_job(
    connection: sqlite3.Connection,
    project_id: str,
    campaign_run_id: str,
) -> JobRecord | None:
    matches = [
        job
        for job in list_jobs(connection, project_id)
        if job.kind == "campaign_production" and job.payload.get("campaign_run_id") == campaign_run_id
    ]
    if not matches:
        return None
    return matches[-1]


def _read(root: Path, campaign_run_id: str) -> CampaignProductionRun:
    if "/" in campaign_run_id or "\\" in campaign_run_id or ".." in campaign_run_id:
        raise CampaignError("campaign run id is not safe", code="malformed_id")
    path = root / "campaigns" / "runs" / campaign_run_id / "manifest.json"
    if _symlink_between(root, path) or not path.is_file():
        raise CampaignError("campaign run is missing", code="missing_run")
    try:
        return CampaignProductionRun.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise CampaignError("campaign run document was rejected", code="invalid_document") from exc


def _cached_run(root: Path, fingerprint: str) -> CampaignProductionRun | None:
    base = root / "campaigns" / "runs"
    if not base.is_dir():
        return None
    matches: list[CampaignProductionRun] = []
    for manifest in sorted(base.glob("*/manifest.json")):
        if manifest.is_symlink():
            continue
        try:
            document = CampaignProductionRun.model_validate_json(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, ValueError):
            continue
        if document.fingerprint == fingerprint and document.status == "succeeded":
            matches.append(document)
    if not matches:
        return None
    return matches[-1]


def _verify_source(
    database: Database,
    root: Path,
    document: CampaignProductionRun,
    source: CampaignSourceRun,
    bound: _Bound,
) -> None:
    if bound.binding is None or bound.binding.source_sha256 != source.source_sha256:
        code = bound.reason or "source_changed"
        raise CampaignError("campaign source no longer matches the run", code=code)
    if source.delivery_id is None or source.delivery_manifest_sha256 is None:
        raise CampaignError("campaign delivery evidence is missing", code="delivery_missing")
    package, package_reason = _package(database, root, bound.binding)
    if package_reason or package is None:
        raise CampaignError("delivery package is not intact", code=package_reason or "delivery_missing")
    align = next(item for item in source.stages if item.stage == "align")
    if document.alignment_provider == "whisperx":
        problem, digest, _job_id, alignment_id = _alignment_facts(database, root, bound.binding, package)
        if problem:
            raise CampaignError("alignment evidence is not current", code=problem)
        if digest != align.artifact_sha256 or alignment_id != align.artifact_id:
            raise CampaignError("alignment hash changed", code="alignment_changed")
        if document.alignment_checkpoint_sha256 != ENGLISH_ALIGNMENT_CHECKPOINT:
            raise CampaignError("alignment checkpoint changed", code="model_revision_changed")
    if package.qa_set_sha256 != source.qa_set_sha256:
        raise CampaignError("qa hash changed", code="qa_changed")
    if source.narration_artifact_id and source.narration_audio_sha256:
        _verify_narration(
            database,
            root,
            bound.binding,
            source.narration_artifact_id,
            source.narration_audio_sha256,
        )
    if package.manifest_sha256 != source.delivery_manifest_sha256:
        raise CampaignError("delivery bytes changed", code="delivery_changed")
    if package.files_sha256 != source.delivery_files_sha256:
        raise CampaignError("delivery bytes changed", code="delivery_changed")
    reviews = _reviews(database, root, bound.binding, package)
    if not reviews.ok or not source.candidates:
        raise CampaignError("review binding changed", code=reviews.reason)
    recorded = source.candidates[0]
    if recorded.review_id != reviews.review_id or recorded.review_decision != reviews.decision:
        raise CampaignError("review binding changed", code="stale_review")
    same_hero = recorded.hero_review_id == reviews.hero_review_id
    same_preview = recorded.preview_artifact_id == reviews.preview_artifact_id
    if not same_hero or not same_preview:
        raise CampaignError("review binding changed", code="stale_review")
    for stage in source.stages:
        skipped = stage.stage in {"align", "delivery", "source_verify"}
        if stage.artifact_id is None or stage.artifact_sha256 is None or skipped:
            continue
        try:
            with database.connect() as connection:
                row = get_artifact(connection, stage.artifact_id)
        except StorageError as exc:
            raise CampaignError("campaign artifact row is missing", code="artifact_missing") from exc
        if row.project_id != bound.binding.project_id or row.source_asset_id != bound.binding.source_asset_id:
            raise CampaignError("campaign artifact belongs to another source", code="cross_source")
        if stage.job_id is None or stage.job_id != row.job_id:
            raise CampaignError("campaign producer is not succeeded", code="producer_missing")
        producer = _producer_problem(database, row.job_id, bound.binding.project_id)
        if producer:
            raise CampaignError("campaign producer is not succeeded", code=producer)
        digest, reason = _hash_uri(root, row.uri)
        if digest is None:
            raise CampaignError("campaign artifact is not a local file", code=reason)
        if digest != stage.artifact_sha256:
            raise CampaignError("campaign artifact hash changed", code=_change_code(stage.stage))


def _verify_narration(
    database: Database,
    root: Path,
    binding: SourceBinding,
    artifact_id: str,
    expected: str,
) -> None:
    try:
        with database.connect() as connection:
            row = get_artifact(connection, artifact_id)
    except StorageError as exc:
        raise CampaignError("narration artifact row is missing", code="artifact_missing") from exc
    classified = _classify_narration(database, root, binding, row)
    if not isinstance(classified, NarrationAudioArtifact):
        raise CampaignError("narration artifact is not current", code=classified)
    if classified.audio_sha256 != expected or classified.artifact_id != artifact_id:
        raise CampaignError("narration hash changed", code="narration_changed")


def _change_code(stage: StageName) -> str:
    if stage == "transcribe":
        return "transcript_changed"
    if stage == "qa":
        return "qa_changed"
    if stage == "narration":
        return "narration_changed"
    if stage == "delivery":
        return "delivery_changed"
    if stage == "align":
        return "alignment_changed"
    return "artifact_changed"
