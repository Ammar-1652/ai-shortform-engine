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

TreatmentMode = Literal["preferred", "eligible", "sparse", "accent_only", "allowed", "blocked"]


class BrollPolicy(Versioned):
    mode: Literal["preferred", "eligible", "blocked"]
    roles: list[str] = Field(default_factory=list, min_length=0, max_length=8)
    min_meaningful_beats: int = Field(default=0, ge=0, le=12)
    max_consecutive_beats: int = Field(default=2, ge=1, le=8)
    relevance_threshold: float = Field(default=0.85, ge=0, le=1)


class CameraPolicy(Versioned):
    mode: Literal["preferred", "allowed", "blocked"]
    min_events: int = Field(default=0, ge=0, le=8)
    max_events: int = Field(default=4, ge=0, le=12)
    max_scale_delta: float = Field(default=0.08, ge=0, le=0.14)
    max_subject_drift_px: int = Field(default=80, ge=0, le=194)


class TransitionPolicy(Versioned):
    mode: Literal["sparse", "allowed", "blocked"]
    max_per_30s: int = Field(default=3, ge=0, le=12)
    forbid_on_word_boundary: bool = True
    fallback: Literal["clean_cut"] = "clean_cut"


class SfxPolicy(Versioned):
    mode: Literal["accent_only", "allowed", "blocked"]
    max_cues_per_30s: int = Field(default=3, ge=0, le=12)
    max_gain_db: float = Field(default=-18.0, ge=-24.0, le=0.0)
    speech_duck_db: float = Field(default=6.0, ge=0.0, le=18.0)
    forbid_on_continuous_dialogue: bool = True


class TreatmentPolicy(Versioned):
    beat_coverage: Literal["required_decision"] = "required_decision"
    broll: BrollPolicy
    camera: CameraPolicy
    transitions: TransitionPolicy
    sfx: SfxPolicy
    motion_graphics: Literal["disabled", "eligible"] = "disabled"


class PresetDefinition(Versioned):
    preset_id: PresetId
    narrative_structure: list[str] = Field(min_length=3, max_length=8)
    camera_language: list[str] = Field(min_length=1, max_length=8)
    motion_recipe_ids: list[EntityId] = Field(min_length=1, max_length=12)
    allowed_style_ids: list[str] = Field(min_length=1, max_length=12)
    caption_mode: Literal["phrase_active_word", "phrase_whole_run"]
    audio_rules: list[str] = Field(min_length=1, max_length=12)
    reject_when: list[str] = Field(min_length=1, max_length=12)
    treatment_policy: TreatmentPolicy
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
