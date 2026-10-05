"""Observe the local production chain and record readiness. This does not approve."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4

from clipforge import __version__
from clipforge.errors import ClipforgeError, StorageError
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri, path_to_file_uri
from clipforge.media.workspace import ensure_within
from clipforge.schemas.benchmark import BenchmarkRun, BenchmarkStage, Readiness, V1ReadinessReport
from clipforge.schemas.governance import ReviewDecision, RightsStatus
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import (
    Database,
    find_artifact,
    get_artifact,
    get_asset_license_record,
    get_job,
    get_source_asset,
    get_source_manifest,
    insert_artifact,
    insert_job,
    list_reviews,
)
from clipforge.storage.repository import ArtifactRow

KIND = "v1_benchmark_run_json"
_CLEARED = {RightsStatus.OWNED, RightsStatus.LICENSED, RightsStatus.CAMPAIGN_PROVIDED}
_ORDER = (
    "campaign_discovery",
    "policy_snapshot",
    "source_inventory",
    "source_acquisition",
    "language_profile",
    "ingest",
    "media_prepare",
    "transcript",
    "visual_analysis",
    "candidate_mining",
    "rough_preview",
    "candidate_review",
    "alignment",
    "hero_plan",
    "hero_render",
    "advanced_plan",
    "optional_voice_narration",
    "advanced_render",
    "qa",
    "hero_review",
    "analytics",
    "local_delivery",
    "platform_dry_run",
    "platform_submit",
)
_KINDS = {
    "transcript": "transcript_json",
    "visual_analysis": "visual_analysis_json",
    "candidate_mining": "candidate_set_json",
    "rough_preview": "rough_preview_set_json",
    "alignment": "alignment_json",
    "hero_plan": "hero_plan_json",
    "hero_render": "hero_draft_set_json",
    "advanced_plan": "advanced_hero_plan_json",
    "advanced_render": "advanced_hero_draft_set_json",
    "qa": "qa_set_json",
}
_OPTIONAL = {"analytics", "optional_voice_narration", "platform_dry_run", "platform_submit"}
_EARLY = {
    "campaign_discovery",
    "policy_snapshot",
    "source_inventory",
    "source_acquisition",
    "language_profile",
    "optional_voice_narration",
}
_STOP = {"failed", "blocked", "unavailable", "policy_blocked", "rights_unverified"}
_SET_FIELDS = {
    "candidate_mining": ("candidate_set_id", "candidate_set_sha256"),
    "rough_preview": ("preview_set_id", "preview_set_sha256"),
    "hero_render": ("hero_set_id", "hero_set_sha256"),
    "advanced_render": ("advanced_set_id", "advanced_set_sha256"),
    "qa": ("qa_set_id", "qa_set_sha256"),
}


class BenchmarkError(ClipforgeError):
    """A readiness record cannot be stored or does not verify."""


def doctor_text() -> str:
    return "\n".join(
        [
            "PASS storage: one sqlite database",
            "PASS decisions: human decisions stay explicit",
            "PASS gates: missing approval blocks the run",
            "PASS network: none",
            "PASS delivery: local package only",
            "PASS platform_publishing: not_implemented",
        ]
    )


def run_benchmark(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    *,
    fixture_kind: str,
    candidate_id: str | None = None,
    voice_provider: str = "none",
    force: bool = False,
    execute: bool = False,
    created_by: str = "benchmark",
    sidecar_hook: object | None = None,
) -> BenchmarkRun:
    """Record the current chain. Missing approvals block the run and write that fact."""
    if fixture_kind not in {"real_authorized", "real_source", "deterministic_synthetic"}:
        raise BenchmarkError("fixture kind must be real_authorized or deterministic_synthetic")
    if voice_provider not in {"none", "voicestudio", "fake"}:
        raise BenchmarkError("voice provider must be none, fake, or voicestudio")
    root = work_root.resolve()
    benchmark_root = root / "benchmarks"
    if benchmark_root.is_symlink():
        raise BenchmarkError("benchmark directory is a symlink")
    started = monotonic()
    stamp = datetime.now(UTC)
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
        manifest = get_source_manifest(connection, source_asset_id)
        license_record = get_asset_license_record(connection, source.license_record_id)
        reviews = list_reviews(connection, source.project_id)
    rights_ok = license_record.status in _CLEARED
    approved = [
        item.candidate_id
        for item in reviews
        if item.subject_kind == "candidate" and item.decision == "approved" and item.candidate_id
    ]
    if candidate_id is not None:
        approved = [item for item in approved if item == candidate_id]
    hero_reviews = [item for item in reviews if item.subject_kind == "hero" and item.decision == "approved"]
    stages: list[BenchmarkStage] = []
    fields: dict[str, str] = {}
    stopped = False
    manual: list[str] = []
    warnings: list[str] = []
    for name in _ORDER:
        if stopped:
            stages.append(_stage(name, "not_run", stamp, cache_hit=False, error_category="not_run"))
            continue
        tick = monotonic()
        stage, extra = _one(
            database,
            root,
            source.project_id,
            source_asset_id,
            name,
            rights_ok=rights_ok,
            manifest_present=manifest is not None,
            approved=approved,
            hero_reviews=hero_reviews,
            candidate_id=candidate_id,
            stamp=stamp,
            fixture_kind=fixture_kind,
            execute=execute,
        )
        stage = stage.model_copy(update={"elapsed_ms": int((monotonic() - tick) * 1000)})
        stages.append(stage)
        fields.update(extra)
        if stage.human_action_required and stage.status == "blocked":
            manual.append(_action(name))
        if stage.status in _STOP and name not in _OPTIONAL:
            stopped = True
    if voice_provider == "voicestudio":
        warnings.append("VoiceStudio was requested and is reported by the voice doctor")
    if any(stage.error_category == "synthetic_fixture" for stage in stages):
        warnings.append("synthetic analytics fixture is not real viewer evidence")
    if fixture_kind == "deterministic_synthetic":
        warnings.append("synthetic_only")
    elapsed_ms = int((monotonic() - started) * 1000)
    evidence = [stage.artifact_sha256 for stage in stages if stage.artifact_sha256]
    run_id = _run_id(manifest.content_sha256, fixture_kind, approved, evidence)
    if not force:
        existing = _existing(database, root, run_id)
        if existing is not None:
            return existing
    qa_status = next(stage.status for stage in stages if stage.stage == "qa")
    document = BenchmarkRun(
        benchmark_run_id=run_id,
        project_id=source.project_id,
        source_asset_id=source_asset_id,
        fixture_kind=fixture_kind,  # type: ignore[arg-type]
        source_sha256=manifest.content_sha256,
        selected_candidate_ids=sorted(set(approved)),
        human_decision_ids=sorted(item.review_id for item in reviews if item.decision == "approved"),
        stages=stages,
        cache_hits=[stage.stage for stage in stages if stage.cache_hit],
        artifact_ids=[stage.artifact_id for stage in stages if stage.artifact_id],
        artifact_hashes=sorted(evidence),
        selected_count=len(set(approved)),
        candidate_set_id=fields.get("candidate_set_id"),
        candidate_set_sha256=fields.get("candidate_set_sha256"),
        preview_set_id=fields.get("preview_set_id"),
        preview_set_sha256=fields.get("preview_set_sha256"),
        hero_set_id=fields.get("hero_set_id"),
        hero_set_sha256=fields.get("hero_set_sha256"),
        advanced_set_id=fields.get("advanced_set_id"),
        advanced_set_sha256=fields.get("advanced_set_sha256"),
        qa_set_id=fields.get("qa_set_id"),
        qa_set_sha256=fields.get("qa_set_sha256"),
        qa_result=_readiness(qa_status),
        elapsed_ms=elapsed_ms,
        work_bytes=_work_bytes(root),
        tool_versions=_tools(),
        model_revisions={"clipforge": __version__},
        manual_actions=manual or ["external platform publishing remains a separate adapter"],
        warnings=warnings,
        readiness=_readiness(_overall(stages, rights_ok)),
        provenance=ArtifactProvenance(
            created_at=stamp,
            created_by=created_by,
            tool="clipforge-benchmark",
            tool_version=__version__,
            source_asset_ids=[source_asset_id],
            inputs_sha256=manifest.content_sha256,
        ),
    )
    _publish(database, root, document, sidecar_hook)
    return document


def list_runs(database: Database, project_id: str) -> list[str]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT artifact_id FROM artifacts
            WHERE project_id = ? AND kind = ?
            ORDER BY created_at, artifact_id
            """,
            (project_id, KIND),
        ).fetchall()
    return [str(row["artifact_id"]) for row in rows]


