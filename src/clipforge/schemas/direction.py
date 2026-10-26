"""Source-grounded editorial direction contracts.

Direction is an input to the deterministic Hero renderer, not executable
creative code.  Every visible decision names the source evidence it came
from, and the renderer only accepts the allowlisted style identifiers below.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.treatment import (
    BeatTreatmentDecision,
    TreatmentAssetObservation,
    TreatmentAssetRequest,
    TreatmentAssetVerification,
)

_SHA = r"^[0-9a-f]{64}$"

DirectionStyleId = Literal[
    "editorial-clean-v1",
    "quran-editorial-v1",
    "quran-readable-v2",
    "concat-editorial-v1",
    "kinetic-caption-v1",
    "documentary-broll-v1",
    "data-explainer-v1",
    "paper-explainer-v1",
    "premium-minimal-v1",
]

# New directed plans use the platform-resilient inner band by default. This
# keeps text, logos, and context away from changing TikTok/Instagram/Shorts
# viewer chrome. Legacy plans retain their persisted region and remain
# immutable; this default only governs newly created direction documents.
SafeRegionId = Literal["portrait-safe-v1", "platform-resilient-portrait-v1"]


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
    # Platform-aware production defaults. Caption grouping happens before the
    # browser so a caption never wraps, clips, or hides words under viewer UI.
    caption_max_lines: Literal[1] = 1
    caption_max_words: int = Field(ge=1, le=8)
    caption_max_chars: int = Field(ge=16, le=64)
    caption_y: int = Field(ge=300, le=1700)

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


class DirectionContextLine(Versioned):
    """One reviewed, single-line context label in the upper blur lane.

    This is optional for non-campaign directions.  When supplied it is a
    declarative editorial summary, never executable copy: the direction
    validator binds it to transcript evidence and requires a review note when
    the wording is not an exact transcript phrase.
    """

    context_id: EntityId
    text: str = Field(min_length=1, max_length=64)
    emoji: Literal["📖", "💡", "🎯", "✨", "⚡", "🧠", "✅", "🔎", "🕌"]
    evidence_ids: list[EntityId] = Field(min_length=1)
    interval: OutputInterval
    copy_mode: Literal["exact_evidence", "human_reviewed_summary", "operator_reviewed_summary"] = (
        "exact_evidence"
    )
    reviewed_by: str | None = Field(default=None, min_length=1, max_length=200)
    review_note: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def is_one_line_and_reviewed(self) -> Self:
        if "\n" in self.text or "\r" in self.text:
            raise ValueError("context line must be one line")
        if self.copy_mode in {"human_reviewed_summary", "operator_reviewed_summary"} and (
            not self.reviewed_by or not self.review_note
        ):
            raise ValueError("reviewed context summaries require reviewer and review note")
        if self.copy_mode == "exact_evidence" and (self.reviewed_by or self.review_note):
            raise ValueError("exact context lines cannot carry summary review metadata")
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
    request_id: EntityId | None = None
    provider_response_sha256: str | None = Field(default=None, pattern=_SHA)
    selection_id: EntityId | None = None
    acquisition_id: EntityId | None = None
    license_evidence_sha256: str | None = Field(default=None, pattern=_SHA)
    registered_asset_sha256: str | None = Field(default=None, pattern=_SHA)
    observation_id: EntityId | None = None
    observation_sha256: str | None = Field(default=None, pattern=_SHA)
    asset_status: Literal["pending", "selected", "acquired", "blocked", "unavailable"] = "acquired"


class TreatmentAssetBindingDocument(Versioned):
    """Immutable persisted request-to-placement handoff for a treatment asset."""

    binding_id: EntityId
    request: TreatmentAssetRequest
    placement: DirectionAssetPlacement
    verification: TreatmentAssetVerification
    observation: TreatmentAssetObservation | None = None
    created_at: AwareDatetime
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def evidence_matches(self) -> Self:
        request, placement, checked = self.request, self.placement, self.verification
        if request.status != "acquired" or placement.asset_status != "acquired":
            raise ValueError("treatment binding requires an acquired request and placement")
        if placement.request_id != request.request_id or placement.asset_id != request.registered_asset_id:
            raise ValueError("treatment binding request and placement disagree")
        for name in (
            "provider_response_sha256",
            "selection_id",
            "acquisition_id",
            "license_evidence_sha256",
            "registered_asset_sha256",
        ):
            if getattr(request, name) != getattr(placement, name) or getattr(request, name) != getattr(
                checked, name
            ):
                raise ValueError(f"treatment binding {name} disagrees")
        if checked.registered_asset_id != placement.asset_id or checked.media_kind != placement.kind:
            raise ValueError("treatment binding verified asset or kind disagrees")
        if self.observation is not None and (
            placement.kind != "graphic"
            or self.observation.asset_id != placement.asset_id
            or placement.observation_id != self.observation.observation_id
        ):
            raise ValueError("treatment observation does not match the visual placement")
        if self.observation is not None and placement.observation_sha256 is None:
            raise ValueError("treatment visual placement is missing its observation hash")
        if placement.kind != request.kind or checked.provider not in request.provider_classes:
            raise ValueError("treatment binding kind or provider was not requested")
        if (
            placement.interval.output_start_us < request.interval.output_start_us
            or placement.interval.output_end_us > request.interval.output_end_us
            or not set(placement.source_evidence_ids).issubset(request.source_evidence_ids)
        ):
            raise ValueError("treatment binding placement escapes the requested beat")
        return self


class TreatmentBindingReference(Versioned):
    binding_id: EntityId
    relative_path: str = Field(pattern=r"^editorial/treatment-bindings/[A-Za-z0-9._:-]+\.json$")
    sha256: str = Field(pattern=_SHA)


class DirectionTreatmentRevision(Versioned):
    parent_direction_id: EntityId
    parent_direction_sha256: str = Field(pattern=_SHA)
    bindings: list[TreatmentBindingReference] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_bindings(self) -> Self:
        if len({item.binding_id for item in self.bindings}) != len(self.bindings):
            raise ValueError("direction revision binding ids must be unique")
        return self


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
        "quran_challenge",
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


class DirectionCameraMotion(Versioned):
    """A bounded, source-grounded camera move for one output interval."""

    motion_id: EntityId
    intent: Literal["orient", "follow", "reveal", "emphasize", "transition", "settle"]
    path: Literal["hold", "push_in", "pull_out", "pan_x", "pan_y", "drift", "parallax", "match_cut"]
    interval: OutputInterval
    source_evidence_ids: list[EntityId] = Field(min_length=1)
    target_x_permille: int = Field(default=500, ge=0, le=1000)
    target_y_permille: int = Field(default=500, ge=0, le=1000)
    scale_start_permille: int = Field(default=1000, ge=1000, le=1140)
    scale_end_permille: int = Field(default=1000, ge=1000, le=1140)
    travel_px: int = Field(default=0, ge=0, le=194)
    intensity: Literal["quiet", "gentle", "active", "peak"] = "gentle"
    easing: Literal["linear", "ease_out_cubic", "ease_in_out_cubic"] = "ease_in_out_cubic"
    fallback: Literal["hold", "contain"] = "hold"

    @model_validator(mode="after")
    def motion_is_bounded(self) -> Self:
        if self.path == "hold" and (
            self.scale_start_permille != 1000 or self.scale_end_permille != 1000 or self.travel_px != 0
        ):
            raise ValueError("hold camera motion cannot change scale or travel")
        envelopes = {
            "quiet": (64, 1060),
            "gentle": (96, 1080),
            "active": (144, 1110),
            "peak": (194, 1140),
        }
        max_travel, max_scale = envelopes[self.intensity]
        if self.travel_px > max_travel or max(self.scale_start_permille, self.scale_end_permille) > max_scale:
            raise ValueError(f"{self.intensity} camera motion exceeds its envelope")
        if self.path == "push_in" and self.scale_end_permille < self.scale_start_permille:
            raise ValueError("push_in camera motion must not zoom out")
        if self.path == "pull_out" and self.scale_end_permille > self.scale_start_permille:
            raise ValueError("pull_out camera motion must not zoom in")
        if self.path in {"pan_x", "pan_y", "drift", "parallax", "match_cut"} and (
            self.scale_start_permille != self.scale_end_permille and self.path != "parallax"
        ):
            raise ValueError(f"{self.path} camera motion cannot change scale")
        if self.path != "hold" and self.travel_px == 0 and self.scale_start_permille == self.scale_end_permille:
            raise ValueError("a non-hold camera motion must have a bounded movement")
        return self


class DirectionTransitionSpec(Versioned):
    """A narrative transition selected for one reviewed cut."""

    transition_id: EntityId
    interval: OutputInterval
    purpose: Literal["cut", "time_shift", "location_change", "reveal", "emphasis", "settle"]
    style: Literal["clean_cut_v1", "concat_push_v1", "concat_blur_dissolve_v1"]
    source_evidence_ids: list[EntityId] = Field(min_length=1)
    sfx_placement_id: EntityId | None = None
    # Canonical output-time boundary.  It is separate from the visual bridge
    # interval so lint can reject a transition that was retimed into a spoken
    # word instead of an actual reviewed cut.
    cut_boundary_us: Microseconds | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def transition_has_positive_interval(self) -> Self:
        if self.interval.output_end_us <= self.interval.output_start_us:
            raise ValueError("direction transition interval must be positive")
        if self.style == "clean_cut_v1" and self.purpose not in {"cut", "settle"}:
            raise ValueError("clean cut transition must have cut or settle purpose")
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
    camera_motion: list[DirectionCameraMotion] = Field(default_factory=list, max_length=12)
    transitions: list[DirectionTransitionSpec] = Field(default_factory=list, max_length=12)
    motion_recipe_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    preset_id: str | None = Field(default=None, max_length=64)
    context_line: DirectionContextLine | None = None
    source_native_text: list[SourceNativeText] = Field(default_factory=list, max_length=8)
    source_native_text_status: Literal["reviewed_absent", "annotated", "unavailable"] = "unavailable"
    treatment_decisions: list[BeatTreatmentDecision] = Field(default_factory=list, max_length=12)
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
        camera_ids = [item.motion_id for item in self.camera_motion]
        if len(set(camera_ids)) != len(camera_ids):
            raise ValueError("direction camera motion ids must be unique")
        if any(
            evidence_id not in evidence_ids
            for item in self.camera_motion
            for evidence_id in item.source_evidence_ids
        ):
            raise ValueError("every camera motion evidence id must be declared by the option")
        camera_sorted = sorted(self.camera_motion, key=lambda item: item.interval.output_start_us)
        if any(
            left.interval.output_end_us > right.interval.output_start_us
            for left, right in pairwise(camera_sorted)
        ):
            raise ValueError("overlapping camera motion intervals are rejected")
        transition_ids = [item.transition_id for item in self.transitions]
        if len(set(transition_ids)) != len(transition_ids):
            raise ValueError("direction transition ids must be unique")
        placement_by_id = {placement.placement_id: placement for placement in self.asset_placements}
        for transition in self.transitions:
            if transition.sfx_placement_id is not None:
                placement_ref = placement_by_id.get(transition.sfx_placement_id)
                if placement_ref is None:
                    raise ValueError("transition SFX must reference an asset placement in the same option")
                if placement_ref.kind != "audio":
                    raise ValueError("transition SFX placement must be an audio asset")
        if any(
            evidence_id not in evidence_ids
            for item in self.transitions
            for evidence_id in item.source_evidence_ids
        ):
            raise ValueError("every transition evidence id must be declared by the option")
        if any(
            left.interval.output_end_us > right.interval.output_start_us
            for left, right in pairwise(
                sorted(self.transitions, key=lambda item: item.interval.output_start_us)
            )
        ):
            raise ValueError("overlapping direction transitions are rejected")
        native_ids = [item.region_id for item in self.source_native_text]
        if len(set(native_ids)) != len(native_ids):
            raise ValueError("source-native text region ids must be unique")
        if self.source_native_text_status == "annotated" and not self.source_native_text:
            raise ValueError("annotated source-native text status requires annotations")
        if self.source_native_text_status == "reviewed_absent" and self.source_native_text:
            raise ValueError("reviewed_absent source-native text status cannot carry annotations")
        if self.style_id in {"quran-editorial-v1", "quran-readable-v2"} and self.context_line is None:
            raise ValueError("quran-editorial-v1 requires a reviewed upper context line")
        graphics = sorted(self.motion_graphics, key=lambda item: item.interval.output_start_us)
        if any(
            left.interval.output_end_us > right.interval.output_start_us for left, right in pairwise(graphics)
        ):
            raise ValueError("overlapping motion graphics are rejected")
        if len(set(self.segment_order)) != len(self.segment_order):
            raise ValueError("direction segment order cannot repeat a segment")
        if self.treatment_decisions:
            beat_ids = {beat.beat_id for beat in self.beats}
            decision_ids = [item.beat_id for item in self.treatment_decisions]
            if len(set(decision_ids)) != len(decision_ids) or set(decision_ids) != beat_ids:
                raise ValueError("treatment decisions must cover each direction beat exactly once")
            known_placement_ids = {item.placement_id for item in self.asset_placements}
            placement_asset_ids = {item.asset_id for item in self.asset_placements}
            known_camera_ids = {item.motion_id for item in self.camera_motion}
            known_transition_ids = {item.transition_id for item in self.transitions}
            known_graphic_ids = {item.graphic_id for item in self.motion_graphics}
            requests_by_id = {
                request.request_id: request
                for decision in self.treatment_decisions
                for request in decision.asset_requests
            }
            for placement in self.asset_placements:
                if placement.request_id is None:
                    continue
                request = requests_by_id.get(placement.request_id)
                if request is None:
                    raise ValueError("asset placement references an unknown treatment request")
                if request.status != "acquired" or request.registered_asset_id != placement.asset_id:
                    raise ValueError("asset placement request is not acquired for the selected asset")
                if placement.provider_response_sha256 != request.provider_response_sha256:
                    raise ValueError("asset placement provider response is stale")
                if (
                    placement.selection_id != request.selection_id
                    or placement.acquisition_id != request.acquisition_id
                ):
                    raise ValueError("asset placement acquisition identity is stale")
                if placement.license_evidence_sha256 != request.license_evidence_sha256:
                    raise ValueError("asset placement license evidence is stale")
                if placement.registered_asset_sha256 != request.registered_asset_sha256:
                    raise ValueError("asset placement byte hash is stale")
            for decision in self.treatment_decisions:
                for layer in (
                    decision.broll,
                    decision.sfx,
                ):
                    if any(item not in known_placement_ids for item in layer.event_ids):
                        raise ValueError(f"{layer.layer} treatment references an unknown placement")
                    if any(item not in placement_asset_ids for item in layer.asset_ids):
                        raise ValueError(f"{layer.layer} treatment references an unknown asset")
                if any(item not in known_camera_ids for item in decision.camera.event_ids):
                    raise ValueError("camera treatment references an unknown camera event")
                if any(item not in known_transition_ids for item in decision.transition.event_ids):
                    raise ValueError("transition treatment references an unknown transition event")
                if any(item not in known_graphic_ids for item in decision.motion_graphics.event_ids):
                    raise ValueError("motion-graphics treatment references an unknown graphic event")
        request_ids = [
            request.request_id for decision in self.treatment_decisions for request in decision.asset_requests
        ]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("treatment asset request ids must be unique")
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
    safe_region_id: SafeRegionId = "platform-resilient-portrait-v1"
    direction_recipe_version: Literal["direction-v1", "direction-v2", "direction-v3", "direction-v4"] = (
        "direction-v2"
    )
    treatment_revision: DirectionTreatmentRevision | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    treatment_fingerprint: str | None = Field(default=None, pattern=_SHA)
    motion_catalog_sha256: str | None = Field(
        default=None, pattern=_SHA, exclude_if=lambda value: value is None
    )
    preset_id: str | None = Field(default=None, max_length=64, exclude_if=lambda value: value is None)
    knowledge_context_id: EntityId | None = Field(default=None, exclude_if=lambda value: value is None)
    knowledge_release_id: EntityId | None = Field(default=None, exclude_if=lambda value: value is None)
    knowledge_context_sha256: str | None = Field(default=None, pattern=_SHA)
    knowledge_decision_trace_id: EntityId | None = Field(default=None, exclude_if=lambda value: value is None)
    knowledge_decision_trace_sha256: str | None = Field(default=None, pattern=_SHA)
    operator_role: Literal["codex_operator", "human_reviewer"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
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
        if selected.preset_id != self.preset_id:
            raise ValueError("selected direction preset does not match the selected option")
        if self.direction_recipe_version == "direction-v2" and selected.context_line is None:
            raise ValueError("direction-v2 requires one reviewed upper context line")
        if self.direction_recipe_version in {"direction-v3", "direction-v4"} and len(
            selected.treatment_decisions
        ) != len(selected.beats):
            raise ValueError("treatment direction requires decisions for every selected beat")
        if (
            self.direction_recipe_version == "direction-v4"
            and selected.asset_placements
            and self.treatment_revision is None
        ):
            raise ValueError("direction-v4 asset placements require a verified treatment revision")
        if self.treatment_revision is not None and self.direction_recipe_version != "direction-v4":
            raise ValueError("treatment revisions require direction-v4")
        if self.safe_region_id == "platform-resilient-portrait-v1":
            for graphic in selected.motion_graphics:
                if graphic.y < 270 or graphic.y + graphic.height > 1320:
                    raise ValueError(
                        "platform-resilient motion graphics must stay above the caption/UI safe lane"
                    )
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("direction provenance must include source_asset_id")
        context_fields = (
            self.knowledge_context_id,
            self.knowledge_release_id,
            self.knowledge_context_sha256,
            self.knowledge_decision_trace_id,
            self.knowledge_decision_trace_sha256,
        )
        if any(value is not None for value in context_fields[:3]) and not all(
            value is not None for value in context_fields[:3]
        ):
            raise ValueError("knowledge context binding requires id, release, and hash")
        if any(value is not None for value in context_fields[3:]) and not all(
            value is not None for value in context_fields[3:]
        ):
            raise ValueError("knowledge decision trace binding requires id and hash")
        if any(value is not None for value in context_fields[3:]) and any(
            value is None for value in context_fields[:3]
        ):
            raise ValueError("knowledge decision trace requires a bound knowledge context")
        return self


class DirectionLintFinding(Versioned):
    """One deterministic direction-lint finding."""

    severity: Literal["error", "warning", "info"]
    code: str = Field(pattern=r"^[a-z][a-z0-9_.:-]{1,80}$")
    message: str = Field(min_length=1, max_length=500)


class DirectionLintReport(Versioned):
    """Reviewable direction lint output bound to one immutable direction."""

    direction_id: EntityId
    direction_sha256: str = Field(pattern=_SHA)
    status: Literal["pass", "fail"]
    findings: list[DirectionLintFinding] = Field(default_factory=list, max_length=64)
