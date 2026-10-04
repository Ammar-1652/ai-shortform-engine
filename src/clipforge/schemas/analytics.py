"""Append-only performance observations. Missing metrics stay missing.

These records describe what was measured. They do not predict, rank, approve,
or publish. A later observation is a new row, not an edit of an old one.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"
_LABEL = r"^(unknown|none|[a-z0-9][a-z0-9-]{0,40})$"
_PLATFORM = r"^[a-z][a-z0-9_]{0,31}$"
_GEOGRAPHY = r"^[A-Z]{2}$"
_WINDOW = r"^[a-z0-9][a-z0-9._:-]{0,63}$"
_RATE = r"^(?:0(?:\.[0-9]{1,6})?|1(?:\.0{1,6})?)$"
_MONEY = r"^(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,4})?$"
_KEY = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"
QAPolicy = Literal["not_required", "historical", "current"]
ReviewChoice = Literal["approved", "rejected", "changes_requested"]


def _reject_unsafe_text(value: str, label: str) -> str:
    stripped = value.strip()
    lowered = stripped.lower()
    if stripped != value:
        raise ValueError(f"{label} must not have surrounding space")
    if any(ord(character) < 32 for character in stripped):
        raise ValueError(f"{label} must not contain control characters")
    if any(token in lowered for token in ("<", ">", "javascript:", "://", "bearer ", "password=")):
        raise ValueError(f"{label} contains markup or a secret-like token")
    if any(token in lowered for token in ("/tmp/", "/home/", "/users/", "viewer_id", "token=")):
        raise ValueError(f"{label} contains a forbidden identifier")
    if "\\" in stripped or stripped.startswith("/") or ".." in stripped.split("/"):
        raise ValueError(f"{label} contains a filesystem path")
    return stripped


class PerformanceMetrics(Versioned):
    """Optional platform measurements. An absent field was not reported."""

    views: int | None = Field(default=None, ge=0)
    unique_viewers: int | None = Field(default=None, ge=0)
    total_watch_time_us: int | None = Field(default=None, ge=0)
    average_watch_time_us: int | None = Field(default=None, ge=0)
    completion_count: int | None = Field(default=None, ge=0)
    completion_rate: str | None = Field(default=None, pattern=_RATE)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)
    follows: int | None = Field(default=None, ge=0)
    clicks: int | None = Field(default=None, ge=0)
    paid_views: int | None = Field(default=None, ge=0)
    revenue_amount: str | None = Field(default=None, pattern=_MONEY)
    revenue_currency: Literal["USD"] | None = None

    @model_validator(mode="after")
    def metrics_agree(self) -> Self:
        if (self.revenue_amount is None) != (self.revenue_currency is None):
            raise ValueError("revenue amount and currency must both be set, or both be absent")
        if self.revenue_amount is not None and Decimal(self.revenue_amount) < 0:
            raise ValueError("revenue cannot be negative")
        views = self.views
        if views is not None and self.completion_count is not None and self.completion_count > views:
            raise ValueError("completion count cannot exceed views")
        if views is not None and self.unique_viewers is not None and self.unique_viewers > views:
            raise ValueError("unique viewers cannot exceed views")
        if views is not None and self.paid_views is not None and self.paid_views > views:
            raise ValueError("paid views cannot exceed views")
        if self.completion_rate is not None and views == 0:
            raise ValueError("completion rate is undefined when views are zero")
        if self.completion_rate is not None and views not in (None, 0) and self.completion_count is not None:
            expected = Decimal(self.completion_count) / Decimal(views)
            reported = Decimal(self.completion_rate)
            if abs(expected - reported) > Decimal("0.001"):
                raise ValueError("completion rate does not match completion count and views")
        return self


class HumanEvidence(Versioned):
    """Manual time and a copied review decision. This does not approve anything."""

    planning_seconds: int | None = Field(default=None, ge=0)
    editing_seconds: int | None = Field(default=None, ge=0)
    review_seconds: int | None = Field(default=None, ge=0)
    correction_seconds: int | None = Field(default=None, ge=0)
    reviewer_id: str | None = Field(default=None, min_length=1, max_length=80)
    review_id: EntityId | None = None
    review_decision: ReviewChoice | None = None
    approval_at: AwareDatetime | None = None

    @field_validator("reviewer_id")
    @classmethod
    def reviewer_is_an_opaque_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _reject_unsafe_text(value, "reviewer_id")

    @model_validator(mode="after")
    def decision_names_a_review(self) -> Self:
        if self.review_decision is not None and self.review_id is None:
            raise ValueError("a copied review decision requires the original review id")
        return self


class ManualLabels(Versioned):
    """Labels a person typed. ``unknown`` means the person did not supply one."""

    hook_type: str = "unknown"
    topic_tags: list[str] = Field(default_factory=list, max_length=8)
    cta: str = "unknown"
    format_tag: str = "unknown"
    audience_tag: str = "unknown"

    @field_validator("hook_type", "cta", "format_tag", "audience_tag")
    @classmethod
    def one_label(cls, value: str) -> str:
        normalized = _reject_unsafe_text(value.lower(), "label")
        if re.fullmatch(_LABEL, normalized) is None:
            raise ValueError("label must be unknown, none, or a short normalized tag")
        return normalized

    @field_validator("topic_tags")
    @classmethod
    def topics_are_normalized(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            normalized = _reject_unsafe_text(value.lower(), "topic tag")
            if re.fullmatch(_LABEL, normalized) is None or normalized in {"unknown", "none"}:
                raise ValueError("topic tags must be short normalized tags")
            cleaned.append(normalized)
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("topic tags must be unique")
        return sorted(cleaned)


class EditorialFeatureSnapshot(Versioned):
    """Facts copied from one artifact at one observed time. Missing facts stay null."""

    snapshot_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    artifact_id: EntityId
    artifact_kind: str = Field(min_length=1, max_length=80)
    observed_at: AwareDatetime
    artifact_sha256: str = Field(pattern=_SHA)
    manifest_sha256: str | None = Field(default=None, pattern=_SHA)
    media_available: bool
    candidate_id: EntityId | None = None
    duration_us: int | None = Field(default=None, gt=0)
    duration_bucket: str | None = None
    candidate_rank: int | None = Field(default=None, ge=1)
    rank_band: str | None = None
    creative_score: str | None = Field(default=None, pattern=_RATE)
    edit_opportunity_score: str | None = Field(default=None, pattern=_RATE)
    transcript_word_count: int | None = Field(default=None, ge=0)
    caption_count: int | None = Field(default=None, ge=0)
    caption_style: str | None = None
    caption_algorithm_version: str | None = None
    alignment_quality: str | None = None
    profile_id: EntityId | None = None
    profile_sha256: str | None = Field(default=None, pattern=_SHA)
    policy_ids: list[EntityId] = Field(default_factory=list)
    motion_library_version: str | None = None
    renderer_recipe: str | None = None
    reframing_strategy: str | None = None
    broll_count: int | None = Field(default=None, ge=0)
    broll_duration_us: int | None = Field(default=None, ge=0)
    sfx_count: int | None = Field(default=None, ge=0)
    sfx_duration_us: int | None = Field(default=None, ge=0)
    sfx_roles: list[str] = Field(default_factory=list)
    sfx_gain_min_db: str | None = None
    sfx_gain_max_db: str | None = None
    typography_count: int | None = Field(default=None, ge=0)
    diagram_count: int | None = Field(default=None, ge=0)
    emphasis_count: int | None = Field(default=None, ge=0)
    evidence_sha256: list[str] = Field(default_factory=list)
    human_review_present: bool | None = None
    human_decision: ReviewChoice | None = None
    labels: ManualLabels = Field(default_factory=ManualLabels)
    platform: str = Field(pattern=_PLATFORM)
    geography: str | None = Field(default=None, pattern=_GEOGRAPHY)
    campaign_id: EntityId | None = None
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def snapshot_is_public(self) -> Self:
        if self.evidence_sha256 != sorted(self.evidence_sha256):
            raise ValueError("evidence hashes must be sorted")
        if len(set(self.evidence_sha256)) != len(self.evidence_sha256):
            raise ValueError("evidence hashes must be unique")
        for digest in self.evidence_sha256:
            if len(digest) != 64:
                raise ValueError("evidence hash must be SHA-256")
        if self.policy_ids != sorted(self.policy_ids):
            raise ValueError("policy ids must be sorted")
        return self


class PerformanceOutcome(Versioned):
    """One immutable measurement of one artifact. Corrections are new rows."""

    outcome_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    artifact_id: EntityId
    artifact_kind: str = Field(min_length=1, max_length=80)
    snapshot_id: EntityId
    candidate_id: EntityId | None = None
    artifact_sha256: str = Field(pattern=_SHA)
    manifest_sha256: str | None = Field(default=None, pattern=_SHA)
    media_available: bool
    duration_us: int | None = Field(default=None, gt=0)
    platform: str = Field(pattern=_PLATFORM)
    platform_post_id: str | None = Field(default=None, max_length=128)
    campaign_id: EntityId | None = None
    geography: str | None = Field(default=None, pattern=_GEOGRAPHY)
    published_at: AwareDatetime | None = None
    observed_at: AwareDatetime
    measurement_window: str = Field(pattern=_WINDOW)
    metrics: PerformanceMetrics
    human: HumanEvidence
    qa_policy: QAPolicy
    qa_artifact_id: EntityId | None = None
    qa_status: Literal["pass", "fail", "insufficient_evidence", "unavailable"] | None = None
    idempotency_key: str = Field(pattern=_KEY)
    provenance: ArtifactProvenance

    @field_validator("platform_post_id")
    @classmethod
    def post_id_is_opaque(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _reject_unsafe_text(value, "platform post id")
        if not cleaned:
            raise ValueError("platform post id must not be blank")
        return cleaned

    @field_validator("platform")
    @classmethod
    def platform_is_normalized(cls, value: str) -> str:
        return _reject_unsafe_text(value, "platform")

    @model_validator(mode="after")
    def times_and_qa_agree(self) -> Self:
        if self.published_at is not None and self.observed_at < self.published_at:
            raise ValueError("observed time cannot precede published time")
        if self.qa_policy == "not_required" and self.qa_artifact_id is not None:
            raise ValueError("a not_required QA policy cannot name a QA artifact")
        if self.qa_policy != "not_required" and self.qa_artifact_id is None:
            raise ValueError("historical and current QA policies require a QA artifact id")
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("outcome provenance must include the source asset")
        return self


class AnalyticsObservationInput(Versioned):
    """One local import row. Unknown fields are rejected."""

    outcome_id: EntityId
    idempotency_key: str = Field(pattern=_KEY)
    project_id: EntityId
    source_asset_id: EntityId
    artifact_id: EntityId
    artifact_kind: str = Field(min_length=1, max_length=80)
    candidate_id: EntityId | None = None
    candidate_media_sha256: str | None = Field(default=None, pattern=_SHA)
    artifact_sha256: str = Field(pattern=_SHA)
    manifest_sha256: str | None = Field(default=None, pattern=_SHA)
    duration_us: int | None = Field(default=None, gt=0)
    platform: str = Field(pattern=_PLATFORM)
    platform_post_id: str | None = Field(default=None, max_length=128)
    campaign_id: EntityId | None = None
    geography: str | None = Field(default=None, pattern=_GEOGRAPHY)
    published_at: AwareDatetime | None = None
    observed_at: AwareDatetime
    measurement_window: str = Field(pattern=_WINDOW)
    metrics: PerformanceMetrics = Field(default_factory=PerformanceMetrics)
    human: HumanEvidence = Field(default_factory=HumanEvidence)
    labels: ManualLabels = Field(default_factory=ManualLabels)
    qa_policy: QAPolicy = "not_required"
    qa_artifact_id: EntityId | None = None
    created_by: str = Field(min_length=1, max_length=80)

    @field_validator("created_by", "platform")
    @classmethod
    def public_text(cls, value: str) -> str:
        return _reject_unsafe_text(value, "field")

    @field_validator("platform_post_id")
    @classmethod
    def post_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _reject_unsafe_text(value, "platform post id")


class AnalyticsImportRecord(Versioned):
    """Provenance for one accepted local file. The filesystem path is not stored."""

    import_id: EntityId
    project_id: EntityId
    content_sha256: str = Field(pattern=_SHA)
    profile_id: EntityId = "clipforge-observation-v1"
    validation_summary: str = Field(default="", max_length=500)
    outcome_ids: list[EntityId] = Field(min_length=1)
    created_at: AwareDatetime
    created_by: str = Field(min_length=1, max_length=80)
    provenance: ArtifactProvenance

    @field_validator("validation_summary", "created_by")
    @classmethod
    def import_text_is_public(cls, value: str) -> str:
        if value == "":
            return value
        return _reject_unsafe_text(value, "import text")


class CohortAggregate(Versioned):
    """Numbers computed only from observations that actually reported each metric."""

    sample_count: int = Field(ge=0)
    small_cohort: bool
    views_count: int = Field(ge=0)
    views_total: int | None = Field(default=None, ge=0)
    views_mean: str | None = None
    views_median: str | None = None
    watch_time_count: int = Field(ge=0)
    watch_time_mean_us: str | None = None
    completion_rate_count: int = Field(ge=0)
    completion_rate_mean: str | None = None
    completion_rate_median: str | None = None
    likes_count: int = Field(ge=0)
    likes_total: int | None = None
    comments_count: int = Field(ge=0)
    comments_total: int | None = None
    shares_count: int = Field(ge=0)
    shares_total: int | None = None
    saves_count: int = Field(ge=0)
    saves_total: int | None = None
    engagement_rate_count: int = Field(ge=0)
    engagement_rate_mean: str | None = None
    paid_views_count: int = Field(ge=0)
    paid_views_total: int | None = None
    revenue_count: int = Field(ge=0)
    revenue_total: str | None = None
    revenue_currency: Literal["USD"] | None = None
    human_time_count: int = Field(ge=0)
    human_time_mean_seconds: str | None = None
    missing_views: int = Field(ge=0)
    missing_completion_rate: int = Field(ge=0)
    missing_revenue: int = Field(ge=0)
    observed_from: AwareDatetime | None = None
    observed_to: AwareDatetime | None = None


class AnalyticsCohort(Versioned):
    """One descriptive slice. The key is a label, not a rank."""

    dimension: str = Field(min_length=1, max_length=40)
    key: str = Field(min_length=1, max_length=80)
    aggregate: CohortAggregate
    artifact_count: int = Field(ge=0)
    profile_ids: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)


class AnalyticsComparison(Versioned):
    """A read-only description. It does not recommend a change."""

    comparison_id: EntityId
    project_id: EntityId
    status: Literal["described", "insufficient_evidence"]
    dimension: str
    observation_count: int = Field(ge=0)
    cohorts: list[AnalyticsCohort]
    note: str = Field(min_length=1, max_length=400)
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def empty_means_insufficient(self) -> Self:
        if self.observation_count == 0 and self.status != "insufficient_evidence":
            raise ValueError("an empty comparison is insufficient_evidence")
        if self.status == "insufficient_evidence" and self.cohorts:
            raise ValueError("insufficient evidence does not include cohort numbers")
        keys = [item.key for item in self.cohorts]
        if keys != sorted(keys):
            raise ValueError("cohorts must be ordered by key")
        return self


class EditorialLabelSet(Versioned):
    """One append-only manual label save. Older rows stay in history."""

    label_set_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    artifact_id: EntityId
    outcome_id: EntityId | None = None
    snapshot_id: EntityId | None = None
    previous_label_set_id: EntityId | None = None
    labels: ManualLabels
    platform: str | None = Field(default=None, pattern=r"^(unknown|[a-z][a-z0-9_]{0,31})$")
    campaign_id: EntityId | None = None
    geography: str | None = Field(default=None, pattern=_GEOGRAPHY)
    reviewer_id: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=500)
    confidence: str | None = Field(default=None, pattern=_RATE)
    created_at: AwareDatetime
    provenance: ArtifactProvenance

    @field_validator("reviewer_id", "notes")
    @classmethod
    def public_note(cls, value: str) -> str:
        if value == "":
            return value
        return _reject_unsafe_text(value, "label text")

    @model_validator(mode="after")
    def lineage_is_present(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("label provenance must include the source asset")
        return self


class EditorialLabelAssignment(Versioned):
    """A request to append one label set. Unknown keys are rejected."""

    project_id: EntityId
    source_asset_id: EntityId
    artifact_id: EntityId
    outcome_id: EntityId | None = None
    snapshot_id: EntityId | None = None
    expected_label_set_id: EntityId | None = None
    expected_artifact_sha256: str | None = Field(default=None, pattern=_SHA)
    labels: ManualLabels = Field(default_factory=ManualLabels)
    platform: str | None = Field(default=None, pattern=r"^(unknown|[a-z][a-z0-9_]{0,31})$")
    campaign_id: EntityId | None = None
    geography: str | None = Field(default=None, pattern=_GEOGRAPHY)
    reviewer_id: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=500)
    confidence: str | None = Field(default=None, pattern=_RATE)

    @field_validator("reviewer_id", "notes")
    @classmethod
    def public_note(cls, value: str) -> str:
        if value == "":
            return value
        return _reject_unsafe_text(value, "label text")


class EditorialLabelHistory(Versioned):
    """Oldest to newest label sets for one artifact. The last row is effective."""

    project_id: EntityId
    artifact_id: EntityId
    effective_label_set_id: EntityId | None = None
    entries: list[EditorialLabelSet]


class AnalyticsLabelCacheRecord(Versioned):
    """Sidecar identity for the current label history. Paths are not stored."""

    project_id: EntityId
    source_asset_id: EntityId
    artifact_id: EntityId
    artifact_sha256: str = Field(pattern=_SHA)
    outcome_id: EntityId | None = None
    snapshot_id: EntityId | None = None
    label_set_id: EntityId
    label_history_sha256: str = Field(pattern=_SHA)
    import_profile_id: str = Field(default="none", max_length=80)
    created_at: AwareDatetime


class AnalyticsImportProfile(Versioned):
    """A local parser profile. It does not contact a platform."""

    profile_id: EntityId
    kind: Literal["native", "tabular"]
    formats: list[Literal["json", "jsonl", "csv"]] = Field(min_length=1)
    unknown_columns: Literal["reject", "ignore"] = "reject"
    columns: dict[str, list[str]] = Field(default_factory=dict)


class ImportValidationSummary(Versioned):
    """What an accepted file contained. The file path is not stored."""

    profile_id: EntityId
    row_count: int = Field(ge=0)
    status: Literal["accepted", "replayed"]


def decimal_text(value: Decimal) -> str:
    """Render a decimal without binary float noise."""
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
