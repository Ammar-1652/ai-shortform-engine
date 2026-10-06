"""A campaign production run. It stores evidence ids, not filesystem paths."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.campaign import _plain
from clipforge.schemas.common import EntityId, Versioned

_SHA = r"^[0-9a-f]{64}$"
RunStatus = Literal["succeeded", "partial", "blocked", "failed", "cancelled"]
StageStatus = Literal["succeeded", "partial", "blocked", "failed", "cancelled", "not_run"]
StageName = Literal[
    "source_verify",
    "ingest",
    "media_prepare",
    "transcribe",
    "vision",
    "mine",
    "preview",
    "review",
    "align",
    "hero_plan",
    "hero_render",
    "advanced",
    "qa",
    "narration",
    "delivery",
]
STAGES: tuple[StageName, ...] = (
    "source_verify",
    "ingest",
    "media_prepare",
    "transcribe",
    "vision",
    "mine",
    "preview",
    "review",
    "align",
    "hero_plan",
    "hero_render",
    "advanced",
    "qa",
    "narration",
    "delivery",
)


def _token(value: str, *, label: str) -> str:
    return _plain(value, label=label)


class CampaignStageRecord(Versioned):
    """One stage for one source. A cache hit still names the producer it reused."""

    stage: StageName
    status: StageStatus
    job_id: EntityId | None = None
    artifact_id: EntityId | None = None
    artifact_sha256: str | None = Field(default=None, pattern=_SHA)
    cache_hit: bool = False
    reason_code: str = Field(min_length=1, max_length=80)

    @field_validator("reason_code")
    @classmethod
    def reason_is_plain(cls, value: str) -> str:
        return _token(value, label="stage reason")


class CampaignCandidateRecord(Versioned):
    """Why one candidate was kept. The runner does not approve it."""

    candidate_id: EntityId
    rank: int = Field(ge=1)
    score: str = Field(default="unavailable", min_length=1, max_length=40)
    selection_reason: str = Field(min_length=1, max_length=200)
    source_start_us: int | None = Field(default=None, ge=0)
    source_end_us: int | None = Field(default=None, ge=0)
    review_id: EntityId | None = None
    review_decision: str = Field(default="not_recorded", min_length=1, max_length=40)
    preview_artifact_id: EntityId | None = None
    hero_review_id: EntityId | None = None
    hero_artifact_id: EntityId | None = None
    advanced_artifact_id: EntityId | None = None
    caption_quality: str = Field(default="provisional", min_length=1, max_length=40)
    alignment_status: str = Field(min_length=1, max_length=40)
    narration_status: str = Field(min_length=1, max_length=40)
    qa_status: str = Field(min_length=1, max_length=40)
    delivery_status: str = Field(min_length=1, max_length=40)

    @field_validator(
        "score",
        "selection_reason",
        "review_decision",
        "caption_quality",
        "alignment_status",
        "narration_status",
        "qa_status",
        "delivery_status",
    )
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _token(value, label="candidate record")

    @model_validator(mode="after")
    def time_map_is_a_positive_span(self) -> Self:
        if (self.source_start_us is None) != (self.source_end_us is None):
            raise ValueError("candidate time map bounds must be set together")
        if (
            self.source_start_us is not None
            and self.source_end_us is not None
            and self.source_end_us <= self.source_start_us
        ):
            raise ValueError("candidate time map must be positive")
        return self


class CampaignSourceRun(Versioned):
    """Evidence for one authorized source inside a campaign run."""

    source_id: EntityId
    source_asset_id: EntityId | None = None
    source_sha256: str = Field(pattern=_SHA)
    rights_state: str = Field(min_length=1, max_length=40)
    stages: list[CampaignStageRecord]
    candidates: list[CampaignCandidateRecord]
    hero_artifact_id: EntityId | None = None
    advanced_artifact_id: EntityId | None = None
    qa_set_id: EntityId | None = None
    qa_set_sha256: str | None = Field(default=None, pattern=_SHA)
    delivery_id: EntityId | None = None
    delivery_manifest_sha256: str | None = Field(default=None, pattern=_SHA)
    delivery_files_sha256: str | None = Field(default=None, pattern=_SHA)
    narration_artifact_id: EntityId | None = None
    narration_audio_sha256: str | None = Field(default=None, pattern=_SHA)
    broll_status: str = Field(default="absent", min_length=1, max_length=40)
    sfx_status: str = Field(default="absent", min_length=1, max_length=40)
    cache_status: Literal["hit", "miss", "mixed"] = "miss"
    status: RunStatus
    reason_code: str = Field(min_length=1, max_length=80)
    requested_locale: str = ""

    @field_validator("rights_state", "reason_code", "broll_status", "sfx_status")
    @classmethod
    def codes_are_plain(cls, value: str) -> str:
        return _token(value, label="source run")

    @model_validator(mode="after")
    def stages_follow_the_contract(self) -> Self:
        names = [item.stage for item in self.stages]
        if names != list(STAGES):
            raise ValueError("campaign stages are missing or out of order")
        return self


class CampaignProductionRun(Versioned):
    """The reproducible record of one campaign execution."""

    campaign_run_id: EntityId
    project_id: EntityId
    campaign_id: EntityId
    created_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    source_ids: list[EntityId] = Field(min_length=1)
    language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    narration_enabled: bool
    voice_id: str | None = None
    engine_id: str | None = None
    model_id: str | None = None
    model_revision: str | None = None
    model_license: str | None = None
    alignment_provider: str = Field(min_length=1, max_length=40)
    alignment_language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    alignment_model: str | None = None
    alignment_revision: str | None = None
    alignment_checkpoint_sha256: str | None = Field(default=None, pattern=_SHA)
    fingerprint: str = Field(pattern=_SHA)
    approval_policy: str = Field(default="existing_human_review", min_length=1, max_length=80)
    publishing: Literal["deferred"] = "deferred"
    browser_concurrency: Literal[1] = 1
    render_policy: Literal["candidate_local_span"] = "candidate_local_span"
    sources: list[CampaignSourceRun]
    status: RunStatus
    reason_code: str = Field(min_length=1, max_length=80)

    @field_validator(
        "voice_id",
        "engine_id",
        "model_id",
        "model_revision",
        "model_license",
        "alignment_provider",
        "alignment_model",
        "alignment_revision",
        "approval_policy",
        "reason_code",
    )
    @classmethod
    def optional_labels_are_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _token(value, label="campaign run")

    @model_validator(mode="after")
    def sources_match_the_selection(self) -> Self:
        if self.source_ids != sorted(self.source_ids):
            raise ValueError("campaign source ids must be in deterministic order")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("campaign source ids must be unique")
        found = [item.source_id for item in self.sources]
        if found != self.source_ids:
            raise ValueError("campaign sources do not match the selected ids")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("campaign completion is earlier than creation")
        text = self.model_dump_json()
        lowered = text.lower()
        if any(token in lowered for token in ("/home/", "/tmp/", "/users/", "file://", "bearer ", "token=")):
            raise ValueError("campaign run contains a path or a secret")
        return self