def show_run(database: Database, work_root: Path, benchmark_id: str) -> str:
    document = _read(work_root.resolve(), benchmark_id)
    _reject_public(document)
    return document.model_dump_json()


def verify_run(database: Database, work_root: Path, benchmark_id: str) -> str:
    """Re-read one benchmark. This does not create a job."""
    root = work_root.resolve()
    document = _read(root, benchmark_id)
    _reject_public(document)
    with database.connect() as connection:
        artifact = get_artifact(connection, benchmark_id)
        job_id = artifact.job_id or ""
        job = get_job(connection, job_id)
        if artifact.kind != KIND or artifact.project_id != document.project_id:
            raise BenchmarkError("benchmark artifact does not match the manifest")
        if artifact.source_asset_id != document.source_asset_id:
            raise BenchmarkError("benchmark artifact source does not match")
        if job.project_id != document.project_id or job.status not in {JobStatus.SUCCEEDED, JobStatus.BLOCKED}:
            raise BenchmarkError("benchmark job is not a finished job")
        for stage in document.stages:
            if stage.artifact_id is None or stage.artifact_sha256 is None:
                continue
            try:
                row = get_artifact(connection, stage.artifact_id)
            except StorageError as exc:
                raise BenchmarkError("benchmark names a missing artifact") from exc
            if row.project_id != document.project_id or row.source_asset_id != document.source_asset_id:
                raise BenchmarkError("benchmark artifact belongs to a different lineage")
            digest = _hash_artifact(root, row)
            if digest is not None and digest != stage.artifact_sha256:
                raise BenchmarkError("benchmark artifact hash does not match")
    return "PASS benchmark"


