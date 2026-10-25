"""Playback observations belong to final human review, not the render producer."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from clipforge.errors import MediaError
from clipforge.schemas.qa import HumanPlaybackReview, HumanPlaybackTarget
from clipforge.transcription.io import dump_json


def playback_target(evidence: dict[str, str]) -> HumanPlaybackTarget:
    """Only copy public, hash-bound facts; no local paths or invented observations."""
    return HumanPlaybackTarget.model_validate(
        {key: evidence[key] for key in HumanPlaybackTarget.model_fields if key != "schema_version"}
    )


def playback_sha256(playback: HumanPlaybackReview) -> str:
    return hashlib.sha256(dump_json(playback).encode("utf-8")).hexdigest()


def validate_playback(
    playback: HumanPlaybackReview,
    evidence: dict[str, str],
    *,
    reviewer: str,
    approving: bool,
    recorded_at: datetime | None = None,
) -> None:
    """An observation of a different MP4, reviewer, or rejected edit cannot approve it."""
    target = playback_target(evidence)
    for key in HumanPlaybackTarget.model_fields:
        if getattr(playback, key) != getattr(target, key):
            raise MediaError("human playback record is stale; reload the exact current video")
    if playback.watch.reviewer != reviewer:
        raise MediaError("human playback reviewer must match the final reviewer")
    if playback.watch.reviewed_at > (recorded_at or datetime.now(UTC)):
        raise MediaError("human playback date cannot be in the future")
    if approving and playback.watch.decision != "accepted_for_final_review":
        raise MediaError("human playback has not accepted this video for final review")
