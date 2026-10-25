"""Narrative editorial presets routed to the typed motion catalog."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from clipforge.schemas.common import EntityId, Versioned

_SHA = r"^[0-9a-f]{64}$"

PresetId = Literal[
    "clean_explainer",
    "proof_comparison",
    "story_reveal",
    "transformation",
    "quote_emotion",
    "product_cta",
]


class PresetDefinition(Versioned):
    preset_id: PresetId
    narrative_structure: list[str] = Field(min_length=3, max_length=8)
    camera_language: list[str] = Field(min_length=1, max_length=8)
    motion_recipe_ids: list[EntityId] = Field(min_length=1, max_length=12)
    allowed_style_ids: list[str] = Field(min_length=1, max_length=12)
    caption_mode: Literal["phrase_active_word", "phrase_whole_run"]
    audio_rules: list[str] = Field(min_length=1, max_length=12)
    reject_when: list[str] = Field(min_length=1, max_length=12)
    preset_sha256: str = Field(pattern=_SHA)

    @model_validator(mode="after")
    def values_are_unique(self) -> Self:
        if len(set(self.motion_recipe_ids)) != len(self.motion_recipe_ids):
            raise ValueError("preset motion recipes must be unique")
        if len(set(self.allowed_style_ids)) != len(self.allowed_style_ids):
            raise ValueError("preset styles must be unique")
        return self


class EditorialPresetCatalog(Versioned):
    presets: list[PresetDefinition] = Field(min_length=6, max_length=32)

    @model_validator(mode="after")
    def preset_ids_are_unique(self) -> Self:
        ids = [item.preset_id for item in self.presets]
        if len(ids) != len(set(ids)):
            raise ValueError("editorial preset ids must be unique")
        return self