def _named(status: str, passed_name: str) -> str:
    if status == "passed":
        return passed_name
    if status in {"failed", "blocked", "not_run", "unavailable"}:
        return status
    return "blocked"


def readiness_report(database: Database, work_root: Path, benchmark_id: str) -> V1ReadinessReport:
    document = _read(work_root.resolve(), benchmark_id)
    skipped = {
        "candidate_review",
        "hero_review",
        "analytics",
        "qa",
        "publish_export",
        "local_delivery",
        "platform_dry_run",
        "platform_submit",
        "campaign_discovery",
        "policy_snapshot",
        "source_inventory",
        "source_acquisition",
        "language_profile",
        "optional_voice_narration",
    }
    technical_names = [name for name in _ORDER if name not in skipped]
    technical = _rollup(document, technical_names)
    editorial = _status(document, "hero_review")
    rights = _status(document, "ingest")
    qa = document.qa_result
    local_delivery = _status(document, "local_delivery")
    if local_delivery == "not_run":
        local_delivery = _status(document, "publish_export")
    limitations = [
        "External platform publishing is not implemented; local delivery export is available.",
        "VoiceStudio is optional and is not a required gate",
        "analytics evidence does not approve, optimize, or publish content",
    ]
    if document.fixture_kind == "deterministic_synthetic":
        limitations.append("synthetic evidence is not real-source verification")
    steps = list(document.manual_actions)
    if "candidate review" not in " ".join(steps):
        steps.append("a person approves the candidate and the Hero")
    overall = document.readiness
    if local_delivery != "passed":
        overall = "blocked"
        limitations.insert(0, "local delivery stays blocked until a verified package exists")
    voice = "unavailable"
    if (
        os.environ.get("CLIPFORGE_VOICESTUDIO_URL", "").strip()
        and os.environ.get("CLIPFORGE_VOICESTUDIO_LIVE_SMOKE", "").strip() == "1"
    ):
        voice = "not_run"
    live = os.environ.get("CLIPFORGE_PLATFORM_LIVE_SMOKE", "").strip() == "1"
    upload = "not_run" if live else "not_configured"
    dry = _status(document, "platform_dry_run")
    if local_delivery == "passed" and upload == "not_configured":
        overall = "blocked_for_external_publish"
    real_state = "unavailable"
    real_reason = "no authorized source supplied"
    produced = any(
        stage.stage in {"publish_export", "local_delivery"} and stage.execution == "executed_stage"
        for stage in document.stages
    )
    if document.fixture_kind in {"real_authorized", "real_source"} and produced and local_delivery == "passed":
        real_state = "passed"
        real_reason = "authorized source delivery was executed and verified"
    evidence_class = "real_source" if document.fixture_kind == "real_source" else "synthetic_only"
    voice_result = "voice_disabled"
    if os.environ.get("CLIPFORGE_VOICESTUDIO_ENABLED", "").strip() == "1":
        voice_result = "voice_provider_unavailable"
    return V1ReadinessReport(
        benchmark_run_id=document.benchmark_run_id,
        technical=_readiness(technical),
        editorial=_readiness(editorial),
        rights=_readiness(rights),
        qa=_readiness(qa),
        local_delivery=_readiness(local_delivery),
        platform_publishing="not_implemented",
        platform_adapter="passed",
        platform_dry_run=_readiness(dry),
        external_upload=upload,  # type: ignore[arg-type]
        voicestudio=_readiness(voice),
        real_source_verified=real_state,  # type: ignore[arg-type]
        real_source_reason=real_reason,
        evidence_class=evidence_class,  # type: ignore[arg-type]
        voice_result=voice_result,  # type: ignore[arg-type]
        multilingual_result="not_run",
        alignment_claim="alignment_not_claimed" if evidence_class == "real_source" else "not_run",
        technical_result=_named(technical, "technical_pass"),  # type: ignore[arg-type]
        local_delivery_result=_named(local_delivery, "local_delivery_pass"),  # type: ignore[arg-type]
        external_publishing="external_publishing_deferred",
        overall=_readiness(overall),
        blocking_limitations=limitations,
        manual_steps=steps,
        provenance=document.provenance,
    )


