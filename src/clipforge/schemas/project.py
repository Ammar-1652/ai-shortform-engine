"""A production project. Organic and paid work are projects with different profiles."""

from __future__ import annotations

from pydantic import AwareDatetime, Field, field_validator

from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.provenance import ArtifactProvenance


class Project(Versioned):
    """Top-level container. Media bytes are not stored on the project row."""

    project_id: EntityId
    name: str = Field(min_length=1, max_length=200)
    created_at: AwareDatetime
    profile_id: EntityId | None = None
    provenance: ArtifactProvenance
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def name_is_visible_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        if any(ord(character) < 32 for character in stripped):
            raise ValueError("name must not contain control characters")
        return stripped
