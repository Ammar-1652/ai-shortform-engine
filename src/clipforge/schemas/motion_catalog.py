"""Typed, provenance-bound motion recipe catalog."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.schemas.editorial import MotionPurpose

_SHA = r"^[0-9a-f]{64}$"


class MotionReference(Versioned):
    """A reviewed source for a normalized motion recipe."""

    reference_id: EntityId
    source_id: EntityId
    title: str = Field(min_length=1, max_length=180)
    reference_kind: Literal["repository_recipe", "skill_guidance", "local_component", "reference_video"]
    permission: Literal["reference_only", "reuse_allowed", "blocked"]
    license_id: str | None = Field(default=None, max_length=100)
    attribution: str | None = Field(default=None, max_length=1000)
    content_sha256: str = Field(pattern=_SHA)
    captured_at: str = Field(min_length=1, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)


class MotionParameter(Versioned):
    """A bounded declarative parameter; arbitrary code is not a parameter type."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    value_type: Literal["string", "integer", "number", "boolean", "color"]
    required: bool = False
    default_value: str | None = Field(default=None, max_length=120)
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def range_is_valid(self) -> Self:
        if self.minimum is not None and self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("motion parameter maximum must be >= minimum")
        if self.required and self.default_value is not None:
            raise ValueError("required motion parameter cannot have a default")
        return self


class MotionRecipe(Versioned):
    """An allowlisted recipe routed to a local Remotion component."""

    recipe_id: EntityId
    reference_id: EntityId
    recipe_version: str = Field(min_length=1, max_length=40)
    state: Literal["reference_only", "experimental", "approved", "blocked"]
    scene_intents: list[str] = Field(min_length=1, max_length=12)
    purposes: list[MotionPurpose] = Field(min_length=1, max_length=4)
    component_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,100}$")
    fallback_component_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,100}$")
    duration_min_us: Microseconds
    duration_max_us: Microseconds
    attention_cost: Literal["low", "medium", "high"]
    readability_risk: Literal["low", "medium", "high"]
    supports_rtl: bool
    supports_captions: bool
    compatible_languages: list[str] = Field(default_factory=list, max_length=32)
    compatible_profiles: list[str] = Field(default_factory=list, max_length=32)
    required_inputs: list[str] = Field(default_factory=list, max_length=16)
    optional_inputs: list[str] = Field(default_factory=list, max_length=16)
    parameters: list[MotionParameter] = Field(default_factory=list, max_length=32)
    overuse_warning: str = Field(min_length=1, max_length=500)
    local_modifications: list[str] = Field(default_factory=list, max_length=16)
    recipe_sha256: str = Field(pattern=_SHA)

    @field_validator(
        "scene_intents",
        "compatible_languages",
        "compatible_profiles",
        "required_inputs",
        "optional_inputs",
    )
    @classmethod
    def recipe_values_are_plain(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]

    @model_validator(mode="after")
    def recipe_is_bounded(self) -> Self:
        if self.duration_max_us < self.duration_min_us:
            raise ValueError("motion recipe duration_max_us must be >= duration_min_us")
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("motion recipe parameter names must be unique")
        if self.state == "approved" and self.reference_id.startswith("unverified"):
            raise ValueError("approved motion recipe cannot use an unverified reference")
        if self.component_id == self.fallback_component_id:
            raise ValueError("motion recipe fallback must be distinct from primary component")
        return self


class MotionCatalogDocument(Versioned):
    """Strict local catalog consumed by direction planning."""

    references: list[MotionReference] = Field(default_factory=list, max_length=128)
    recipes: list[MotionRecipe] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def references_and_recipes_are_unique(self) -> Self:
        reference_ids = [item.reference_id for item in self.references]
        recipe_ids = [item.recipe_id for item in self.recipes]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("motion reference ids must be unique")
        if len(recipe_ids) != len(set(recipe_ids)):
            raise ValueError("motion recipe ids must be unique")
        reference_set = set(reference_ids)
        if any(item.reference_id not in reference_set for item in self.recipes):
            raise ValueError("motion recipe references an unknown reference")
        return self
