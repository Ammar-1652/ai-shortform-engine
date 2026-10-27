"""Typed per-beat treatment decisions for the editorial direction layer."""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.provenance import ArtifactProvenance

TreatmentState = Literal["use", "omit_with_reason", "blocked_by_policy", "needs_review"]
TreatmentLayer = Literal["broll", "camera", "transition", "sfx", "motion_graphics"]
TreatmentOmissionReason = Literal[
    "dialogue_clarity",
    "no_relevant_asset",
    "face_collision",
    "protected_region_collision",
    "quiet_payoff",
    "short_interval",
    "no_semantic_cut",
    "policy_preference",
    "unsupported_capability",
    "missing_evidence",
]
TreatmentAssetStatus = Literal["pending", "selected", "acquired", "blocked", "unavailable"]
CollisionStatus = Literal["clear", "blocked", "unknown"]
TreatmentRegionRole = Literal[
    "face",
    "active_subject",
    "source_text",
    "caption",
    "logo",
    "cta",
    "platform_safe",
    "broll",
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
    status: TreatmentAssetStatus = "pending"
    provider_response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    selection_id: EntityId | None = None
    acquisition_id: EntityId | None = None
    license_evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    registered_asset_id: EntityId | None = None
    registered_asset_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def request_is_bounded(self) -> Self:
        if any(not term.strip() or len(term.strip()) > 80 for term in self.query_terms):
            raise ValueError("asset request query terms must be short non-empty values")
        if self.kind == "audio" and "graphic" in self.provider_classes:
            raise ValueError("audio asset requests cannot use a graphic-only provider class")
        if self.status in {"selected", "acquired"} and (
            self.provider_response_sha256 is None or self.selection_id is None
        ):
            raise ValueError("selected asset requests require provider response and selection evidence")
        if self.status == "acquired" and (
            self.acquisition_id is None
            or self.license_evidence_sha256 is None
            or self.registered_asset_id is None
            or self.registered_asset_sha256 is None
        ):
            raise ValueError(
                "acquired asset requests require acquisition, license, and registered asset evidence"
            )
        return self


class TreatmentAssetVerification(Versioned):
    """Evidence returned only after an existing provider/rights boundary verifies an asset."""

    provider: Literal["envato", "openverse", "local"]
    provider_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_id: EntityId
    acquisition_id: EntityId
    license_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    registered_asset_id: EntityId
    registered_asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_kind: Literal["graphic", "audio"]
    status: Literal["verified"] = "verified"


class TreatmentRegion(Versioned):
    """One output-space protected region used by treatment collision checks."""

    region_id: EntityId
    role: TreatmentRegionRole
    interval: OutputInterval
    x: int = Field(ge=0, le=1080)
    y: int = Field(ge=0, le=1920)
    width: int = Field(gt=0, le=1080)
    height: int = Field(gt=0, le=1920)
    source: Literal["visual_analysis", "platform_profile", "render_input"]

    @model_validator(mode="after")
    def stays_in_output(self) -> Self:
        if self.x + self.width > 1080 or self.y + self.height > 1920:
            raise ValueError("treatment region must stay inside the portrait output")
        return self


class TreatmentObservationFrame(Versioned):
    relative_path: str = Field(pattern=r"^editorial/treatment-observations/[A-Za-z0-9._:/-]+\.jpg$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    timestamp_us: Microseconds


class TreatmentAssetObservation(Versioned):
    """Decoded, reviewed observation of a selected visual asset."""

    observation_id: EntityId
    asset_id: EntityId
    source_asset_id: EntityId
    media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_interval: OutputInterval
    source_in_us: Microseconds = 0
    source_out_us: Microseconds | None = None
    source_evidence_ids: list[EntityId] = Field(min_length=1, max_length=16)
    frames: list[TreatmentObservationFrame] = Field(min_length=1, max_length=8)
    observed_labels: list[str] = Field(min_length=1, max_length=16)
    relevance_score: float = Field(ge=0, le=1)
    relevance_threshold: float = Field(ge=0, le=1)
    analyzer_version: Literal["ffmpeg-frame-probe-v1", "ffmpeg-frame-probe-v2"] = "ffmpeg-frame-probe-v1"
    reviewed_by: str = Field(min_length=1, max_length=200)
    review_note: str = Field(min_length=1, max_length=500)
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def score_is_actionable(self) -> Self:
        if self.analyzer_version == "ffmpeg-frame-probe-v2":
            duration = self.output_interval.output_end_us - self.output_interval.output_start_us
            if self.source_out_us != self.source_in_us + duration:
                raise ValueError("observation source span must match its selected output duration")
            timestamps = [frame.timestamp_us for frame in self.frames]
            if timestamps != sorted(set(timestamps)) or any(
                not self.source_in_us <= timestamp < self.source_out_us for timestamp in timestamps
            ):
                raise ValueError("observation frames must be ordered inside the selected source span")
        if self.relevance_score < self.relevance_threshold:
            raise ValueError("visual observation relevance is below its required threshold")
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("visual observation provenance must include the source asset")
        return self


class TreatmentVisualEvidence(Versioned):
    """Measured visual and collision facts for one treatment decision."""

    visual_scene_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    protected_region_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    collision_status: CollisionStatus = "unknown"
    relevance_status: Literal["related", "unrelated", "unknown"] = "unknown"
    relevance_score: float | None = Field(default=None, ge=0, le=1)
    relevance_threshold: float | None = Field(default=None, ge=0, le=1)
    evidence_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    regions: list[TreatmentRegion] = Field(default_factory=list, max_length=32)
    note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def status_has_evidence(self) -> Self:
        if self.collision_status == "clear" and not self.protected_region_ids:
            raise ValueError("clear collision evidence requires protected region ids")
        if self.relevance_status != "unknown" and not self.evidence_ids:
            raise ValueError("relevance status requires evidence ids")
        if self.relevance_status != "unknown" and self.relevance_score is None:
            raise ValueError("relevance status requires a numeric relevance score")
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
    visual_evidence: TreatmentVisualEvidence | None = None
    audio_mix_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
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


class TreatmentAudioMixResult(Versioned):
    """Hash-bound requested/applied SFX mix policy and measured output facts."""

    mix_id: EntityId
    treatment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    cue_event_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    applied_gain_db: list[float] = Field(default_factory=list, max_length=32)
    duck_db: list[float] = Field(default_factory=list, max_length=32)
    source_in_us: list[int] = Field(default_factory=list, max_length=32)
    fade_in_us: list[int] = Field(default_factory=list, max_length=32)
    fade_out_us: list[int] = Field(default_factory=list, max_length=32)
    speech_overlap_windows: list[OutputInterval | None] = Field(default_factory=list, max_length=32)
    silence_windows: list[OutputInterval] = Field(default_factory=list, max_length=32)
    intelligibility_status: Literal["unverified", "pass", "fail"] = "unverified"
    intelligibility_method: Literal[
        "", "decoded_window_signal_v1", "decoded_window_signal_v2", "no_audio_cues_v1"
    ] = ""
    intelligibility_checked_windows: list[OutputInterval] = Field(default_factory=list, max_length=32)
    intelligibility_failed_windows: list[OutputInterval] = Field(default_factory=list, max_length=32)
    intelligibility_encoded_rms_windows: list[float] = Field(default_factory=list, max_length=32)
    intelligibility_speech_reference_rms_windows: list[float] = Field(default_factory=list, max_length=32)
    intelligibility_sfx_reference_rms_windows: list[float] = Field(default_factory=list, max_length=32)
    intelligibility_margin_db: list[float] = Field(default_factory=list, max_length=32)
    intelligibility_note: str = Field(default="", max_length=500)
    measured_integrated_lufs: float | None = None
    measured_true_peak_dbfs: float | None = None
    measured_rms_windows: list[float] = Field(default_factory=list, max_length=128)
    status: Literal["planned", "measured"] = "planned"

    @model_validator(mode="after")
    def measured_result_has_facts(self) -> Self:
        if self.status == "measured" and (
            self.measured_integrated_lufs is None
            or self.measured_true_peak_dbfs is None
            or not self.measured_rms_windows
        ):
            raise ValueError("measured audio mix results require loudness, true-peak, and RMS facts")
        if self.intelligibility_status == "unverified" and self.status == "measured":
            raise ValueError("measured audio mix results require decoded intelligibility evidence")
        if self.intelligibility_status != "unverified" and not self.intelligibility_method:
            raise ValueError("audio intelligibility status requires a measurement method")
        if self.intelligibility_status == "pass" and self.intelligibility_failed_windows:
            raise ValueError("passed intelligibility cannot contain failed windows")
        if self.intelligibility_status == "fail" and not (
            self.intelligibility_failed_windows or self.intelligibility_note
        ):
            raise ValueError("failed intelligibility requires failed windows or a failure note")
        if self.intelligibility_method == "decoded_window_signal_v2":
            expected = len(self.intelligibility_checked_windows)
            if any(
                len(values) != expected
                for values in (
                    self.intelligibility_encoded_rms_windows,
                    self.intelligibility_speech_reference_rms_windows,
                    self.intelligibility_sfx_reference_rms_windows,
                    self.intelligibility_margin_db,
                )
            ):
                raise ValueError("decoded intelligibility v2 facts must match checked windows")
        numeric = [
            self.measured_integrated_lufs,
            self.measured_true_peak_dbfs,
            *self.measured_rms_windows,
            *self.intelligibility_encoded_rms_windows,
            *self.intelligibility_speech_reference_rms_windows,
            *self.intelligibility_sfx_reference_rms_windows,
            *self.intelligibility_margin_db,
        ]
        if any(value is not None and not math.isfinite(value) for value in numeric):
            raise ValueError("audio mix measurements must be finite")
        if len(self.applied_gain_db) != len(self.cue_event_ids):
            raise ValueError("audio mix gain facts must match cue event ids")
        if len(self.duck_db) != len(self.cue_event_ids):
            raise ValueError("audio mix duck facts must match cue event ids")
        for label, values in (
            ("source in", self.source_in_us),
            ("fade in", self.fade_in_us),
            ("fade out", self.fade_out_us),
        ):
            if len(values) != len(self.cue_event_ids):
                raise ValueError(f"audio mix {label} facts must match cue event ids")
        if len(self.speech_overlap_windows) != len(self.cue_event_ids):
            raise ValueError("audio mix speech-overlap facts must match cue event ids")
        return self


class TreatmentAudioMeasurement(Versioned):
    """Decoded post-encode mix evidence bound to the planned treatment bundle."""

    measurement_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId
    treatment_evidence_sha256: str = Field(pattern=r"^$|^[0-9a-f]{64}$")
    encoded_media_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mix: TreatmentAudioMixResult
    created_at: AwareDatetime
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def is_bound(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("audio measurement provenance must include the source asset")
        if self.mix.status != "measured":
            raise ValueError("audio measurement must contain measured mix facts")
        if self.mix.treatment_fingerprint != "0" * 64 and not self.treatment_evidence_sha256:
            raise ValueError("directed audio measurement requires treatment evidence binding")
        return self


class TreatmentPolicyFinding(Versioned):
    severity: Literal["error", "warning", "info"]
    code: str = Field(pattern=r"^[a-z][a-z0-9_.:-]{1,80}$")
    message: str = Field(min_length=1, max_length=500)


class TreatmentAssetReceipt(Versioned):
    placement_id: EntityId
    request_id: EntityId
    asset_id: EntityId
    kind: Literal["graphic", "audio"]
    interval: OutputInterval
    source_in_us: Microseconds
    provider_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_id: EntityId
    acquisition_id: EntityId
    license_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    registered_asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_id: EntityId | None = None
    observation_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class TreatmentEvidenceBundle(Versioned):
    """Canonical, persisted treatment facts consumed by every downstream gate."""

    bundle_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId
    direction_id: EntityId
    direction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    treatment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    decisions: list[BeatTreatmentDecision] = Field(min_length=1, max_length=12)
    asset_receipts: list[TreatmentAssetReceipt] = Field(default_factory=list, max_length=32)
    observations: list[TreatmentAssetObservation] = Field(default_factory=list, max_length=32)
    policy_findings: list[TreatmentPolicyFinding] = Field(default_factory=list, max_length=64)
    audio_mix: TreatmentAudioMixResult | None = None
    created_at: AwareDatetime
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def observation_receipts_are_embedded(self) -> Self:
        observations = {item.observation_id: item for item in self.observations}
        for receipt in self.asset_receipts:
            if receipt.observation_id is None:
                continue
            observation = observations.get(receipt.observation_id)
            if observation is None or receipt.observation_sha256 is None:
                raise ValueError("treatment receipt observation must be embedded in the evidence bundle")
            if (
                observation.asset_id != receipt.asset_id
                or observation.media_sha256 != receipt.registered_asset_sha256
            ):
                raise ValueError("embedded treatment observation is bound to another asset")
        return self


class TreatmentPlanSummary(Versioned):
    """Stable summary used by CLI, cache, and review payloads."""

    treatment_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    beat_count: int = Field(ge=1, le=32)
    used_layers: list[TreatmentLayer] = Field(default_factory=list, max_length=160)
    blocked_layers: list[TreatmentLayer] = Field(default_factory=list, max_length=160)
    omitted_layers: list[TreatmentLayer] = Field(default_factory=list, max_length=160)
    provider_request_count: int = Field(default=0, ge=0, le=256)
