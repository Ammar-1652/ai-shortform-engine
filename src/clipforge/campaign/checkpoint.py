"""Durable campaign execution checkpoints.

Checkpoints live beside the existing campaign manifest under the ignored work
root. They make recovery explicit without becoming a second artifact or
approval store.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.media.workspace import atomic_replace, ensure_within, mkdir_contained, reject_symlink_chain
from clipforge.schemas.campaign_run import CampaignSourceRun
from clipforge.schemas.execution import ExecutionStatus, ProductionExecutionCheckpoint, RunStageReceipt
from clipforge.schemas.provenance import ArtifactProvenance


class CheckpointError(MediaError):
    """A checkpoint cannot be trusted or safely promoted."""


def execution_id(request_fingerprint: str) -> str:
    """Return a stable, path-safe id for a request fingerprint."""
    return f"execution-{request_fingerprint[:24]}"


def checkpoint_path(root: Path, checkpoint_id: str) -> Path:
    if re.fullmatch(r"execution-[a-f0-9]{24,32}", checkpoint_id) is None:
        raise CheckpointError("checkpoint id is not safe")
    return root.resolve() / "campaigns" / "executions" / checkpoint_id / "checkpoint.json"


@contextmanager
def execution_lock(root: Path) -> Iterator[None]:
    """Serialize controller mutations; the kernel releases the lock on crash."""
    root = root.absolute()
    reject_symlink_chain(root)
    path = root / "campaigns" / "executions" / "controller.lock"
    mkdir_contained(root, path.parent)
    reject_symlink_chain(path)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CheckpointError(
                "campaign controller is busy; inspect the active run before retrying"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def journal_path(root: Path, checkpoint_id: str) -> Path:
    return checkpoint_path(root, checkpoint_id).with_name("journal.jsonl")


def checkpoint_digest(checkpoint: ProductionExecutionCheckpoint) -> str:
    payload = checkpoint.model_dump(mode="json")
    payload.pop("checkpoint_sha256", None)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_checkpoint(
    checkpoint: ProductionExecutionCheckpoint,
    *,
    root: Path,
) -> tuple[ProductionExecutionCheckpoint, Path]:
    """Atomically write and read back a checkpoint with its calculated hash."""
    resolved = root.resolve()
    final = checkpoint_path(resolved, checkpoint.checkpoint_id)
    mkdir_contained(resolved, final.parent)
    reject_symlink_chain(final)
    bound = ProductionExecutionCheckpoint.model_validate(
        {**checkpoint.model_dump(mode="json"), "checkpoint_sha256": checkpoint_digest(checkpoint)}
    )
    text = json.dumps(bound.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    partial = final.with_name(".checkpoint.json.partial")
    ensure_within(resolved, partial)
    reject_symlink_chain(partial)
    # Keep immutable revisions as well as the current recovery pointer.
    history = final.parent / "history" / f"{bound.checkpoint_sha256}.json"
    mkdir_contained(resolved, history.parent)
    reject_symlink_chain(history)
    if not history.exists():
        history_partial = history.with_suffix(".partial")
        reject_symlink_chain(history_partial)
        history_partial.write_text(text, encoding="utf-8")
        atomic_replace(history_partial, history, resolved)
    elif history.read_text(encoding="utf-8") != text:
        raise CheckpointError("checkpoint history hash conflicts with existing bytes")
    partial.write_text(text, encoding="utf-8")
    atomic_replace(partial, final, resolved)
    try:
        loaded = ProductionExecutionCheckpoint.model_validate_json(final.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise CheckpointError("written checkpoint could not be read back") from exc
    if loaded != bound or checkpoint_digest(loaded) != loaded.checkpoint_sha256:
        raise CheckpointError("written checkpoint hash is stale")
    return loaded, final


def load_checkpoint(root: Path, checkpoint_id: str) -> ProductionExecutionCheckpoint:
    resolved = root.resolve()
    path = checkpoint_path(resolved, checkpoint_id)
    reject_symlink_chain(path)
    if not path.is_file():
        raise CheckpointError(f"execution checkpoint is missing: {checkpoint_id}")
    try:
        checkpoint = ProductionExecutionCheckpoint.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise CheckpointError(f"execution checkpoint is invalid: {checkpoint_id}") from exc
    if checkpoint_digest(checkpoint) != checkpoint.checkpoint_sha256:
        raise CheckpointError("execution checkpoint hash is stale")
    if checkpoint.checkpoint_id != checkpoint_id or checkpoint.run_id != checkpoint_id:
        raise CheckpointError("execution checkpoint belongs to another run")
    return checkpoint


def find_checkpoint_for_final_run(
    root: Path, final_campaign_run_id: str
) -> ProductionExecutionCheckpoint | None:
    """Find the immutable execution receipt that produced one campaign run."""
    base = root.resolve() / "campaigns" / "executions"
    reject_symlink_chain(base)
    if not base.is_dir():
        return None
    for candidate in sorted(base.glob("*/checkpoint.json")):
        checkpoint = load_checkpoint(root, candidate.parent.name)
        if checkpoint.final_campaign_run_id == final_campaign_run_id:
            return checkpoint
    return None


def append_stage_receipt(root: Path, receipt: RunStageReceipt) -> Path:
    """Append one receipt after its output facts have been verified."""
    resolved = root.resolve()
    path = journal_path(resolved, receipt.run_id)
    mkdir_contained(resolved, path.parent)
    reject_symlink_chain(path)
    ensure_within(resolved, path)
    line = json.dumps(receipt.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    return path


def stage_receipts(
    *,
    run_id: str,
    source: CampaignSourceRun,
    dependency_sha256: str = "",
    attempt: int = 1,
) -> list[RunStageReceipt]:
    """Convert the source's verified stage records into journal receipts."""
    now = datetime.now(UTC)
    found: list[RunStageReceipt] = []
    for stage in source.stages:
        status = {
            "not_run": "planned",
            "partial": "needs_review",
        }.get(stage.status, stage.status)
        found.append(
            RunStageReceipt(
                run_id=run_id,
                source_id=source.source_id,
                stage=stage.stage,
                status=cast(ExecutionStatus, status),
                attempt=attempt,
                input_sha256=source.source_sha256,
                dependency_sha256=dependency_sha256,
                output_artifact_id=stage.artifact_id,
                output_sha256=stage.artifact_sha256 or "",
                reason_code=stage.reason_code,
                updated_at=now,
                provenance=ArtifactProvenance(
                    created_at=now,
                    created_by="system_enforcer",
                    tool="clipforge-campaign-checkpoint",
                    tool_version="0.1.0",
                    source_asset_ids=[source.source_asset_id] if source.source_asset_id else [],
                    inputs_sha256=source.source_sha256,
                ),
            )
        )
    return found
