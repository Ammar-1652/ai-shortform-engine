"""Operator aggregate over the existing campaign runner. It does not render."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from clipforge.campaign.acquisition import latest_successful_result
from clipforge.campaign.antoine import policy_sha256
from clipforge.campaign.production import (
    bind_campaign_source,
    reframe_facts,
    resume_campaign,
    run_campaign,
    verify_campaign_run,
)
from clipforge.campaign.providers import CampaignError
from clipforge.language.registry import capability_for
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import ensure_within, mkdir_contained
from clipforge.publish.service import explain_package
from clipforge.schemas.campaign_operator import CampaignSelectionDocument
from clipforge.schemas.campaign_run import CampaignCandidateRecord, CampaignProductionRun, CampaignSourceRun
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.production_manifest import (
    CampaignProductionCacheRecord,
    CampaignProductionManifest,
    CampaignProductionSource,
    CampaignProductionStageFact,
    manifest_digest,
)
from clipforge.storage import Database, insert_job
from clipforge.storage.repository import update_job

_RELOAD = "The campaign selection changed while this page was open; reload before saving."
_KIND = "campaign_operator_production"
_ZERO = "0" * 64


def production_plan(database: Database, work_root: Path, selection_id: str) -> str:
    """Describe a production. This does not write."""
    root = work_root.resolve()
    selection = _selection(root, selection_id)
    _current(root, selection, None)
    lines = [
        f"selection {selection.selection_id} {selection.status}",
        f"language {selection.language}",
        f"narration {'requested' if selection.narration_enabled else 'narration_not_requested'}",
        "publishing deferred",
        "whop_live not_configured",
        "envato discovery_only",
    ]
    for choice in selection.sources:
        acquired = latest_successful_result(root, choice.source_id, choice.source_sha256)
        state = "acquisition" if acquired is not None else "binding"
        lines.append(f"{choice.source_id} {choice.rights_state} {state}")
    del database
    return "\n".join(lines)


def produce(
    database: Database,
    work_root: Path,
    selection_id: str,
    *,
    operator_id: str,
    force: bool = False,
    expected_selection_sha256: str | None = None,
    narration_probe: Callable[[str, str], None] | None = None,
    promotion_hook: Callable[[str], None] | None = None,
) -> CampaignProductionManifest:
    """Run the existing pipeline and record one aggregate manifest."""
    root = work_root.resolve()
    selection = _selection(root, selection_id)
    _current(root, selection, expected_selection_sha256)
    _require_language(selection.language, selection.narration_enabled)
    if selection.status != "ready":
        raise CampaignError("campaign selection is not ready", code=selection.reason_code)
    from clipforge.campaign.operator import _require_acquisition_or_binding

    _require_acquisition_or_binding(root, database, selection)
    _recover_running_jobs(database, selection.project_id)
    _clean_partials(root)
    if not force:
        cached = _cached(database, root, selection)
        if cached is not None:
            return cached
    produced = run_campaign(
        database,
        root,
        campaign_id=selection.campaign_id,
        source_ids=list(selection.source_ids),
        language=selection.language,
        narration_enabled=selection.narration_enabled,
        force=force,
        created_by=operator_id,
        narration_probe=narration_probe,
    )
    if produced.status == "succeeded":
        verify_campaign_run(database, root, produced.campaign_run_id)
    document = _build(root, database, selection, produced, operator_id, hit=False)
    _promote(database, root, document, previous=None, hook=promotion_hook)
    return _read(root, document.run_id)


def resume_production(
    database: Database,
    work_root: Path,
    run_id: str,
    *,
    operator_id: str,
    expected_selection_sha256: str | None = None,
    promotion_hook: Callable[[str], None] | None = None,
) -> CampaignProductionManifest:
    """Retry the pipeline sources that are not still verified."""
    root = work_root.resolve()
    current = _read(root, run_id)
    selection = _selection(root, current.selection_id)
    _current(root, selection, expected_selection_sha256)
    _recover_running_jobs(database, selection.project_id)
    _clean_partials(root)
    produced = resume_campaign(database, root, current.pipeline_run_id, created_by=operator_id)
    if produced.status == "succeeded":
        verify_campaign_run(database, root, produced.campaign_run_id)
    document = _build(
        root,
        database,
        selection,
        produced,
        operator_id,
        hit=False,
        run_id=current.run_id,
        created_at=current.created_at,
    )
    previous = _manifest_path(root, current.run_id).read_bytes()
    _promote(database, root, document, previous=previous, hook=promotion_hook, replace=True)
    return _read(root, current.run_id)


def cancel_production(work_root: Path, run_id: str) -> CampaignProductionManifest:
    """Mark an incomplete aggregate cancelled. Succeeded source records stay."""
    root = work_root.resolve()
    current = _read(root, run_id)
    _clean_partials(root)
    sources = []
    for source in current.sources:
        if source.status == "succeeded":
            sources.append(source)
            continue
        sources.append(source.model_copy(update={"status": "cancelled", "failure_code": "cancelled"}))
    status = "partial" if any(item.status == "succeeded" for item in sources) else "cancelled"
    drafted = current.model_copy(
        update={"sources": sources, "status": status, "reason_code": "cancelled", "manifest_sha256": _ZERO}
    )
    stored = _stamp(drafted)
    path = _manifest_path(root, current.run_id)
    previous = path.read_bytes()
    try:
        _write_final(root, stored)
    except OSError as exc:
        path.write_bytes(previous)
        raise CampaignError("production manifest was not promoted", code="promotion_failed") from exc
    return stored


def list_productions(work_root: Path, campaign_id: str) -> list[str]:
    return [item.run_id for item in _all(work_root.resolve()) if item.campaign_id == campaign_id]


def show_production(work_root: Path, run_id: str) -> str:
    return _read(work_root.resolve(), run_id).model_dump_json()


def verify_production(database: Database, work_root: Path, run_id: str) -> str:
    """Re-check the aggregate and the pipeline run. This does not write."""
    root = work_root.resolve()
    document = _read(root, run_id)
    if document.policy_fingerprint != policy_sha256():
        raise CampaignError("campaign policy changed", code="stale_policy")
    if document.status != "succeeded":
        raise CampaignError("production is not succeeded", code=document.reason_code)
    verify_campaign_run(database, root, document.pipeline_run_id)
    for source in document.sources:
        if source.status != "succeeded":
            raise CampaignError("production source is not succeeded", code=source.failure_code or "failed")
        if source.delivery_relative is None:
            raise CampaignError("delivery is missing", code="delivery_missing")
        _delivery_ok(root, source.delivery_relative)
    return f"PASS production {document.run_id}"


def production_report(work_root: Path, run_id: str) -> str:
    document = _read(work_root.resolve(), run_id)
    lines = [
        f"run {document.run_id}",
        f"pipeline {document.pipeline_run_id}",
        f"status {document.status} {document.reason_code}",
        f"language {document.language}",
        f"narration {'requested' if document.narration_enabled else 'narration_not_requested'}",
        f"cache {'hit' if document.cache.hit else 'miss'}",
        "publishing deferred",
        "whop_live not_configured",
    ]
    for source in document.sources:
        lines.append(
            " ".join(
                [
                    source.source_id,
                    source.status,
                    f"review {source.review_decision or 'missing'}",
                    f"qa {source.qa_set_id or 'missing'}",
                    f"delivery {source.delivery_id or 'missing'}",
                    f"locale {source.requested_locale}",
                    f"alignment {source.alignment_status}",
                    f"provider {source.alignment_provider}",
                    f"model {source.alignment_model_id}",
                    f"revision {source.alignment_model_revision}",
                    f"checkpoint {source.alignment_checkpoint_sha256}",
                    f"alignment_artifact {source.alignment_artifact_id}",
                    f"alignment_cache {source.alignment_cache_status}",
                    f"alignment_blocker {source.alignment_blocker}",
                    f"narration {source.narration_status}",
                    f"cache {source.cache_status}",
                    f"reframe {source.reframe_applied}",
                    f"reframe_blocker {source.reframe_blocker}",
                ]
            )
        )
    return "\n".join(lines)


def board_productions(work_root: Path, campaign_id: str) -> dict[str, object]:
    rows = [
        {"run_id": item.run_id, "status": item.status, "reason_code": item.reason_code}
        for item in _all(work_root.resolve())
        if item.campaign_id == campaign_id
    ]
    return {"campaign_id": campaign_id, "productions": rows, "publishing": "deferred"}


def board_production(work_root: Path, run_id: str) -> dict[str, object]:
    document = _read(work_root.resolve(), run_id)
    payload: dict[str, object] = {
        "run_id": document.run_id,
        "pipeline_run_id": document.pipeline_run_id,
        "campaign_id": document.campaign_id,
        "status": document.status,
        "reason_code": document.reason_code,
        "language": document.language,
        "narration_enabled": document.narration_enabled,
        "cache_hit": document.cache.hit,
        "publishing": "deferred",
        "sources": [_source_card(item) for item in document.sources],
    }
    _reject(payload)
    return payload


def board_production_source(work_root: Path, run_id: str, source_id: str) -> dict[str, object]:
    document = _read(work_root.resolve(), run_id)
    for source in document.sources:
        if source.source_id == source_id:
            payload = {"run_id": document.run_id, "publishing": "deferred", **_source_card(source)}
            _reject(payload)
            return payload
    raise CampaignError("production source is missing", code="missing_source")


def board_production_delivery(work_root: Path, run_id: str) -> dict[str, object]:
    document = _read(work_root.resolve(), run_id)
    rows = [
        {
            "source_id": source.source_id,
            "delivery_id": source.delivery_id,
            "delivery_relative": source.delivery_relative,
            "delivery_manifest_sha256": source.delivery_manifest_sha256,
            "final_media_sha256": source.final_media_sha256,
        }
        for source in document.sources
    ]
    payload: dict[str, object] = {"run_id": document.run_id, "deliveries": rows, "publishing": "deferred"}
    _reject(payload)
    return payload


def _build(
    root: Path,
    database: Database,
    selection: CampaignSelectionDocument,
    produced: CampaignProductionRun,
    operator_id: str,
    *,
    hit: bool,
    run_id: str | None = None,
    created_at: datetime | None = None,
) -> CampaignProductionManifest:
    by_id = {item.source_id: item for item in produced.sources}
    sources = [
        _source(root, database, by_id[source_id], produced.project_id, produced)
        for source_id in selection.source_ids
    ]
    created = created_at or datetime.now(UTC)
    cache = CampaignProductionCacheRecord(
        cache_key=_cache_key(selection, produced),
        pipeline_fingerprint=produced.fingerprint,
        selection_sha256=_file_sha(root, selection.selection_id),
        policy_fingerprint=selection.policy_fingerprint,
        catalogue_fingerprint=selection.catalogue_fingerprint,
        hit=hit,
    )
    drafted = CampaignProductionManifest.model_construct(
        schema_version="1.0.0",
        run_id=run_id or str(uuid4()),
        pipeline_run_id=produced.campaign_run_id,
        campaign_id=selection.campaign_id,
        project_id=produced.project_id,
        selection_id=selection.selection_id,
        selection_sha256=_file_sha(root, selection.selection_id),
        selection_fingerprint=selection.evidence_fingerprint,
        catalogue_fingerprint=selection.catalogue_fingerprint,
        policy_fingerprint=selection.policy_fingerprint,
        operator_id=operator_id,
        source_ids=list(selection.source_ids),
        language=produced.language,
        narration_enabled=produced.narration_enabled,
        voice_id=produced.voice_id,
        engine_id=produced.engine_id,
        model_id=produced.model_id,
        model_revision=produced.model_revision,
        sources=sources,
        cache=cache,
        status=produced.status,
        reason_code=produced.reason_code,
        created_at=created,
        completed_at=datetime.now(UTC),
        manifest_sha256=_ZERO,
        publishing="deferred",
    )
    return _stamp(drafted)


def _source(
    root: Path,
    database: Database,
    pipeline: CampaignSourceRun,
    project_id: str,
    produced: CampaignProductionRun,
) -> CampaignProductionSource:
    acquired = latest_successful_result(root, pipeline.source_id, pipeline.source_sha256)
    candidate = pipeline.candidates[0] if pipeline.candidates else None
    delivery_relative = None
    if pipeline.delivery_id is not None:
        delivery_relative = f"deliveries/{pipeline.delivery_id}/manifest.json"
    video_sha = None
    if delivery_relative is not None:
        video_sha = _video_sha(root, delivery_relative)
    artifact_id = pipeline.advanced_artifact_id or pipeline.hero_artifact_id
    snapshot = _analytics_snapshot(database, project_id, artifact_id)
    stages = [
        CampaignProductionStageFact(
            stage=item.stage,
            status=item.status,
            cache_hit=item.cache_hit,
            reason_code=item.reason_code,
        )
        for item in pipeline.stages
    ]
    if pipeline.status == "succeeded":
        stages.append(
            CampaignProductionStageFact(
                stage="final_review",
                status="succeeded",
                cache_hit=pipeline.cache_status == "hit",
                reason_code="approved",
            )
        )
    else:
        stages.append(
            CampaignProductionStageFact(
                stage="final_review",
                status="blocked",
                cache_hit=False,
                reason_code=pipeline.reason_code,
            )
        )
    reframed = reframe_facts(bind_campaign_source(database, pipeline.source_id), pipeline, root)
    stage_reason = reframed.blocker if reframed.blocker != "none" else reframed.applied
    stages.append(
        CampaignProductionStageFact(
            stage="reframe",
            status=reframed.status,
            cache_hit=reframed.cache_hit,
            reason_code=stage_reason[:80],
        )
    )
    align_stage = next(item for item in pipeline.stages if item.stage == "align")
    failure = None if pipeline.status == "succeeded" else pipeline.reason_code
    source_status = pipeline.status
    if pipeline.status == "succeeded" and reframed.status == "blocked":
        failure = reframed.blocker
        source_status = "blocked"
    return CampaignProductionSource(
        source_id=pipeline.source_id,
        source_sha256=pipeline.source_sha256,
        byte_size=_size(database, pipeline.source_id),
        acquisition_id=None if acquired is None else acquired.acquisition_id,
        acquisition_sha256=None if acquired is None else acquired.source_sha256,
        status=source_status,
        cache_status=pipeline.cache_status,
        failure_code=failure,
        candidate_id=None if candidate is None else candidate.candidate_id,
        review_id=None if candidate is None else candidate.review_id,
        review_decision=None if candidate is None else candidate.review_decision,
        hero_review_id=None if candidate is None else candidate.hero_review_id,
        hero_artifact_id=pipeline.hero_artifact_id,
        advanced_artifact_id=pipeline.advanced_artifact_id,
        qa_set_id=pipeline.qa_set_id,
        analytics_snapshot_id=snapshot,
        analytics_status="recorded" if snapshot else "not_recorded",
        alignment_status=_alignment_state(candidate),
        narration_status=_narration_label(candidate, pipeline),
        narration_artifact_id=pipeline.narration_artifact_id,
        narration_audio_sha256=pipeline.narration_audio_sha256,
        delivery_id=pipeline.delivery_id,
        delivery_manifest_sha256=pipeline.delivery_manifest_sha256,
        delivery_relative=delivery_relative,
        final_media_sha256=video_sha,
        stages=stages,
        reframe_requested=reframed.requested,
        reframe_applied=reframed.applied,
        reframe_plan_id=reframed.plan_id,
        reframe_trajectory_sha256=reframed.trajectory_sha256,
        reframe_evidence_sha256=reframed.evidence_sha256,
        reframe_status=reframed.status,
        reframe_cache_hit=reframed.cache_hit,
        reframe_blocker=reframed.blocker,
        requested_locale=pipeline.requested_locale or produced.language,
        transcript_language=produced.language,
        alignment_provider=produced.alignment_provider,
        alignment_model_id=produced.alignment_model or "none",
        alignment_model_revision=produced.alignment_revision or "none",
        alignment_checkpoint_sha256=produced.alignment_checkpoint_sha256 or "none",
        alignment_artifact_id=align_stage.artifact_id or "none",
        alignment_cache_status=pipeline.cache_status,
        alignment_blocker="none" if align_stage.status == "succeeded" else align_stage.reason_code,
    )


def _alignment_state(candidate: CampaignCandidateRecord | None) -> str:
    if candidate is None:
        return "alignment_not_claimed"
    return str(candidate.alignment_status)


def _narration_label(candidate: CampaignCandidateRecord | None, pipeline: CampaignSourceRun) -> str:
    if candidate is not None:
        return str(candidate.narration_status)
    if pipeline.narration_artifact_id is None:
        return "narration_not_requested"
    return _narration_state(pipeline)


def _narration_state(pipeline: CampaignSourceRun) -> str:
    if pipeline.narration_artifact_id and pipeline.narration_audio_sha256:
        return "verified_live"
    return pipeline.reason_code or "narration_missing"


def _promote(
    database: Database,
    root: Path,
    document: CampaignProductionManifest,
    *,
    previous: bytes | None,
    hook: Callable[[str], None] | None,
    replace: bool = False,
) -> None:
    path = _manifest_path(root, document.run_id)
    staging = path.with_name("manifest.json.partial")
    text = document.model_dump_json() + "\n"
    try:
        _step(hook, "staging_write")
        mkdir_contained(root, path.parent)
        staging.write_text(text, encoding="utf-8")
        CampaignProductionManifest.model_validate_json(staging.read_text(encoding="utf-8"))
        _step(hook, "database_insert")
        _store_job(database, document)
        _step(hook, "final_rename")
        os.replace(staging, path)
    except (CampaignError, OSError, ValidationError, ValueError) as exc:
        if staging.is_file() and not staging.is_symlink():
            staging.unlink()
        if previous is not None and (not path.is_file() or replace):
            path.write_bytes(previous)
        code = exc.code if isinstance(exc, CampaignError) else "promotion_failed"
        _fail_job(database, document, code)
        raise CampaignError("production manifest was not promoted", code=code) from exc
    if staging.exists():
        staging.unlink()


def _cached(
    database: Database, root: Path, selection: CampaignSelectionDocument
) -> CampaignProductionManifest | None:
    file_sha = _file_sha(root, selection.selection_id)
    for document in reversed(_all(root)):
        if document.selection_id != selection.selection_id or document.status != "succeeded":
            continue
        if document.selection_sha256 != file_sha or document.policy_fingerprint != selection.policy_fingerprint:
            continue
        try:
            verify_campaign_run(database, root, document.pipeline_run_id)
        except CampaignError:
            continue
        return document
    return None


def _stamp(document: CampaignProductionManifest) -> CampaignProductionManifest:
    payload = document.model_dump(mode="json")
    payload["manifest_sha256"] = manifest_digest(document)
    return CampaignProductionManifest.model_validate(payload)


def _store_job(database: Database, document: CampaignProductionManifest) -> None:
    now = datetime.now(UTC)
    record = JobRecord(
        job_id=document.run_id,
        project_id=document.project_id,
        kind=_KIND,
        status=JobStatus.SUCCEEDED if document.status == "succeeded" else JobStatus.FAILED,
        created_at=document.created_at,
        updated_at=now,
        error_message=None if document.status == "succeeded" else document.reason_code,
        payload={
            "run_id": document.run_id,
            "pipeline_run_id": document.pipeline_run_id,
            "selection_id": document.selection_id,
            "selection_sha256": document.selection_sha256,
            "policy_fingerprint": document.policy_fingerprint,
        },
    )
    with database.transaction() as connection:
        found = connection.execute("SELECT job_id FROM jobs WHERE job_id = ?", (document.run_id,)).fetchone()
        if found is None:
            insert_job(connection, record)
        else:
            update_job(connection, record)


def _fail_job(database: Database, document: CampaignProductionManifest, code: str) -> None:
    if code == "promotion_failed" and document.status == "succeeded":
        try:
            _store_failed(database, document, code)
        except Exception:
            return


def _store_failed(database: Database, document: CampaignProductionManifest, code: str) -> None:
    now = datetime.now(UTC)
    record = JobRecord(
        job_id=document.run_id,
        project_id=document.project_id,
        kind=_KIND,
        status=JobStatus.FAILED,
        created_at=document.created_at,
        updated_at=now,
        error_message=code,
        payload={"run_id": document.run_id, "pipeline_run_id": document.pipeline_run_id},
    )
    with database.transaction() as connection:
        found = connection.execute("SELECT job_id FROM jobs WHERE job_id = ?", (document.run_id,)).fetchone()
        if found is None:
            insert_job(connection, record)
        else:
            update_job(connection, record)


def _recover_running_jobs(database: Database, project_id: str) -> None:
    now = datetime.now(UTC).isoformat()
    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = 'failed', error_message = 'interrupted', updated_at = ?
            WHERE project_id = ? AND kind = ? AND status = 'running'
            """,
            (now, project_id, _KIND),
        )


