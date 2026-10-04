"""Build, verify, and recover a local delivery package. This does not upload."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from clipforge import __version__
from clipforge.errors import ClipforgeError, MediaError, StorageError
from clipforge.jobs.promote import PromotionError, promote
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri, path_to_file_uri
from clipforge.media.workspace import (
    SourceWorkspace,
    _mkdir_contained,
    advanced_read_lock,
    candidate_read_lock,
    ensure_within,
    hero_read_lock,
    prepare_read_lock,
    preview_read_lock,
    publish_lock,
    qa_read_lock,
    transcribe_read_lock,
    vision_read_lock,
)
from clipforge.publish.errors import EXTERNAL_PUBLISHING, PublishError
from clipforge.publish.preflight import DeliveryFacts, cache_fingerprint, preflight_delivery
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.publish import (
    PublishCacheRecord,
    PublishExportInput,
    PublishFile,
    PublishPackageDocument,
    PublishReadinessReport,
)
from clipforge.storage import (
    Database,
    get_job,
    get_source_asset,
    insert_artifact,
    insert_job,
    list_artifacts_for_source,
    list_jobs,
    update_job,
)

KIND = "publish_package_json"
JOB = "publish_export"
PROFILE_ID = "local-delivery-v1"
_STALE_AFTER = timedelta(minutes=15)
_FORBIDDEN = ("/tmp/", "/home/", "/users/", "://", "\\", "bearer ", "password=", "viewer_id", "token=")


@dataclass(frozen=True, slots=True)
class ExportResult:
    """A finished local package or a verified cache hit."""

    delivery_id: str
    status: str
    manifest_sha256: str
    job_id: str | None
    artifact_id: str
    video_sha256: str
    video_size: int
    relative_package: str


def doctor_text() -> str:
    """Report exporter, filesystem policy, and ffprobe. No network and no upload."""
    ffprobe = shutil.which("ffprobe")
    probe = "PASS ffprobe: present" if ffprobe else "FAIL ffprobe: missing"
    lines = [
        "PASS exporter: local-delivery-v1",
        "PASS filesystem: work-root-relative delivery packages",
        probe,
        "PASS external_publishing: not_implemented",
        "PASS voicestudio: not required unless narration is requested",
    ]
    return "\n".join(lines)


def doctor_ok() -> bool:
    return shutil.which("ffprobe") is not None


def plan_delivery(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    candidate_id: str,
    *,
    destination: str = "local",
    include_narration: bool = False,
    narration_artifact_id: str | None = None,
) -> str:
    """Read-only preflight. This writes no job and copies no media."""
    facts = preflight_delivery(
        database,
        work_root,
        source_asset_id,
        candidate_id,
        destination=destination,
        include_narration=include_narration,
        narration_artifact_id=narration_artifact_id,
        probe=True,
    )
    payload = PublishExportInput(
        project_id=facts.project_id,
        source_asset_id=facts.source_asset_id,
        candidate_id=facts.candidate_id,
        include_narration=include_narration,
        narration_artifact_id=narration_artifact_id,
        profile_fingerprint=facts.profile_fingerprint,
        force=False,
    )
    text = payload.model_dump_json()
    _reject_public(text)
    return text


def export_delivery(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    candidate_id: str,
    *,
    destination: str = "local",
    include_narration: bool = False,
    narration_artifact_id: str | None = None,
    force: bool = False,
    created_by: str = "publish",
    copy_hook: Callable[[], None] | None = None,
    commit_hook: Callable[[], None] | None = None,
    sidecar_hook: Callable[[], None] | None = None,
) -> ExportResult:
    """Copy a verified Advanced Hero package. A failed preflight inserts no job."""
    if destination != "local":
        raise PublishError(EXTERNAL_PUBLISHING, category="unsupported_destination")
    root = work_root.resolve()
    facts = preflight_delivery(
        database,
        root,
        source_asset_id,
        candidate_id,
        destination=destination,
        include_narration=include_narration,
        narration_artifact_id=narration_artifact_id,
        probe=False,
    )
    fingerprint = cache_fingerprint(facts)
    if not force:
        hit = _cache_hit(database, root, facts.project_id, source_asset_id, fingerprint)
        if hit is not None:
            return hit
    _prepare_dirs(root)
    try:
        facts.workspace.ensure()
    except MediaError as exc:
        raise PublishError(_clean(root, exc), category="unsafe_path") from exc
    with _export_locks(facts.workspace):
        facts = preflight_delivery(
            database,
            root,
            source_asset_id,
            candidate_id,
            destination=destination,
            include_narration=include_narration,
            narration_artifact_id=narration_artifact_id,
            probe=True,
        )
        fingerprint = cache_fingerprint(facts)
        if not force:
            hit = _cache_hit(database, root, facts.project_id, source_asset_id, fingerprint)
            if hit is not None:
                return hit
        delivery_id = _delivery_id(root, fingerprint, force=force)
        job = _running_job(
            facts, delivery_id, fingerprint, include_narration, narration_artifact_id, created_by
        )
        with database.transaction() as connection:
            insert_job(connection, job)
        staging = _staging(root, delivery_id)
        try:
            document, record = _stage(root, staging, facts, delivery_id, fingerprint, job, created_by)
            if copy_hook is not None:
                copy_hook()
        except PublishError as exc:
            status = JobStatus.CANCELLED if exc.category == "cancelled" else JobStatus.FAILED
            _finish_job(database, job, status, str(exc))
            _discard_tree(root, staging)
            raise
        except KeyboardInterrupt:
            _finish_job(database, job, JobStatus.CANCELLED, "delivery export was cancelled")
            _discard_tree(root, staging)
            raise
        except (OSError, MediaError, StorageError, ValueError, RuntimeError) as exc:
            _finish_job(database, job, JobStatus.FAILED, _clean(root, exc))
            _discard_tree(root, staging)
            raise PublishError(_clean(root, exc), category="artifact_changed") from exc
        return _promote(
            database,
            root,
            facts,
            job,
            document,
            record,
            staging,
            commit_hook=commit_hook,
            sidecar_hook=sidecar_hook,
        )


def list_deliveries(database: Database, work_root: Path, source_asset_id: str) -> str:
    """List local packages. This does not write."""
    root = work_root.resolve()
    rows = _packages(database, root, source_asset_id)
    if not rows:
        return "No local delivery packages are stored for this source."
    lines = []
    for delivery_id, digest, status in rows:
        lines.append(f"{delivery_id}\t{status}\t{digest}")
    return "\n".join(lines)


def show_delivery(database: Database, work_root: Path, source_asset_id: str, delivery_id: str) -> str:
    """Print one public manifest. This does not write."""
    document = _require_package(database, work_root.resolve(), source_asset_id, delivery_id)
    text = document.model_dump_json()
    _reject_public(text)
    return text


def verify_delivery(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    delivery_id: str,
    *,
    destination: str = "local",
) -> str:
    """Re-check one package. This does not write a job or replace bytes."""
    root = work_root.resolve()
    document = _require_package(database, root, source_asset_id, delivery_id)
    facts = preflight_delivery(
        database,
        root,
        source_asset_id,
        document.candidate_id,
        destination=destination,
        include_narration=document_has_narration(document),
        narration_artifact_id=None
        if not document_has_narration(document)
        else _narration_id(database, document),
        probe=True,
    )
    if cache_fingerprint(facts) != document.cache_fingerprint:
        raise PublishError("delivery no longer matches the current advanced Hero", category="artifact_changed")
    manifest = _manifest_path(root, delivery_id)
    if not _package_ok(root, document, manifest):
        raise PublishError("delivery package bytes do not match the manifest", category="artifact_changed")
    return f"PASS delivery {delivery_id}"


def recover_delivery(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    delivery_id: str,
    *,
    now: datetime | None = None,
    stale_after: timedelta = _STALE_AFTER,
) -> str:
    """Mark a stale running export failed. Incomplete work is not promoted."""
    root = work_root.resolve()
    _safe_id(delivery_id)
    moment = now or datetime.now(UTC)
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
        jobs = [
            job
            for job in list_jobs(connection, source.project_id)
            if job.kind == JOB and job.payload.get("delivery_id") == delivery_id
        ]
    if not jobs:
        raise PublishError("delivery job is missing", category="artifact_missing")
    changed: list[str] = []
    for job in jobs:
        if job.status is not JobStatus.RUNNING:
            continue
        if moment - job.updated_at < stale_after:
            continue
        _finish_job(
            database,
            job,
            JobStatus.FAILED,
            "stale running delivery was recovered from updated_at. It was not marked succeeded.",
            moment=moment,
        )
        changed.append(job.job_id)
    _discard_tree(root, _staging(root, delivery_id))
    if not changed:
        raise PublishError("no stale running delivery job was recovered", category="artifact_missing")
    return "\n".join(changed)


def resume_delivery(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    delivery_id: str,
    *,
    created_by: str = "publish",
) -> ExportResult:
    """Start a new attempt only when the previous package is not a verified success."""
    root = work_root.resolve()
    document = _find_document(database, root, source_asset_id, delivery_id)
    if document is not None and _package_ok(root, document, _manifest_path(root, delivery_id)):
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
            jobs = [
                job
                for job in list_jobs(connection, source.project_id)
                if job.payload.get("delivery_id") == delivery_id and job.kind == JOB
            ]
        if any(job.status is JobStatus.SUCCEEDED for job in jobs):
            raise PublishError("delivery is a verified success and was not resumed", category="cache_hit")
    include = False
    narration_id: str | None = None
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
        previous = [
            job
            for job in list_jobs(connection, source.project_id)
            if job.kind == JOB and job.payload.get("delivery_id") == delivery_id
        ]
    if previous:
        latest = max(previous, key=lambda job: (job.updated_at, job.job_id))
        if latest.status is JobStatus.RUNNING:
            raise PublishError(
                "delivery job is still running. Recover it before resuming.", category="artifact_changed"
            )
        include = latest.payload.get("include_narration") == "1"
        raw_narration = latest.payload.get("narration_artifact_id", "-")
        narration_id = None if raw_narration in {"", "-"} else raw_narration
    candidate_id = document.candidate_id if document is not None else _candidate_from_jobs(previous)
    return export_delivery(
        database,
        root,
        source_asset_id,
        candidate_id,
        include_narration=include,
        narration_artifact_id=narration_id,
        force=True,
        created_by=created_by,
    )


def observe_stage(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    candidate_id: str | None,
) -> dict[str, str | bool | None]:
    """Classify the delivery stage without copying media or calling ffmpeg."""
    if not candidate_id:
        return _observed("blocked", "candidate_missing", cache_hit=False)
    try:
        facts = preflight_delivery(
            database,
            work_root,
            source_asset_id,
            candidate_id,
            probe=False,
        )
    except PublishError as exc:
        return _observed("blocked", exc.category, cache_hit=False)
    hit = _cache_hit(
        database,
        work_root.resolve(),
        facts.project_id,
        source_asset_id,
        cache_fingerprint(facts),
    )
    if hit is None:
        return _observed("blocked", "not_exported", cache_hit=False)
    return _observed(
        "passed",
        "none",
        cache_hit=True,
        delivery_id=hit.delivery_id,
        manifest_sha256=hit.manifest_sha256,
        artifact_id=hit.artifact_id,
        job_id=hit.job_id,
        classification="local_delivery_ready",
    )


def delivery_readiness(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    candidate_id: str,
) -> PublishReadinessReport:
    """Report local delivery separately from platform publishing."""
    root = work_root.resolve()
    category = "none"
    facts: DeliveryFacts | None
    try:
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
        project_id = source.project_id
    except StorageError as exc:
        raise PublishError("source does not exist", category="source_changed") from exc
    try:
        facts = preflight_delivery(database, root, source_asset_id, candidate_id, probe=False)
    except PublishError as exc:
        facts = None
        category = exc.category
    verified = None
    if facts is not None:
        verified = _cache_hit(database, root, facts.project_id, source_asset_id, cache_fingerprint(facts))
        if verified is None:
            category = "not_exported"
    local = "passed" if verified is not None else "blocked"
    axes = _axes(category, facts is not None, local == "passed")
    overall = "passed" if local == "passed" and all(value == "passed" for value in axes.values()) else "blocked"
    limitations = [
        EXTERNAL_PUBLISHING,
        "no authorized source supplied",
        "analytics evidence does not approve, optimize, or publish content",
    ]
    return PublishReadinessReport(
        project_id=project_id,
        source_asset_id=source_asset_id,
        candidate_id=candidate_id,
        delivery_id=None if verified is None else verified.delivery_id,
        technical=axes["technical"],  # type: ignore[arg-type]
        editorial=axes["editorial"],  # type: ignore[arg-type]
        rights=axes["rights"],  # type: ignore[arg-type]
        qa=axes["qa"],  # type: ignore[arg-type]
        local_delivery=local,  # type: ignore[arg-type]
        platform_publishing="not_implemented",
        voicestudio=_voice_state(),  # type: ignore[arg-type]
        real_source_verified="unavailable",
        real_source_reason="no authorized source supplied",
        overall=overall,  # type: ignore[arg-type]
        failure_category=category,
        limitations=limitations,
    )


def document_has_narration(document: PublishPackageDocument) -> bool:
    return any(item.role == "narration" for item in document.files)


def _voice_state() -> str:
    url = os.environ.get("CLIPFORGE_VOICESTUDIO_URL", "").strip()
    live = os.environ.get("CLIPFORGE_VOICESTUDIO_LIVE_SMOKE", "").strip()
    if url and live == "1":
        return "not_run"
    return "unavailable"


def _axes(category: str, preflight_ok: bool, delivered: bool) -> dict[str, str]:
    if preflight_ok and delivered:
        return {"technical": "passed", "editorial": "passed", "rights": "passed", "qa": "passed"}
    if preflight_ok:
        return {"technical": "passed", "editorial": "passed", "rights": "passed", "qa": "passed"}
    axes = {"technical": "blocked", "editorial": "blocked", "rights": "blocked", "qa": "blocked"}
    if category == "qa_failed":
        axes["qa"] = "failed"
    elif category.startswith("qa_"):
        axes["qa"] = "blocked"
    elif category.startswith("approval"):
        axes["editorial"] = "blocked"
    elif category == "rights_blocked":
        axes["rights"] = "blocked"
    else:
        axes["technical"] = "blocked"
    return axes


def _observed(
    status: str,
    category: str,
    *,
    cache_hit: bool,
    delivery_id: str | None = None,
    manifest_sha256: str | None = None,
    artifact_id: str | None = None,
    job_id: str | None = None,
    classification: str = "blocked",
) -> dict[str, str | bool | None]:
    return {
        "status": status,
        "error_category": category,
        "cache_hit": cache_hit,
        "delivery_id": delivery_id,
        "manifest_sha256": manifest_sha256,
        "artifact_id": artifact_id,
        "job_id": job_id,
        "readiness_classification": classification if status == "passed" else "blocked",
    }


@contextmanager
def _export_locks(workspace: SourceWorkspace) -> Iterator[None]:
    with (
        prepare_read_lock(workspace),
        transcribe_read_lock(workspace),
        vision_read_lock(workspace),
        candidate_read_lock(workspace),
        preview_read_lock(workspace),
        hero_read_lock(workspace),
        advanced_read_lock(workspace),
        qa_read_lock(workspace),
        publish_lock(workspace),
    ):
        yield


def _prepare_dirs(root: Path) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True)
        _mkdir_contained(root, root / "deliveries")
        _mkdir_contained(root, root / "deliveries" / "current")
    except MediaError as exc:
        raise PublishError(_clean(root, exc), category="unsafe_path") from exc


def _delivery_id(root: Path, fingerprint: str, *, force: bool) -> str:
    if not force:
        candidate = fingerprint[:32]
        path = root / "deliveries" / candidate
        if not path.exists() and not path.is_symlink():
            return candidate
    return hashlib.sha256(f"{fingerprint}:{uuid4().hex}".encode()).hexdigest()[:32]


def _running_job(
    facts: DeliveryFacts,
    delivery_id: str,
    fingerprint: str,
    include_narration: bool,
    narration_artifact_id: str | None,
    created_by: str,
) -> JobRecord:
    del created_by
    now = datetime.now(UTC)
    return JobRecord(
        job_id=str(uuid4()),
        project_id=facts.project_id,
        kind=JOB,
        status=JobStatus.RUNNING,
        created_at=now,
        updated_at=now,
        payload={
            "source_asset_id": facts.source_asset_id,
            "source_sha256": facts.source_sha256,
            "candidate_id": facts.candidate_id,
            "delivery_id": delivery_id,
            "cache_fingerprint": fingerprint,
            "profile_fingerprint": facts.profile_fingerprint,
            "destination": "local",
            "include_narration": "1" if include_narration else "0",
            "narration_artifact_id": narration_artifact_id or "-",
        },
    )


def _stage(
    root: Path,
    staging: Path,
    facts: DeliveryFacts,
    delivery_id: str,
    fingerprint: str,
    job: JobRecord,
    created_by: str,
) -> tuple[PublishPackageDocument, PublishCacheRecord]:
    try:
        _mkdir_contained(root, staging)
        _mkdir_contained(root, staging / "candidates")
        _mkdir_contained(root, staging / "candidates" / facts.candidate_id)
    except MediaError as exc:
        raise PublishError(_clean(root, exc), category="unsafe_path") from exc
    video_name = f"candidates/{facts.candidate_id}/video.mp4"
    metadata_name = f"candidates/{facts.candidate_id}/metadata.json"
    _copy_exact(facts.video_path, staging / video_name, facts.video_sha256, facts.video_size)
    cues = facts.caption_cues if _cues_safe(facts.caption_cues) else ()
    caption_mode = "authoritative" if cues else "embedded_or_unavailable"
    if cues:
        srt_name = f"candidates/{facts.candidate_id}/captions.srt"
        vtt_name = f"candidates/{facts.candidate_id}/captions.vtt"
        (staging / srt_name).write_text(_srt(cues), encoding="utf-8")
        (staging / vtt_name).write_text(_vtt(cues), encoding="utf-8")
    narration_name: str | None = None
    if facts.narration_path is not None and facts.narration_sha256 is not None:
        narration_name = f"candidates/{facts.candidate_id}/narration.wav"
        _copy_exact(
            facts.narration_path,
            staging / narration_name,
            facts.narration_sha256,
            facts.narration_path.stat().st_size,
        )
    metadata = _metadata(facts, caption_mode)
    metadata_text = json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _reject_public(metadata_text)
    (staging / metadata_name).write_text(metadata_text, encoding="utf-8")
    files = [
        _file(root, staging, delivery_id, video_name, "video"),
        _file(root, staging, delivery_id, metadata_name, "metadata"),
    ]
    if cues:
        files.append(_file(root, staging, delivery_id, srt_name, "captions_srt"))
        files.append(_file(root, staging, delivery_id, vtt_name, "captions_vtt"))
    if narration_name is not None:
        files.append(_file(root, staging, delivery_id, narration_name, "narration"))
    now = datetime.now(UTC)
    document = PublishPackageDocument(
        delivery_id=delivery_id,
        project_id=facts.project_id,
        source_asset_id=facts.source_asset_id,
        source_sha256=facts.source_sha256,
        candidate_id=facts.candidate_id,
        candidate_rank=facts.candidate_rank,
        candidate_set_id=facts.candidate_set_id,
        candidate_set_sha256=facts.candidate_set_sha256,
        advanced_set_id=facts.advanced_set_id,
        advanced_set_sha256=facts.advanced_set_sha256,
        advanced_artifact_id=facts.advanced_artifact_id,
        advanced_artifact_sha256=facts.advanced_artifact_sha256,
        advanced_artifact_size_bytes=facts.advanced_artifact_size,
        advanced_plan_id=facts.advanced_plan_id,
        advanced_plan_sha256=facts.advanced_plan_sha256,
        alignment_id=facts.alignment_id,
        alignment_sha256=facts.alignment_sha256,
        qa_set_id=facts.qa_set_id,
        qa_set_sha256=facts.qa_set_sha256,
        approval_review_id=facts.approval_review_id,
        profile_fingerprint=facts.profile_fingerprint,
        caption_mode=caption_mode,  # type: ignore[arg-type]
        cache_fingerprint=fingerprint,
        files=files,
        created_at=now,
    )
    _reject_public(document.model_dump_json())
    manifest = staging / "manifest.json"
    manifest.write_text(document.model_dump_json(indent=2) + "\n", encoding="utf-8")
    PublishPackageDocument.model_validate_json(manifest.read_text(encoding="utf-8"))
    checksum = staging / "checksums.sha256"
    checksum.write_text(_checksum_text(staging, document), encoding="utf-8")
    if not _checksums_match(staging, document, checksum):
        raise PublishError("checksum file does not match the staged bytes", category="artifact_changed")
    artifact_id = str(uuid4())
    record = PublishCacheRecord(
        project_id=facts.project_id,
        source_asset_id=facts.source_asset_id,
        delivery_id=delivery_id,
        job_id=job.job_id,
        artifact_id=artifact_id,
        source_sha256=facts.source_sha256,
        candidate_id=facts.candidate_id,
        candidate_set_id=facts.candidate_set_id,
        candidate_set_sha256=facts.candidate_set_sha256,
        advanced_set_id=facts.advanced_set_id,
        advanced_set_sha256=facts.advanced_set_sha256,
        advanced_artifact_sha256=facts.advanced_artifact_sha256,
        advanced_artifact_size_bytes=facts.advanced_artifact_size,
        video_sha256=facts.video_sha256,
        video_size_bytes=facts.video_size,
        plan_sha256=facts.advanced_plan_sha256,
        alignment_sha256=facts.alignment_sha256,
        qa_set_id=facts.qa_set_id,
        qa_set_sha256=facts.qa_set_sha256,
        approval_review_id=facts.approval_review_id,
        profile_fingerprint=facts.profile_fingerprint,
        cache_fingerprint=fingerprint,
        manifest_sha256=sha256_file(manifest),
        manifest_size_bytes=manifest.stat().st_size,
        checksum_sha256=sha256_file(checksum),
        checksum_size_bytes=checksum.stat().st_size,
        files=files,
        created_at=now,
    )
    _reject_public(record.model_dump_json())
    del created_by
    return document, record


def _promote(
    database: Database,
    root: Path,
    facts: DeliveryFacts,
    job: JobRecord,
    document: PublishPackageDocument,
    record: PublishCacheRecord,
    staging: Path,
    *,
    commit_hook: Callable[[], None] | None,
    sidecar_hook: Callable[[], None] | None,
) -> ExportResult:
    final = root / "deliveries" / document.delivery_id
    sidecar = _sidecar_path(root, facts.source_asset_id)
    previous = sidecar.read_bytes() if sidecar.is_file() and not sidecar.is_symlink() else None
    created = False
    manifest = final / "manifest.json"

    def write_output() -> None:
        return None

    def write_manifest() -> None:
        PublishPackageDocument.model_validate_json((staging / "manifest.json").read_text(encoding="utf-8"))

    def commit_database() -> None:
        nonlocal created
        succeeded = _succeeded_job(job, record.manifest_sha256)
        provenance = ArtifactProvenance(
            created_at=record.created_at,
            created_by="publish",
            tool="clipforge-publish",
            tool_version=__version__,
            source_asset_ids=[facts.source_asset_id],
            parent_artifact_ids=[facts.advanced_artifact_id],
            job_id=job.job_id,
            inputs_sha256=facts.advanced_artifact_sha256,
        )
        with database.transaction() as connection:
            if final.exists() or final.is_symlink():
                raise PublishError("delivery directory already exists", category="artifact_changed")
            staging.rename(final)
            created = True
            if not _package_ok(root, document, manifest):
                raise PublishError(
                    "promoted delivery bytes do not match the manifest", category="artifact_changed"
                )
            update_job(connection, succeeded)
            insert_artifact(
                connection,
                artifact_id=record.artifact_id,
                project_id=facts.project_id,
                job_id=job.job_id,
                source_asset_id=facts.source_asset_id,
                kind=KIND,
                uri=path_to_file_uri(manifest),
                provenance=provenance,
            )
            _write_bytes(sidecar, (record.model_dump_json(indent=2) + "\n").encode("utf-8"))
            if commit_hook is not None:
                commit_hook()
            if sidecar_hook is not None:
                sidecar_hook()

    def rollback() -> None:
        nonlocal created
        if staging.exists() or staging.is_symlink():
            _discard_tree(root, staging)
        if created:
            _discard_tree(root, final)
            created = False
        if previous is None:
            if sidecar.is_symlink() or sidecar.is_file():
                sidecar.unlink()
        else:
            _write_bytes(sidecar, previous)
        _finish_job(
            database, job, JobStatus.FAILED, "delivery promotion failed. The previous package was restored."
        )

    try:
        promote(
            write_output=write_output,
            write_manifest=write_manifest,
            commit_database=commit_database,
            write_sidecar=lambda: None,
            rollback_database=rollback,
        )
    except PromotionError as exc:
        raise PublishError(
            "delivery package was not published. The previous package was kept.", category="artifact_changed"
        ) from exc
    stored = sha256_file(manifest)
    return ExportResult(
        document.delivery_id,
        "succeeded",
        stored,
        job.job_id,
        record.artifact_id,
        facts.video_sha256,
        facts.video_size,
        f"deliveries/{document.delivery_id}",
    )


def _cache_hit(
    database: Database,
    root: Path,
    project_id: str,
    source_asset_id: str,
    fingerprint: str,
) -> ExportResult | None:
    with database.connect() as connection:
        rows = [
            row
            for row in list_artifacts_for_source(connection, project_id, source_asset_id)
            if row.kind == KIND
        ]
    for row in rows:
        manifest = _contained_file(root, row.uri)
        if manifest is None:
            continue
        try:
            document = PublishPackageDocument.model_validate_json(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        if document.cache_fingerprint != fingerprint:
            continue
        if not _package_ok(root, document, manifest):
            continue
        with database.connect() as connection:
            if row.job_id is None:
                continue
            try:
                job = get_job(connection, row.job_id)
            except StorageError:
                continue
        if job.status is not JobStatus.SUCCEEDED:
            continue
        video = next(item for item in document.files if item.role == "video")
        return ExportResult(
            document.delivery_id,
            "cache_hit",
            sha256_file(manifest),
            job.job_id,
            row.artifact_id,
            video.sha256,
            video.size_bytes,
            f"deliveries/{document.delivery_id}",
        )
    return None


def _package_ok(root: Path, document: PublishPackageDocument, manifest: Path) -> bool:
    if manifest.is_symlink() or not manifest.is_file():
        return False
    package = manifest.parent
    if package.is_symlink():
        return False
    for item in document.files:
        path = _relative_file(root, item.relative_path)
        if path is None or path.stat().st_size != item.size_bytes or sha256_file(path) != item.sha256:
            return False
    checksum = package / "checksums.sha256"
    return _checksums_match(package, document, checksum)


def _checksums_match(package: Path, document: PublishPackageDocument, checksum: Path) -> bool:
    path = _relative_inside(package, checksum)
    if path is None:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return text == _checksum_text(package, document)


def _checksum_text(package: Path, document: PublishPackageDocument) -> str:
    entries = [("manifest.json", sha256_file(package / "manifest.json"))]
    for item in document.files:
        prefix = f"deliveries/{document.delivery_id}/"
        if not item.relative_path.startswith(prefix):
            raise PublishError("delivery file path is not inside the package", category="unsafe_path")
        relative = item.relative_path[len(prefix) :]
        file_path = package / relative
        if file_path.is_symlink() or not file_path.is_file():
            raise PublishError("delivery file is missing", category="artifact_missing")
        entries.append((relative, sha256_file(file_path)))
    lines = [f"{digest}  {relative}\n" for relative, digest in sorted(entries)]
    return "".join(lines)


def _metadata(facts: DeliveryFacts, caption_mode: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "approval_review_id": facts.approval_review_id,
        "audio_codec": facts.audio_codec,
        "broll": [{"asset_id": asset_id, "sha256": digest} for asset_id, digest in facts.broll],
        "candidate_id": facts.candidate_id,
        "candidate_rank": facts.candidate_rank,
        "caption_mode": caption_mode,
        "diagrams": list(facts.diagrams),
        "emphasis": list(facts.emphasis),
        "fps": "30/1",
        "height": 1920,
        "output_duration_us": facts.output_duration_us,
        "profile_fingerprint": facts.profile_fingerprint,
        "profile_id": PROFILE_ID,
        "qa_set_id": facts.qa_set_id,
        "sfx": [{"asset_id": asset_id, "sha256": digest} for asset_id, digest in facts.sfx],
        "source_duration_us": facts.source_duration_us,
        "source_sha256": facts.source_sha256,
        "advanced_artifact_sha256": facts.advanced_artifact_sha256,
        "typography": list(facts.typography),
        "video_codec": facts.video_codec,
        "width": 1080,
    }
    if facts.narration_sha256 is not None:
        payload["narration"] = {
            "channels": facts.narration_channels,
            "duration_us": facts.narration_duration_us,
            "engine_id": facts.narration_engine_id,
            "model_id": facts.narration_model_id,
            "model_revision": facts.narration_model_revision,
            "provider_id": facts.narration_provider_id,
            "sample_rate": facts.narration_sample_rate,
            "script_sha256": facts.narration_script_sha256,
            "sha256": facts.narration_sha256,
        }
    return payload


def _file(
    root: Path,
    staging: Path,
    delivery_id: str,
    package_relative: str,
    role: Literal["video", "metadata", "captions_srt", "captions_vtt", "narration", "checksums", "manifest"],
) -> PublishFile:
    path = staging / package_relative
    if path.is_symlink() or not path.is_file():
        raise PublishError("staged delivery file is missing", category="artifact_missing")
    ensure_within(root, path)
    relative = f"deliveries/{delivery_id}/{package_relative}"
    return PublishFile(
        relative_path=relative, sha256=sha256_file(path), size_bytes=path.stat().st_size, role=role
    )


def _copy_exact(source: Path, target: Path, digest: str, size: int) -> None:
    if source.is_symlink() or target.is_symlink():
        raise PublishError("refusing to copy through a symlink", category="unsafe_path")
    shutil.copyfile(source, target)
    if sha256_file(target) != digest or target.stat().st_size != size:
        raise PublishError("copied bytes do not match the verified source", category="artifact_changed")


def _cues_safe(cues: tuple[tuple[int, int, str], ...]) -> bool:
    for start, end, text in cues:
        if end <= start or "\n" in text or "-->" in text or not text.strip():
            return False
    return bool(cues)


def _srt(cues: tuple[tuple[int, int, str], ...]) -> str:
    blocks = []
    for index, (start, end, text) in enumerate(cues, start=1):
        blocks.append(f"{index}\n{_clock(start, vtt=False)} --> {_clock(end, vtt=False)}\n{text}\n")
    return "\n".join(blocks)


def _vtt(cues: tuple[tuple[int, int, str], ...]) -> str:
    lines = ["WEBVTT", ""]
    for index, (start, end, text) in enumerate(cues, start=1):
        lines.append(str(index))
        lines.append(f"{_clock(start, vtt=True)} --> {_clock(end, vtt=True)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _clock(microseconds: int, *, vtt: bool) -> str:
    millis = max(microseconds, 0) // 1000
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, fraction = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{fraction:03d}"


def _succeeded_job(job: JobRecord, manifest_sha256: str) -> JobRecord:
    payload = dict(job.payload)
    payload["manifest_sha256"] = manifest_sha256
    return job.model_copy(
        update={
            "status": JobStatus.SUCCEEDED,
            "updated_at": datetime.now(UTC),
            "payload": payload,
            "error_message": None,
        }
    )


def _finish_job(
    database: Database,
    job: JobRecord,
    status: JobStatus,
    message: str,
    *,
    moment: datetime | None = None,
) -> None:
    updated = job.model_copy(
        update={
            "status": status,
            "updated_at": moment or datetime.now(UTC),
            "error_message": message[:2000],
        }
    )
    with database.transaction() as connection:
        update_job(connection, updated)


def _packages(database: Database, root: Path, source_asset_id: str) -> list[tuple[str, str, str]]:
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
        rows = list_artifacts_for_source(connection, source.project_id, source_asset_id)
    found: list[tuple[str, str, str]] = []
    for row in rows:
        if row.kind != KIND:
            continue
        manifest = _contained_file(root, row.uri)
        if manifest is None:
            continue
        try:
            document = PublishPackageDocument.model_validate_json(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        status = "succeeded" if _package_ok(root, document, manifest) else "failed"
        found.append((document.delivery_id, sha256_file(manifest), status))
    return sorted(found)


def _require_package(
    database: Database, root: Path, source_asset_id: str, delivery_id: str
) -> PublishPackageDocument:
    document = _find_document(database, root, source_asset_id, delivery_id)
    if document is None:
        raise PublishError("delivery package is missing", category="artifact_missing")
    return document


def _find_document(
    database: Database, root: Path, source_asset_id: str, delivery_id: str
) -> PublishPackageDocument | None:
    _safe_id(delivery_id)
    with database.connect() as connection:
        try:
            source = get_source_asset(connection, source_asset_id)
        except StorageError as exc:
            raise PublishError("source does not exist", category="source_changed") from exc
        rows = list_artifacts_for_source(connection, source.project_id, source_asset_id)
    for row in rows:
        if row.kind != KIND:
            continue
        manifest = _contained_file(root, row.uri)
        if manifest is None:
            continue
        try:
            document = PublishPackageDocument.model_validate_json(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        if document.delivery_id == delivery_id:
            return document
    return None


def _narration_id(database: Database, document: PublishPackageDocument) -> str | None:
    with database.connect() as connection:
        source = get_source_asset(connection, document.source_asset_id)
        jobs = list_jobs(connection, source.project_id)
    matched = [
        job for job in jobs if job.kind == JOB and job.payload.get("delivery_id") == document.delivery_id
    ]
    if not matched:
        return None
    latest = max(matched, key=lambda job: (job.updated_at, job.job_id))
    value = latest.payload.get("narration_artifact_id", "-")
    return None if value in {"", "-"} else value


def _candidate_from_jobs(jobs: list[JobRecord]) -> str:
    if not jobs:
        raise PublishError("delivery candidate is missing", category="candidate_missing")
    latest = max(jobs, key=lambda job: (job.updated_at, job.job_id))
    candidate_id = latest.payload.get("candidate_id")
    if not candidate_id:
        raise PublishError("delivery candidate is missing", category="candidate_missing")
    return candidate_id


def _manifest_path(root: Path, delivery_id: str) -> Path:
    _safe_id(delivery_id)
    return root / "deliveries" / delivery_id / "manifest.json"


def _sidecar_path(root: Path, source_asset_id: str) -> Path:
    _safe_id(source_asset_id)
    return root / "deliveries" / "current" / f"{source_asset_id}.json"


def _staging(root: Path, delivery_id: str) -> Path:
    _safe_id(delivery_id)
    return root / "deliveries" / f".partial-{delivery_id}"


def _contained_file(root: Path, uri: str) -> Path | None:
    if not uri.startswith("file:"):
        return None
    return _relative_file(root, _work_relative(root, path_from_file_uri(uri)))


def _work_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return ""


def _relative_file(root: Path, relative: str) -> Path | None:
    if not relative or relative.startswith("/") or "\\" in relative or ".." in relative.split("/"):
        return None
    current = root
    for part in relative.split("/"):
        if part in {"", ".", ".."}:
            return None
        current = current / part
        if current.is_symlink():
            return None
    if not current.is_file():
        return None
    try:
        ensure_within(root, current)
    except ClipforgeError:
        return None
    return current


def _relative_inside(package: Path, path: Path) -> Path | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        path.relative_to(package)
    except ValueError:
        return None
    return path


def _discard_tree(root: Path, path: Path) -> None:
    try:
        ensure_within(root, path)
    except ClipforgeError:
        return
    if path.is_symlink():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()


def _write_bytes(path: Path, payload: bytes) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise PublishError("delivery sidecar path is a symlink", category="unsafe_path")
    partial = path.with_name(f"{path.name}.partial")
    if partial.is_symlink():
        raise PublishError("delivery sidecar path is a symlink", category="unsafe_path")
    partial.write_bytes(payload)
    os.replace(partial, path)


def _safe_id(value: str) -> None:
    if not value or value != Path(value).name or value in {".", ".."} or "\\" in value or "/" in value:
        raise PublishError("delivery id is not a safe identifier", category="unsafe_path")


def _reject_public(text: str) -> None:
    lowered = text.lower()
    if any(token in lowered for token in _FORBIDDEN):
        raise PublishError("delivery record contains a path, URL, or secret-like token", category="unsafe_path")


def _clean(root: Path, exc: BaseException) -> str:
    return str(exc).replace(str(root), "work")
