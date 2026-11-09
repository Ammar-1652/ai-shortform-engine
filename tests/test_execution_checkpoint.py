"""Durable production execution checkpoints and read-only inspection."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.campaign.checkpoint import (
    CheckpointError,
    checkpoint_digest,
    load_checkpoint,
    stage_receipts,
    write_checkpoint,
)
from clipforge.schemas.campaign_run import STAGES, CampaignSourceRun, CampaignStageRecord
from clipforge.schemas.execution import ProductionExecutionCheckpoint


def _source(source_id: str, status: str = "partial") -> CampaignSourceRun:
    return CampaignSourceRun(
        source_id=source_id,
        source_sha256="a" * 64,
        rights_state="allowed",
        stages=[CampaignStageRecord(stage=stage, status="not_run", reason_code="planned") for stage in STAGES],
        candidates=[],
        status=status,  # type: ignore[arg-type]
        reason_code="planned",
    )


def _checkpoint() -> ProductionExecutionCheckpoint:
    now = datetime.now(UTC)
    return ProductionExecutionCheckpoint(
        checkpoint_id="execution-123456789012345678901234",
        run_id="execution-123456789012345678901234",
        campaign_id="campaign-1",
        project_id="project-1",
        request_fingerprint="b" * 64,
        source_ids=["source-1"],
        status="running",
        checkpoint_sha256="0" * 64,
        created_at=now,
        updated_at=now,
    )


def test_checkpoint_is_atomic_hash_bound_and_readable(tmp_path: Path) -> None:
    stored, path = write_checkpoint(_checkpoint(), root=tmp_path)
    assert path.is_file()
    assert stored.checkpoint_sha256 == checkpoint_digest(stored)
    assert load_checkpoint(tmp_path, stored.checkpoint_id) == stored
    assert not list(path.parent.glob("*.partial"))


def test_checkpoint_tampering_fails_closed(tmp_path: Path) -> None:
    _stored, path = write_checkpoint(_checkpoint(), root=tmp_path)
    payload = path.read_text(encoding="utf-8").replace('"status": "running"', '"status": "failed"')
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(CheckpointError, match="hash is stale"):
        load_checkpoint(tmp_path, "execution-123456789012345678901234")


def test_stage_receipts_convert_not_run_and_partial_to_recoverable_states() -> None:
    receipts = stage_receipts(run_id="execution-1", source=_source("source-1"))
    assert len(receipts) == len(STAGES)
    assert {item.status for item in receipts} == {"planned"}


def test_checkpoint_rejects_public_path_like_payload() -> None:
    with pytest.raises(ValidationError):
        ProductionExecutionCheckpoint(
            checkpoint_id="execution-123456789012345678901234",
            run_id="execution-123456789012345678901234",
            campaign_id="campaign-1",
            project_id="project-1",
            request_fingerprint="b" * 64,
            source_ids=["source-1"],
            status="running",
            checkpoint_sha256="0" * 64,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            current_source_id="/tmp/private",
        )