def _selection(root: Path, selection_id: str) -> CampaignSelectionDocument:
    if "/" in selection_id or "\\" in selection_id or ".." in selection_id:
        raise CampaignError("selection id is not safe", code="malformed_id")
    path = root / "campaigns" / "selections" / selection_id / "selection.json"
    if path.is_symlink() or not path.is_file():
        raise CampaignError("campaign selection is missing", code="missing_selection")
    try:
        return CampaignSelectionDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise CampaignError("campaign selection was rejected", code="invalid_document") from exc


def _current(root: Path, selection: CampaignSelectionDocument, expected: str | None) -> None:
    from clipforge.campaign.operator import catalogue_fingerprint

    if selection.catalogue_fingerprint != catalogue_fingerprint(selection.campaign_id):
        raise CampaignError("campaign catalogue changed", code="stale_catalogue")
    if selection.policy_fingerprint != policy_sha256():
        raise CampaignError("campaign policy changed", code="stale_policy")
    current = _file_sha(root, selection.selection_id)
    if expected is not None and expected != current:
        raise CampaignError(_RELOAD, code="stale_selection")


def _require_language(language: str, narration: bool) -> None:
    try:
        capability = capability_for(language)
    except ValueError as exc:
        raise CampaignError("language is unsupported", code="unsupported_language") from exc
    if narration and capability.narration_evidence != "verified_live":
        code = capability.narration_reason if capability.narration_reason != "none" else "unsupported_language"
        raise CampaignError("narration locale is not verified", code=code)


