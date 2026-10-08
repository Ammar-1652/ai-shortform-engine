"""Advanced Hero contracts. These do not replace Hero draft v1.

Music is not part of this profile. A face box is geometry, not a speaker.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.schemas.direction import MotionStyleSpec
from clipforge.schemas.editorial import BrollEvent, MotionPurpose, OutputInterval
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"
_SAFE_X = 48
_SAFE_Y = 48
_FRAME_W = 1080
_FRAME_H = 1920


def advanced_fingerprint(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class ReframingStrategy(Versioned):
    """Named crop strategy. It does not identify a speaker."""

    strategy_id: Literal[
        "contain",
        "center_crop",
        "manual_window",
        "visual_safe_window",
        "multi_face_safe_window",
        "saliency_window",
        "face_follow",
    ]


class ReframingWindow(Versioned):
    """One crop on the visual frame. Coordinates are pixels inside that frame."""

    window_id: EntityId
    strategy_id: ReframingStrategy
    output_start_us: Microseconds
    output_end_us: Microseconds
    source_x: int = Field(ge=0)
    source_y: int = Field(ge=0)
    source_width: int = Field(ge=1)
    source_height: int = Field(ge=1)
    frame_width: int = Field(ge=1)
    frame_height: int = Field(ge=1)

    @model_validator(mode="after")
    def window_is_inside(self) -> Self:
        if self.output_end_us <= self.output_start_us:
            raise ValueError("reframing window duration must be positive")
        if self.source_x + self.source_width > self.frame_width:
            raise ValueError("reframing window extends past the visual frame width")
        if self.source_y + self.source_height > self.frame_height:
            raise ValueError("reframing window extends past the visual frame height")
        return self


class CaptionWordTiming(Versioned):
    """One forced word inside a grouped Advanced Hero caption."""

    word_id: EntityId
    text: str = Field(min_length=1, max_length=200)
    output_start_us: Microseconds
    output_end_us: Microseconds
    output_start_frame: int = Field(ge=0)
    output_end_frame_exclusive: int = Field(ge=1)

    @model_validator(mode="after")
    def interval_is_positive(self) -> Self:
        if self.output_end_us <= self.output_start_us:
            raise ValueError("caption word microsecond interval must be positive")
        if self.output_end_frame_exclusive <= self.output_start_frame:
            raise ValueError("caption word frame interval must be positive and half-open")
        return self


class TypographyEvent(Versioned):
    """On-screen text copied from alignment or a validated payload. It is not HTML."""

    event_id: EntityId
    interval: OutputInterval
    purpose: MotionPurpose
    component_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=80)
    x: int = Field(ge=_SAFE_X, le=_FRAME_W - _SAFE_X)
    y: int = Field(ge=_SAFE_Y, le=_FRAME_H - _SAFE_Y)
    font_size: int = Field(ge=24, le=96)
    color: Literal["#ffffff"] = "#ffffff"
    words: list[CaptionWordTiming] = Field(default_factory=list)

    @model_validator(mode="after")
    def box_stays_in_safe_area(self) -> Self:
        if "<" in self.component_id or ">" in self.component_id:
            raise ValueError("typography component id must be plain text")
        if self.y + self.font_size > _FRAME_H - _SAFE_Y:
            raise ValueError("typography extends below the safe area")
        if self.component_id.startswith("caption-") and not self.words:
            raise ValueError("advanced captions require forced word timing")
        for word in self.words:
            if word.output_start_us < self.interval.output_start_us:
                raise ValueError("caption word starts before its cue")
            if word.output_end_us > self.interval.output_end_us:
                raise ValueError("caption word ends after its cue")
        return self


class DiagramPayload(Versioned):
    """Structured diagram facts. Unknown keys are rejected by the base model."""

    kind: Literal["number_comparison", "two_step", "callout"]
    left_label: str = Field(min_length=1, max_length=40)
    right_label: str = Field(min_length=1, max_length=40)
    left_value: int = Field(ge=0, le=1_000_000_000)
    right_value: int = Field(ge=0, le=1_000_000_000)
    # Optional exact display strings preserve currency, decimal, and unit text.
    # Numeric magnitudes remain for proportional geometry when a grounded
    # comparison is explicitly supplied.
    left_display: str | None = Field(default=None, min_length=1, max_length=40)
    right_display: str | None = Field(default=None, min_length=1, max_length=40)


class DiagramEvent(Versioned):
    """A local diagram. Geometry is numbers, not an SVG or HTML string."""

    event_id: EntityId
    interval: OutputInterval
    purpose: MotionPurpose
    component_id: str = Field(min_length=1, max_length=80)
    payload: DiagramPayload
    x: int = Field(ge=_SAFE_X)
    y: int = Field(ge=_SAFE_Y)
    width: int = Field(ge=80, le=900)
    height: int = Field(ge=80, le=600)

    @model_validator(mode="after")
    def box_stays_in_safe_area(self) -> Self:
        if self.payload.kind != "number_comparison":
            raise ValueError(f"unsupported production diagram kind: {self.payload.kind}")
        if self.x + self.width > _FRAME_W - _SAFE_X:
            raise ValueError("diagram extends past the safe area width")
        if self.y + self.height > _FRAME_H - _SAFE_Y:
            raise ValueError("diagram extends past the safe area height")
        return self


class AssetBinding(Versioned):
    """Rights-cleared local asset used by one advanced plan. No filesystem path."""

    asset_id: EntityId
    project_id: EntityId
    kind: Literal["graphic", "audio"]
    sha256: str = Field(pattern=_SHA)
    license_record_id: EntityId
    license_status: Literal["owned", "licensed", "campaign_provided"]
    provenance_sha256: str = Field(pattern=_SHA)
    display_name: str = Field(min_length=1, max_length=80)


class AudioMixEvent(Versioned):
    """One SFX cue. Music is not a role in this schema."""

    event_id: EntityId
    interval: OutputInterval
    asset_id: EntityId
    role: Literal["sfx"] = "sfx"
    gain_db: float = Field(ge=-24, le=6)
    sfx_source_in_us: Microseconds = Field(default=0, ge=0)
    fade_in_us: Microseconds = Field(default=20_000, ge=0, le=100_000)
    fade_out_us: Microseconds = Field(default=60_000, ge=0, le=200_000)
    # A clean production plan must bind a sound effect to source-grounded
    # evidence. Empty values are retained only so older immutable plans remain
    # readable; the production render gate rejects them.
    source_evidence_ids: list[EntityId] = Field(default_factory=list)
    purpose: MotionPurpose | None = None
    relevance_note: str = Field(default="", max_length=500)


class EmphasisEvent(Versioned):
    """One forced word selected by a named rule. Text is copied."""

    event_id: EntityId
    word_id: EntityId
    text: str = Field(min_length=1, max_length=200)
    output_start_us: Microseconds
    output_end_us: Microseconds
    output_start_frame: int = Field(ge=0)
    output_end_frame_exclusive: int = Field(ge=1)
    purpose: MotionPurpose
    rule_id: Literal["number_or_currency", "terminal_punctuation", "diagram_label"]


class AdvancedHeroProfile(Versioned):
    """Output-changing advanced Hero settings. This is not hero-draft-v1."""

    profile_id: Literal["advanced-hero-v1"] = "advanced-hero-v1"
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    fps_numerator: Literal[30] = 30
    fps_denominator: Literal[1] = 1
    video_codec: Literal["h264"] = "h264"
    pixel_format: Literal["yuv420p"] = "yuv420p"
    audio_codec: Literal["aac"] = "aac"
    audio_sample_rate: Literal[48000] = 48000
    audio_loudness_lufs: float = -16
    audio_true_peak_dbfs: float = -1.5
    audio_lra_lu: float = 11
    narration_duck_db: float = -12
    # SFX are accents under speech, never competing foreground audio.
    sfx_default_gain_db: float = Field(default=-18, ge=-24, le=0)
    sfx_max_gain_db: Literal[-18] = -18
    sfx_fade_in_us: Microseconds = Field(default=20_000, ge=0, le=100_000)
    sfx_fade_out_us: Microseconds = Field(default=60_000, ge=0, le=200_000)
    audio_mix_version: Literal["advanced-audio-mix-v1"] = "advanced-audio-mix-v1"
    background: Literal["neutral-dark-v1"] = "neutral-dark-v1"
    caption_algorithm_version: Literal["advanced-caption-v1", "advanced-caption-clean-v1"] = (
        "advanced-caption-clean-v1"
    )
    typography_version: Literal["advanced-typography-v1", "advanced-typography-clean-v1"] = (
        "advanced-typography-clean-v1"
    )
    diagram_version: Literal["advanced-diagram-v1", "advanced-diagram-grounded-v1"] = (
        "advanced-diagram-grounded-v1"
    )
    renderer_recipe_version: Literal[
        "advanced-hero-renderer-v1", "advanced-hero-renderer-clean-v1", "advanced-hero-renderer-directed-v2"
    ] = "advanced-hero-renderer-clean-v1"
    staging_recipe_version: Literal["time-map-v1-audio-envelope", "time-map-v2-frame-quantized"] = (
        "time-map-v2-frame-quantized"
    )
    motion_library_version: Literal["advanced-motion-v1", "advanced-motion-clean-v1"] = (
        "advanced-motion-clean-v1"
    )
    reframing: ReframingStrategy
    broll_policy: Literal["rights_cleared_local"] = "rights_cleared_local"
    sfx_policy: Literal["rights_cleared_local"] = "rights_cleared_local"
    music_allowed: Literal[False] = False
    max_broll_events: int = Field(default=4, ge=0, le=8)
    max_sfx_events: int = Field(default=4, ge=0, le=8)
    min_gain_db: Literal[-24] = -24
    max_gain_db: Literal[6] = 6
    duration_tolerance_us: Literal[100_000] = 100_000
    manual_window: ReframingWindow | None = None

    @model_validator(mode="after")
    def manual_window_matches_strategy(self) -> Self:
        if self.reframing.strategy_id == "manual_window" and self.manual_window is None:
            raise ValueError("manual_window strategy requires a reframing window")
        if self.reframing.strategy_id != "manual_window" and self.manual_window is not None:
            raise ValueError("a manual window is only stored for the manual_window strategy")
        return self

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        # Round-30 profiles predate the explicit audio policy fields.  Keep
        # their recorded fingerprint verifiable without reinterpreting them;
        # every clean-v1 profile includes the complete current payload.
        if self.renderer_recipe_version == "advanced-hero-renderer-v1":
            for key in (
                "audio_loudness_lufs",
                "audio_true_peak_dbfs",
                "audio_lra_lu",
                "narration_duck_db",
                "sfx_default_gain_db",
                "sfx_max_gain_db",
                "sfx_fade_in_us",
                "sfx_fade_out_us",
                "audio_mix_version",
                "staging_recipe_version",
            ):
                payload.pop(key, None)
        return advanced_fingerprint(payload)


class AdvancedHeroRenderInput(Versioned):
    """Facts for one advanced composition. Paths are local staging names, not URLs."""

    composition_id: Literal["AdvancedHeroDraft"] = "AdvancedHeroDraft"
    candidate_id: EntityId
    advanced_set_id: EntityId
    duration_in_frames: int = Field(ge=1)
    fps_numerator: Literal[30] = 30
    fps_denominator: Literal[1] = 1
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    reframing_strategy: str = Field(min_length=1, max_length=40)
    reframing_config_sha256: str = Field(pattern=_SHA)
    profile_fingerprint: str = Field(pattern=_SHA)
    style_id: str = Field(default="legacy-v1", min_length=1, max_length=64)
    style_fingerprint: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    motion_style: MotionStyleSpec | None = None
    direction_id: str = Field(default="", max_length=128)
    direction_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    safe_region_id: str = Field(default="portrait-safe-v1", min_length=1, max_length=64)
    alignment_sha256: str = Field(pattern=_SHA)
    hero_plan_sha256: str = Field(pattern=_SHA)
    advanced_plan_sha256: str = Field(pattern=_SHA)
    base_video_name: Literal["analysis.mp4"] = "analysis.mp4"
    speech_name: Literal["asr.flac"] = "asr.flac"
    language: str = "en-US"
    captions: list[TypographyEvent] = Field(default_factory=list)
    typography: list[TypographyEvent] = Field(default_factory=list)
    diagrams: list[DiagramEvent] = Field(default_factory=list)
    emphasis: list[EmphasisEvent] = Field(default_factory=list)
    broll: list[BrollEvent] = Field(default_factory=list)
    sfx: list[AudioMixEvent] = Field(default_factory=list)
    windows: list[ReframingWindow] = Field(default_factory=list)
    asset_names: dict[str, str] = Field(default_factory=dict)
    trajectory_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    time_map_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    source_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    output_duration_us: int = Field(default=0, ge=0)
    source_gain_db: float = Field(default=0, ge=-24, le=6)
    narration_gain_db: float = Field(default=0, ge=-24, le=6)
    audio_loudness_lufs: float = -16
    audio_true_peak_dbfs: float = -1.5
    audio_lra_lu: float = 11
    audio_mix_version: Literal["advanced-audio-mix-v1"] = "advanced-audio-mix-v1"
    debug_overlays: Literal[False] = False

    @model_validator(mode="after")
    def local_names_only(self) -> Self:
        if self.motion_style is not None and self.motion_style.style_id != self.style_id:
            raise ValueError("render input motion style does not match style_id")
        if self.style_id != "legacy-v1" and not self.style_fingerprint:
            raise ValueError("production motion style requires a fingerprint")
        for name in self.asset_names.values():
            lowered = name.lower()
            if lowered.startswith(("http://", "https://")) or ".." in name or name.startswith("/"):
                raise ValueError("advanced asset name must be a staging file name")
        return self


class AdvancedHeroDraftOutput(Versioned):
    """One rendered advanced draft."""

    candidate_id: EntityId
    rank: int = Field(ge=1)
    hero_review_id: EntityId
    hero_review_digest: str = Field(pattern=_SHA)
    alignment_id: EntityId
    alignment_sha256: str = Field(pattern=_SHA)
    hero_plan_id: EntityId
    hero_plan_sha256: str = Field(pattern=_SHA)
    advanced_plan_sha256: str = Field(pattern=_SHA)
    direction_id: str = Field(default="", max_length=128)
    direction_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    style_id: str = Field(default="legacy-v1", min_length=1, max_length=64)
    render_input_sha256: str = Field(pattern=_SHA)
    preview_relative_path: str = Field(min_length=1, max_length=512)
    preview_sha256: str = Field(pattern=_SHA)
    preview_size_bytes: int = Field(ge=1)
    output_duration_us: Microseconds
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    output_fps_numerator: Literal[30] = 30
    output_fps_denominator: Literal[1] = 1
    detected_video_codec: str = Field(min_length=1, max_length=40)
    detected_pixel_format: str = Field(min_length=1, max_length=40)
    detected_audio_codec: str = Field(min_length=1, max_length=40)
    detected_audio_sample_rate: int = Field(ge=1)
    detected_duration_us: Microseconds
    duration_error_us: int

    @model_validator(mode="after")
    def path_is_contained(self) -> Self:
        parts = self.preview_relative_path.split("/")
        if len(parts) != 3 or parts[0] != "candidates" or parts[2] != "advanced.mp4":
            raise ValueError("advanced preview path must be candidates/<id>/advanced.mp4")
        if parts[1] != self.candidate_id or parts[1] in {"", ".", ".."}:
            raise ValueError("advanced preview path candidate id does not match")
        return self


class AdvancedHeroPlanDocument(Versioned):
    """Deterministic advanced edit for one approved Hero candidate."""

    plan_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    candidate_set_artifact_id: EntityId
    candidate_set_sha256: str = Field(pattern=_SHA)
    rough_preview_artifact_id: EntityId
    rough_manifest_sha256: str = Field(pattern=_SHA)
    hero_artifact_id: EntityId
    hero_set_id: EntityId
    hero_manifest_sha256: str = Field(pattern=_SHA)
    hero_review_id: EntityId
    hero_review_digest: str = Field(pattern=_SHA)
    alignment_id: EntityId
    alignment_sha256: str = Field(pattern=_SHA)
    hero_plan_id: EntityId
    hero_plan_sha256: str = Field(pattern=_SHA)
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    time_map_sha256: str = Field(pattern=_SHA)
    profile_fingerprint: str = Field(pattern=_SHA)
    direction_id: str = Field(default="", max_length=128)
    direction_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    style_id: str = Field(default="legacy-v1", min_length=1, max_length=64)
    style_fingerprint: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    safe_region_id: str = Field(default="portrait-safe-v1", min_length=1, max_length=64)
    motion_style: MotionStyleSpec | None = None
    reframing_strategy: str = Field(min_length=1, max_length=40)
    reframing_config_sha256: str = Field(pattern=_SHA)
    windows: list[ReframingWindow] = Field(default_factory=list)
    captions: list[TypographyEvent] = Field(default_factory=list)
    typography: list[TypographyEvent] = Field(default_factory=list)
    diagrams: list[DiagramEvent] = Field(default_factory=list)
    emphasis: list[EmphasisEvent] = Field(default_factory=list)
    broll: list[BrollEvent] = Field(default_factory=list)
    sfx: list[AudioMixEvent] = Field(default_factory=list)
    assets: list[AssetBinding] = Field(default_factory=list)
    qa_requirements: list[str] = Field(min_length=1)
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def events_do_not_overlap_illegally(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("advanced plan provenance must include source_asset_id")
        _reject_overlaps(self.broll, "b-roll")
        _reject_overlaps_typed(self.captions, "captions")
        _reject_overlaps_typed(self.typography, "typography")
        for event in self.sfx:
            if event.role != "sfx":
                raise ValueError("advanced Hero audio rejects music")
        if self.motion_style is not None:
            if self.motion_style.style_id != self.style_id:
                raise ValueError("advanced plan motion style does not match style_id")
            if self.style_fingerprint == "":
                raise ValueError("advanced plan motion style requires a fingerprint")
        return self


class AdvancedHeroDraftSetDocument(Versioned):
    """One immutable advanced Hero run. It does not replace the Hero v1 set."""

    advanced_set_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    candidate_set_artifact_id: EntityId
    candidate_set_sha256: str = Field(pattern=_SHA)
    rough_preview_artifact_id: EntityId
    rough_manifest_sha256: str = Field(pattern=_SHA)
    hero_artifact_id: EntityId
    hero_set_id: EntityId
    hero_manifest_sha256: str = Field(pattern=_SHA)
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    profile: AdvancedHeroProfile
    profile_fingerprint: str = Field(pattern=_SHA)
    reframing_strategy: str = Field(min_length=1, max_length=40)
    reframing_config_sha256: str = Field(pattern=_SHA)
    advanced_input_sha256: str = Field(pattern=_SHA)
    direction_sha256s: list[str] = Field(default_factory=list)
    style_ids: list[str] = Field(default_factory=list)
    drafts: list[AdvancedHeroDraftOutput] = Field(min_length=1)
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def set_is_consistent(self) -> Self:
        if self.profile.fingerprint() != self.profile_fingerprint:
            raise ValueError("advanced profile fingerprint does not match the stored profile")
        if self.profile.music_allowed is not False:
            raise ValueError("advanced Hero profile cannot allow music")
        ranks = [item.rank for item in self.drafts]
        if ranks != list(range(1, len(self.drafts) + 1)):
            raise ValueError("advanced ranks must be 1..n in list order")
        if self.provenance.inputs_sha256 != self.advanced_input_sha256:
            raise ValueError("provenance input digest must be the advanced input digest")
        return self


class AdvancedHeroCacheRecord(Versioned):
    """Sidecar for the current advanced set."""

    project_id: EntityId
    source_asset_id: EntityId
    advanced_set_id: EntityId
    job_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    candidate_set_artifact_id: EntityId
    candidate_set_sha256: str = Field(pattern=_SHA)
    rough_preview_artifact_id: EntityId
    rough_manifest_sha256: str = Field(pattern=_SHA)
    hero_artifact_id: EntityId
    hero_set_id: EntityId
    hero_manifest_sha256: str = Field(pattern=_SHA)
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    profile_fingerprint: str = Field(pattern=_SHA)
    reframing_strategy: str = Field(min_length=1, max_length=40)
    reframing_config_sha256: str = Field(pattern=_SHA)
    advanced_input_sha256: str = Field(pattern=_SHA)
    direction_sha256s: list[str] = Field(default_factory=list)
    manifest_sha256: str = Field(pattern=_SHA)
    manifest_size_bytes: int = Field(ge=1)
    rendered_count: int = Field(ge=1)
    validation_status: Literal["passed"]
    created_at: AwareDatetime


def _reject_overlaps(events: list[BrollEvent], label: str) -> None:
    ordered = sorted(events, key=lambda item: (item.interval.output_start_us, item.event_id))
    previous_end = -1
    for event in ordered:
        if event.interval.output_start_us < previous_end:
            raise ValueError(f"overlapping {label} events are rejected")
        previous_end = event.interval.output_end_us


def _reject_overlaps_typed(events: list[TypographyEvent], label: str) -> None:
    ordered = sorted(events, key=lambda item: (item.interval.output_start_us, item.event_id))
    previous_end = -1
    for event in ordered:
        if event.interval.output_start_us < previous_end:
            raise ValueError(f"overlapping {label} events are rejected")
        previous_end = event.interval.output_end_us
