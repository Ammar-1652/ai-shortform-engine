"""Mine candidates for one source id.

Lock order is fixed: shared prepare, shared transcribe, shared vision, then
the exclusive candidate lock. The locks are held for the whole read and the
mining run. A busy lock fails before a job row is inserted.
"""

from __future__ import annotations

import getpass
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import ValidationError

from clipforge import __version__
from clipforge.candidates.cache import read_candidate_cache
from clipforge.candidates.constants import DISK_ESTIMATE_BYTES, JOB_CANDIDATE, KIND_CANDIDATE, RECIPE_VERSION
from clipforge.candidates.engine import mine_documents
from clipforge.candidates.inputs import EvidencePair, load_evidence_pair
from clipforge.candidates.integrity import candidate_problems
from clipforge.errors import MediaError, StorageError
from clipforge.media.disk import read_disk, require_disk_budget
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri, path_to_file_uri
from clipforge.media.workspace import (
    SourceWorkspace,
    candidate_lock,
    ensure_within,
    prepare_read_lock,
    transcribe_read_lock,
    vision_read_lock,
)
from clipforge.schemas.candidates import (
    CandidateMiningCacheRecord,
    CandidateMiningDocument,
    CandidateMiningProfile,
)
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import (
    Database,
    find_artifact,
    get_job,
    insert_artifact,
    insert_job,
    list_jobs,
    update_artifact,
    update_job,
)
from clipforge.transcription.io import publish_json

_PROFILE = CandidateMiningProfile()


@dataclass(frozen=True, slots=True)
class CandidateMineResult:
    job_id: str
    mining_id: str
    source_asset_id: str
    project_id: str
    transcript_id: str
    transcript_sha256: str
    visual_analysis_id: str
    visual_analysis_sha256: str
    candidate_input_sha256: str
    raw_hypothesis_count: int
    hard_filtered_count: int
    duplicate_count: int
    eligible_distinct_count: int
    selected_count: int
    below_soft_target: bool
    candidate_path: Path
    candidate_sha256: str
    cache_hit: bool
    runtime_seconds: float


def default_profile() -> CandidateMiningProfile:
    return _PROFILE


def profile_for_project(
    profile: CandidateMiningProfile,
    project_profile_id: str | None,
) -> CandidateMiningProfile:
    """Apply campaign duration intent without changing generic mining defaults."""
    if project_profile_id != "profile-tarteel-campaign":
        return profile
    return profile.model_copy(
        update={
            "hard_min_duration_us": 25_000_000,
            "preferred_min_duration_us": 40_000_000,
            "preferred_max_duration_us": 45_000_000,
            "hard_max_duration_us": 55_000_000,
            "boundary_padding_us": 120_000,
        }
    )


def mine_source(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    force: bool = False,
    profile: CandidateMiningProfile | None = None,
    created_by: str | None = None,
) -> CandidateMineResult:
    """Mine ``source_asset_id``. Paths to transcript or visual JSON are not accepted."""
    root = work_root.resolve()
    active = profile or default_profile()
    pair = load_evidence_pair(database, source_asset_id, root)
    if profile is None:
        with database.connect() as connection:
            from clipforge.storage import get_project

            project = get_project(connection, pair.source.project_id)
        # Tarteel edits need enough uninterrupted context for a real
        # hook/body/punch arc. Keep the generic miner unchanged for other
        # projects, while making this campaign's duration intent part of its
        # cache fingerprint and candidate evidence.
        active = profile_for_project(active, project.profile_id)
    _validate_candidate_workspace(pair.workspace)
    actor = created_by.strip()[:200] if created_by and created_by.strip() else _actor()
    started = perf_counter()
    prepare_busy = (
        f"another media prepare is already active for source {source_asset_id}. "
        "Clipforge refused to start candidate mining so derived evidence cannot be replaced."
    )
    transcript_busy = (
        f"another transcription is already active for source {source_asset_id}. "
        "Clipforge refused to start candidate mining while the current transcript can be replaced."
    )
    vision_busy = (
        f"another visual analysis is already active for source {source_asset_id}. "
        "Clipforge refused to start candidate mining while the current visual analysis can be replaced."
    )
    with (
        prepare_read_lock(pair.workspace, busy=prepare_busy),
        transcribe_read_lock(pair.workspace, busy=transcript_busy),
        vision_read_lock(pair.workspace, busy=vision_busy),
        candidate_lock(pair.workspace),
    ):
        pair = load_evidence_pair(database, source_asset_id, root)
        _fail_stale(database, pair)
        if not force and _cache_ready(database, pair, active):
            return _cache_result(database, pair, started)
        _require_budget(root)
        now = datetime.now(UTC)
        job = _running_job(pair, active, now)
        with database.transaction() as connection:
            insert_job(connection, job)
        mining_id = str(uuid.uuid4())
        run_dir: Path | None = None
        try:
            pair = _confirm_pair(database, source_asset_id, root, pair)
            run_dir = pair.workspace.make_candidate_run(mining_id)
            document = mine_documents(
                transcript=pair.transcript,
                visual=pair.visual,
                profile=active,
                mining_id=mining_id,
                created_at=now,
                created_by=actor,
                job_id=job.job_id,
                source_sha256=pair.manifest.content_sha256,
                transcript_sha256=pair.transcript_sha256,
                visual_sha256=pair.visual_sha256,
                candidate_input_sha256=pair.candidate_input_sha256,
                transcript_job_id=pair.transcript_job.job_id,
                visual_job_id=pair.visual_job.job_id,
                transcript_recipe_name=pair.transcript_record.recipe_name,
                transcript_recipe_version=pair.transcript_record.recipe_version,
                visual_recipe_name=pair.visual_record.recipe_name,
                visual_recipe_version=pair.visual_record.recipe_version,
                tool_version=__version__,
            )
            final = run_dir / "candidates.json"
            _write_log(run_dir / "logs" / f"{job.job_id}.log", _log_text(document), root)
            digest, size = publish_json(final, document, root, pair.workspace.partial_for(final))
            record = _cache_record(pair, document, job.job_id, digest, size, now)
            _commit_and_publish(database, pair, job, document, final, record, actor, root)
        except KeyboardInterrupt:
            _abandon(database, job, JobStatus.CANCELLED, "candidate mining cancelled", run_dir, root)
            raise
        except (MediaError, StorageError, OSError, ValidationError, ValueError) as exc:
            _abandon(database, job, JobStatus.FAILED, str(exc), run_dir, root)
            raise
    return _result(document, job_id=job.job_id, path=final, digest=digest, cache_hit=False, started=started)


