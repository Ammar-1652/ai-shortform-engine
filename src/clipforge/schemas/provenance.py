"""Who produced an artifact, and which parents it came from."""

from __future__ import annotations

from pydantic import AwareDatetime, Field

from clipforge.schemas.common import EntityId, Versioned


class ArtifactProvenance(Versioned):
    """Required lineage for stored media decisions and derived artifacts.

    ``source_asset_ids`` is empty only for records that are not derived from a
    source video (for example a newly created project). Derived media must list
    the source.
    """

    created_at: AwareDatetime
    created_by: str = Field(min_length=1, max_length=200)
    tool: str = Field(min_length=1, max_length=200)
    tool_version: str = Field(min_length=1, max_length=80)
    source_asset_ids: list[EntityId] = Field(default_factory=list)
    parent_artifact_ids: list[EntityId] = Field(default_factory=list)
    job_id: EntityId | None = None
    inputs_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
