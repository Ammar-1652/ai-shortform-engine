"""Typed per-beat treatment decisions for the editorial direction layer."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.editorial import MotionPurpose, OutputInterval

TreatmentState = Literal["use", "omit_with_reason", "blocked_by_policy", "needs_review"]
TreatmentLayer = Literal["broll", "camera", "transition", "sfx", "motion_graphics"]
TreatmentOmissionReason = Literal[
    "dialogue_clarity",
    "no_relevant_asset",
    "face_collision",
    "quiet_payoff",
    "short_interval",
    "no_semantic_cut",
    "policy_preference",
    "unsupported_capability",
    "missing_evidence",
]


class TreatmentLayerDecision(Versioned):
    """A decision for one optional visual/audio layer on one beat."""

    layer: TreatmentLayer
    state: TreatmentState
    purpose: MotionPurpose | None = None
    rationale: str = Field(min_length=1, max_length=500)
    source_evidence_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    omission_reason: TreatmentOmissionReason | None = None
    fallback: Literal["source_footage", "clean_cut", "hold", "silence", "none"] = "none"
    asset_request_ids: list[EntityId] = Field(default_factory=list, max_length=8)
    asset_ids: list[EntityId] = Field(default_factory=list, max_length=8)
    event_ids: list[EntityId] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def state_has_required_explanation(self) -> Self:
        if self.state == "omit_with_reason" and self.omission_reason is None:
            raise ValueError("omitted treatment must have a structured omission_reason")
        if self.state in {"blocked_by_policy", "needs_review"} and self.omission_reason is not None:
            raise ValueError("blocked or review treatment cannot use an omission_reason")
        if self.state == "use" and not (self.event_ids or self.asset_ids or self.asset_request_ids):
            raise ValueError("used treatment must reference an event, asset, or asset request")
        if self.state != "use" and (self.event_ids or self.asset_ids):
            raise ValueError("non-used treatment cannot reference selected events or assets")
        return self


class BrollTreatmentDecision(TreatmentLayerDecision):
    layer: Literal["broll"] = "broll"
    role: (
        Literal[
            "context",
            "proof",
            "process",
            "reaction",
            "result",
            "contrast",
            "atmosphere",
            "product_detail",
        ]
        | None
    ) = None
    query_terms: list[str] = Field(default_factory=list, max_length=8)
    negative_terms: list[str] = Field(default_factory=list, max_length=8)
    relevance_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def used_broll_has_role(self) -> Self:
        if self.state == "use" and (self.role is None or not self.relevance_note):
            raise ValueError("used B-roll must declare a role and relevance_note")
        return self


class CameraTreatmentDecision(TreatmentLayerDecision):
    layer: Literal["camera"] = "camera"
    mode: Literal["static", "push_in", "pull_out", "follow_subject", "reframe", "settle"] | None = None
    intensity: Literal["quiet", "gentle", "active", "peak"] = "gentle"
    protected_regions: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def used_camera_has_mode(self) -> Self:
        if self.state == "use" and self.mode is None:
            raise ValueError("used camera treatment must declare a mode")
        return self


class TransitionTreatmentDecision(TreatmentLayerDecision):
    layer: Literal["transition"] = "transition"
    style: Literal["clean_cut_v1", "concat_push_v1", "concat_blur_dissolve_v1"] | None = None
    cut_boundary_us: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def used_transition_has_style(self) -> Self:
        if self.state == "use" and (self.style is None or self.cut_boundary_us is None):
            raise ValueError("used transition must declare style and cut_boundary_us")
        return self


class SfxTreatmentDecision(TreatmentLayerDecision):
    layer: Literal["sfx"] = "sfx"
    role: Literal["accent", "reveal", "transition", "reaction", "settle"] | None = None
    gain_db: float = Field(default=-18.0, ge=-24.0, le=0.0)
    duck_db: float = Field(default=6.0, ge=0.0, le=18.0)
    max_overlap_us: int = Field(default=300_000, ge=0, le=2_000_000)

    @model_validator(mode="after")
    def used_sfx_has_role(self) -> Self:
        if self.state == "use" and self.role is None:
            raise ValueError("used SFX must declare a role")
        return self


class MotionGraphicsTreatmentDecision(TreatmentLayerDecision):
    layer: Literal["motion_graphics"] = "motion_graphics"
    template: str | None = Field(default=None, max_length=80)


class TreatmentAssetRequest(Versioned):
    """A bounded provider request produced from a source-grounded beat."""

    request_id: EntityId
    beat_id: EntityId
    kind: Literal["graphic", "audio"]
    role: str = Field(min_length=1, max_length=40)
    query_terms: list[str] = Field(min_length=1, max_length=8)
    negative_terms: list[str] = Field(default_factory=list, max_length=8)
    provider_classes: list[Literal["local", "envato", "openverse"]] = Field(min_length=1, max_length=3)
    interval: OutputInterval
    source_evidence_ids: list[EntityId] = Field(min_length=1, max_length=16)
    relevance_threshold: float = Field(default=0.85, ge=0, le=1)

    @model_validator(mode="after")
    def request_is_bounded(self) -> Self:
        if any(not term.strip() or len(term.strip()) > 80 for term in self.query_terms):
            raise ValueError("asset request query terms must be short non-empty values")
        if self.kind == "audio" and "graphic" in self.provider_classes:
            raise ValueError("audio asset requests cannot use a graphic-only provider class")
        return self


class BeatTreatmentDecision(Versioned):
    """Complete treatment coverage for one hook/body/punch beat."""

    beat_id: EntityId
    output_interval: OutputInterval
    narrative_purpose: Literal["orient", "explain", "prove", "react", "contrast", "reveal", "resolve", "settle"]
    source_evidence_ids: list[EntityId] = Field(min_length=1, max_length=16)
    broll: BrollTreatmentDecision
    camera: CameraTreatmentDecision
    transition: TransitionTreatmentDecision
    sfx: SfxTreatmentDecision
    motion_graphics: MotionGraphicsTreatmentDecision
    asset_requests: list[TreatmentAssetRequest] = Field(default_factory=list, max_length=8)
    dependency_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def layers_match_evidence_and_beat(self) -> Self:
        if not self.output_interval.output_end_us > self.output_interval.output_start_us:
            raise ValueError("treatment beat interval must be positive")
        for layer in (self.broll, self.camera, self.transition, self.sfx, self.motion_graphics):
            if any(item not in self.source_evidence_ids for item in layer.source_evidence_ids):
                raise ValueError(f"{layer.layer} treatment references evidence outside its beat")
        if any(request.beat_id != self.beat_id for request in self.asset_requests):
            raise ValueError("asset request must belong to its treatment beat")
        if any(
            evidence_id not in self.source_evidence_ids
            for request in self.asset_requests
            for evidence_id in request.source_evidence_ids
        ):
            raise ValueError("asset request references evidence outside its beat")
        return self


class TreatmentPlanSummary(Versioned):
    """Stable summary used by CLI, cache, and review payloads."""

    treatment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    beat_count: int = Field(ge=1, le=32)
    used_layers: list[TreatmentLayer] = Field(default_factory=list, max_length=160)
    blocked_layers: list[TreatmentLayer] = Field(default_factory=list, max_length=160)
    omitted_layers: list[TreatmentLayer] = Field(default_factory=list, max_length=160)
    provider_request_count: int = Field(default=0, ge=0, le=256)