def _validate_candidate_workspace(workspace: SourceWorkspace) -> None:
    """Reject unsafe existing candidate paths without creating any directories."""
    candidate_root = workspace.candidate_root()
    root = workspace.root.resolve()
    if candidate_root.is_symlink():
        raise MediaError(f"refusing to follow symlinked candidate workspace {candidate_root}")
    if candidate_root.exists():
        ensure_within(root, candidate_root)
        if not candidate_root.is_dir():
            raise MediaError(f"candidate workspace {candidate_root} exists and is not a directory")
        runs = candidate_root / "runs"
        if runs.is_symlink():
            raise MediaError(f"refusing to follow symlinked candidate runs directory {runs}")
        if runs.exists() and not runs.is_dir():
            raise MediaError(f"candidate runs path {runs} exists and is not a directory")


def _confirm_pair(database: Database, source_asset_id: str, root: Path, expected: EvidencePair) -> EvidencePair:
    """Read the evidence pair again after the job exists. A changed digest fails the job."""
    current = load_evidence_pair(database, source_asset_id, root)
    if current.candidate_input_sha256 != expected.candidate_input_sha256:
        raise MediaError(
            "transcript or visual analysis changed after candidate mining locked the source. "
            "The candidate job was not published."
        )
    return current


def _cache_ready(database: Database, pair: EvidencePair, profile: CandidateMiningProfile) -> bool:
    record = read_candidate_cache(pair.workspace.candidate_sidecar())
    if record is None:
        return False
    with database.connect() as connection:
        row = find_artifact(connection, pair.source.project_id, pair.source.source_asset_id, KIND_CANDIDATE)
        if row is None or row.job_id is None:
            return False
        try:
            job = get_job(connection, row.job_id)
        except StorageError:
            return False
    try:
        path = path_from_file_uri(row.uri)
        candidate_root = pair.workspace.candidate_root()
        if candidate_root.is_symlink():
            return False
        ensure_within(pair.workspace.root, candidate_root)
        ensure_within(candidate_root, path)
        if path.is_symlink():
            return False
        document = CandidateMiningDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError, MediaError):
        return False
    return not candidate_problems(
        document,
        record,
        candidate_path=path,
        work_root=pair.workspace.root,
        workspace=pair.workspace,
        pair=pair,
        profile=profile,
        artifact_job_id=row.job_id,
        artifact_uri=row.uri,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
    )


def _cache_result(database: Database, pair: EvidencePair, started: float) -> CandidateMineResult:
    with database.connect() as connection:
        row = find_artifact(connection, pair.source.project_id, pair.source.source_asset_id, KIND_CANDIDATE)
    if row is None or row.job_id is None:
        raise MediaError("candidate cache matched but the artifact row disappeared before reuse")
    path = path_from_file_uri(row.uri)
    document = CandidateMiningDocument.model_validate_json(path.read_text(encoding="utf-8"))
    return _result(
        document,
        job_id=row.job_id,
        path=path,
        digest=sha256_file(path),
        cache_hit=True,
        started=started,
    )