def _one(
    database: Database,
    root: Path,
    project_id: str,
    source_asset_id: str,
    name: str,
    *,
    rights_ok: bool,
    manifest_present: bool,
    approved: list[str],
    hero_reviews: list[ReviewDecision],
    candidate_id: str | None,
    stamp: datetime,
    fixture_kind: str,
    execute: bool,
) -> tuple[BenchmarkStage, dict[str, str]]:
    if name == "ingest":
        if not rights_ok:
            return _stage(name, "blocked", stamp, cache_hit=False, error_category="rights", human=True), {}
        return _stage(name, "passed", stamp, cache_hit=True, error_category="none"), {}
    if name == "media_prepare":
        if manifest_present:
            return _stage(name, "passed", stamp, cache_hit=True), {}
        return _gap(name, stamp, "missing_evidence")
    if name == "candidate_review":
        if candidate_id is not None and candidate_id not in approved:
            return _gap(name, stamp, "missing_approval")
        if not approved:
            return _gap(name, stamp, "missing_approval")
        return _stage(name, "passed", stamp, cache_hit=True), {}
    if name == "hero_review":
        if not hero_reviews:
            return _gap(name, stamp, "missing_approval")
        return _stage(name, "passed", stamp, cache_hit=True), {}
    if name == "analytics":
        with database.connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM performance_outcomes WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if count is not None and int(count[0]) > 0:
            return _stage(name, "passed", stamp, cache_hit=True), {}
        if fixture_kind == "deterministic_synthetic":
            _write_synthetic_analytics(root)
            return (
                _stage(name, "passed", stamp, cache_hit=True, error_category="synthetic_fixture"),
                {},
            )
        return _stage(name, "not_run", stamp, cache_hit=False, error_category="not_run"), {}
    if name == "platform_dry_run":
        return _platform_dry_run(database, root, source_asset_id, candidate_id, approved, stamp)
    if name == "platform_submit":
        return _platform_submit(stamp)
    if name in _EARLY:
        return (
            _stage(
                name,
                "not_run",
                stamp,
                cache_hit=False,
                error_category="not_configured",
                execution="not_run",
            ),
            {},
        )
    if name in {"publish_export", "local_delivery"}:
        from clipforge.publish.service import observe_stage

        chosen = candidate_id
        if chosen is None and approved:
            chosen = sorted(approved)[0]
        observed = observe_stage(database, root, source_asset_id, chosen)
        if execute and observed["status"] != "passed" and chosen is not None:
            return _export_for_execute(database, root, source_asset_id, chosen, stamp, stage_name=name)
        status = observed["status"]
        category = observed["error_category"]
        delivery_id = observed["delivery_id"]
        manifest_sha = observed["manifest_sha256"]
        artifact_id = observed["artifact_id"]
        job_id = observed["job_id"]
        classification = observed["readiness_classification"]
        return (
            _stage(
                name,
                str(status),
                stamp,
                cache_hit=bool(observed["cache_hit"]),
                artifact_id=str(artifact_id) if artifact_id else None,
                error_category=str(category),
                human=status != "passed",
                job_id=str(job_id) if job_id else None,
                delivery_id=str(delivery_id) if delivery_id else None,
                delivery_manifest_sha256=str(manifest_sha) if manifest_sha else None,
                readiness_classification=str(classification),
            ),
            {},
        )
    kind = _KINDS[name]
    with database.connect() as connection:
        row = find_artifact(connection, project_id, source_asset_id, kind)
    if row is None:
        if execute and name not in {"candidate_review", "hero_review"}:
            return _execute_missing(database, root, source_asset_id, name, stamp)
        return _gap(name, stamp, "missing_evidence")
    digest = _hash_artifact(root, row)
    if digest is None:
        missing = _stage(
            name,
            "unavailable",
            stamp,
            cache_hit=False,
            artifact_id=row.artifact_id,
            error_category="missing_file",
        )
        return missing, {}
    if name == "qa" and not _qa_passed(root, row):
        return (
            _stage(
                name,
                "failed",
                stamp,
                cache_hit=False,
                artifact_id=row.artifact_id,
                artifact_sha256=digest,
                error_category="qa_failed",
                human=True,
            ),
            {},
        )
    extra: dict[str, str] = {}
    pair = _SET_FIELDS.get(name)
    if pair is not None:
        extra[pair[0]] = row.artifact_id
        extra[pair[1]] = digest
    return (
        _stage(
            name,
            "passed",
            stamp,
            cache_hit=True,
            artifact_id=row.artifact_id,
            artifact_sha256=digest,
        ),
        extra,
    )


