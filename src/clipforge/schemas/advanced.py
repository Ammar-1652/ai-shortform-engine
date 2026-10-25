"""Advanced Hero contracts. These do not replace Hero draft v1.

Music is not part of this profile. A face box is geometry, not a speaker.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.campaign import CampaignOverlaySpec
from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.schemas.direction import MotionStyleSpec, SourceNativeText
from clipforge.schemas.editorial import BrollEvent, MotionPurpose, OutputInterval
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.roles import WorkflowRolePolicy
from clipforge.schemas.time import TimeMapDocument, digest_time_map

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
    verification_status: Literal["unverified", "correct", "incorrect"] = "unverified"
    source_word_ids: list[EntityId] = Field(default_factory=list)

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
    font_size: int = Field(ge=24, le=160)
    color: Literal["#ffffff"] = "#ffffff"
    emoji: Literal["📖", "💡", "🎯", "✨", "⚡", "🧠", "✅", "🔎", "🕌"] | None = None
    words: list[CaptionWordTiming] = Field(default_factory=list)

    @model_validator(mode="after")
    def box_stays_in_safe_area(self) -> Self:
        if "<" in self.component_id or ">" in self.component_id:
            raise ValueError("typography component id must be plain text")
        if self.y + self.font_size > _FRAME_H - _SAFE_Y:
            raise ValueError("typography extends below the safe area")
        if self.component_id.startswith("caption-") and not self.words:
            raise ValueError("advanced captions require forced word timing")
        if self.component_id == "context-line-v1" and self.emoji is None:
            raise ValueError("context-line-v1 requires an allowlisted emoji")
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


class MotionGraphicEvent(Versioned):
    """One source-grounded native Remotion illustration.

    The template is an allowlisted renderer component, never operator-supplied
    JSX, SVG, CSS, or a remote asset.  Text and evidence stay in the typed plan
    so a visual cannot become a free-floating unsupported claim.
    """

    event_id: EntityId
    template: Literal[
        "credit_card",
        "travel_postcard",
        "business_identity",
        "business_spotlight",
        "quran_challenge",
    ]
    interval: OutputInterval
    purpose: MotionPurpose
    source_evidence_ids: list[EntityId] = Field(min_length=1)
    display_text: str = Field(min_length=1, max_length=100)
    x: int = Field(ge=_SAFE_X, le=812)
    y: int = Field(ge=120, le=1240)
    width: int = Field(ge=220, le=840)
    height: int = Field(ge=180, le=560)

    @model_validator(mode="after")
    def stays_in_graphic_region(self) -> Self:
        if self.x + self.width > _FRAME_W - _SAFE_X:
            raise ValueError("motion graphic extends past the safe area width")
        if self.y + self.height > 1480:
            raise ValueError("motion graphic extends into the reserved caption lane")
        return self


class CameraMotionEvent(Versioned):
    """A deterministic output-space camera move selected by direction."""

    event_id: EntityId
    interval: OutputInterval
    intent: Literal["orient", "follow", "reveal", "emphasize", "transition", "settle"]
    path: Literal["hold", "push_in", "pull_out", "pan_x", "pan_y", "drift", "parallax", "match_cut"]
    target_x_permille: int = Field(default=500, ge=0, le=1000)
    target_y_permille: int = Field(default=500, ge=0, le=1000)
    scale_start_permille: int = Field(default=1000, ge=1000, le=1140)
    scale_end_permille: int = Field(default=1000, ge=1000, le=1140)
    travel_px: int = Field(default=0, ge=0, le=194)
    intensity: Literal["quiet", "gentle", "active", "peak"] = "gentle"
    easing: Literal["linear", "ease_out_cubic", "ease_in_out_cubic"] = "ease_in_out_cubic"
    source_evidence_ids: list[EntityId] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def camera_event_is_bounded(self) -> Self:
        if self.path == "hold" and (
            self.scale_start_permille != 1000 or self.scale_end_permille != 1000 or self.travel_px != 0
        ):
            raise ValueError("hold camera event cannot change scale or travel")
        envelopes = {"quiet": (64, 1060), "gentle": (96, 1080), "active": (144, 1110), "peak": (194, 1140)}
        max_travel, max_scale = envelopes[self.intensity]
        if self.travel_px > max_travel or max(self.scale_start_permille, self.scale_end_permille) > max_scale:
            raise ValueError(f"{self.intensity} camera event exceeds its envelope")
        if self.path == "push_in" and self.scale_end_permille < self.scale_start_permille:
            raise ValueError("push_in camera event must not zoom out")
        if self.path == "pull_out" and self.scale_end_permille > self.scale_start_permille:
            raise ValueError("pull_out camera event must not zoom in")
        if (
            self.path in {"pan_x", "pan_y", "drift", "match_cut"}
            and self.scale_start_permille != self.scale_end_permille
        ):
            raise ValueError(f"{self.path} camera event cannot change scale")
        if self.path != "hold" and self.travel_px == 0 and self.scale_start_permille == self.scale_end_permille:
            raise ValueError("a non-hold camera event must have a bounded movement")
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


class TransitionEvent(Versioned):
    """A short, deterministic bridge at a reviewed TimeMap cut."""

    event_id: EntityId
    interval: OutputInterval
    purpose: Literal[MotionPurpose.VISUAL_REVEAL] = MotionPurpose.VISUAL_REVEAL
    style: Literal["clean_cut_v1", "concat_push_v1", "concat_blur_dissolve_v1"] = "clean_cut_v1"
    source_evidence_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    direction_purpose: Literal["cut", "time_shift", "location_change", "reveal", "emphasis", "settle"] = "cut"
    sfx_placement_id: EntityId | None = None


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
    motion_graphics_version: Literal["advanced-motion-graphics-v1"] = "advanced-motion-graphics-v1"
    renderer_recipe_version: Literal[
        "advanced-hero-renderer-v1",
        "advanced-hero-renderer-clean-v1",
        "advanced-hero-renderer-directed-v2",
        "advanced-hero-renderer-directed-v3",
        "advanced-hero-renderer-directed-v4",
    ] = "advanced-hero-renderer-directed-v3"
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
    # An explicitly reviewed, ordered crop trajectory. The legacy singular
    # field remains readable so previously recorded profile fingerprints stay
    # verifiable; new plans should prefer this when the source subject moves.
    manual_windows: list[ReframingWindow] = Field(default_factory=list)

    @model_validator(mode="after")
    def manual_window_matches_strategy(self) -> Self:
        if self.reframing.strategy_id == "manual_window":
            if self.manual_window is None and not self.manual_windows:
                raise ValueError("manual_window strategy requires reviewed crop window(s)")
            if self.manual_window is not None and self.manual_windows:
                raise ValueError("choose the legacy singular crop or manual_windows, not both")
        elif self.manual_window is not None or self.manual_windows:
            raise ValueError("a manual window is only stored for the manual_window strategy")
        return self

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        # Keep old profile digests stable when the additive trajectory field
        # is unused. A populated trajectory is an output-changing dependency.
        if not self.manual_windows:
            payload.pop("manual_windows", None)
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
                "motion_graphics_version",
            ):
                payload.pop(key, None)
        # v2 predates native illustration events.  Its recorded fingerprints
        # must remain verifiable when a stored profile is read by this build.
        elif self.renderer_recipe_version == "advanced-hero-renderer-directed-v2":
            payload.pop("motion_graphics_version", None)
        return advanced_fingerprint(payload)


class FramePaletteSpec(Versioned):
    """Source-bound, allowlisted palette for an editorial frame treatment."""

    analyzer_version: Literal["source-frame-palette-v1"] = "source-frame-palette-v1"
    source_sha256: str = Field(pattern=_SHA)
    family: Literal["olive", "sage", "charcoal"]
    dominant_hex: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    primary_hex: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    accent_hex: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    backdrop_hex: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    backdrop_alt_hex: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    sample_times_us: list[Microseconds] = Field(min_length=1, max_length=8)


class AdvancedHeroRenderInput(Versioned):
    """Facts for one advanced composition. Paths are local staging names, not URLs."""

    composition_id: Literal["AdvancedHeroDraft"] = "AdvancedHeroDraft"
    renderer_recipe_version: Literal[
        "advanced-hero-renderer-v1",
        "advanced-hero-renderer-clean-v1",
        "advanced-hero-renderer-directed-v2",
        "advanced-hero-renderer-directed-v3",
        "advanced-hero-renderer-directed-v4",
    ] = "advanced-hero-renderer-v1"
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
    frame_style_id: str = Field(default="none-v1", min_length=1, max_length=64)
    frame_backdrop_id: Literal["blurred-source-v1", "palette-solid-v1"] = "blurred-source-v1"
    frame_layout_id: Literal["standard-card-v1", "platform-bleed-v1"] = "standard-card-v1"
    frame_palette: FramePaletteSpec | None = None
    direction_id: str = Field(default="", max_length=128)
    direction_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    treatment_fingerprint: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    preset_id: str = Field(default="", max_length=64)
    pilot_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    motion_recipe_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    motion_catalog_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    knowledge_context_id: str = Field(default="", max_length=128)
    knowledge_release_id: str = Field(default="", max_length=128)
    knowledge_context_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    knowledge_decision_trace_id: str = Field(default="", max_length=128)
    knowledge_decision_trace_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    editorial_arc_id: str = Field(default="", max_length=128)
    editorial_arc_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    editorial_arc_review_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    quran_review_id: str = Field(default="", max_length=128)
    quran_review_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    speech_review_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    arabic_corrections_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    caption_alignment_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    safe_region_id: str = Field(default="portrait-safe-v1", min_length=1, max_length=64)
    alignment_sha256: str = Field(pattern=_SHA)
    hero_plan_sha256: str = Field(pattern=_SHA)
    hero_review_status: Literal["approved", "pending"] = "approved"
    advanced_plan_sha256: str = Field(pattern=_SHA)
    base_video_name: Literal["analysis.mp4"] = "analysis.mp4"
    speech_name: Literal["asr.flac"] = "asr.flac"
    campaign_overlay: CampaignOverlaySpec | None = None
    overlay_exclusion_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    language: str = "en-US"
    captions: list[TypographyEvent] = Field(default_factory=list)
    typography: list[TypographyEvent] = Field(default_factory=list)
    diagrams: list[DiagramEvent] = Field(default_factory=list)
    motion_graphics: list[MotionGraphicEvent] = Field(default_factory=list)
    camera_motion: list[CameraMotionEvent] = Field(default_factory=list)
    source_native_text: list[SourceNativeText] = Field(default_factory=list)
    emphasis: list[EmphasisEvent] = Field(default_factory=list)
    transitions: list[TransitionEvent] = Field(default_factory=list)
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
    workflow_roles: WorkflowRolePolicy | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def local_names_only(self) -> Self:
        if bool(self.knowledge_context_id) != bool(self.knowledge_context_sha256):
            raise ValueError("knowledge context id and hash must be recorded together")
        if bool(self.knowledge_context_id) != bool(self.knowledge_release_id):
            raise ValueError("knowledge context requires a release id")
        if bool(self.knowledge_decision_trace_id) != bool(self.knowledge_decision_trace_sha256):
            raise ValueError("knowledge decision trace id and hash must be recorded together")
        if self.knowledge_decision_trace_id and not self.knowledge_context_id:
            raise ValueError("knowledge decision trace requires a knowledge context")
        if self.motion_style is not None and self.motion_style.style_id != self.style_id:
            raise ValueError("render input motion style does not match style_id")
        if self.style_id != "legacy-v1" and not self.style_fingerprint:
            raise ValueError("production motion style requires a fingerprint")
        if self.frame_style_id == "auto-source-palette-v1" and self.frame_palette is None:
            raise ValueError("auto-source-palette-v1 requires a source-bound frame palette")
        if self.frame_style_id == "auto-source-palette-v1" and self.frame_layout_id != "platform-bleed-v1":
            raise ValueError("auto-source-palette-v1 requires the platform-bleed frame layout")
        if self.frame_palette is not None and self.frame_palette.source_sha256 != self.source_sha256:
            raise ValueError("frame palette must bind the render source hash")
        if self.frame_style_id != "none-v1" and self.frame_backdrop_id != "palette-solid-v1":
            raise ValueError("framed renders must use the palette backdrop instead of source blur")
        for name in self.asset_names.values():
            lowered = name.lower()
            if lowered.startswith(("http://", "https://")) or ".." in name or name.startswith("/"):
                raise ValueError("advanced asset name must be a staging file name")
        if self.campaign_overlay is not None:
            if self.style_id != "legacy-v1" and not self.overlay_exclusion_sha256:
                raise ValueError("clean campaign overlays require overlay exclusion evidence")
            names = [self.campaign_overlay.watermark_asset_name]
            if self.campaign_overlay.cta_render_mode == "alpha_video_v1":
                names.append(self.campaign_overlay.cta_asset_name)
            elif self.campaign_overlay.cta_frame_prefix is not None:
                names.append(self.campaign_overlay.cta_frame_prefix)
            for name in names:
                if name not in self.asset_names.values():
                    raise ValueError("campaign overlay asset is not present in staged asset_names")
        return self


class AdvancedHeroDraftOutput(Versioned):
    """One rendered advanced draft."""

    candidate_id: EntityId
    rank: int = Field(ge=1)
    hero_review_id: EntityId
    hero_review_digest: str = Field(pattern=_SHA)
    hero_review_status: Literal["approved", "pending"] = "approved"
    alignment_id: EntityId
    alignment_sha256: str = Field(pattern=_SHA)
    hero_plan_id: EntityId
    hero_plan_sha256: str = Field(pattern=_SHA)
    advanced_plan_sha256: str = Field(pattern=_SHA)
    direction_id: str = Field(default="", max_length=128)
    direction_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    treatment_fingerprint: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    preset_id: str = Field(default="", max_length=64)
    pilot_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    motion_recipe_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    motion_catalog_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    knowledge_context_id: str = Field(default="", max_length=128)
    knowledge_release_id: str = Field(default="", max_length=128)
    knowledge_context_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    knowledge_decision_trace_id: str = Field(default="", max_length=128)
    knowledge_decision_trace_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    editorial_arc_id: str = Field(default="", max_length=128)
    editorial_arc_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    editorial_arc_review_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    quran_review_id: str = Field(default="", max_length=128)
    quran_review_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    speech_review_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    arabic_corrections_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    caption_alignment_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
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
    # New directed renders bind decoded cue-edge evidence. Empty values keep
    # historical immutable manifests readable; clean production QA rejects
    # them when the evidence report is absent.
    caption_coverage_relative_path: str = Field(default="", max_length=512)
    caption_coverage_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    viewer_evidence_relative_path: str = Field(default="", max_length=512)
    viewer_evidence_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    overlay_exclusion_relative_path: str = Field(default="", max_length=512)
    overlay_exclusion_sha256: str = Field(default="", pattern=r"^$|" + _SHA)

    @model_validator(mode="after")
    def knowledge_binding_is_complete(self) -> Self:
        if bool(self.knowledge_context_id) != bool(self.knowledge_context_sha256):
            raise ValueError("knowledge context id and hash must be recorded together")
        if bool(self.knowledge_context_id) != bool(self.knowledge_release_id):
            raise ValueError("knowledge context requires a release id")
        if bool(self.knowledge_decision_trace_id) != bool(self.knowledge_decision_trace_sha256):
            raise ValueError("knowledge decision trace id and hash must be recorded together")
        if self.knowledge_decision_trace_id and not self.knowledge_context_id:
            raise ValueError("knowledge decision trace requires a knowledge context")
        return self

    @model_validator(mode="after")
    def path_is_contained(self) -> Self:
        parts = self.preview_relative_path.split("/")
        if len(parts) != 3 or parts[0] != "candidates" or parts[2] != "advanced.mp4":
            raise ValueError("advanced preview path must be candidates/<id>/advanced.mp4")
        if parts[1] != self.candidate_id or parts[1] in {"", ".", ".."}:
            raise ValueError("advanced preview path candidate id does not match")
        if bool(self.caption_coverage_relative_path) != bool(self.caption_coverage_sha256):
            raise ValueError("caption evidence path and hash must be recorded together")
        if self.caption_coverage_relative_path and self.caption_coverage_relative_path != (
            f"candidates/{self.candidate_id}/caption-coverage.json"
        ):
            raise ValueError("caption evidence must belong to this candidate")
        if bool(self.viewer_evidence_relative_path) != bool(self.viewer_evidence_sha256):
            raise ValueError("viewer evidence path and hash must be recorded together")
        if self.viewer_evidence_relative_path and self.viewer_evidence_relative_path != (
            f"candidates/{self.candidate_id}/viewer-evidence/bundle.json"
        ):
            raise ValueError("viewer evidence must belong to this candidate")
        if bool(self.overlay_exclusion_relative_path) != bool(self.overlay_exclusion_sha256):
            raise ValueError("overlay exclusion evidence path and hash must be recorded together")
        if self.overlay_exclusion_relative_path and self.overlay_exclusion_relative_path != (
            f"candidates/{self.candidate_id}/overlay-exclusion.json"
        ):
            raise ValueError("overlay exclusion evidence must belong to this candidate")
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
    hero_review_status: Literal["approved", "pending"] = "approved"
    alignment_id: EntityId
    alignment_sha256: str = Field(pattern=_SHA)
    hero_plan_id: EntityId
    hero_plan_sha256: str = Field(pattern=_SHA)
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    # New plans persist the exact map used for Advanced staging. ``None``
    # keeps older immutable plans readable.
    time_map: TimeMapDocument | None = None
    time_map_sha256: str = Field(pattern=_SHA)
    editorial_arc_id: str = Field(default="", max_length=128)
    editorial_arc_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    editorial_arc_review_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    quran_review_id: str = Field(default="", max_length=128)
    quran_review_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    speech_review_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    arabic_corrections_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    caption_alignment_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    profile_fingerprint: str = Field(pattern=_SHA)
    direction_id: str = Field(default="", max_length=128)
    direction_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    treatment_fingerprint: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    preset_id: str = Field(default="", max_length=64)
    pilot_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    motion_recipe_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    motion_catalog_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    knowledge_context_id: str = Field(default="", max_length=128)
    knowledge_release_id: str = Field(default="", max_length=128)
    knowledge_context_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    knowledge_decision_trace_id: str = Field(default="", max_length=128)
    knowledge_decision_trace_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    style_id: str = Field(default="legacy-v1", min_length=1, max_length=64)
    style_fingerprint: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    safe_region_id: str = Field(default="portrait-safe-v1", min_length=1, max_length=64)
    motion_style: MotionStyleSpec | None = None
    frame_style_id: str = Field(default="none-v1", min_length=1, max_length=64)
    frame_backdrop_id: Literal["blurred-source-v1", "palette-solid-v1"] = "blurred-source-v1"
    frame_layout_id: Literal["standard-card-v1", "platform-bleed-v1"] = "standard-card-v1"
    frame_palette: FramePaletteSpec | None = None
    reframing_strategy: str = Field(min_length=1, max_length=40)
    reframing_config_sha256: str = Field(pattern=_SHA)
    windows: list[ReframingWindow] = Field(default_factory=list)
    captions: list[TypographyEvent] = Field(default_factory=list)
    typography: list[TypographyEvent] = Field(default_factory=list)
    diagrams: list[DiagramEvent] = Field(default_factory=list)
    motion_graphics: list[MotionGraphicEvent] = Field(default_factory=list)
    camera_motion: list[CameraMotionEvent] = Field(default_factory=list)
    source_native_text: list[SourceNativeText] = Field(default_factory=list)
    emphasis: list[EmphasisEvent] = Field(default_factory=list)
    transitions: list[TransitionEvent] = Field(default_factory=list)
    broll: list[BrollEvent] = Field(default_factory=list)
    sfx: list[AudioMixEvent] = Field(default_factory=list)
    assets: list[AssetBinding] = Field(default_factory=list)
    campaign_overlay: CampaignOverlaySpec | None = None
    qa_requirements: list[str] = Field(min_length=1)
    workflow_roles: WorkflowRolePolicy | None = Field(default=None, exclude_if=lambda value: value is None)
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def events_do_not_overlap_illegally(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("advanced plan provenance must include source_asset_id")
        if bool(self.knowledge_context_id) != bool(self.knowledge_context_sha256):
            raise ValueError("knowledge context id and hash must be recorded together")
        if bool(self.knowledge_context_id) != bool(self.knowledge_release_id):
            raise ValueError("knowledge context requires a release id")
        if bool(self.knowledge_decision_trace_id) != bool(self.knowledge_decision_trace_sha256):
            raise ValueError("knowledge decision trace id and hash must be recorded together")
        if self.knowledge_decision_trace_id and not self.knowledge_context_id:
            raise ValueError("knowledge decision trace requires a knowledge context")
        if self.time_map is not None and digest_time_map(self.time_map) != self.time_map_sha256:
            raise ValueError("advanced plan time_map_sha256 does not match time_map")
        _reject_overlaps(self.broll, "b-roll")
        _reject_overlaps_typed(self.captions, "captions")
        _reject_overlaps_typed(self.typography, "typography")
        _reject_overlaps_typed(self.motion_graphics, "motion graphics")
        _reject_overlaps_typed(self.camera_motion, "camera motion")
        for event in self.sfx:
            if event.role != "sfx":
                raise ValueError("advanced Hero audio rejects music")
        if self.motion_style is not None:
            if self.motion_style.style_id != self.style_id:
                raise ValueError("advanced plan motion style does not match style_id")
            if self.style_fingerprint == "":
                raise ValueError("advanced plan motion style requires a fingerprint")
        if self.frame_style_id == "auto-source-palette-v1" and self.frame_palette is None:
            raise ValueError("auto-source-palette-v1 requires a source-bound frame palette")
        if self.frame_style_id == "auto-source-palette-v1" and self.frame_layout_id != "platform-bleed-v1":
            raise ValueError("auto-source-palette-v1 requires the platform-bleed frame layout")
        if self.frame_palette is not None and self.frame_palette.source_sha256 != self.source_sha256:
            raise ValueError("frame palette must bind the plan source hash")
        if self.frame_style_id != "none-v1" and self.frame_backdrop_id != "palette-solid-v1":
            raise ValueError("framed plans must use the palette backdrop instead of source blur")
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
    hero_review_status: Literal["approved", "pending"] = "approved"
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    profile: AdvancedHeroProfile
    profile_fingerprint: str = Field(pattern=_SHA)
    reframing_strategy: str = Field(min_length=1, max_length=40)
    reframing_config_sha256: str = Field(pattern=_SHA)
    advanced_input_sha256: str = Field(pattern=_SHA)
    # Empty keeps pre-checkpoint manifests readable; new browser renders bind
    # the exact local Remotion worker recipe so a changed renderer cannot hit
    # an old cache entry.
    renderer_dependency_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    direction_sha256s: list[str] = Field(default_factory=list)
    knowledge_context_sha256s: list[str] = Field(default_factory=list)
    knowledge_decision_trace_sha256s: list[str] = Field(default_factory=list)
    style_ids: list[str] = Field(default_factory=list)
    workflow_roles: WorkflowRolePolicy | None = Field(default=None, exclude_if=lambda value: value is None)
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
        if any(item.hero_review_status != self.hero_review_status for item in self.drafts):
            raise ValueError("advanced draft review status must match the set status")
        output_contexts = sorted(
            {item.knowledge_context_sha256 for item in self.drafts if item.knowledge_context_sha256}
        )
        output_traces = sorted(
            {
                item.knowledge_decision_trace_sha256
                for item in self.drafts
                if item.knowledge_decision_trace_sha256
            }
        )
        if self.knowledge_context_sha256s != output_contexts:
            raise ValueError("advanced knowledge context fingerprints do not match drafts")
        if self.knowledge_decision_trace_sha256s != output_traces:
            raise ValueError("advanced knowledge decision fingerprints do not match drafts")
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
    hero_review_status: Literal["approved", "pending"] = "approved"
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    profile_fingerprint: str = Field(pattern=_SHA)
    reframing_strategy: str = Field(min_length=1, max_length=40)
    reframing_config_sha256: str = Field(pattern=_SHA)
    advanced_input_sha256: str = Field(pattern=_SHA)
    renderer_dependency_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    direction_sha256s: list[str] = Field(default_factory=list)
    knowledge_context_sha256s: list[str] = Field(default_factory=list)
    knowledge_decision_trace_sha256s: list[str] = Field(default_factory=list)
    workflow_roles: WorkflowRolePolicy | None = Field(default=None, exclude_if=lambda value: value is None)
    manifest_sha256: str = Field(pattern=_SHA)
    manifest_size_bytes: int = Field(ge=1)
    rendered_count: int = Field(ge=1)
    validation_status: Literal["passed"]
    created_at: AwareDatetime


class AdvancedRenderProgress(Versioned):
    """Checkpoint for a resumable Advanced Remotion run."""

    advanced_set_id: EntityId
    # Preallocated before the first worker starts so a resumed run keeps the
    # same artifact binding for viewer evidence and the eventual DB row.
    artifact_id: EntityId | None = None
    source_asset_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    hero_review_status: Literal["approved", "pending"]
    candidate_ids: list[EntityId] = Field(min_length=1)
    completed_candidate_ids: list[EntityId] = Field(default_factory=list)
    completed_media_sha256: dict[EntityId, str] = Field(default_factory=dict)
    batch_sha256: str = Field(pattern=_SHA)
    renderer_dependency_sha256: str = Field(pattern=_SHA)
    state: Literal["running", "failed", "complete"] = "running"
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def completed_candidates_are_known(self) -> Self:
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("render progress candidate ids must be unique")
        if any(item not in self.candidate_ids for item in self.completed_candidate_ids):
            raise ValueError("render progress contains an unknown completed candidate")
        if set(self.completed_candidate_ids) != set(self.completed_media_sha256):
            raise ValueError("completed candidates require media hash receipts")
        if any(re.fullmatch(_SHA, value) is None for value in self.completed_media_sha256.values()):
            raise ValueError("completed media hashes must be sha256")
        if self.state == "complete" and set(self.completed_candidate_ids) != set(self.candidate_ids):
            raise ValueError("a complete render progress record must include every candidate")
        return self


def _reject_overlaps(events: list[BrollEvent], label: str) -> None:
    ordered = sorted(events, key=lambda item: (item.interval.output_start_us, item.event_id))
    previous_end = -1
    for event in ordered:
        if event.interval.output_start_us < previous_end:
            raise ValueError(f"overlapping {label} events are rejected")
        previous_end = event.interval.output_end_us


class _TimedPlanEvent(Protocol):
    event_id: str
    interval: OutputInterval


def _reject_overlaps_typed(events: Sequence[_TimedPlanEvent], label: str) -> None:
    # The upper context sentence intentionally spans the complete output and
    # occupies its own lane. It may coexist in time with hook/body/punch cards;
    # all non-context typography must remain mutually exclusive.
    if label == "typography":
        events = tuple(event for event in events if getattr(event, "component_id", "") != "context-line-v1")
    ordered = sorted(events, key=lambda item: (item.interval.output_start_us, item.event_id))
    previous_end = -1
    for event in ordered:
        if event.interval.output_start_us < previous_end:
            raise ValueError(f"overlapping {label} events are rejected")
        previous_end = event.interval.output_end_us