def _running_job(pair: EvidencePair, profile: CandidateMiningProfile, now: datetime) -> JobRecord:
    return JobRecord(
        job_id=str(uuid.uuid4()),
        project_id=pair.source.project_id,
        kind=JOB_CANDIDATE,
        status=JobStatus.RUNNING,
        created_at=now,
        updated_at=now,
        payload={
            "source_asset_id": pair.source.source_asset_id,
            "source_sha256": pair.manifest.content_sha256,
            "transcript_id": pair.transcript.transcript_id,
            "transcript_sha256": pair.transcript_sha256,
            "transcript_job_id": pair.transcript_job.job_id,
            "visual_analysis_id": pair.visual.analysis_id,
            "visual_analysis_sha256": pair.visual_sha256,
            "visual_job_id": pair.visual_job.job_id,
            "candidate_input_sha256": pair.candidate_input_sha256,
            "recipe_version": RECIPE_VERSION,
            "profile_fingerprint": profile.fingerprint(),
            "cache": "miss",
        },
    )


def _cache_record(
    pair: EvidencePair,
    document: CandidateMiningDocument,
    job_id: str,
    digest: str,
    size: int,
    created_at: datetime,
) -> CandidateMiningCacheRecord:
    return CandidateMiningCacheRecord(
        project_id=pair.source.project_id,
        source_asset_id=pair.source.source_asset_id,
        mining_id=document.mining_id,
        job_id=job_id,
        source_sha256=pair.manifest.content_sha256,
        transcript_id=pair.transcript.transcript_id,
        transcript_sha256=pair.transcript_sha256,
        visual_analysis_id=pair.visual.analysis_id,
        visual_analysis_sha256=pair.visual_sha256,
        candidate_input_sha256=pair.candidate_input_sha256,
        profile_fingerprint=document.profile_fingerprint,
        window_algorithm_version=document.window_algorithm_version,
        tokenizer_version=document.tokenizer_version,
        scoring_version=document.scoring_version,
        dedupe_version=document.dedupe_version,
        candidate_artifact_sha256=digest,
        candidate_artifact_size=size,
        selected_count=document.summary.selected_count,
        validation_status="passed",
        created_at=created_at,
    )


def _commit_and_publish(
    database: Database,
    pair: EvidencePair,
    job: JobRecord,
    document: CandidateMiningDocument,
    candidate_path: Path,
    record: CandidateMiningCacheRecord,
    actor: str,
    root: Path,
) -> None:
    previous = _artifact_snapshot(database, pair)
    provenance = ArtifactProvenance(
        created_at=document.created_at,
        created_by=actor,
        tool="clipforge-candidate",
        tool_version=__version__,
        source_asset_ids=[pair.source.source_asset_id],
        job_id=job.job_id,
        inputs_sha256=document.candidate_input_sha256,
    )
    payload = dict(job.payload)
    payload["mining_id"] = document.mining_id
    payload["selected_count"] = str(document.summary.selected_count)
    succeeded = job.model_copy(
        update={
            "status": JobStatus.SUCCEEDED,
            "updated_at": document.created_at,
            "error_message": None,
            "payload": payload,
        }
    )
    with database.transaction() as connection:
        existing = find_artifact(
            connection,
            pair.source.project_id,
            pair.source.source_asset_id,
            KIND_CANDIDATE,
        )
        uri = path_to_file_uri(candidate_path)
        if existing is None:
            insert_artifact(
                connection,
                artifact_id=str(uuid.uuid4()),
                project_id=pair.source.project_id,
                job_id=job.job_id,
                source_asset_id=pair.source.source_asset_id,
                kind=KIND_CANDIDATE,
                uri=uri,
                provenance=provenance,
            )
        else:
            update_artifact(
                connection,
                artifact_id=existing.artifact_id,
                project_id=pair.source.project_id,
                job_id=job.job_id,
                source_asset_id=pair.source.source_asset_id,
                kind=KIND_CANDIDATE,
                uri=uri,
                provenance=provenance,
            )
        update_job(connection, succeeded)
    try:
        publish_json(
            pair.workspace.candidate_sidecar(),
            record,
            root,
            pair.workspace.partial_for(pair.workspace.candidate_sidecar()),
        )
    except (OSError, MediaError) as exc:
        _revert_artifact(database, pair, previous, job, str(exc))
        raise MediaError(
            f"candidate sidecar was not published: {exc}. The previous candidate set remains current."
        ) from exc


