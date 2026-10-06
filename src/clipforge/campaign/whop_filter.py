"""Deterministic Whop campaign filters. Membership is not rights evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from clipforge.schemas.whop import WhopCampaignRecord, WhopCampaignSnapshot
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
        reason = _reason(campaign, request, snapshot.exported_at, moment)
        decisions.append(
            WhopFilterDecision(
                campaign_id=campaign.campaign_id,
                included=reason is None,
                reason_code=reason or "included",
            )
        )
    return decisions


def _reason(
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
    source_reason = _source_reason(campaign, request)
    if source_reason is not None:
        return source_reason
    return None


def _source_reason(campaign: WhopCampaignRecord, request: WhopLiveDiscoveryRequest) -> str | None:
    if not campaign.sources:
        return "missing_source"
    saw_allowed = False
    first = "rights_not_allowed"
    for source in campaign.sources:
        if source.availability == "missing":
            first = "missing_source"
            continue
        if request.media_format is not None and source.media_format not in {None, request.media_format}:
            first = "format_mismatch"
            continue
        if (
            request.max_size_bytes is not None
            and source.size_bytes is not None
            and source.size_bytes > request.max_size_bytes
        ):
            first = "source_too_large"
            continue
        if (
            source.duration_us is not None
            and request.min_duration_us is not None
            and source.duration_us < request.min_duration_us
        ):
            first = "duration_out_of_range"
            continue
        if (
            source.duration_us is not None
            and request.max_duration_us is not None
            and source.duration_us > request.max_duration_us
        ):
            first = "duration_out_of_range"
            continue
        required = request.require_rights or "allowed"
        if source.rights_state != required or source.policy_state != "allowed":
            first = "rights_not_allowed" if source.rights_state != required else "policy_blocked"
            continue
        if source.availability not in {"available", "unknown"}:
            first = "source_unavailable"
            continue
        saw_allowed = True
    if saw_allowed:
        return None
    return first


def _category(campaign: WhopCampaignRecord) -> str:
    return (campaign.category or "").casefold()


def _lower(values: list[str]) -> set[str]:
    return {item.casefold() for item in values}


def _search_text(campaign: WhopCampaignRecord) -> str:
    parts = [campaign.title, campaign.category or "", campaign.payout_text or ""]
    parts.extend(source.display_name for source in campaign.sources)
    return " ".join(parts).casefold()
