"""Deterministic cohort descriptions. Missing numbers are not zeroes."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from clipforge.schemas.analytics import (
    AnalyticsCohort,
    AnalyticsComparison,
    CohortAggregate,
    EditorialFeatureSnapshot,
    PerformanceOutcome,
    decimal_text,
)
from clipforge.schemas.provenance import ArtifactProvenance

DIMENSIONS = (
    "platform",
    "campaign",
    "geography",
    "profile",
    "source",
    "measurement_window",
    "duration_bucket",
    "hook_type",
    "topic_tag",
    "cta",
    "format_tag",
    "audience_tag",
    "caption_presence",
    "broll_presence",
    "sfx_presence",
    "typography_presence",
    "diagram_presence",
    "reframing_strategy",
    "motion_library_version",
    "rank_band",
)

_SMALL = 5


@dataclass(frozen=True, slots=True)
class ComparisonFilter:
    platform: str | None = None
    campaign_id: str | None = None
    geography: str | None = None
    profile_id: str | None = None
    source_asset_id: str | None = None
    observed_from: datetime | None = None
    observed_to: datetime | None = None
    measurement_window: str | None = None
    duration_bucket: str | None = None
    hook_type: str | None = None
    topic_tag: str | None = None
    cta: str | None = None
    format_tag: str | None = None
    audience_tag: str | None = None
    caption_presence: str | None = None
    broll_presence: str | None = None
    sfx_presence: str | None = None
    typography_presence: str | None = None
    diagram_presence: str | None = None
    reframing_strategy: str | None = None
    motion_library_version: str | None = None
    rank_band: str | None = None


def compare_outcomes(
    *,
    project_id: str,
    dimension: str,
    pairs: list[tuple[PerformanceOutcome, EditorialFeatureSnapshot]],
    comparison_filter: ComparisonFilter,
    created_at: datetime,
    created_by: str,
) -> AnalyticsComparison:
    if dimension not in DIMENSIONS:
        raise ValueError(f"unknown comparison dimension {dimension}")
    chosen = [pair for pair in pairs if _matches(pair[0], pair[1], comparison_filter)]
    chosen.sort(key=lambda pair: (pair[0].observed_at, pair[0].outcome_id))
    if not chosen:
        return AnalyticsComparison(
            comparison_id=_comparison_id(project_id, dimension, comparison_filter),
            project_id=project_id,
            status="insufficient_evidence",
            dimension=dimension,
            observation_count=0,
            cohorts=[],
            note="insufficient_evidence: no observations matched. Missing metrics were not treated as zero.",
            provenance=_provenance(created_at, created_by, source_asset_ids=[]),
        )
    grouped: dict[str, list[tuple[PerformanceOutcome, EditorialFeatureSnapshot]]] = defaultdict(list)
    for outcome, snapshot in chosen:
        for key in _keys(outcome, snapshot, dimension):
            grouped[key].append((outcome, snapshot))
    cohorts = [_cohort(dimension, key, grouped[key]) for key in sorted(grouped)]
    return AnalyticsComparison(
        comparison_id=_comparison_id(project_id, dimension, comparison_filter),
        project_id=project_id,
        status="described",
        dimension=dimension,
        observation_count=len(chosen),
        cohorts=cohorts,
        note=(
            "This is descriptive evidence only. "
            "Missing metrics were not treated as zero. "
            "A row with several topic tags is counted in each of those tags."
        ),
        provenance=_provenance(
            created_at,
            created_by,
            source_asset_ids=sorted({outcome.source_asset_id for outcome, _snapshot in chosen}),
        ),
    )


def format_comparison(document: AnalyticsComparison) -> str:
    lines = [document.note, f"status: {document.status}", f"dimension: {document.dimension}"]
    lines.append(f"observations: {document.observation_count}")
    if document.status == "insufficient_evidence":
        return "\n".join(lines)
    for cohort in document.cohorts:
        item = cohort.aggregate
        lines.append(f"cohort {cohort.key}: {item.sample_count} observations")
        if item.small_cohort:
            lines.append(f"cohort {cohort.key}: small cohort")
        lines.append(f"cohort {cohort.key}: views coverage {item.views_count}/{item.sample_count}")
        if item.views_median is not None:
            lines.append(f"cohort {cohort.key}: median views {item.views_median}")
        lines.append(
            f"cohort {cohort.key}: completion-rate coverage {item.completion_rate_count}/{item.sample_count}"
        )
        if item.completion_rate_median is not None:
            lines.append(f"cohort {cohort.key}: median completion rate {item.completion_rate_median}")
    return "\n".join(lines)


def _cohort(
    dimension: str,
    key: str,
    rows: list[tuple[PerformanceOutcome, EditorialFeatureSnapshot]],
) -> AnalyticsCohort:
    sample = len(rows)
    views = [row[0].metrics.views for row in rows if row[0].metrics.views is not None]
    watch = [
        row[0].metrics.average_watch_time_us for row in rows if row[0].metrics.average_watch_time_us is not None
    ]
    rates = [
        Decimal(row[0].metrics.completion_rate) for row in rows if row[0].metrics.completion_rate is not None
    ]
    likes = _ints(rows, "likes")
    comments = _ints(rows, "comments")
    shares = _ints(rows, "shares")
    saves = _ints(rows, "saves")
    paid = _ints(rows, "paid_views")
    revenue = [
        Decimal(row[0].metrics.revenue_amount) for row in rows if row[0].metrics.revenue_amount is not None
    ]
    human = [_human_seconds(row[0]) for row in rows]
    human_present = [item for item in human if item is not None]
    engagement = _engagement(rows)
    profiles = sorted({row[1].profile_id for row in rows if row[1].profile_id})
    policies = sorted({policy for row in rows for policy in row[1].policy_ids})
    times = [row[0].observed_at for row in rows]
    aggregate = CohortAggregate(
        sample_count=sample,
        small_cohort=sample < _SMALL,
        views_count=len(views),
        views_total=sum(views) if views else None,
        views_mean=_mean_ints(views),
        views_median=_median_ints(views),
        watch_time_count=len(watch),
        watch_time_mean_us=_mean_ints(watch),
        completion_rate_count=len(rates),
        completion_rate_mean=_mean_decimals(rates),
        completion_rate_median=_median_decimals(rates),
        likes_count=len(likes),
        likes_total=sum(likes) if likes else None,
        comments_count=len(comments),
        comments_total=sum(comments) if comments else None,
        shares_count=len(shares),
        shares_total=sum(shares) if shares else None,
        saves_count=len(saves),
        saves_total=sum(saves) if saves else None,
        engagement_rate_count=len(engagement),
        engagement_rate_mean=_mean_decimals(engagement),
        paid_views_count=len(paid),
        paid_views_total=sum(paid) if paid else None,
        revenue_count=len(revenue),
        revenue_total=_sum_decimals(revenue),
        revenue_currency="USD" if revenue else None,
        human_time_count=len(human_present),
        human_time_mean_seconds=_mean_ints(human_present),
        missing_views=sample - len(views),
        missing_completion_rate=sample - len(rates),
        missing_revenue=sample - len(revenue),
        observed_from=min(times),
        observed_to=max(times),
    )
    return AnalyticsCohort(
        dimension=dimension,
        key=key,
        aggregate=aggregate,
        artifact_count=len({row[0].artifact_id for row in rows}),
        profile_ids=profiles,
        policy_ids=policies,
    )


def _ints(
    rows: list[tuple[PerformanceOutcome, EditorialFeatureSnapshot]],
    name: str,
) -> list[int]:
    found: list[int] = []
    for outcome, _snapshot in rows:
        value = getattr(outcome.metrics, name)
        if value is not None:
            found.append(int(value))
    return found


def _engagement(rows: list[tuple[PerformanceOutcome, EditorialFeatureSnapshot]]) -> list[Decimal]:
    found: list[Decimal] = []
    for outcome, _snapshot in rows:
        metrics = outcome.metrics
        if (
            metrics.views is None
            or metrics.views <= 0
            or metrics.likes is None
            or metrics.comments is None
            or metrics.shares is None
            or metrics.saves is None
        ):
            continue
        total = metrics.likes + metrics.comments + metrics.shares + metrics.saves
        found.append(Decimal(total) / Decimal(metrics.views))
    return found


def _human_seconds(outcome: PerformanceOutcome) -> int | None:
    parts = [
        outcome.human.planning_seconds,
        outcome.human.editing_seconds,
        outcome.human.review_seconds,
        outcome.human.correction_seconds,
    ]
    present = [item for item in parts if item is not None]
    if not present:
        return None
    return sum(present)


def _mean_ints(values: list[int]) -> str | None:
    if not values:
        return None
    return decimal_text(Decimal(sum(values)) / Decimal(len(values)))


def _median_ints(values: list[int]) -> str | None:
    if not values:
        return None
    return _median_decimals([Decimal(item) for item in values])


def _mean_decimals(values: list[Decimal]) -> str | None:
    if not values:
        return None
    return decimal_text(sum(values, Decimal(0)) / Decimal(len(values)))


def _median_decimals(values: list[Decimal]) -> str | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return decimal_text(ordered[middle])
    return decimal_text((ordered[middle - 1] + ordered[middle]) / Decimal(2))


def _sum_decimals(values: list[Decimal]) -> str | None:
    if not values:
        return None
    return decimal_text(sum(values, Decimal(0)))


def _matches(
    outcome: PerformanceOutcome,
    snapshot: EditorialFeatureSnapshot,
    chosen: ComparisonFilter,
) -> bool:
    if chosen.platform is not None and outcome.platform != chosen.platform:
        return False
    if chosen.campaign_id is not None and outcome.campaign_id != chosen.campaign_id:
        return False
    if chosen.geography is not None and outcome.geography != chosen.geography:
        return False
    if chosen.profile_id is not None and snapshot.profile_id != chosen.profile_id:
        return False
    if chosen.source_asset_id is not None and outcome.source_asset_id != chosen.source_asset_id:
        return False
    if chosen.observed_from is not None and outcome.observed_at < chosen.observed_from:
        return False
    if chosen.observed_to is not None and outcome.observed_at > chosen.observed_to:
        return False
    if chosen.measurement_window is not None and outcome.measurement_window != chosen.measurement_window:
        return False
    checks = {
        "duration_bucket": snapshot.duration_bucket,
        "hook_type": snapshot.labels.hook_type,
        "cta": snapshot.labels.cta,
        "format_tag": snapshot.labels.format_tag,
        "audience_tag": snapshot.labels.audience_tag,
        "caption_presence": _presence(snapshot.caption_count),
        "broll_presence": _presence(snapshot.broll_count),
        "sfx_presence": _presence(snapshot.sfx_count),
        "typography_presence": _presence(snapshot.typography_count),
        "diagram_presence": _presence(snapshot.diagram_count),
        "reframing_strategy": snapshot.reframing_strategy,
        "motion_library_version": snapshot.motion_library_version,
        "rank_band": snapshot.rank_band,
    }
    for name, actual in checks.items():
        expected = getattr(chosen, name)
        if expected is not None and actual != expected:
            return False
    return chosen.topic_tag is None or chosen.topic_tag in snapshot.labels.topic_tags


def _keys(
    outcome: PerformanceOutcome,
    snapshot: EditorialFeatureSnapshot,
    dimension: str,
) -> list[str]:
    if dimension == "topic_tag":
        return list(snapshot.labels.topic_tags) or ["unspecified"]
    value = {
        "platform": outcome.platform,
        "campaign": outcome.campaign_id,
        "geography": outcome.geography,
        "profile": snapshot.profile_id,
        "source": outcome.source_asset_id,
        "measurement_window": outcome.measurement_window,
        "duration_bucket": snapshot.duration_bucket,
        "hook_type": snapshot.labels.hook_type,
        "cta": snapshot.labels.cta,
        "format_tag": snapshot.labels.format_tag,
        "audience_tag": snapshot.labels.audience_tag,
        "caption_presence": _presence(snapshot.caption_count),
        "broll_presence": _presence(snapshot.broll_count),
        "sfx_presence": _presence(snapshot.sfx_count),
        "typography_presence": _presence(snapshot.typography_count),
        "diagram_presence": _presence(snapshot.diagram_count),
        "reframing_strategy": snapshot.reframing_strategy,
        "motion_library_version": snapshot.motion_library_version,
        "rank_band": snapshot.rank_band,
    }[dimension]
    return [value or "unspecified"]


def _presence(count: int | None) -> str | None:
    if count is None:
        return None
    if count == 0:
        return "absent"
    return "present"


def _comparison_id(project_id: str, dimension: str, chosen: ComparisonFilter) -> str:
    payload = json.dumps(asdict(chosen), sort_keys=True, default=_json_default)
    return hashlib.sha256(f"{project_id}:{dimension}:{payload}".encode()).hexdigest()


def _json_default(value: object) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _provenance(
    created_at: datetime,
    created_by: str,
    *,
    source_asset_ids: list[str] | tuple[str, ...],
) -> ArtifactProvenance:
    return ArtifactProvenance(
        created_at=created_at,
        created_by=created_by,
        tool="clipforge-analytics",
        tool_version="0",
        source_asset_ids=list(source_asset_ids),
    )
