"""Record platform attempts. A receipt is the only path to published."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from clipforge.errors import ClipforgeError, StorageError
from clipforge.platform.publisher import DryRunPublisher, FakePublisher, Publisher, live_upload_enabled
from clipforge.publish.errors import PublishError
from clipforge.publish.service import verify_delivery
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.publish import (
    PublishAttempt,
    PublishReadiness,
    PublishReceipt,
    PublishRequest,
    PublishTarget,
)
from clipforge.storage import (
    Database,
    get_job,
    get_project,
    get_source_asset,
    insert_artifact,
    insert_job,
    list_jobs,
    update_job,
)
from clipforge.storage.repository import list_artifacts_for_source

KIND = "platform_publish_attempt_json"
JOB = "platform_publish"
_STALE = timedelta(minutes=15)


def doctor_text() -> str:
    upload = "not_run" if live_upload_enabled() else "not_configured"
    return "\n".join(
        [
            "PASS platform_adapter: available",
            f"PASS external_upload: {upload}",
            "PASS network: disabled unless CLIPFORGE_PLATFORM_LIVE_SMOKE=1",
            "PASS credentials: not stored in the database or artifacts",
        ]
    )


def capabilities_text() -> str:
    payload = DryRunPublisher().capabilities()
    return json.dumps(payload, sort_keys=True)


def dry_run_attempt(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    candidate_id: str,
    target: PublishTarget,
    *,
    publisher: Publisher | None = None,
    created_by: str = "publish",
) -> PublishAttempt:
    """Validate a target against the current package. This does not upload."""
    adapter = publisher or DryRunPublisher()
    request = _request(database, work_root, source_asset_id, candidate_id, target)
    try:
        adapter.dry_run(request)
    except (ValueError, TimeoutError) as exc:
        raise PublishError(_safe_error(exc), category="unsupported_destination") from exc
    return _store(
        database,
        work_root,
        request,
        "dry_run_passed",
        provider_version="dry-run-1",
        created_by=created_by,
        receipt=None,
    )


def submit_attempt(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    candidate_id: str,
    target: PublishTarget,
    *,
    publisher: Publisher | None = None,
    force: bool = False,
    created_by: str = "publish",
) -> PublishAttempt:
    """Submit only through an explicit publisher. The default CLI has none."""
    if publisher is None:
        if not live_upload_enabled():
            raise PublishError("external upload is not configured", category="not_configured")
        raise PublishError("no platform adapter is configured", category="not_configured")
    request = _request(database, work_root, source_asset_id, candidate_id, target)
    existing = _find_idempotent(database, request)
    if existing is not None and not force:
        if existing.state == "unknown":
            publisher.status(existing)
        return existing
    try:
        publisher.validate(request)
    except ValueError as exc:
        raise PublishError(_safe_error(exc), category="unsupported_destination") from exc
    attempt = _store(
        database,
        work_root,
        request,
        "uploading",
        provider_version="pending",
        created_by=created_by,
        receipt=None,
    )
    try:
        receipt = publisher.submit(request)
    except TimeoutError:
        return _update(database, work_root, attempt, "unknown", "timeout", None)
    except ValueError as exc:
        text = str(exc).lower()
        if any(token in text for token in ("bearer", "token", "password", "secret")):
            return _update(database, work_root, attempt, "failed", "secret_response", None)
        if "cancel" in text:
            return _update(database, work_root, attempt, "cancelled", "cancelled", None)
        return _update(database, work_root, attempt, "failed", "rejected", None)
    if not isinstance(receipt, PublishReceipt):
        return _update(database, work_root, attempt, "failed", "malformed_receipt", None)
    try:
        checked = PublishReceipt.model_validate(receipt.model_dump())
    except ValueError:
        return _update(database, work_root, attempt, "failed", "secret_response", None)
    if checked.manifest_sha256 != request.manifest_sha256 or checked.status != "published":
        return _update(database, work_root, attempt, "failed", "malformed_receipt", None)
    return _update(database, work_root, attempt, "published", "none", checked)


def cancel_attempt(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    attempt_id: str,
    *,
    publisher: Publisher | None = None,
) -> PublishAttempt:
    attempt = _load(database, work_root, source_asset_id, attempt_id)
    if attempt.state == "published":
        raise PublishError("a verified receipt cannot be cancelled into success", category="artifact_changed")
    adapter = publisher or FakePublisher()
    outcome = adapter.cancel(attempt)
    if outcome == "published":
        raise PublishError("cancellation must not report success", category="artifact_changed")
    return _update(database, work_root, attempt, "cancelled", "cancelled", None)


def status_attempt(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    attempt_id: str,
    *,
    publisher: Publisher | None = None,
) -> str:
    """Read an attempt. An unknown attempt is not submitted again."""
    attempt = _load(database, work_root, source_asset_id, attempt_id)
    adapter = publisher or DryRunPublisher()
    reported = adapter.status(attempt)
    if attempt.state == "unknown" and reported == "published":
        return "unknown"
    return (
        f"local delivery: passed\nexternal platform: {attempt.state}\n"
        f"provider_status: {reported}\nattempt_id: {attempt.attempt_id}"
    )


def recover_attempt(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    attempt_id: str,
    *,
    now: datetime | None = None,
    stale_after: timedelta = _STALE,
) -> str:
    attempt = _load(database, work_root, source_asset_id, attempt_id)
    if attempt.state != "uploading":
        raise PublishError("only an uploading attempt can be recovered", category="artifact_missing")
    moment = now or datetime.now(UTC)
    with database.connect() as connection:
        job = get_job(connection, _job_id(database, attempt))
    if moment - job.updated_at < stale_after:
        raise PublishError("uploading attempt is still fresh", category="artifact_changed")
    _update(database, work_root, attempt, "unknown", "recovered", None)
    _finish_job(database, job, "stale uploading attempt is unknown. It was not marked published.", moment)
    return attempt.attempt_id


def show_attempt(database: Database, work_root: Path, source_asset_id: str, attempt_id: str) -> str:
    attempt = _load(database, work_root, source_asset_id, attempt_id)
    label = "dry_run_passed" if attempt.state == "dry_run_passed" else attempt.state
    lines = [
        "local delivery: passed",
        f"external platform: {label}",
        f"attempt_id: {attempt.attempt_id}",
        f"state: {attempt.state}",
        f"manifest_sha256: {attempt.request.manifest_sha256}",
    ]
    if attempt.receipt is not None:
        lines.append(f"remote_item_id: {attempt.receipt.remote_item_id}")
    text = "\n".join(lines)
    if any(token in text.lower() for token in ("bearer ", "token=", "password=")):
        raise PublishError("attempt text contains a secret", category="unsafe_path")
    return text


def readiness_text(
    *,
    local_passed: bool,
    dry_run: str,
    project_id: str,
    source_asset_id: str,
) -> PublishReadiness:
    local = "passed" if local_passed else "blocked"
    upload = "not_configured" if not live_upload_enabled() else "not_run"
    overall = "blocked_for_external_publish" if local_passed else "blocked"
    return PublishReadiness(
        project_id=project_id,
        source_asset_id=source_asset_id,
        technical="passed" if local_passed else "blocked",
        editorial="passed" if local_passed else "blocked",
        rights="passed" if local_passed else "blocked",
        qa="passed" if local_passed else "blocked",
        local_delivery=local,  # type: ignore[arg-type]
        platform_adapter="passed",
        platform_dry_run=dry_run,  # type: ignore[arg-type]
        external_upload=upload,  # type: ignore[arg-type]
        real_source_verified="unavailable",
        voicestudio="unavailable",
        overall=overall,  # type: ignore[arg-type]
        reason="no authorized source supplied",
    )


def _request(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    candidate_id: str,
    target: PublishTarget,
) -> PublishRequest:
    from clipforge.publish.service import _find_document, _manifest_path, _package_ok

    root = work_root.resolve()
    document = _find_document(database, root, source_asset_id, target.delivery_id)
    if document is None:
        raise PublishError("local delivery is missing", category="artifact_missing")
    if document.candidate_id != candidate_id:
        raise PublishError("local delivery candidate does not match", category="candidate_missing")
    manifest = _manifest_path(root, document.delivery_id)
    if not _package_ok(root, document, manifest):
        raise PublishError("local delivery package changed", category="artifact_changed")
    from clipforge.media.hashing import sha256_file

    manifest_sha = sha256_file(manifest)
    if target.manifest_sha256 != manifest_sha:
        raise PublishError("local delivery manifest hash changed", category="artifact_changed")
    try:
        verify_delivery(database, root, source_asset_id, document.delivery_id)
    except PublishError:
        raise
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
        project = get_project(connection, source.project_id)
    profile_id = project.profile_id or "unprofiled"
    now = datetime.now(UTC)
    try:
        return PublishRequest(
            request_id=str(uuid4()),
            project_id=source.project_id,
            source_asset_id=source_asset_id,
            source_sha256=document.source_sha256,
            candidate_id=candidate_id,
            delivery_id=document.delivery_id,
            manifest_sha256=manifest_sha,
            advanced_artifact_sha256=document.advanced_artifact_sha256,
            qa_set_id=document.qa_set_id,
            qa_set_sha256=document.qa_set_sha256,
            approval_review_id=document.approval_review_id,
            campaign_profile_id=profile_id,
            idempotency_key=_idempotency(target, manifest_sha),
            created_at=now,
            target=target.model_copy(
                update={
                    "delivery_id": document.delivery_id,
                    "manifest_sha256": manifest_sha,
                    "campaign_id": profile_id,
                }
            ),
        )
    except ValueError as exc:
        raise PublishError(_safe_error(exc), category="unsafe_path") from exc


def _idempotency(target: PublishTarget, manifest_sha: str) -> str:
    import hashlib

    raw = json.dumps(
        {
            "platform": target.platform,
            "account_label": target.account_label,
            "destination_id": target.destination_id,
            "manifest_sha256": manifest_sha,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _store(
    database: Database,
    work_root: Path,
    request: PublishRequest,
    state: str,
    *,
    provider_version: str,
    created_by: str,
    receipt: PublishReceipt | None,
) -> PublishAttempt:
    now = datetime.now(UTC)
    attempt_id = str(uuid4())
    attempt = PublishAttempt(
        attempt_id=attempt_id,
        request=request,
        state=state,  # type: ignore[arg-type]
        provider_version=provider_version,
        error_category="none",
        receipt=receipt,
        created_at=now,
        updated_at=now,
    )
    path = _attempt_path(work_root, attempt_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _job_payload(attempt)
    job_status = JobStatus.SUCCEEDED if state in {"dry_run_passed", "published"} else JobStatus.RUNNING
    if state in {"failed", "cancelled", "unknown"}:
        job_status = JobStatus.FAILED if state == "failed" else JobStatus.CANCELLED
    error = None
    if job_status is JobStatus.FAILED:
        error = attempt.error_category
    job = JobRecord(
        job_id=str(uuid4()),
        project_id=request.project_id,
        kind=JOB,
        status=job_status,
        created_at=now,
        updated_at=now,
        error_message=error,
        payload=payload,
    )
    text = attempt.model_dump_json()
    _reject_secrets(text)
    with database.transaction() as connection:
        insert_job(connection, job)
        insert_artifact(
            connection,
            artifact_id=attempt_id,
            project_id=request.project_id,
            job_id=job.job_id,
            source_asset_id=request.source_asset_id,
            kind=KIND,
            uri=path.resolve().as_uri(),
            provenance=ArtifactProvenance(
                created_at=now,
                created_by=created_by,
                tool="clipforge-platform",
                tool_version="0.1.0",
                source_asset_ids=[request.source_asset_id],
                job_id=job.job_id,
                inputs_sha256=request.manifest_sha256,
            ),
        )
        path.write_text(text + "\n", encoding="utf-8")
    return attempt


def _update(
    database: Database,
    work_root: Path,
    attempt: PublishAttempt,
    state: str,
    category: str,
    receipt: PublishReceipt | None,
) -> PublishAttempt:
    updated = attempt.model_copy(
        update={
            "state": state,
            "error_category": category,
            "receipt": receipt,
            "provider_version": "fake-1" if receipt is not None else attempt.provider_version,
            "updated_at": datetime.now(UTC),
        }
    )
    text = updated.model_dump_json()
    _reject_secrets(text)
    path = _attempt_path(work_root, attempt.attempt_id)
    path.write_text(text + "\n", encoding="utf-8")
    with database.connect() as connection:
        source = get_source_asset(connection, attempt.request.source_asset_id)
        jobs = [
            job
            for job in list_jobs(connection, source.project_id)
            if job.kind == JOB and job.payload.get("attempt_id") == attempt.attempt_id
        ]
    if jobs:
        job = jobs[-1]
        status = JobStatus.SUCCEEDED if state == "published" else JobStatus.FAILED
        if state == "cancelled":
            status = JobStatus.CANCELLED
        if state == "unknown":
            status = JobStatus.FAILED
        error = None if status is JobStatus.SUCCEEDED else f"publish attempt is {state}"
        if state == "unknown":
            error = "publish attempt is unknown. It was not marked published."
        replaced = job.model_copy(
            update={
                "status": status,
                "updated_at": datetime.now(UTC),
                "error_message": error,
                "payload": _job_payload(updated),
            }
        )
        with database.transaction() as connection:
            update_job(connection, replaced)
    return updated


def _load(database: Database, work_root: Path, source_asset_id: str, attempt_id: str) -> PublishAttempt:
    path = _attempt_path(work_root, attempt_id)
    if path.is_symlink() or not path.is_file():
        raise PublishError("publish attempt is missing", category="artifact_missing")
    try:
        attempt = PublishAttempt.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PublishError("publish attempt could not be read", category="artifact_missing") from exc
    if attempt.request.source_asset_id != source_asset_id:
        raise PublishError("publish attempt belongs to another source", category="artifact_changed")
    with database.connect() as connection:
        try:
            get_source_asset(connection, source_asset_id)
        except StorageError as exc:
            raise PublishError("source does not exist", category="source_changed") from exc
    return attempt


def _find_idempotent(database: Database, request: PublishRequest) -> PublishAttempt | None:
    root_jobs: list[JobRecord]
    with database.connect() as connection:
        root_jobs = [
            job
            for job in list_jobs(connection, request.project_id)
            if job.kind == JOB and job.payload.get("idempotency_key") == request.idempotency_key
        ]
        rows = list_artifacts_for_source(connection, request.project_id, request.source_asset_id)
    if not root_jobs:
        return None
    wanted = {job.payload.get("attempt_id") for job in root_jobs}
    for row in rows:
        if row.kind != KIND or row.artifact_id not in wanted:
            continue
        if not row.uri.startswith("file:"):
            continue
        from clipforge.media.local_file import path_from_file_uri

        path = path_from_file_uri(row.uri)
        if path.is_symlink() or not path.is_file():
            continue
        try:
            attempt = PublishAttempt.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        same_key = attempt.request.idempotency_key == request.idempotency_key
        same_manifest = attempt.request.manifest_sha256 == request.manifest_sha256
        if same_key and same_manifest and attempt.state != "dry_run_passed":
            return attempt
    return None


def _job_payload(attempt: PublishAttempt) -> dict[str, str]:
    return {
        "source_asset_id": attempt.request.source_asset_id,
        "source_sha256": attempt.request.source_sha256,
        "candidate_id": attempt.request.candidate_id,
        "delivery_id": attempt.request.delivery_id,
        "manifest_sha256": attempt.request.manifest_sha256,
        "idempotency_key": attempt.request.idempotency_key,
        "attempt_id": attempt.attempt_id,
        "state": attempt.state,
        "platform": attempt.request.target.platform,
        "account_label": attempt.request.target.account_label,
    }


def _job_id(database: Database, attempt: PublishAttempt) -> str:
    with database.connect() as connection:
        source = get_source_asset(connection, attempt.request.source_asset_id)
        jobs = [
            job
            for job in list_jobs(connection, source.project_id)
            if job.payload.get("attempt_id") == attempt.attempt_id
        ]
    if not jobs:
        raise PublishError("publish job is missing", category="artifact_missing")
    return jobs[-1].job_id


def _finish_job(database: Database, job: JobRecord, message: str, moment: datetime) -> None:
    updated = job.model_copy(
        update={
            "status": JobStatus.FAILED,
            "updated_at": moment,
            "error_message": message[:2000],
        }
    )
    with database.transaction() as connection:
        update_job(connection, updated)


def _attempt_path(work_root: Path, attempt_id: str) -> Path:
    if "/" in attempt_id or "\\" in attempt_id or attempt_id in {"", ".", ".."}:
        raise PublishError("attempt id is not safe", category="unsafe_path")
    return work_root.resolve() / "platform" / attempt_id / "attempt.json"


def _safe_error(exc: BaseException) -> str:
    text = str(exc)
    lowered = text.lower()
    if any(token in lowered for token in ("bearer", "token", "password", "secret", "api_key")):
        return "publish request was rejected because it contained a secret"
    return text[:300]


def _reject_secrets(text: str) -> None:
    lowered = text.lower()
    if any(token in lowered for token in ("bearer ", "password=", "token=", "api_key", "authorization:")):
        raise PublishError("refusing to store a secret in a publish attempt", category="unsafe_path")


def _list_attempt_lines(database: Database, work_root: Path, source_asset_id: str) -> list[str]:
    del work_root
    try:
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
            rows = list_artifacts_for_source(connection, source.project_id, source_asset_id)
    except (ClipforgeError, StorageError):
        return []
    lines: list[str] = []
    for row in rows:
        if row.kind != KIND or not row.uri.startswith("file:"):
            continue
        from clipforge.media.local_file import path_from_file_uri

        path = path_from_file_uri(row.uri)
        if path.is_symlink() or not path.is_file():
            continue
        try:
            attempt = PublishAttempt.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        lines.append(f"attempt\t{attempt.attempt_id}\t{attempt.state}")
    return lines
