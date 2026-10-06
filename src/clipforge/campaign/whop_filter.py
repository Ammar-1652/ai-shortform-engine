"""Deterministic Whop campaign filters. Membership is not rights evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from clipforge.schemas.whop import WhopCampaignRecord, WhopCampaignSnapshot, WhopCampaignSourceRecord
from clipforge.schemas.whop_discovery import WhopFilterDecision, WhopLiveDiscoveryRequest


def filter_campaigns(
    snapshot: WhopCampaignSnapshot,
    request: WhopLiveDiscoveryRequest,
    *,
    now: datetime | None = None,
) -> list[WhopFilterDecision]:
    """Return one decision per campaign. The order follows the snapshot."""
    moment = now or datetime.now(UTC)
    decisions: list[WhopFilterDecision] = []
    for campaign in snapshot.campaigns:
        reason, source_ids = _decision(campaign, request, snapshot.exported_at, moment)
        decisions.append(
            WhopFilterDecision(
                campaign_id=campaign.campaign_id,
                included=reason is None,
                reason_code=reason or "included",
                included_source_ids=source_ids,
            )
        )
    return decisions


def campaign_block_reason(
    campaign: WhopCampaignRecord,
    request: WhopLiveDiscoveryRequest,
    exported_at: datetime,
    now: datetime,
) -> str | None:
    """Return a campaign-level exclusion. Source checks are separate."""
    return _campaign_reason(campaign, request, exported_at, now)


def source_block_reason(
    source: WhopCampaignSourceRecord,
    request: WhopLiveDiscoveryRequest,
) -> str | None:
    """Return why one source fails the request. A selected flag is not a pass."""
    return _one_source(source, request)


def _decision(
    campaign: WhopCampaignRecord,
    request: WhopLiveDiscoveryRequest,
    exported_at: datetime,
    now: datetime,
) -> tuple[str | None, list[str]]:
    reason = _campaign_reason(campaign, request, exported_at, now)
    if reason is not None:
        return reason, []
    source_reason, source_ids = _passing_sources(campaign, request)
    if source_reason is not None:
        return source_reason, []
    return None, source_ids


def _campaign_reason(
    campaign: WhopCampaignRecord,
    request: WhopLiveDiscoveryRequest,
    exported_at: datetime,
    now: datetime,
) -> str | None:
    if request.require_status is not None and campaign.status != request.require_status:
        return "status_not_active"
    if request.prohibited_categories and _category(campaign) in _lower(request.prohibited_categories):
        return "category_prohibited"
    if request.allowed_categories and _category(campaign) not in _lower(request.allowed_categories):
        return "category_not_allowed"
    if request.require_policy is not None and campaign.policy_state != request.require_policy:
        return "policy_blocked"
    if campaign.policy_state in {"unknown", "prohibited"}:
        return "policy_blocked"
    if request.language is not None and campaign.language not in {None, request.language}:
        return "language_mismatch"
    if request.query is not None and request.query.casefold() not in _search_text(campaign):
        return "search_mismatch"
    if request.max_age_hours is not None and exported_at < now - timedelta(hours=request.max_age_hours):
        return "stale_campaign"
    return None


def _passing_sources(
    campaign: WhopCampaignRecord,
    request: WhopLiveDiscoveryRequest,
) -> tuple[str | None, list[str]]:
    if not campaign.sources:
        return "missing_source", []
    passed: list[str] = []
    first = "rights_not_allowed"
    for source in campaign.sources:
        reason = _one_source(source, request)
        if reason is None:
            passed.append(source.source_id)
            continue
        if not passed:
            first = reason
    if passed:
        return None, sorted(set(passed))
    return first, []


def _one_source(source: WhopCampaignSourceRecord, request: WhopLiveDiscoveryRequest) -> str | None:
    if source.availability == "missing":
        return "missing_source"
    if request.media_format is not None and source.media_format not in {None, request.media_format}:
        return "format_mismatch"
    if (
        request.max_size_bytes is not None
        and source.size_bytes is not None
        and source.size_bytes > request.max_size_bytes
    ):
        return "source_too_large"
    if (
        source.duration_us is not None
        and request.min_duration_us is not None
        and source.duration_us < request.min_duration_us
    ):
        return "duration_out_of_range"
    if (
        source.duration_us is not None
        and request.max_duration_us is not None
        and source.duration_us > request.max_duration_us
    ):
        return "duration_out_of_range"
    required = request.require_rights or "allowed"
    if source.rights_state != required or source.policy_state != "allowed":
        if source.rights_state != required:
            return "rights_not_allowed"
        return "policy_blocked"
    if source.availability not in {"available", "unknown"}:
        return "source_unavailable"
    if source.content_sha256 is None:
        return "missing_content_hash"
    return None


def _category(campaign: WhopCampaignRecord) -> str:
    return (campaign.category or "").casefold()


def _lower(values: list[str]) -> set[str]:
    return {item.casefold() for item in values}


def _search_text(campaign: WhopCampaignRecord) -> str:
    parts = [campaign.title, campaign.category or "", campaign.payout_text or ""]
    parts.extend(source.display_name for source in campaign.sources)
    return " ".join(parts).casefold()
