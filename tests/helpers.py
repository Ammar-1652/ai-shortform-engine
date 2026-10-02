"""Shared builders for contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimelineSegment, TimeMapDocument, digest_time_map


def stamp() -> datetime:
    return datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def provenance(source_ids: list[str] | None = None) -> ArtifactProvenance:
    return ArtifactProvenance(
        created_at=stamp(),
        created_by="tester",
        tool="pytest",
        tool_version="0.1.0",
        source_asset_ids=list(source_ids or []),
    )


def jump_map() -> TimeMapDocument:
    return TimeMapDocument(
        time_map_id="map-jump-1",
        segments=[
            TimelineSegment(
                segment_id="seg-a",
                source_start_us=10_000_000,
                source_end_us=15_000_000,
            ),
            TimelineSegment(
                segment_id="seg-b",
                source_start_us=20_000_000,
                source_end_us=25_000_000,
            ),
        ],
    )


def jump_digest() -> str:
    return digest_time_map(jump_map())