def _gap(name: str, stamp: datetime, category: str) -> tuple[BenchmarkStage, dict[str, str]]:
    return _stage(name, "blocked", stamp, cache_hit=False, error_category=category, human=True), {}


def _stage(
    name: str,
    status: str,
    stamp: datetime,
    *,
    cache_hit: bool,
    artifact_id: str | None = None,
    artifact_sha256: str | None = None,
    error_category: str = "none",
    human: bool = False,
    job_id: str | None = None,
    delivery_id: str | None = None,
    delivery_manifest_sha256: str | None = None,
    readiness_classification: str | None = None,
    execution: str | None = None,
) -> BenchmarkStage:
    if readiness_classification is None:
        if error_category == "synthetic_fixture":
            readiness_classification = "synthetic_fixture"
        elif status == "passed":
            readiness_classification = "technical_ready"
        else:
            readiness_classification = "blocked"
    if execution is None:
        if status == "passed" and cache_hit:
            execution = "recorded_evidence"
        elif status == "not_run":
            execution = "not_run"
        elif status == "unavailable":
            execution = "unavailable"
        else:
            execution = "blocked"
    return BenchmarkStage(
        stage=name,
        status=status,  # type: ignore[arg-type]
        started_at=stamp,
        finished_at=stamp,
        elapsed_ms=0,
        cache_hit=cache_hit,
        job_id=job_id,
        artifact_id=artifact_id,
        artifact_sha256=artifact_sha256,
        error_category=error_category,
        human_action_required=human,
        delivery_id=delivery_id,
        delivery_manifest_sha256=delivery_manifest_sha256,
        readiness_classification=readiness_classification,
        execution=execution,  # type: ignore[arg-type]
    )


def _export_for_execute(
    database: Database,
    root: Path,
    source_asset_id: str,
    candidate_id: str,
    stamp: datetime,
    *,
    stage_name: str,
) -> tuple[BenchmarkStage, dict[str, str]]:
    """Copy the local package when execute is set. This does not upload."""
    from clipforge.publish.errors import PublishError
    from clipforge.publish.service import export_delivery

    try:
        exported = export_delivery(
            database,
            root,
            source_asset_id,
            candidate_id,
            created_by="benchmark",
        )
    except PublishError as exc:
        return (
            _stage(
                stage_name,
                "blocked",
                stamp,
                cache_hit=False,
                error_category=exc.category,
                human=True,
                execution="blocked",
            ),
            {},
        )
    return (
        _stage(
            stage_name,
            "passed",
            stamp,
            cache_hit=False,
            artifact_id=exported.artifact_id,
            job_id=exported.job_id,
            delivery_id=exported.delivery_id,
            delivery_manifest_sha256=exported.manifest_sha256,
            readiness_classification="local_delivery_ready",
            execution="executed_stage",
        ),
        {},
    )


