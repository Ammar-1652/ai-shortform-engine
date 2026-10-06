"""Current policy fingerprint for provider intake. Antoine stock stays blocked."""

from __future__ import annotations

import hashlib
import json

from clipforge.campaign.antoine import CAMPAIGN_ID, policy_sha256


def current_policy_fingerprint(campaign_id: str) -> str:
    """Hash the policy that is current for this campaign.

    Antoine uses the catalogue policy. Another campaign uses a local allow
    fingerprint. Callers compare a stored hash to this value and fail closed
    when they differ.
    """
    if campaign_id == CAMPAIGN_ID:
        return policy_sha256()
    body = json.dumps(
        {"campaign_id": campaign_id, "provider_intake": "allowed"},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def campaign_blocks_outside_media(campaign_id: str) -> bool:
    """Antoine forbids stock and other outside media. Other campaigns do not."""
    return campaign_id == CAMPAIGN_ID
