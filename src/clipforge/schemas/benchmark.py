"""Local readiness evidence. A benchmark does not approve or publish."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"
Readiness = Literal[
    "passed",
    "failed",
    "blocked",
    "not_run",
    "unavailable",
    "blocked_for_external_publish",
]
Execution = Literal[
    "recorded_evidence",
    "executed_stage",
    "cache_hit",
    "not_run",
    "blocked",
    "unavailable",
]
FixtureKind = Literal["real_authorized", "deterministic_synthetic"]


def _public(value: str) -> bool:
    lowered = value.lower()
    if any(ord(character) < 32 for character in value):
        return False
    tokens = ("/tmp/", "/home/", "/users/", "\\", "://", "bearer ", "password=", "viewer_id", "token=")
    return not any(token in lowered for token in tokens)


class BenchmarkStage(Versioned):
    """One measured step. Missing evidence stays blocked or unavailable."""

    stage: str = Field(min_length=1, max_length=40)
    status: Readiness
    started_at: AwareDatetime
    finished_at: AwareDatetime
    elapsed_ms: int = Field(ge=0)
    job_id: EntityId | None = None
    cache_hit: bool
    artifact_id: EntityId | None = None
    artifact_sha256: str | None = Field(default=None, pattern=_SHA)
    error_category: str = Field(default="none", max_length=40)
    human_action_required: bool = False
    delivery_id: EntityId | None = None
    delivery_manifest_sha256: str | None = Field(default=None, pattern=_SHA)
    readiness_classification: str = Field(default="not_recorded", max_length=40)
    execution: Execution = "recorded_evidence"

    @model_validator(mode="after")
    def times_move_forward(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("stage finished before it started")
        texts = (self.stage, self.error_category, self.readiness_classification)
        if any(not _public(item) for item in texts):
            raise ValueError("stage text contains a forbidden token")
        return self


class BenchmarkRun(Versioned):
    """One local readiness pass. Paths and raw media are not stored."""

    benchmark_run_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    fixture_kind: FixtureKind
    source_sha256: str = Field(pattern=_SHA)
    candidate_set_id: EntityId | None = None
    candidate_set_sha256: str | None = Field(default=None, pattern=_SHA)
    preview_set_id: EntityId | None = None
    preview_set_sha256: str | None = Field(default=None, pattern=_SHA)
    hero_set_id: EntityId | None = None
    hero_set_sha256: str | None = Field(default=None, pattern=_SHA)
    advanced_set_id: EntityId | None = None
    advanced_set_sha256: str | None = Field(default=None, pattern=_SHA)
    qa_set_id: EntityId | None = None
    qa_set_sha256: str | None = Field(default=None, pattern=_SHA)
    selected_candidate_ids: list[EntityId] = Field(default_factory=list)
    human_decision_ids: list[EntityId] = Field(default_factory=list)
    stages: list[BenchmarkStage] = Field(min_length=1)
    cache_hits: list[str] = Field(default_factory=list)
    artifact_ids: list[EntityId] = Field(default_factory=list)
    artifact_hashes: list[str] = Field(default_factory=list)
    output_width: int | None = Field(default=None, gt=0)
    output_height: int | None = Field(default=None, gt=0)
    output_video_codec: str | None = None
    output_audio_codec: str | None = None
    output_fps: str | None = None
    source_duration_us: int | None = Field(default=None, gt=0)
    output_duration_us: int | None = Field(default=None, gt=0)
    candidate_count: int | None = Field(default=None, ge=0)
    selected_count: int | None = Field(default=None, ge=0)
    preview_count: int | None = Field(default=None, ge=0)
    hero_count: int | None = Field(default=None, ge=0)
    advanced_count: int | None = Field(default=None, ge=0)
    qa_result: Readiness
    elapsed_ms: int = Field(ge=0)
    work_bytes: int | None = Field(default=None, ge=0)
    tool_versions: dict[str, str] = Field(default_factory=dict)
    model_revisions: dict[str, str] = Field(default_factory=dict)
    manual_actions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    readiness: Readiness
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def public_lists_are_safe(self) -> Self:
        texts = [
            *self.manual_actions,
            *self.warnings,
            *self.tool_versions.values(),
            *self.model_revisions.values(),
        ]
        if any(not _public(item) for item in texts):
            raise ValueError("benchmark text contains a forbidden token")
        if self.artifact_hashes != sorted(self.artifact_hashes):
            raise ValueError("artifact hashes must be sorted")
        return self


class V1ReadinessReport(Versioned):
    """What is ready, what is blocked, and what a person still has to do."""

    benchmark_run_id: EntityId
    technical: Readiness
    editorial: Readiness
    rights: Readiness
    qa: Readiness
    local_delivery: Readiness
    platform_publishing: Literal["not_implemented"] = "not_implemented"
    platform_adapter: Literal["passed", "unavailable"] = "passed"
    platform_dry_run: Readiness = "not_run"
    external_upload: Literal["not_configured", "not_run", "passed", "failed", "blocked", "unavailable"] = (
        "not_configured"
    )
    voicestudio: Readiness
    real_source_verified: Readiness
    real_source_reason: str = Field(min_length=1, max_length=160)
    overall: Readiness
    blocking_limitations: list[str] = Field(default_factory=list)
    manual_steps: list[str] = Field(default_factory=list)
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def limitations_are_public(self) -> Self:
        texts = [self.real_source_reason, *self.blocking_limitations, *self.manual_steps]
        if any(not _public(item) for item in texts):
            raise ValueError("readiness text contains a forbidden token")
        if self.platform_publishing != "not_implemented":
            raise ValueError("platform publishing is not implemented")
        return self