def _platform_dry_run(
    database: Database,
    root: Path,
    source_asset_id: str,
    candidate_id: str | None,
    approved: list[str],
    stamp: datetime,
) -> tuple[BenchmarkStage, dict[str, str]]:
    """Validate the current package with DryRunPublisher. No socket is opened."""
    from clipforge.platform.publisher import DryRunPublisher
    from clipforge.platform.service import dry_run_attempt
    from clipforge.publish.errors import PublishError
    from clipforge.publish.service import observe_stage
    from clipforge.schemas.publish import PublishTarget
    from clipforge.storage import list_jobs

    chosen = candidate_id
    if chosen is None and approved:
        chosen = sorted(approved)[0]
    observed = observe_stage(database, root, source_asset_id, chosen)
    if observed["status"] != "passed" or not observed["delivery_id"] or not observed["manifest_sha256"]:
        return (
            _stage(
                "platform_dry_run",
                "not_run",
                stamp,
                cache_hit=False,
                error_category="not_run",
                execution="not_run",
            ),
            {},
        )
    delivery_id = str(observed["delivery_id"])
    manifest_sha = str(observed["manifest_sha256"])
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
        jobs = list_jobs(connection, source.project_id)
    for job in jobs:
        payload = job.payload
        if job.kind != "platform_publish" or payload.get("state") != "dry_run_passed":
            continue
        same = payload.get("delivery_id") == delivery_id and payload.get("manifest_sha256") == manifest_sha
        attempt_id = payload.get("attempt_id")
        if same and attempt_id:
            return (
                _stage(
                    "platform_dry_run",
                    "passed",
                    stamp,
                    cache_hit=True,
                    artifact_id=attempt_id,
                    artifact_sha256=manifest_sha,
                    job_id=job.job_id,
                    readiness_classification="platform_dry_run",
                    execution="cache_hit",
                ),
                {},
            )
    if chosen is None:
        return (
            _stage(
                "platform_dry_run",
                "not_run",
                stamp,
                cache_hit=False,
                error_category="not_run",
                execution="not_run",
            ),
            {},
        )
    target = PublishTarget(
        platform="fake",
        account_label="benchmark",
        destination_id="local-dry-run",
        title="Local dry run",
        description="Validates the local package only.",
        tags=["benchmark"],
        campaign_id="unprofiled",
        privacy="public",
        delivery_id=delivery_id,
        manifest_sha256=manifest_sha,
    )
    try:
        attempt = dry_run_attempt(
            database,
            root,
            source_asset_id,
            chosen,
            target,
            publisher=DryRunPublisher(),
        )
    except PublishError as exc:
        return (
            _stage(
                "platform_dry_run",
                "blocked",
                stamp,
                cache_hit=False,
                error_category=exc.category,
                human=True,
                execution="blocked",
            ),
            {},
        )
    return (
        _stage(
            "platform_dry_run",
            "passed",
            stamp,
            cache_hit=False,
            artifact_id=attempt.attempt_id,
            artifact_sha256=manifest_sha,
            readiness_classification="platform_dry_run",
            execution="executed_stage",
        ),
        {},
    )


def _platform_submit(stamp: datetime) -> tuple[BenchmarkStage, dict[str, str]]:
    """Remote submit stays not_run. No adapter is contacted from a benchmark."""
    return (
        _stage(
            "platform_submit",
            "not_run",
            stamp,
            cache_hit=False,
            error_category="not_configured",
            execution="not_run",
        ),
        {},
    )


def _execute_missing(
    database: Database,
    root: Path,
    source_asset_id: str,
    name: str,
    stamp: datetime,
) -> tuple[BenchmarkStage, dict[str, str]]:
    """Run one missing stage. An existing artifact is not treated as execution."""
    try:
        if name == "media_prepare":
            from clipforge.media.prepare import prepare_source

            result = prepare_source(
                database=database,
                source_asset_id=source_asset_id,
                work_root=root,
                created_by="benchmark",
            )
            mode = "cache_hit" if result.proxy_from_cache else "executed_stage"
            return (
                _stage(
                    name,
                    "passed",
                    stamp,
                    cache_hit=result.proxy_from_cache,
                    execution=mode,
                    job_id=result.job_id,
                ),
                {},
            )
        if name == "transcript":
            return (
                _stage(
                    name,
                    "unavailable",
                    stamp,
                    cache_hit=False,
                    error_category="model_not_downloaded",
                    execution="unavailable",
                ),
                {},
            )
        return (
            _stage(
                name,
                "blocked",
                stamp,
                cache_hit=False,
                error_category="not_executed",
                execution="blocked",
                human=True,
            ),
            {},
        )
    except ClipforgeError:
        return (
            _stage(
                name,
                "blocked",
                stamp,
                cache_hit=False,
                error_category="execute_failed",
                execution="blocked",
                human=True,
            ),
            {},
        )


