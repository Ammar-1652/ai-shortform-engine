"""Run several sources through one SQLite database. Concurrency stays at 1."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import ClipforgeError, StorageError
from clipforge.jobs.payload import assert_public_payload
from clipforge.jobs.promote import PromotionError, promote
from clipforge.media.workspace import ensure_within
from clipforge.schemas.batch import BatchChild, BatchManifest, aggregate_batch_status
from clipforge.schemas.jobs import JobStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import Database, get_job, get_project, get_source_asset

SidecarHook = Callable[[], None]


class BatchError(ClipforgeError):
    """A batch cannot start or its current record is not acceptable."""


@dataclass(frozen=True, slots=True)
class ChildOutcome:
    """One child result. Identifiers and hashes only."""

    job_id: str
    cache_hit: bool
    artifact_id: str | None = None
    artifact_sha256: str | None = None
    cache_identity: str | None = None


Operation = Callable[[str, str, bool], ChildOutcome | tuple[str, bool]]


@dataclass(frozen=True, slots=True)
class _ProfileFacts:
    profile_id: str | None
    profile_sha256: str | None
    policy_ids: tuple[str, ...]


def run_batch(
    *,
    database: Database,
    source_asset_ids: list[str],
    work_root: Path,
    created_by: str,
    operations: list[str] | None = None,
    concurrency: int = 1,
    force: bool = False,
    executor: Operation | None = None,
    sidecar_hook: SidecarHook | None = None,
) -> BatchManifest:
    """Execute sources in the given order. One failure does not erase another source."""
    if concurrency != 1:
        raise BatchError("batch concurrency must be 1. Parallel batches are not claimed.")
    _reject_duplicates(source_asset_ids)
    chosen = operations or ["media_prepare"]
    root = work_root.resolve()
    project_id, facts = _one_project(database, source_asset_ids)
    now = datetime.now(UTC)
    batch_id = str(uuid.uuid4())
    active = executor or _production_executor(database, root, created_by)
    children: list[BatchChild] = []
    for source_id in source_asset_ids:
        for operation in chosen:
            children.append(_run_child(active, source_id, operation, force))
    return _publish(
        root,
        batch_id,
        project_id,
        source_asset_ids,
        chosen,
        children,
        created_by,
        now,
        None,
        facts,
        force,
        sidecar_hook,
    )


def resume_batch(
    database: Database,
    batch_id: str,
    work_root: Path,
    *,
    created_by: str,
    executor: Operation | None = None,
    sidecar_hook: SidecarHook | None = None,
) -> BatchManifest:
    """Rerun failed, blocked, or incomplete children. Verified successes are kept."""
    root = work_root.resolve()
    current = load_batch(root, batch_id)
    active = executor or _production_executor(database, root, created_by)
    children: list[BatchChild] = []
    for child in current.children:
        if child.status == "succeeded" and _succeeded_still_valid(database, current, child):
            children.append(child)
            continue
        children.append(_run_child(active, child.source_asset_id, child.operation, False))
    facts = _ProfileFacts(current.profile_id, current.profile_sha256, tuple(current.policy_ids))
    return _publish(
        root,
        batch_id,
        current.project_id,
        list(current.source_asset_ids),
        list(current.operations),
        children,
        created_by,
        current.created_at,
        current,
        facts,
        current.force,
        sidecar_hook,
    )


def list_batch(work_root: Path, batch_id: str) -> str:
    document = load_batch(work_root.resolve(), batch_id)
    lines = [
        f"batch_id: {document.batch_id}",
        f"project_id: {document.project_id}",
        f"status: {document.status}",
        f"profile_id: {document.profile_id or '-'}",
        "sources: " + ", ".join(document.source_asset_ids),
    ]
    for child in document.children:
        lines.append(
            f"{child.source_asset_id}\t{child.operation}\t{child.status}\t"
            f"{'hit' if child.cache_hit else 'miss'}\t{child.job_id or '-'}\t"
            f"{child.artifact_sha256 or '-'}"
        )
    return "\n".join(lines)


def show_batch(work_root: Path, batch_id: str) -> str:
    document = load_batch(work_root.resolve(), batch_id)
    lines = [list_batch(work_root, batch_id), f"policies: {', '.join(document.policy_ids) or '-'}"]
    for child in document.children:
        if child.cache_identity:
            lines.append(f"cache_identity: {child.source_asset_id} {child.cache_identity}")
        if child.error:
            lines.append(f"error: {child.source_asset_id} {child.error}")
    return "\n".join(lines)


def verify_batch(work_root: Path, batch_id: str) -> None:
    """Re-read the batch manifest. This does not rewrite it."""
    root = work_root.resolve()
    path = _manifest_path(root, batch_id)
    if path.is_symlink() or path.parent.is_symlink():
        raise BatchError("batch manifest is a symlink")
    ensure_within(root, path)
    load_batch(root, batch_id)


def load_batch(root: Path, batch_id: str) -> BatchManifest:
    path = _manifest_path(root, batch_id)
    if path.is_symlink() or not path.is_file():
        raise BatchError(f"no batch {batch_id}")
    try:
        return BatchManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, UnicodeError) as exc:
        raise BatchError(f"batch {batch_id} could not be read: {exc}") from exc


def _run_child(executor: Operation, source_id: str, operation: str, force: bool) -> BatchChild:
    try:
        outcome = _as_outcome(executor(source_id, operation, force))
    except ClipforgeError as exc:
        return BatchChild(
            source_asset_id=source_id,
            operation=operation,
            status="failed",
            error=_public_error(str(exc)),
        )
    return BatchChild(
        source_asset_id=source_id,
        operation=operation,
        status="succeeded",
        job_id=outcome.job_id,
        cache_hit=outcome.cache_hit,
        artifact_id=outcome.artifact_id,
        artifact_sha256=outcome.artifact_sha256,
        cache_identity=outcome.cache_identity,
    )


def _as_outcome(value: ChildOutcome | tuple[str, bool]) -> ChildOutcome:
    if isinstance(value, ChildOutcome):
        return value
    job_id, cache_hit = value
    return ChildOutcome(job_id=job_id, cache_hit=cache_hit)


def _publish(
    root: Path,
    batch_id: str,
    project_id: str,
    source_ids: list[str],
    operations: list[str],
    children: list[BatchChild],
    actor: str,
    created_at: datetime,
    previous: BatchManifest | None,
    facts: _ProfileFacts,
    force: bool,
    sidecar_hook: SidecarHook | None,
) -> BatchManifest:
    status = aggregate_batch_status([item.status for item in children])
    document = BatchManifest(
        batch_id=batch_id,
        project_id=project_id,
        source_asset_ids=source_ids,
        operations=operations,
        children=children,
        status=status,
        force=force,
        profile_id=facts.profile_id,
        profile_sha256=facts.profile_sha256,
        policy_ids=list(facts.policy_ids),
        created_at=created_at,
        updated_at=datetime.now(UTC),
        provenance=ArtifactProvenance(
            created_at=created_at,
            created_by=actor,
            tool="clipforge-batch",
            tool_version="0",
            source_asset_ids=source_ids,
        ),
    )
    path = _manifest_path(root, batch_id)
    _reject_linked_batch_dir(root, path)
    ensure_within(root, path.parent)
    payload = json.dumps(document.model_dump(mode="json"), sort_keys=True)
    assert_public_payload({"batch": "ok"})
    if "://" in payload or "/home/" in payload or "/tmp/" in payload or "\\" in payload:
        raise BatchError("batch manifest contained a filesystem path and was not written")
    partial = path.with_suffix(".json.partial")
    previous_bytes = None
    if previous is not None and path.is_file() and not path.is_symlink():
        previous_bytes = path.read_bytes()

    def write_output() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _reject_linked_batch_dir(root, path)
        partial.write_text(payload + "\n", encoding="utf-8")

    def write_manifest() -> None:
        BatchManifest.model_validate_json(payload)

    def commit_database() -> None:
        return None

    def write_sidecar() -> None:
        if sidecar_hook is not None:
            sidecar_hook()
        partial.replace(path)

    def rollback() -> None:
        if partial.is_file() and not partial.is_symlink():
            partial.unlink()
        if previous_bytes is None:
            if path.is_file() and not path.is_symlink():
                path.unlink()
            return
        path.write_bytes(previous_bytes)

    try:
        promote(
            write_output=write_output,
            write_manifest=write_manifest,
            commit_database=commit_database,
            write_sidecar=write_sidecar,
            rollback_database=rollback,
        )
    except PromotionError as exc:
        if partial.is_file() and not partial.is_symlink():
            partial.unlink()
        raise BatchError(str(exc)) from exc
    return document


def _one_project(database: Database, source_ids: list[str]) -> tuple[str, _ProfileFacts]:
    if not source_ids:
        raise BatchError("a batch needs at least one source id")
    projects: set[str] = set()
    with database.connect() as connection:
        for source_id in source_ids:
            try:
                source = get_source_asset(connection, source_id)
            except StorageError as exc:
                raise BatchError(str(exc)) from exc
            projects.add(source.project_id)
        if len(projects) != 1:
            raise BatchError("a batch cannot mix projects. Run one project at a time.")
        project_id = next(iter(projects))
        project = get_project(connection, project_id)
    facts = _profile_facts(project.profile_id)
    return project_id, facts


def _profile_facts(profile_id: str | None) -> _ProfileFacts:
    if profile_id is None:
        return _ProfileFacts(None, None, ())
    from clipforge.policy.loader import PolicyError, resolve_profile

    try:
        resolved = resolve_profile(profile_id)
    except PolicyError as exc:
        raise BatchError(str(exc)) from exc
    return _ProfileFacts(resolved.profile_id, resolved.profile_sha256, resolved.policy_ids)


def _reject_duplicates(source_ids: list[str]) -> None:
    if len(source_ids) != len(set(source_ids)):
        raise BatchError("duplicate source ids are rejected")


def _succeeded_still_valid(database: Database, document: BatchManifest, child: BatchChild) -> bool:
    if child.job_id is None:
        return False
    try:
        with database.connect() as connection:
            job = get_job(connection, child.job_id)
    except StorageError:
        return False
    if job.status is not JobStatus.SUCCEEDED or job.project_id != document.project_id:
        return False
    recorded_source = job.payload.get("source_asset_id")
    if recorded_source and recorded_source != child.source_asset_id:
        return False
    if child.artifact_sha256:
        recorded = {
            job.payload.get("analysis_proxy_sha256"),
            job.payload.get("asr_audio_sha256"),
            job.payload.get("transcript_sha256"),
            job.payload.get("artifact_sha256"),
        }
        if child.artifact_sha256 not in recorded and any(item for item in recorded):
            return False
    return True


def _public_error(text: str) -> str:
    if "://" in text or "\\" in text or "/tmp/" in text or "/home/" in text:
        return "operation failed; local path omitted"
    return text[:500]


def _manifest_path(root: Path, batch_id: str) -> Path:
    if "/" in batch_id or "\\" in batch_id or ".." in batch_id.split("/"):
        raise BatchError("batch id is not a safe identifier")
    return root / "batches" / batch_id / "manifest.json"


def _reject_linked_batch_dir(root: Path, manifest: Path) -> None:
    current = root
    relative = manifest.parent.relative_to(root)
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise BatchError("batch directory is a symlink")


def _production_executor(database: Database, root: Path, actor: str) -> Operation:
    def run(source_id: str, operation: str, force: bool) -> ChildOutcome:
        del force
        if operation != "media_prepare":
            raise BatchError(f"batch operation {operation} is not supported")
        from clipforge.media.prepare import prepare_source

        result = prepare_source(
            database=database,
            source_asset_id=source_id,
            work_root=root,
            created_by=actor,
        )
        identity = f"media_prepare:{result.proxy_sha256}"
        hit = bool(result.proxy_from_cache and result.audio_from_cache is not False)
        return ChildOutcome(
            job_id=result.job_id,
            cache_hit=hit,
            artifact_sha256=result.proxy_sha256,
            cache_identity=identity,
        )

    return run
