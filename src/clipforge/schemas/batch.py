"""One batch of sources in one SQLite database. Status cannot outrank the children."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.provenance import ArtifactProvenance

BatchStatus = Literal["succeeded", "failed", "partial", "cancelled", "running"]
ChildStatus = Literal["succeeded", "failed", "blocked", "cancelled", "pending", "running"]


class BatchChild(Versioned):
    """One source operation inside a batch. Paths are not stored."""

    source_asset_id: EntityId
    operation: str = Field(min_length=1, max_length=80)
    status: ChildStatus
    job_id: EntityId | None = None
    cache_hit: bool = False
    artifact_id: EntityId | None = None
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    cache_identity: str | None = Field(default=None, max_length=200)
    error: str | None = Field(default=None, max_length=500)


class BatchManifest(Versioned):
    """Durable batch record. Child status decides the aggregate."""

    batch_id: EntityId
    project_id: EntityId
    source_asset_ids: list[EntityId] = Field(min_length=1)
    operations: list[str] = Field(min_length=1)
    children: list[BatchChild]
    status: BatchStatus
    concurrency: Literal[1] = 1
    force: bool = False
    profile_id: EntityId | None = None
    profile_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    policy_ids: list[EntityId] = Field(default_factory=list)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def status_matches_children(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("batch updated_at is earlier than created_at")
        if len(self.source_asset_ids) != len(set(self.source_asset_ids)):
            raise ValueError("batch source ids must be unique")
        expected = aggregate_batch_status([item.status for item in self.children])
        if self.status != expected and self.status != "running":
            raise ValueError(
                f"batch status is {self.status} but the children aggregate to {expected}. "
                "Do not report incomplete work as succeeded."
            )
        blob = " ".join(
            [
                self.batch_id,
                self.project_id,
                self.profile_id or "",
                *self.policy_ids,
                *self.source_asset_ids,
                *self.operations,
                *(item.error or "" for item in self.children),
                *(item.cache_identity or "" for item in self.children),
            ]
        )
        if "://" in blob or "\\" in blob or "/tmp/" in blob or "/home/" in blob:
            raise ValueError("batch manifest must not contain filesystem paths")
        return self


def aggregate_batch_status(statuses: list[str]) -> BatchStatus:
    """Return the strongest honest status for these children."""
    if not statuses or any(item in {"pending", "running"} for item in statuses):
        return "running"
    if any(item == "failed" for item in statuses):
        return "failed" if all(item == "failed" for item in statuses) else "partial"
    if any(item == "blocked" for item in statuses):
        return "partial"
    if any(item == "cancelled" for item in statuses):
        return "cancelled" if all(item == "cancelled" for item in statuses) else "partial"
    if all(item == "succeeded" for item in statuses):
        return "succeeded"
    return "partial"