def _readiness(value: str) -> Readiness:
    allowed = {
        "passed",
        "failed",
        "blocked",
        "not_run",
        "unavailable",
        "blocked_for_external_publish",
    }
    if value not in allowed:
        raise BenchmarkError("readiness status is unknown")
    if value == "passed":
        return "passed"
    if value == "failed":
        return "failed"
    if value == "blocked":
        return "blocked"
    if value == "not_run":
        return "not_run"
    if value == "blocked_for_external_publish":
        return "blocked_for_external_publish"
    return "unavailable"


def _overall(stages: list[BenchmarkStage], rights_ok: bool) -> str:
    required = [stage for stage in stages if stage.stage not in _OPTIONAL]
    if any(stage.status == "failed" for stage in required):
        return "failed"
    if any(stage.status == "unavailable" for stage in required):
        return "unavailable"
    blocking = {"blocked", "not_run", "policy_blocked", "rights_unverified"}
    if any(stage.status in blocking for stage in required) or not rights_ok:
        return "blocked"
    return "passed"


def _rollup(document: BenchmarkRun, names: list[str]) -> str:
    found = [stage.status for stage in document.stages if stage.stage in names]
    if any(item == "failed" for item in found):
        return "failed"
    if any(item == "unavailable" for item in found):
        return "unavailable"
    if any(item in {"blocked", "not_run"} for item in found):
        return "blocked"
    return "passed"


def _status(document: BenchmarkRun, name: str) -> str:
    for stage in document.stages:
        if stage.stage == name:
            return stage.status
    return "not_run"


def _qa_passed(root: Path, row: ArtifactRow) -> bool:
    path = _contained(root, row)
    if path is None:
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    status = payload.get("status")
    if isinstance(status, dict):
        status = status.get("value") or status.get("status")
    return status == "pass"


def _hash_artifact(root: Path, row: ArtifactRow) -> str | None:
    path = _contained(root, row)
    if path is None:
        return None
    return sha256_file(path)


def _contained(root: Path, row: ArtifactRow) -> Path | None:
    if not row.uri.startswith("file:"):
        return None
    path = path_from_file_uri(row.uri)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        ensure_within(root, path)
    except ClipforgeError:
        return None
    return path


def _publish(database: Database, root: Path, document: BenchmarkRun, sidecar_hook: object | None) -> None:
    _reject_public(document)
    base = root / "benchmarks"
    if base.is_symlink():
        raise BenchmarkError("benchmark directory is a symlink")
    run_path = _run_path(root, document.benchmark_run_id)
    current = _current_path(root, document.source_asset_id)
    ensure_within(root, run_path)
    partial = run_path.with_suffix(".json.partial")
    previous = current.read_bytes() if current.is_file() and not current.is_symlink() else None
    payload = document.model_dump_json()
    replaced = False
    now = document.provenance.created_at
    job_id = str(uuid4())

    def write_output() -> None:
        run_path.parent.mkdir(parents=True, exist_ok=True)
        if run_path.is_symlink() or current.is_symlink() or partial.is_symlink():
            raise BenchmarkError("benchmark path is a symlink")
        partial.write_text(payload + "\n", encoding="utf-8")

    def write_manifest() -> None:
        BenchmarkRun.model_validate_json(payload)

    def commit_database() -> None:
        nonlocal replaced
        with database.transaction() as connection:
            if sidecar_hook is not None:
                if not callable(sidecar_hook):
                    raise BenchmarkError("sidecar hook is not callable")
                sidecar_hook()
            status = JobStatus.SUCCEEDED
            error_message = None
            if document.readiness == "failed":
                status = JobStatus.FAILED
                error_message = "a benchmark stage failed"
            elif document.readiness in {"blocked", "unavailable"}:
                status = JobStatus.BLOCKED
            insert_job(
                connection,
                JobRecord(
                    job_id=job_id,
                    project_id=document.project_id,
                    kind="v1_benchmark",
                    status=status,
                    created_at=now,
                    updated_at=now,
                    error_message=error_message,
                    payload={
                        "source_asset_id": document.source_asset_id,
                        "benchmark_run_id": document.benchmark_run_id,
                        "readiness": document.readiness,
                    },
                ),
            )
            insert_artifact(
                connection,
                artifact_id=document.benchmark_run_id,
                project_id=document.project_id,
                job_id=job_id,
                source_asset_id=document.source_asset_id,
                kind=KIND,
                uri=path_to_file_uri(run_path),
                provenance=document.provenance.model_copy(update={"job_id": job_id}),
            )
            partial.replace(run_path)
            current.parent.mkdir(parents=True, exist_ok=True)
            current.write_text(payload + "\n", encoding="utf-8")
            replaced = True

    def rollback() -> None:
        if partial.is_file() and not partial.is_symlink():
            partial.unlink()
        if not replaced:
            return
        if run_path.is_file() and not run_path.is_symlink():
            run_path.unlink()
        if previous is None:
            if current.is_file() and not current.is_symlink():
                current.unlink()
        else:
            current.write_bytes(previous)

    from clipforge.jobs.promote import PromotionError, promote

    try:
        promote(
            write_output=write_output,
            write_manifest=write_manifest,
            commit_database=commit_database,
            write_sidecar=lambda: None,
            rollback_database=rollback,
        )
    except PromotionError as exc:
        raise BenchmarkError("benchmark sidecar was not saved") from exc


