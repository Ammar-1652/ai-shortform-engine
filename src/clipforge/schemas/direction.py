"""Source-grounded editorial direction contracts.

Direction is an input to the deterministic Hero renderer, not executable
creative code.  Every visible decision names the source evidence it came
from, and the renderer only accepts the allowlisted style identifiers below.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Literal, Self

from pydantic import Field, model_validator

from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"

DirectionStyleId = Literal[
    "editorial-clean-v1",
    "kinetic-caption-v1",
    "documentary-broll-v1",
    "data-explainer-v1",
    "paper-explainer-v1",
    "premium-minimal-v1",
]


class MotionStyleSpec(Versioned):
    """Serializable numeric style choices consumed by Python and Remotion."""

    style_id: str = Field(min_length=1, max_length=64)
    easing: Literal["linear", "ease_out_cubic", "ease_in_out_cubic"]
    enter_frames: int = Field(ge=0, le=30)
    exit_frames: int = Field(ge=0, le=30)
    max_travel_px: int = Field(ge=0, le=80)
    max_scale_permille: int = Field(ge=1000, le=1100)
    caption_mode: Literal["phrase_active_word", "phrase_whole_run"]
    contrast: Literal["legacy", "outline_shadow_backplate", "soft_backplate", "minimal_outline"]
    font_identity: str = Field(min_length=1, max_length=100)
    font_sha256: list[str] = Field(default_factory=list, max_length=8)
    accent: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    safe_left: int = Field(ge=0, le=300)
    safe_right: int = Field(ge=0, le=300)
    safe_top: int = Field(ge=0, le=400)
    safe_bottom: int = Field(ge=0, le=500)
    max_simultaneous_emphasis: int = Field(ge=0, le=2)

    @model_validator(mode="after")
    def safe_region_is_portrait_usable(self) -> Self:
        if self.safe_left + self.safe_right >= 1080:
            raise ValueError("motion style leaves no horizontal portrait safe area")
        if self.safe_top + self.safe_bottom >= 1920:
            raise ValueError("motion style leaves no vertical portrait safe area")
        import re

        if any(re.fullmatch(_SHA, digest) is None for digest in self.font_sha256):
            raise ValueError("font dependencies must be sha256 hex digests")
        return self


class DirectionEvidence(Versioned):
    """Verifiable transcript/visual evidence for one editorial choice."""

    evidence_id: EntityId
    source_word_ids: list[EntityId] = Field(min_length=1)
    source_segment_ids: list[EntityId] = Field(min_length=1)
    source_text: str = Field(min_length=1, max_length=1000)
    visual_scene_ids: list[EntityId] = Field(default_factory=list)
    note: str = Field(min_length=1, max_length=500)


class DirectionBeat(Versioned):
    """One hook/body/punch beat. Text is copied from the source evidence."""

    beat_id: EntityId
    kind: Literal["hook", "body", "punch"]
    purpose: Literal["context", "contrast", "consequence", "payoff"]
    source_segment_ids: list[EntityId] = Field(min_length=1)
    evidence_ids: list[EntityId] = Field(min_length=1)
    # None means narrative direction only; no duplicate title is painted.
    display_text: str | None = Field(default=None, min_length=1, max_length=80)
    output_start_us: Microseconds | None = None
    output_end_us: Microseconds | None = None

    @model_validator(mode="after")
    def interval_is_complete(self) -> Self:
        if (self.output_start_us is None) != (self.output_end_us is None):
            raise ValueError("direction beat output interval must contain both bounds")
        if (
            self.output_start_us is not None
            and self.output_end_us is not None
            and self.output_end_us <= self.output_start_us
        ):
            raise ValueError("direction beat output interval must be positive")
        return self


class DirectionAssetPlacement(Versioned):
    """A reviewed, source-grounded placement for one local asset.

    Asset timing is never inferred from the number of assets. The selected
    option must name the exact output interval, the source evidence that makes
    the asset relevant, and a plain-language editorial reason. The renderer
    consumes this declarative record; it cannot execute operator code.
    """

    placement_id: EntityId
    asset_id: EntityId
    kind: Literal["graphic", "audio"]
    interval: OutputInterval
    source_in_us: Microseconds = Field(default=0, ge=0)
    source_evidence_ids: list[EntityId] = Field(min_length=1)
    purpose: MotionPurpose
    relevance_note: str = Field(min_length=1, max_length=500)
    # Exact labels copied from the reviewed local asset catalog. A prose note
    # is editorial context, not semantic proof that a stock clip is relevant.
    asset_tags: list[str] = Field(default_factory=list, max_length=24)
    gain_db: float | None = Field(default=None, ge=-24, le=6)


class DirectionMotionGraphic(Versioned):
    """A native Remotion illustration tied to exact spoken evidence.

    This is deliberately not an asset placement: it has no downloaded bytes,
    remote URL, or executable payload. ``template`` selects one audited
    renderer component and ``display_text`` is copied from the evidence named
    below.  The lower caption lane is reserved, so an illustration cannot be
    used as a decorative replacement for readable captions.
    """

    graphic_id: EntityId
    template: Literal[
        "credit_card",
        "travel_postcard",
        "business_identity",
        "business_spotlight",
    ]
    interval: OutputInterval
    source_evidence_ids: list[EntityId] = Field(min_length=1)
    purpose: MotionPurpose
    display_text: str = Field(min_length=1, max_length=100)
    x: int = Field(ge=48, le=812)
    y: int = Field(ge=120, le=1240)
    width: int = Field(ge=220, le=840)
    height: int = Field(ge=180, le=560)

    @model_validator(mode="after")
    def stays_out_of_caption_lane(self) -> Self:
        if self.x + self.width > 1032:
            raise ValueError("motion graphic extends past the portrait safe area width")
        # Captions occupy the lower portrait lane. Native illustrations must
        # leave it free rather than relying on opacity or layer order.
        if self.y + self.height > 1480:
            raise ValueError("motion graphic extends into the reserved caption lane")
        return self


class SourceNativeText(Versioned):
    """Reviewed text already present in source footage.

    This annotation never paints or removes source pixels. It only gives the
    deterministic renderer enough evidence to suppress a duplicate optional
    typography card when the source itself already displays the same phrase.
    """

    region_id: EntityId
    interval: OutputInterval
    text: str = Field(min_length=1, max_length=200)
    visual_scene_ids: list[EntityId] = Field(min_length=1)
    note: str = Field(min_length=1, max_length=500)


class DirectionOption(Versioned):
    """One source-grounded direction alternative presented to the selector."""

    option_id: EntityId
    style_id: DirectionStyleId
    title: str = Field(min_length=1, max_length=120)
    beats: list[DirectionBeat] = Field(min_length=3, max_length=12)
    evidence: list[DirectionEvidence] = Field(min_length=1)
    asset_placements: list[DirectionAssetPlacement] = Field(default_factory=list, max_length=12)
    motion_graphics: list[DirectionMotionGraphic] = Field(default_factory=list, max_length=4)
    source_native_text: list[SourceNativeText] = Field(default_factory=list, max_length=8)
    source_native_text_status: Literal["reviewed_absent", "annotated", "unavailable"] = "unavailable"
    segment_order: list[EntityId] = Field(min_length=1)
    selection_score: float = Field(ge=0, le=1)
    selection_reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def has_hook_body_punch(self) -> Self:
        kinds = {beat.kind for beat in self.beats}
        if kinds != {"hook", "body", "punch"}:
            raise ValueError("direction option must contain hook, body, and punch beats")
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("direction evidence ids must be unique")
        if len({beat.beat_id for beat in self.beats}) != len(self.beats):
            raise ValueError("direction beat ids must be unique")
        if any(evidence_id not in evidence_ids for beat in self.beats for evidence_id in beat.evidence_ids):
            raise ValueError("every beat evidence id must be declared by the option")
        placement_ids = [placement.placement_id for placement in self.asset_placements]
        if len(set(placement_ids)) != len(placement_ids):
            raise ValueError("direction asset placement ids must be unique")
        if any(
            evidence_id not in evidence_ids
            for placement in self.asset_placements
            for evidence_id in placement.source_evidence_ids
        ):
            raise ValueError("every asset placement evidence id must be declared by the option")
        for placement in self.asset_placements:
            if placement.kind == "graphic" and placement.gain_db is not None:
                raise ValueError("graphic placement cannot declare an audio gain")
        graphic_ids = [graphic.graphic_id for graphic in self.motion_graphics]
        if len(set(graphic_ids)) != len(graphic_ids):
            raise ValueError("direction motion graphic ids must be unique")
        if any(
            evidence_id not in evidence_ids
            for graphic in self.motion_graphics
            for evidence_id in graphic.source_evidence_ids
        ):
            raise ValueError("every motion graphic evidence id must be declared by the option")
        native_ids = [item.region_id for item in self.source_native_text]
        if len(set(native_ids)) != len(native_ids):
            raise ValueError("source-native text region ids must be unique")
        if self.source_native_text_status == "annotated" and not self.source_native_text:
            raise ValueError("annotated source-native text status requires annotations")
        if self.source_native_text_status == "reviewed_absent" and self.source_native_text:
            raise ValueError("reviewed_absent source-native text status cannot carry annotations")
        graphics = sorted(self.motion_graphics, key=lambda item: item.interval.output_start_us)
        if any(
            left.interval.output_end_us > right.interval.output_start_us for left, right in pairwise(graphics)
        ):
            raise ValueError("overlapping motion graphics are rejected")
        if len(set(self.segment_order)) != len(self.segment_order):
            raise ValueError("direction segment order cannot repeat a segment")
        return self


class DirectionDocument(Versioned):
    """Immutable, validated direction selected for one promoted candidate."""

    direction_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    hero_plan_sha256: str = Field(pattern=_SHA)
    time_map_sha256: str = Field(pattern=_SHA)
    alignment_sha256: str = Field(pattern=_SHA)
    visual_analysis_sha256: str = Field(pattern=_SHA)
    options: list[DirectionOption] = Field(min_length=3, max_length=3)
    selected_option_id: EntityId
    selection_mode: Literal["automatic", "operator_override"]
    style_id: DirectionStyleId
    style_fingerprint: str = Field(pattern=_SHA)
    safe_region_id: Literal["portrait-safe-v1"] = "portrait-safe-v1"
    direction_recipe_version: Literal["direction-v1"] = "direction-v1"
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def selection_is_consistent(self) -> Self:
        ids = [option.option_id for option in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError("direction option ids must be unique")
        selected = next(
            (option for option in self.options if option.option_id == self.selected_option_id),
            None,
        )
        if selected is None:
            raise ValueError("selected direction option is not present")
        if selected.style_id != self.style_id:
            raise ValueError("selected direction style does not match the selected option")
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("direction provenance must include source_asset_id")
        return self
