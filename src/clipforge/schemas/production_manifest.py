"""Operator aggregate for one campaign production. Paths are relative."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.campaign import _plain
from clipforge.schemas.common import EntityId, Versioned

_SHA = r"^[0-9a-f]{64}$"
ProductionStatus = Literal["succeeded", "partial", "failed", "blocked", "cancelled"]


class CampaignProductionStageFact(Versioned):
    """One pipeline stage copied from the existing campaign run."""

    stage: str = Field(min_length=1, max_length=40)
    status: str = Field(min_length=1, max_length=40)
    cache_hit: bool
    reason_code: str = Field(min_length=1, max_length=80)

    @field_validator("stage", "status", "reason_code")
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="production stage")


class CampaignProductionCacheRecord(Versioned):
    """Identity of one aggregate. A hit still revalidates the pipeline evidence."""

    cache_key: str = Field(pattern=_SHA)
    pipeline_fingerprint: str = Field(pattern=_SHA)
    selection_sha256: str = Field(pattern=_SHA)
    policy_fingerprint: str = Field(pattern=_SHA)
    catalogue_fingerprint: str = Field(pattern=_SHA)
    hit: bool


class CampaignProductionSource(Versioned):
    """Evidence for one selected source inside an aggregate production."""

    source_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    byte_size: int | None = Field(default=None, ge=0)
    acquisition_id: EntityId | None = None
    acquisition_sha256: str | None = Field(default=None, pattern=_SHA)
    status: ProductionStatus
    cache_status: Literal["hit", "miss", "mixed"]
    failure_code: str | None = None
    candidate_id: EntityId | None = None
    review_id: EntityId | None = None
    review_decision: str | None = None
    hero_review_id: EntityId | None = None
    hero_artifact_id: EntityId | None = None
    advanced_artifact_id: EntityId | None = None
    qa_set_id: EntityId | None = None
    analytics_snapshot_id: EntityId | None = None
    analytics_status: str = Field(min_length=1, max_length=40)
    alignment_status: str = Field(min_length=1, max_length=40)
    narration_status: str = Field(min_length=1, max_length=40)
    narration_artifact_id: EntityId | None = None
    narration_audio_sha256: str | None = Field(default=None, pattern=_SHA)
    delivery_id: EntityId | None = None
    delivery_manifest_sha256: str | None = Field(default=None, pattern=_SHA)
    delivery_relative: str | None = None
    final_media_sha256: str | None = Field(default=None, pattern=_SHA)
    stages: list[CampaignProductionStageFact]
    reframe_requested: str = "contain"
    reframe_applied: str = "contain"
    reframe_plan_id: str = "none"
    reframe_trajectory_sha256: str = "none"
    reframe_evidence_sha256: str = "none"
    reframe_status: str = "succeeded"
    reframe_cache_hit: bool = False
    reframe_blocker: str = "none"
    requested_locale: str = "en-US"
    transcript_language: str = "en-US"
    alignment_provider: str = "none"
    alignment_model_id: str = "none"
    alignment_model_revision: str = "none"
    alignment_checkpoint_sha256: str = "none"
    alignment_artifact_id: str = "none"
    alignment_cache_status: str = "miss"
    alignment_blocker: str = "none"

    @field_validator(
        "failure_code",
        "review_decision",
        "analytics_status",
        "alignment_status",
        "narration_status",
        "delivery_relative",
        "reframe_requested",
        "reframe_applied",
        "reframe_plan_id",
        "reframe_trajectory_sha256",
        "reframe_evidence_sha256",
        "reframe_status",
        "reframe_blocker",
        "requested_locale",
        "transcript_language",
        "alignment_provider",
        "alignment_model_id",
        "alignment_model_revision",
        "alignment_checkpoint_sha256",
        "alignment_artifact_id",
        "alignment_cache_status",
        "alignment_blocker",
    )
    @classmethod
    def facts_are_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="production source")


class CampaignProductionManifest(Versioned):
    """One operator production. It points at the existing pipeline run."""

    run_id: EntityId
    pipeline_run_id: EntityId
    campaign_id: EntityId
    project_id: EntityId
    selection_id: EntityId
    selection_sha256: str = Field(pattern=_SHA)
    selection_fingerprint: str = Field(pattern=_SHA)
    catalogue_fingerprint: str = Field(pattern=_SHA)
    policy_fingerprint: str = Field(pattern=_SHA)
    operator_id: EntityId
    source_ids: list[EntityId] = Field(min_length=1)
    language: str = Field(min_length=2, max_length=16)
    narration_enabled: bool
    voice_id: str | None = None
    engine_id: str | None = None
    model_id: str | None = None
    model_revision: str | None = None
    sources: list[CampaignProductionSource] = Field(min_length=1)
    cache: CampaignProductionCacheRecord
    status: ProductionStatus
    reason_code: str = Field(min_length=1, max_length=80)
    created_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    manifest_sha256: str = Field(pattern=_SHA)
    publishing: Literal["deferred"] = "deferred"

    @field_validator("language", "reason_code", "voice_id", "engine_id", "model_id", "model_revision")
    @classmethod
    def labels_are_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="production manifest")

    @model_validator(mode="after")
    def identity_matches(self) -> Self:
        found = [item.source_id for item in self.sources]
        if found != self.source_ids:
            raise ValueError("production sources must follow the selection order")
        if self.manifest_sha256 != manifest_digest(self):
            raise ValueError("production manifest hash does not match the body")
        text = self.model_dump_json().lower()
        if any(token in text for token in ("/home/", "/tmp/", "/users/", "file://", "bearer ", "token=")):
            raise ValueError("production manifest contains a path or a secret")
        return self


def manifest_digest(document: CampaignProductionManifest) -> str:
    """Hash every field except the manifest hash itself."""
    body = document.model_dump(mode="json")
    body.pop("manifest_sha256", None)
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
