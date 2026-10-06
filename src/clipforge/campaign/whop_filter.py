"""Deterministic Whop campaign filters. Membership is not rights evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from clipforge.schemas.whop import WhopCampaignRecord, WhopCampaignSnapshot, WhopCampaignSourceRecord
from clipforge.schemas.whop_discovery import (
    WhopFilterDecision,
    WhopLiveDiscoveryRequest,
    WhopSourceExclusion,
)


def filter_campaigns(
    snapshot: WhopCampaignSnapshot,
    request: WhopLiveDiscoveryRequest,
    *,
    now: datetime | None = None,
) -> list[WhopFilterDecision]:
    """Return one decision per campaign. The order follows the snapshot."""
    moment = now or datetime.now(UTC)
    fingerprint = request_fingerprint(request)
    decisions: list[WhopFilterDecision] = []
    for campaign in snapshot.campaigns:
        reason, source_ids, excluded = _decision(campaign, request, snapshot.exported_at, moment)
        decisions.append(
            WhopFilterDecision(
                campaign_id=campaign.campaign_id,
                included=reason is None,
                reason_code=reason or "included",
                included_source_ids=source_ids,
                excluded_sources=[
                    WhopSourceExclusion(source_id=source_id, reason_code=code) for source_id, code in excluded
                ],
                filter_fingerprint=fingerprint,
            )
        )
    return decisions


def request_fingerprint(request: WhopLiveDiscoveryRequest) -> str:
    """Hash the filter. The request id and timestamp are not filter facts."""
    payload = request.model_dump(mode="json")
    payload.pop("created_at", None)
    payload.pop("request_id", None)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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
) -> tuple[str | None, list[str], list[tuple[str, str]]]:
    reason = _campaign_reason(campaign, request, exported_at, now)
    if reason is not None:
        return reason, [], []
    source_reason, source_ids, excluded = _passing_sources(campaign, request)
    if source_reason is not None:
        return source_reason, [], excluded
    return None, source_ids, excluded


def _campaign_reason(
    campaign: WhopCampaignRecord,
    request: WhopLiveDiscoveryRequest,
    exported_at: datetime,
    now: datetime,
) -> str | None:
    if request.require_status is not None and campaign.status in {"unknown", ""}:
        return "missing_status"
    if request.require_status is not None and campaign.status != request.require_status:
        return "status_not_active"
    if (request.prohibited_categories or request.allowed_categories) and not campaign.category:
        return "missing_category"
    if request.prohibited_categories and _category(campaign) in _lower(request.prohibited_categories):
        return "category_prohibited"
    if request.allowed_categories and _category(campaign) not in _lower(request.allowed_categories):
        return "category_not_allowed"
    if request.require_policy is not None and campaign.policy_state != request.require_policy:
        return "policy_blocked"
    if campaign.policy_state in {"unknown", "prohibited"}:
        return "policy_blocked"
    if request.language is not None and campaign.language is None:
        return "missing_language"
    if request.language is not None and campaign.language != request.language:
        return "language_mismatch"
    if request.query is not None and request.query.casefold() not in _search_text(campaign):
        return "search_mismatch"
    if request.max_age_hours is not None and exported_at < now - timedelta(hours=request.max_age_hours):
        return "stale_campaign"
    return None


def _passing_sources(
    campaign: WhopCampaignRecord,
    request: WhopLiveDiscoveryRequest,
) -> tuple[str | None, list[str], list[tuple[str, str]]]:
    if not campaign.sources:
        return "missing_source", [], []
    passed: list[str] = []
    excluded: list[tuple[str, str]] = []
    for source in campaign.sources:
        reason = _one_source(source, request)
        if reason is None:
            passed.append(source.source_id)
            continue
        excluded.append((source.source_id, reason))
    if passed:
        return None, sorted(set(passed)), excluded
    first = excluded[0][1] if excluded else "rights_not_allowed"
    return first, [], excluded


def _one_source(source: WhopCampaignSourceRecord, request: WhopLiveDiscoveryRequest) -> str | None:
    if source.availability == "missing":
        return "missing_source"
    if source.availability == "unknown" and not request.permit_unknown_availability:
        return "source_unavailable"
    if source.availability not in {"available", "unknown"}:
        return "source_unavailable"
    if request.media_format is not None and source.media_format is None:
        return "missing_format"
    if request.media_format is not None and source.media_format != request.media_format:
        return "format_mismatch"
    if request.max_size_bytes is not None and source.size_bytes is None:
        return "missing_size"
    if (
        request.max_size_bytes is not None
        and source.size_bytes is not None
        and source.size_bytes > request.max_size_bytes
    ):
        return "source_too_large"
    duration_required = request.min_duration_us is not None or request.max_duration_us is not None
    if duration_required and source.duration_us is None:
        return "missing_duration"
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
    if source.rights_state in {"", "unknown"} or source.rights_state != required:
        return "rights_not_allowed"
    if source.policy_state != "allowed":
        return "policy_blocked"
    if request.require_acquisition_reference and not source.acquisition_reference:
        return "manual_download_required"
    if source.direct_download == "unavailable" and not source.acquisition_reference:
        return "manual_download_required"
    declared = _declared_hash(source)
    acquired = source.acquired_file_sha256
    if source.acquisition_status == "hash_mismatch" or (
        acquired is not None and declared is not None and acquired != declared
    ):
        return "hash_mismatch"
    if declared is None:
        return "missing_content_hash"
    return None


def _declared_hash(source: WhopCampaignSourceRecord) -> str | None:
    return source.declared_content_sha256 or source.content_sha256


def _category(campaign: WhopCampaignRecord) -> str:
    return (campaign.category or "").casefold()


def _lower(values: list[str]) -> set[str]:
    return {item.casefold() for item in values}


def _search_text(campaign: WhopCampaignRecord) -> str:
    parts = [campaign.title, campaign.category or "", campaign.payout_text or ""]
    parts.extend(source.display_name for source in campaign.sources)
    return " ".join(parts).casefold()