def _video_sha(root: Path, relative: str) -> str | None:
    path = root / relative
    try:
        ensure_within(root, path)
    except Exception:
        return None
    document, reason = explain_package(root, path)
    if document is None or reason:
        return None
    for item in document.files:
        if item.role == "video":
            return item.sha256
    return None


def _delivery_ok(root: Path, relative: str) -> None:
    path = root / relative
    document, reason = explain_package(root, path)
    if document is None or reason:
        raise CampaignError("delivery package is not current", code=reason or "delivery_missing")


def _analytics_snapshot(database: Database, project_id: str, artifact_id: str | None) -> str | None:
    if artifact_id is None:
        return None
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT snapshot_id FROM editorial_feature_snapshots
            WHERE project_id = ? AND artifact_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (project_id, artifact_id),
        ).fetchone()
    if row is None:
        return None
    return str(row["snapshot_id"])


def _size(database: Database, source_id: str) -> int | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT size_bytes FROM source_manifests WHERE original_filename = ?",
            (f"{source_id}.mp4",),
        ).fetchone()
    if row is None:
        return None
    return int(row["size_bytes"])


def _cache_key(selection: CampaignSelectionDocument, produced: CampaignProductionRun) -> str:
    import hashlib
    import json

    body = {
        "narration": selection.narration_enabled,
        "pipeline": produced.fingerprint,
        "policy": selection.policy_fingerprint,
        "selection": selection.evidence_fingerprint,
        "sources": list(selection.source_ids),
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _all(root: Path) -> list[CampaignProductionManifest]:
    base = root / "campaigns" / "production"
    if not base.is_dir():
        return []
    found = []
    for path in sorted(base.glob("*/manifest.json")):
        if path.is_symlink():
            continue
        try:
            found.append(CampaignProductionManifest.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, ValidationError, ValueError):
            continue
    return found


def _read(root: Path, run_id: str) -> CampaignProductionManifest:
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        raise CampaignError("production id is not safe", code="malformed_id")
    path = _manifest_path(root, run_id)
    if path.is_symlink() or not path.is_file():
        raise CampaignError("production is missing", code="missing_production")
    try:
        return CampaignProductionManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise CampaignError("production manifest was rejected", code="invalid_document") from exc


def _write_final(root: Path, document: CampaignProductionManifest) -> None:
    path = _manifest_path(root, document.run_id)
    mkdir_contained(root, path.parent)
    partial = path.with_name("manifest.json.partial")
    partial.write_text(document.model_dump_json() + "\n", encoding="utf-8")
    os.replace(partial, path)


def _manifest_path(root: Path, run_id: str) -> Path:
    return root / "campaigns" / "production" / run_id / "manifest.json"


def _file_sha(root: Path, selection_id: str) -> str:
    return sha256_file(root / "campaigns" / "selections" / selection_id / "selection.json")


def _clean_partials(root: Path) -> None:
    base = root / "campaigns" / "production"
    if not base.is_dir():
        return
    for partial in base.glob("*/*.partial"):
        if partial.is_symlink() or partial.is_file():
            partial.unlink()


def _step(hook: Callable[[str], None] | None, name: str) -> None:
    if hook is not None:
        hook(name)


def _source_card(source: CampaignProductionSource) -> dict[str, object]:
    return {
        "source_id": source.source_id,
        "status": source.status,
        "cache_status": source.cache_status,
        "failure_code": source.failure_code,
        "review_decision": source.review_decision,
        "hero_review_id": source.hero_review_id,
        "qa_set_id": source.qa_set_id,
        "requested_locale": source.requested_locale,
        "transcript_language": source.transcript_language,
        "alignment_status": source.alignment_status,
        "alignment_provider": source.alignment_provider,
        "alignment_model_id": source.alignment_model_id,
        "alignment_model_revision": source.alignment_model_revision,
        "alignment_checkpoint_sha256": source.alignment_checkpoint_sha256,
        "alignment_artifact_id": source.alignment_artifact_id,
        "alignment_cache_status": source.alignment_cache_status,
        "alignment_blocker": source.alignment_blocker,
        "narration_status": source.narration_status,
        "analytics_status": source.analytics_status,
        "delivery_relative": source.delivery_relative,
        "delivery_manifest_sha256": source.delivery_manifest_sha256,
        "final_media_sha256": source.final_media_sha256,
        "reframe_requested": source.reframe_requested,
        "reframe_applied": source.reframe_applied,
        "reframe_plan_id": source.reframe_plan_id,
        "reframe_trajectory_sha256": source.reframe_trajectory_sha256,
        "reframe_evidence_sha256": source.reframe_evidence_sha256,
        "reframe_status": source.reframe_status,
        "reframe_cache_hit": source.reframe_cache_hit,
        "reframe_blocker": source.reframe_blocker,
        "source_sha256": source.source_sha256,
        "byte_size": source.byte_size,
        "candidate_review_path": _review_path("review/candidates", source.candidate_id),
        "hero_review_path": _review_path("hero-review/candidates", source.candidate_id),
        "stages": [_stage_card(item) for item in source.stages],
    }


def _review_path(prefix: str, candidate_id: str | None) -> str | None:
    if candidate_id is None:
        return None
    return f"{prefix}/{candidate_id}"


def _stage_card(item: CampaignProductionStageFact) -> dict[str, object]:
    return {
        "stage": item.stage,
        "status": item.status,
        "cache_hit": item.cache_hit,
        "reason_code": item.reason_code,
    }


def _reject(payload: dict[str, object]) -> None:
    import json

    text = json.dumps(payload).lower()
    if any(token in text for token in ("/home/", "/tmp/", "/users/", "file://", "bearer ", "token=")):
        raise CampaignError("production board payload contains a path or a secret", code="invalid_document")