def _existing(database: Database, root: Path, run_id: str) -> BenchmarkRun | None:
    path = _run_path(root, run_id)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        document = BenchmarkRun.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    with database.connect() as connection:
        row = connection.execute(
            "SELECT artifact_id FROM artifacts WHERE artifact_id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return document


def _read(root: Path, benchmark_id: str) -> BenchmarkRun:
    path = _run_path(root, benchmark_id)
    if path.is_symlink() or not path.is_file():
        raise BenchmarkError("benchmark manifest is missing")
    try:
        return BenchmarkRun.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise BenchmarkError("benchmark manifest could not be read") from exc


def _reject_public(document: BenchmarkRun) -> None:
    text = document.model_dump_json()
    if any(token in text.lower() for token in ("/tmp/", "/home/", "/users/", "://", "viewer_id")):
        raise BenchmarkError("benchmark manifest contains a forbidden token")


def _run_id(source_sha: str, fixture_kind: str, approved: list[str], hashes: list[str]) -> str:
    body = json.dumps(
        {
            "source_sha256": source_sha,
            "fixture_kind": fixture_kind,
            "approved": sorted(approved),
            "hashes": sorted(hashes),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode()).hexdigest()[:32]


def _run_path(root: Path, benchmark_id: str) -> Path:
    if "/" in benchmark_id or "\\" in benchmark_id or ".." in benchmark_id:
        raise BenchmarkError("benchmark id is not a safe identifier")
    return root / "benchmarks" / "runs" / benchmark_id / "manifest.json"


def _current_path(root: Path, source_asset_id: str) -> Path:
    if "/" in source_asset_id or "\\" in source_asset_id or ".." in source_asset_id:
        raise BenchmarkError("source id is not a safe identifier")
    return root / "benchmarks" / source_asset_id / "current.json"


def _write_synthetic_analytics(root: Path) -> None:
    """Write a labelled fixture. It is not a viewer metric and does not approve anything."""
    directory = root / "benchmarks" / "fixtures"
    path = directory / "synthetic-analytics.json"
    if directory.is_symlink() or path.is_symlink():
        raise BenchmarkError("synthetic analytics path is a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "evidence_class": "synthetic_fixture",
        "fixture_kind": "deterministic_synthetic",
        "note": "synthetic analytics fixture is not real viewer evidence",
        "viewer_metrics": "absent",
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")


def _action(name: str) -> str:
    labels = {
        "ingest": "clear source rights",
        "candidate_review": "approve the selected candidate",
        "hero_review": "approve the Hero",
        "qa": "record a passing QA result",
    }
    return labels.get(name, f"produce the {name} evidence")


def _tools() -> dict[str, str]:
    versions = {"python": platform.python_version(), "clipforge": __version__}
    from shutil import which

    if which("ffmpeg") is None:
        versions["ffmpeg"] = "unavailable"
    else:
        versions["ffmpeg"] = "present"
    if which("ffprobe") is None:
        versions["ffprobe"] = "unavailable"
    else:
        versions["ffprobe"] = "present"
    return versions


def _work_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        total += path.stat().st_size
    return total
