"""Shared field types. Time fields are integer microseconds, never floats."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

# Seven days. Stays inside JavaScript Number.MAX_SAFE_INTEGER (2^53 - 1).
MAX_TIMELINE_US = 7 * 24 * 60 * 60 * 1_000_000

Microseconds = Annotated[
    int,
    Field(
        ge=0,
        le=MAX_TIMELINE_US,
        description="Integer microseconds on the clock named by the parent field. Not seconds or frames.",
    ),
]

EntityId = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        description="Stable id. UUID text is the usual value.",
    ),
]


class ContractModel(BaseModel):
    """Base model. Unknown fields are rejected so a score cannot be smuggled in."""

    model_config = ConfigDict(extra="forbid")


class Versioned(ContractModel):
    """A document whose stored shape can change in a later schema version."""

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
