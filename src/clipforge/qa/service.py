"""Run and read QA sets. ffprobe stays outside the SQLite write transaction."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from clipforge import __version__
from clipforge.errors import ClipforgeError, MediaError, StorageError
from clipforge.hero.advanced_service import KIND_ADVANCED, _load_current_document
from clipforge.hero.show import load_current_hero
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri, path_to_file_uri
from clipforge.media.workspace import (
    SourceWorkspace,
    advanced_read_lock,
    candidate_read_lock,
    hero_read_lock,
    prepare_read_lock,
    preview_read_lock,
    qa_lock,
    transcribe_read_lock,
    vision_read_lock,
)
from clipforge.policy.engine import PolicyContext, evaluate_policy
from clipforge.policy.loader import PolicyError, ProfileResolution, resolve_profile
from clipforge.preview.inputs import PreviewInputs, load_preview_inputs
from clipforge.preview.service import default_profile
from clipforge.qa.technical import TechnicalInputs, technical_checks
from clipforge.schemas.advanced import (
    AdvancedHeroDraftSetDocument,
    AdvancedHeroPlanDocument,
    advanced_fingerprint,
)
from clipforge.schemas.governance import AssetLicenseRecord, ComplianceStatus
from clipforge.schemas.jobs import JobRecord, QACheck, QAKind, QAResult, QAStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.qa import PolicyDigest, QACacheRecord, QASetDocument, aggregate_status
from clipforge.schemas.roles import WorkflowRolePolicy
from clipforge.storage import (
    Database,
    find_artifact,
    get_asset_license_record,
    get_project,
    get_source_asset,
    insert_artifact,
    insert_job,
    update_job,
)
from clipforge.storage.repository import ArtifactRow
from clipforge.transcription.io import publish_json

KIND_QA = "qa_set_json"
JOB_QA = "qa_run"


class QAError(ClipforgeError):
    """QA cannot run or the current set is not an acceptable gate."""


@dataclass(frozen=True, slots=True)
class QARunResult:
    qa_set_id: str
    artifact_id: str
    profile_id: str
    status: str
    technical_status: str
    campaign_status: str
    manifest_sha256: str


def run_qa(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    created_by: str,
    config_root: Path | None = None,
) -> QARunResult:
    """Evaluate the current advanced Hero artifact and publish a QA set."""
    root = work_root.resolve()
    inputs = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=default_profile().fingerprint(),
        create_workspace=True,
    )
    workspace = inputs.pair.workspace
    project_id = inputs.pair.source.project_id
    with (
        prepare_read_lock(workspace, busy=_busy(source_asset_id, "media prepare")),
        transcribe_read_lock(workspace, busy=_busy(source_asset_id, "transcription")),
        vision_read_lock(workspace, busy=_busy(source_asset_id, "visual analysis")),
        candidate_read_lock(workspace, busy=_busy(source_asset_id, "candidate mining")),
        preview_read_lock(workspace, busy=_busy(source_asset_id, "rough preview")),
        hero_read_lock(workspace),
        advanced_read_lock(workspace),
        qa_lock(workspace),
    ):
        prepared = _prepare(database, inputs, workspace, root, config_root)
        _reject_symlinks(prepared, root)
        job = _running_job(project_id, source_asset_id, datetime.now(UTC), created_by)
        with database.transaction() as connection:
            insert_job(connection, job)
        run_dir: Path | None = None
        try:
            document = _build_document(prepared, job.job_id, created_by, datetime.now(UTC))
            run_dir = workspace.qa_run_dir(document.qa_set_id)
            workspace.prepare_qa_file(run_dir / "manifest.json")
            manifest = run_dir / "manifest.json"
            publish_json(manifest, document, root, workspace.partial_for(manifest))
            digest = sha256_file(manifest)
            artifact_id = str(uuid.uuid4())
            record = _cache_record(document, artifact_id, digest, manifest.stat().st_size)
            previous = _snapshot(database, project_id, source_asset_id)
            _commit(database, job, document, manifest, artifact_id)
            try:
                sidecar = workspace.qa_sidecar()
                publish_json(sidecar, record, root, workspace.partial_for(sidecar))
            except (OSError, MediaError) as exc:
                _revert(database, document, previous, job, str(exc))
                raise QAError(
                    f"QA sidecar was not published: {exc}. The previous QA set remains current."
                ) from exc
        except KeyboardInterrupt:
            _abandon(database, job, "cancelled", "QA run cancelled")
            raise
        except (QAError, MediaError, StorageError, OSError, ValidationError, PolicyError) as exc:
            _abandon(database, job, "failed", str(exc))
            raise
    return QARunResult(
        document.qa_set_id,
        artifact_id,
        document.profile_id,
        document.status.value,
        document.technical.status.value,
        document.campaign.status.value,
        digest,
    )


def list_qa(database: Database, source_asset_id: str, work_root: Path) -> str:
    document = _current(database, source_asset_id, work_root)
    if document is None:
        return "No current QA set is stored for this source."
    return "\n".join(
        [
            f"qa_set_id: {document.qa_set_id}",
            f"target_artifact_id: {document.target_artifact_id}",
            f"profile_id: {document.profile_id}",
            "policies: " + ", ".join(item.policy_id for item in document.policies),
            f"technical: {document.technical.status.value}",
            f"campaign: {document.campaign.status.value}",
            f"status: {document.status.value}",
            f"created_at: {document.provenance.created_at.isoformat()}",
        ]
    )


def show_qa(database: Database, source_asset_id: str, work_root: Path) -> str:
    document = _current(database, source_asset_id, work_root)
    if document is None:
        raise QAError("no current QA set. Run `clipforge qa run` after an advanced Hero render.")
    lines = [
        f"qa_set_id: {document.qa_set_id}",
        f"profile_id: {document.profile_id}",
        f"profile_sha256: {document.profile_sha256}",
        f"status: {document.status.value}",
    ]
    for result in (document.technical, document.campaign):
        lines.append(f"{result.kind.value}: {result.status.value}")
        for check in result.checks:
            lines.append(f"  {check.name}: {check.status.value}: {check.evidence}")
    text = "\n".join(lines)
    if "/home/" in text or "/tmp/" in text or "://" in text:
        raise QAError("QA evidence contained a filesystem path and was not shown")
    return text


def verify_qa(
    database: Database,
    source_asset_id: str,
    work_root: Path,
    *,
    config_root: Path | None = None,
) -> None:
    """Re-check the current QA set. This does not rewrite it."""
    root = work_root.resolve()
    document, record, manifest = _load_bound(database, source_asset_id, root)
    if sha256_file(manifest) != record.manifest_sha256:
        raise QAError("QA manifest hash does not match the sidecar")
    try:
        loaded = load_preview_inputs(
            database,
            source_asset_id,
            root,
            profile_fingerprint=default_profile().fingerprint(),
            create_workspace=False,
        )
    except MediaError as exc:
        text = str(exc).replace(str(root), "work")
        raise QAError(f"QA verify failed because current inputs changed: {text}") from exc
    fresh = _prepare(database, loaded, loaded.pair.workspace, root, config_root)
    if fresh.document.advanced_set_id != _advanced_set(database, source_asset_id, root):
        raise QAError("QA target advanced set changed")
    if fresh.artifact_id != document.target_artifact_id:
        raise QAError("QA target artifact changed")
    if fresh.manifest_sha256 != document.target_manifest_sha256:
        raise QAError("advanced manifest hash changed")
    if fresh.resolution.profile_sha256 != document.profile_sha256:
        raise QAError("profile hash changed")
    current_policies = {item.policy_id: item.sha256 for item in fresh.resolution.policies}
    stored_policies = {item.policy_id: item.sha256 for item in document.policies}
    if current_policies != stored_policies:
        raise QAError("policy hash changed")
    job_id = document.provenance.job_id or document.qa_set_id
    rebuilt = _build_document(fresh, job_id, "verify", document.provenance.created_at)
    if rebuilt.technical.status != document.technical.status:
        raise QAError(f"technical QA status changed to {rebuilt.technical.status.value}")
    if rebuilt.campaign.status != document.campaign.status:
        raise QAError(f"campaign QA status changed to {rebuilt.campaign.status.value}")
    if rebuilt.status != document.status:
        raise QAError(f"QA aggregate status changed to {rebuilt.status.value}")


def gate_qa(
    database: Database,
    source_asset_id: str,
    work_root: Path,
    *,
    config_root: Path | None = None,
) -> QASetDocument:
    """Return the current QA set only when both kinds pass and the bindings still match."""
    verify_qa(database, source_asset_id, work_root, config_root=config_root)
    document, _record, _manifest = _load_bound(database, source_asset_id, work_root.resolve())
    if document.technical.status is not QAStatus.PASS or document.campaign.status is not QAStatus.PASS:
        raise QAError(
            "QA gate blocked: "
            f"technical {document.technical.status.value}, campaign {document.campaign.status.value}"
        )
    if document.status is not QAStatus.PASS:
        raise QAError(f"QA gate blocked: aggregate {document.status.value}")
    for result in (document.technical, document.campaign):
        for check in result.checks:
            if not check.evidence.strip():
                raise QAError(f"QA gate blocked: {check.name} has no evidence")
    return document


def qa_public_facts(database: Database, source_asset_id: str, work_root: Path) -> dict[str, object]:
    """Sanitized QA facts for the review page. Missing QA is an empty gate, not a pass."""
    try:
        document, record, _manifest = _load_bound(database, source_asset_id, work_root.resolve())
    except ClipforgeError:
        return {
            "qa_set_id": None,
            "qa_manifest_sha256": None,
            "profile_id": None,
            "policy_ids": [],
            "technical_status": None,
            "campaign_status": None,
            "qa_status": None,
        }
    return {
        "qa_set_id": document.qa_set_id,
        "qa_manifest_sha256": record.manifest_sha256,
        "profile_id": document.profile_id,
        "policy_ids": [item.policy_id for item in document.policies],
        "technical_status": document.technical.status.value,
        "campaign_status": document.campaign.status.value,
        "qa_status": document.status.value,
    }


@dataclass(frozen=True, slots=True)
class _Prepared:
    database: Database
    workspace: SourceWorkspace
    root: Path
    project_id: str
    source_asset_id: str
    document: AdvancedHeroDraftSetDocument
    artifact_id: str
    manifest_sha256: str
    plans: tuple[AdvancedHeroPlanDocument, ...]
    resolution: ProfileResolution
    source_license: AssetLicenseRecord | None
    source_sha256: str
    hero_artifact_id: str
    hero_manifest_sha256: str
    hero_alignment_sha256: dict[str, str]
    hero_plan_sha256: dict[str, str]
    visual_sha256: str
    duration_us: int


def _prepare(
    database: Database,
    inputs: PreviewInputs,
    workspace: SourceWorkspace,
    root: Path,
    config_root: Path | None,
) -> _Prepared:
    source_asset_id = inputs.pair.source.source_asset_id
    project_id = inputs.pair.source.project_id
    with database.connect() as connection:
        project = get_project(connection, project_id)
        if not project.profile_id:
            raise QAError(
                "QA requires a project profile. "
                "Run `clipforge project set-profile PROJECT_ID PROFILE_ID`. "
                "The organic profile is not assigned automatically."
            )
        source = get_source_asset(connection, source_asset_id)
        try:
            license_record = get_asset_license_record(connection, source.license_record_id)
        except StorageError:
            license_record = None
        row = find_artifact(connection, project_id, source_asset_id, KIND_ADVANCED)
    if row is None:
        raise QAError(
            "QA requires a current advanced Hero artifact. "
            "Run `clipforge hero advanced render` before `clipforge qa run`."
        )
    document = _load_current_document(database, source_asset_id, root)
    if document is None:
        raise QAError("QA requires a current advanced Hero manifest. The rough preview is not a substitute.")
    try:
        resolution = resolve_profile(project.profile_id, config_root=config_root)
    except PolicyError as exc:
        raise QAError(str(exc)) from exc
    hero = load_current_hero(database, source_asset_id, root)
    plans: list[AdvancedHeroPlanDocument] = []
    for draft in document.drafts:
        path = workspace.advanced_plan_file(draft.candidate_id)
        if path.is_symlink():
            raise QAError(f"advanced plan for {draft.candidate_id} is a symlink")
        if not path.is_file():
            raise QAError(f"advanced plan for {draft.candidate_id} is missing")
        plans.append(AdvancedHeroPlanDocument.model_validate_json(path.read_text(encoding="utf-8")))
    manifest = workspace.advanced_run_dir(document.advanced_set_id) / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise QAError("advanced manifest is missing or a symlink")
    source_file = path_from_file_uri(inputs.pair.source.uri)
    duration = max(window.output_end_us for plan in plans for window in plan.windows)
    return _Prepared(
        database=database,
        workspace=workspace,
        root=root,
        project_id=project_id,
        source_asset_id=source_asset_id,
        document=document,
        artifact_id=row.artifact_id,
        manifest_sha256=sha256_file(manifest),
        plans=tuple(plans),
        resolution=resolution,
        source_license=license_record,
        source_sha256=sha256_file(source_file),
        hero_artifact_id=hero.artifact_id,
        hero_manifest_sha256=hero.manifest_sha256,
        hero_alignment_sha256={item.candidate_id: item.alignment_sha256 for item in hero.document.drafts},
        hero_plan_sha256={item.candidate_id: item.edit_plan_sha256 for item in hero.document.drafts},
        visual_sha256=inputs.pair.visual_sha256,
        duration_us=duration,
    )


def _reject_symlinks(prepared: _Prepared, root: Path) -> None:
    from clipforge.hero.advanced_assets import confine_work_path

    document = prepared.document
    for draft in document.drafts:
        lexical = prepared.workspace.advanced_run_dir(document.advanced_set_id) / draft.preview_relative_path
        try:
            confine_work_path(root, lexical.relative_to(root).as_posix(), label="advanced media")
        except MediaError as exc:
            if "symlink" in str(exc).lower() or "escapes" in str(exc).lower():
                raise QAError(str(exc).replace(str(root), "work")) from exc


def _build_document(prepared: _Prepared, job_id: str, actor: str, now: datetime) -> QASetDocument:
    document = prepared.document
    technical = technical_checks(
        TechnicalInputs(
            database=prepared.database,
            workspace=prepared.workspace,
            root=prepared.root,
            document=document,
            artifact_id=prepared.artifact_id,
            manifest_sha256=prepared.manifest_sha256,
            plans=prepared.plans,
            source_sha256=prepared.source_sha256,
            hero_artifact_id=prepared.hero_artifact_id,
            hero_manifest_sha256=prepared.hero_manifest_sha256,
            hero_alignment_sha256=prepared.hero_alignment_sha256,
            hero_plan_sha256=prepared.hero_plan_sha256,
            visual_sha256=prepared.visual_sha256,
            duration_us=prepared.duration_us,
        )
    )
    campaign = _campaign_checks(prepared)
    technical_result = _qa_result(prepared, QAKind.TECHNICAL, technical, job_id, actor, now, "qa-technical")
    campaign_result = _qa_result(
        prepared, QAKind.CAMPAIGN_COMPLIANCE, campaign, job_id, actor, now, "qa-campaign"
    )
    status = aggregate_status(technical_result.status, campaign_result.status)
    policies = [
        PolicyDigest(policy_id=item.policy_id, sha256=item.sha256) for item in prepared.resolution.policies
    ]
    treatment_fingerprints = {
        plan.treatment_fingerprint for plan in prepared.plans if plan.treatment_fingerprint
    }
    treatment_evidence_fingerprints = {
        plan.treatment_evidence_sha256 for plan in prepared.plans if plan.treatment_evidence_sha256
    }
    treatment_mix_fingerprints = {
        advanced_fingerprint(plan.treatment_audio_mix.model_dump(mode="json"))
        for plan in prepared.plans
        if plan.treatment_audio_mix is not None
    }
    if len(treatment_fingerprints) > 1:
        raise QAError("QA plans have inconsistent treatment fingerprints")
    if len(treatment_evidence_fingerprints) > 1:
        raise QAError("QA plans have inconsistent treatment evidence fingerprints")
    if len(treatment_mix_fingerprints) > 1:
        raise QAError("QA plans have inconsistent treatment audio mix fingerprints")
    return QASetDocument(
        workflow_roles=WorkflowRolePolicy(),
        qa_set_id=str(uuid.uuid4()),
        project_id=prepared.project_id,
        source_asset_id=prepared.source_asset_id,
        target_artifact_id=prepared.artifact_id,
        target_artifact_kind=KIND_ADVANCED,
        target_manifest_sha256=prepared.manifest_sha256,
        profile_id=prepared.resolution.profile_id,
        profile_sha256=prepared.resolution.profile_sha256,
        policies=policies,
        technical=technical_result,
        campaign=campaign_result,
        status=status,
        treatment_fingerprint=next(iter(treatment_fingerprints), ""),
        treatment_evidence_sha256=next(iter(treatment_evidence_fingerprints), ""),
        treatment_evidence_relative_path=next(
            (
                plan.treatment_evidence_relative_path
                for plan in prepared.plans
                if plan.treatment_evidence_relative_path
            ),
            "",
        ),
        # The evidence digest covers the complete direction option, request
        # bindings, collision/omission receipts, and the audio mix.  Keep the
        # legacy field name for compatibility, but never substitute the audio
        # sub-hash for the canonical treatment summary.
        treatment_summary_sha256=next(iter(treatment_evidence_fingerprints), ""),
        provenance=ArtifactProvenance(
            created_at=now,
            created_by=actor,
            tool="clipforge-qa",
            tool_version=__version__,
            source_asset_ids=[prepared.source_asset_id],
            parent_artifact_ids=[prepared.artifact_id],
            job_id=job_id,
        ),
    )


def _campaign_checks(prepared: _Prepared) -> list[QACheck]:
    context = PolicyContext(
        database=prepared.database,
        project_id=prepared.project_id,
        source_asset_id=prepared.source_asset_id,
        source_license=prepared.source_license,
        plans=prepared.plans,
        work_root=prepared.root,
        workspace=prepared.workspace,
        profile_id=prepared.resolution.profile_id,
    )
    checks: list[QACheck] = []
    for policy in prepared.resolution.policies:
        result = evaluate_policy(policy.policy_id, context)
        status = QAStatus(result.status.value)
        if result.status is ComplianceStatus.PASS:
            status = QAStatus.PASS
        checks.append(QACheck(name=policy.policy_id, status=status, evidence=result.evidence))
    return checks


def _qa_result(
    prepared: _Prepared,
    kind: QAKind,
    checks: list[QACheck],
    job_id: str,
    actor: str,
    now: datetime,
    tool: str,
) -> QAResult:
    if not checks:
        checks = [
            QACheck(
                name="empty",
                status=QAStatus.INSUFFICIENT_EVIDENCE,
                evidence="no checks were produced",
            )
        ]
    statuses = [item.status for item in checks]
    return QAResult(
        qa_id=str(uuid.uuid4()),
        project_id=prepared.project_id,
        artifact_id=prepared.artifact_id,
        kind=kind,
        status=aggregate_status(*statuses),
        checks=checks,
        provenance=ArtifactProvenance(
            created_at=now,
            created_by=actor,
            tool=tool,
            tool_version=__version__,
            source_asset_ids=[prepared.source_asset_id],
            parent_artifact_ids=[prepared.artifact_id],
            job_id=job_id,
        ),
    )


def _running_job(project_id: str, source_asset_id: str, now: datetime, actor: str) -> JobRecord:
    from clipforge.schemas.jobs import JobStatus

    return JobRecord(
        job_id=str(uuid.uuid4()),
        project_id=project_id,
        kind=JOB_QA,
        status=JobStatus.RUNNING,
        created_at=now,
        updated_at=now,
        payload={"source_asset_id": source_asset_id, "actor": actor},
    )


def _cache_record(document: QASetDocument, artifact_id: str, digest: str, size: int) -> QACacheRecord:
    return QACacheRecord(
        project_id=document.project_id,
        source_asset_id=document.source_asset_id,
        qa_set_id=document.qa_set_id,
        artifact_id=artifact_id,
        target_artifact_id=document.target_artifact_id,
        target_artifact_kind=document.target_artifact_kind,
        target_manifest_sha256=document.target_manifest_sha256,
        profile_id=document.profile_id,
        profile_sha256=document.profile_sha256,
        manifest_sha256=digest,
        manifest_size_bytes=size,
        status=document.status,
        created_at=document.provenance.created_at,
    )


def _commit(
    database: Database, job: JobRecord, document: QASetDocument, manifest: Path, artifact_id: str
) -> None:
    from clipforge.schemas.jobs import JobStatus

    succeeded = job.model_copy(
        update={"status": JobStatus.SUCCEEDED, "updated_at": datetime.now(UTC), "error_message": None}
    )
    with database.transaction() as connection:
        insert_artifact(
            connection,
            artifact_id=artifact_id,
            project_id=document.project_id,
            job_id=job.job_id,
            source_asset_id=document.source_asset_id,
            kind=KIND_QA,
            uri=path_to_file_uri(manifest),
            provenance=document.provenance,
        )
        update_job(connection, succeeded)


def _abandon(database: Database, job: JobRecord, status: str, message: str) -> None:
    from clipforge.schemas.jobs import JobStatus

    chosen = JobStatus.CANCELLED if status == "cancelled" else JobStatus.FAILED
    updated = job.model_copy(
        update={
            "status": chosen,
            "updated_at": datetime.now(UTC),
            "error_message": message[:2000],
        }
    )
    with database.transaction() as connection:
        update_job(connection, updated)


def _snapshot(database: Database, project_id: str, source_asset_id: str) -> ArtifactRow | None:
    with database.connect() as connection:
        return find_artifact(connection, project_id, source_asset_id, KIND_QA)


def _revert(
    database: Database,
    document: QASetDocument,
    previous: ArtifactRow | None,
    job: JobRecord,
    reason: str,
) -> None:
    from clipforge.schemas.jobs import JobStatus

    failed = job.model_copy(
        update={
            "status": JobStatus.FAILED,
            "updated_at": datetime.now(UTC),
            "error_message": f"sidecar publish failed: {reason}"[:2000],
        }
    )
    with database.transaction() as connection:
        connection.execute(
            "DELETE FROM artifacts WHERE project_id = ? AND source_asset_id = ? AND kind = ? AND job_id = ?",
            (document.project_id, document.source_asset_id, KIND_QA, job.job_id),
        )
        update_job(connection, failed)
    del previous


def _current(database: Database, source_asset_id: str, work_root: Path) -> QASetDocument | None:
    try:
        document, _record, _manifest = _load_bound(database, source_asset_id, work_root.resolve())
    except QAError:
        return None
    return document


def _load_bound(
    database: Database, source_asset_id: str, root: Path
) -> tuple[QASetDocument, QACacheRecord, Path]:
    workspace = _workspace_for_source(database, source_asset_id, root)
    sidecar = workspace.qa_sidecar()
    if not sidecar.is_file() or sidecar.is_symlink():
        raise QAError("no current QA set")
    try:
        record = QACacheRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise QAError(f"QA sidecar could not be read: {exc}") from exc
    manifest = workspace.qa_run_dir(record.qa_set_id) / "manifest.json"
    if not manifest.is_file() or manifest.is_symlink():
        raise QAError("QA manifest is missing or a symlink")
    try:
        document = QASetDocument.model_validate_json(manifest.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise QAError(f"QA manifest could not be read: {exc}") from exc
    return document, record, manifest


def _workspace_for_source(database: Database, source_asset_id: str, root: Path) -> SourceWorkspace:
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
    return SourceWorkspace(root, source.project_id, source.source_asset_id)


def _advanced_set(database: Database, source_asset_id: str, root: Path) -> str:
    document = _load_current_document(database, source_asset_id, root)
    if document is None:
        raise QAError("current advanced Hero set is missing")
    return document.advanced_set_id


def _busy(source: str, label: str) -> str:
    return f"another {label} is active for source {source}."