def _artifact_snapshot(
    database: Database,
    pair: EvidencePair,
) -> tuple[str, str | None, str, ArtifactProvenance] | None:
    with database.connect() as connection:
        row = find_artifact(connection, pair.source.project_id, pair.source.source_asset_id, KIND_CANDIDATE)
    if row is None:
        return None
    return row.artifact_id, row.job_id, row.uri, row.provenance


def _revert_artifact(
    database: Database,
    pair: EvidencePair,
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
                project_id=pair.source.project_id,
                job_id=job_id,
                source_asset_id=pair.source.source_asset_id,
                kind=KIND_CANDIDATE,
                uri=uri,
                provenance=provenance,
            )
        else:
            connection.execute(
                """
                DELETE FROM artifacts
                WHERE project_id = ? AND source_asset_id = ? AND kind = ? AND job_id = ?
                """,
                (
                    pair.source.project_id,
                    pair.source.source_asset_id,
                    KIND_CANDIDATE,
                    job.job_id,
                ),
            )
        update_job(connection, failed)


def _fail_stale(database: Database, pair: EvidencePair) -> None:
    now = datetime.now(UTC)
    with database.transaction() as connection:
        for existing in list_jobs(connection, pair.source.project_id):
            if existing.kind != JOB_CANDIDATE or existing.status is not JobStatus.RUNNING:
                continue
            if existing.payload.get("source_asset_id") != pair.source.source_asset_id:
                continue
            update_job(
                connection,
                existing.model_copy(
                    update={
                        "status": JobStatus.FAILED,
                        "updated_at": now,
                        "error_message": (
                            "interrupted before completion. The candidate lock was free, so no live "
                            "candidate mining owned this running job. Partial outputs were not promoted."
                        ),
                    }
                ),
            )


def _require_budget(root: Path) -> None:
    status = read_disk(root if root.exists() else root.parent)
    try:
        require_disk_budget(status.free_bytes, status.reserve_bytes, DISK_ESTIMATE_BYTES)
    except MediaError as exc:
        raise MediaError(f"{exc} Candidate mining was not started.") from exc


def _abandon(
    database: Database,
    job: JobRecord,
    status: JobStatus,
    message: str,
    run_dir: Path | None,
    root: Path,
) -> None:
    notes: list[str] = []
    try:
        _cleanup_failed_run(run_dir, root)
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


def _cleanup_failed_run(run_dir: Path | None, root: Path) -> None:
    if run_dir is None or not run_dir.exists():
        return
    ensure_within(root, run_dir)
    if run_dir.is_symlink():
        raise MediaError(f"refusing to clean a symlinked candidate run {run_dir}")
    for path in sorted(run_dir.rglob("*")):
        if path.is_symlink():
            raise MediaError(f"refusing to clean symlink {path}")
        ensure_within(root, path)
        if path.is_file() and ".partial." in path.name:
            path.unlink()


def _write_log(path: Path, text: str, root: Path) -> None:
    ensure_within(root, path)
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _log_text(document: CandidateMiningDocument) -> str:
    summary = document.summary
    return (
        f"mining_id {document.mining_id}\n"
        f"raw {summary.raw_hypothesis_count}\n"
        f"hard_filtered {summary.hard_filtered_count}\n"
        f"duplicates {summary.duplicate_count}\n"
        f"selected {summary.selected_count}\n"
        "editorial heuristic only; edit opportunity is separate; no virality probability\n"
    )


def _result(
    document: CandidateMiningDocument,
    *,
    job_id: str,
    path: Path,
    digest: str,
    cache_hit: bool,
    started: float,
) -> CandidateMineResult:
    summary = document.summary
    return CandidateMineResult(
        job_id=job_id,
        mining_id=document.mining_id,
        source_asset_id=document.source_asset_id,
        project_id=document.project_id,
        transcript_id=document.transcript_id,
        transcript_sha256=document.transcript_sha256,
        visual_analysis_id=document.visual_analysis_id,
        visual_analysis_sha256=document.visual_analysis_sha256,
        candidate_input_sha256=document.candidate_input_sha256,
        raw_hypothesis_count=summary.raw_hypothesis_count,
        hard_filtered_count=summary.hard_filtered_count,
        duplicate_count=summary.duplicate_count,
        eligible_distinct_count=summary.eligible_distinct_count,
        selected_count=summary.selected_count,
        below_soft_target=summary.below_soft_target,
        candidate_path=path,
        candidate_sha256=digest,
        cache_hit=cache_hit,
        runtime_seconds=perf_counter() - started,
    )


def _actor() -> str:
    try:
        return getpass.getuser()
    except OSError as exc:
        raise MediaError(f"could not determine the OS user for provenance: {exc}") from exc
