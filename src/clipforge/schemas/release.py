"""Local executable release identity; snapshots do not grant asset or review rights."""

from __future__ import annotations

from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.editorial_knowledge import _relative


class ReleaseFile(Versioned):
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def confined(self) -> Self:
        _relative(self.relative_path, label="release file")
        return self


class ProductionRelease(Versioned):
    release_id: EntityId
    code_sha: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    files: list[ReleaseFile] = Field(min_length=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime

    @model_validator(mode="after")
    def ordered(self) -> Self:
        paths = [item.relative_path for item in self.files]
        if paths != sorted(set(paths)):
            raise ValueError("release files must be sorted and unique")
        return self
