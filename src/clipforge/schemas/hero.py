"""Hero draft contracts. These are separate from rough previews.

Approval stays a human ``ReviewDecision``. Forced alignment is not provisional
timing. Motion events do not change the candidate TimeMap.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.schemas.editorial import EditPlan
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"


def hero_fingerprint(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class HeroProfile(Versioned):
    """Output-changing Hero draft settings. This is not the rough-preview profile."""

    profile_id: Literal["hero-draft-v1"] = "hero-draft-v1"
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    fps_numerator: Literal[30] = 30
    fps_denominator: Literal[1] = 1
    video_fit: Literal["contain"] = "contain"
    background: Literal["neutral-dark-v1"] = "neutral-dark-v1"
    caption_algorithm_version: Literal["hero-caption-v1"] = "hero-caption-v1"
    caption_style_version: Literal["hero-caption-style-v1"] = "hero-caption-style-v1"
    renderer_recipe_version: Literal["hero-draft-renderer-v1"] = "hero-draft-renderer-v1"
    motion_library_version: Literal["motion-library-v1"] = "motion-library-v1"
    video_codec: Literal["h264"] = "h264"
    pixel_format: Literal["yuv420p"] = "yuv420p"
    audio_codec: Literal["aac"] = "aac"
    audio_enabled: Literal[True] = True
    h264_crf: int = Field(default=23, ge=0, le=51)

    def fingerprint(self) -> str:
        return hero_fingerprint(self.model_dump(mode="json"))


class AlignedWord(Versioned):
    """One forced word. Text is copied from the transcript. Times are not provisional."""

    word_id: EntityId
    candidate_id: EntityId
    text: str = Field(min_length=1, max_length=200)
    source_start_us: Microseconds
    source_end_us: Microseconds
    output_start_us: Microseconds
    output_end_us: Microseconds
    output_start_frame: int = Field(ge=0)
    output_end_frame_exclusive: int = Field(ge=1)
    alignment_quality: Literal["forced"] = "forced"
    segment_index: int = Field(default=-1, ge=-1)

    @model_validator(mode="after")
    def ranges_are_positive(self) -> Self:
        if self.source_end_us <= self.source_start_us:
            raise ValueError("aligned word source duration must be positive")
        if self.output_end_us <= self.output_start_us:
            raise ValueError("aligned word output duration must be positive")
        if self.output_end_frame_exclusive <= self.output_start_frame:
            raise ValueError("aligned word frame interval must be positive and half-open")
        return self


class ForcedAlignmentDocument(Versioned):
    """Forced alignment for one approved candidate. The TimeMap stays authoritative."""

    alignment_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId
    transcript_id: EntityId
    transcript_sha256: str = Field(pattern=_SHA)
    asr_audio_sha256: str = Field(pattern=_SHA)
    time_map_sha256: str = Field(pattern=_SHA)
    review_id: EntityId
    review_digest: str = Field(pattern=_SHA)
    rough_preview_artifact_id: EntityId
    model_name: str = Field(min_length=1, max_length=80)
    whisperx_version: str = Field(min_length=1, max_length=40)
    device: Literal["cpu", "cuda"]
    config_sha256: str = Field(pattern=_SHA)
    words: list[AlignedWord] = Field(min_length=1)
    provenance: ArtifactProvenance
    locale: str = "en-US"
    normalized_language: str = "en"
    model_revision: str = ""
    checkpoint_sha256: str = ""
    model_license: str = ""
    alignment_status: str = "unspecified"
    alignment_scope: str = "selected_clip"
    alignment_recipe: str = "hero-align-v1"
    binding_sha256: str = ""
    manifest_sha256: str = ""
    unavailable_reason: str = "none"

    @model_validator(mode="after")
    def words_are_monotonic(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("alignment provenance must include source_asset_id")
        previous_output = -1
        seen: set[str] = set()
        for word in self.words:
            if word.candidate_id != self.candidate_id:
                raise ValueError("aligned word candidate id does not match the document")
            if word.word_id in seen:
                raise ValueError("aligned word ids must be unique")
            seen.add(word.word_id)
            if word.output_start_us < previous_output:
                raise ValueError("aligned words must be monotonic in output order")
            if word.output_end_us <= word.output_start_us or word.source_end_us <= word.source_start_us:
                raise ValueError("aligned word intervals must be positive")
            previous_output = word.output_end_us
        grouped: dict[int, list[AlignedWord]] = {}
        for word in self.words:
            grouped.setdefault(word.segment_index, []).append(word)
        for group in grouped.values():
            ordered = sorted(group, key=lambda item: (item.source_start_us, item.source_end_us))
            previous_source_end = -1
            for word in ordered:
                if word.source_start_us < previous_source_end:
                    raise ValueError("aligned words overlap inside one TimeMap segment")
                previous_source_end = word.source_end_us
        if self.alignment_status == "verified_live" and self.model_name == "fake-forced-align-v1":
            raise ValueError("a fake alignment cannot be verified live")
        if self.checkpoint_sha256 and len(self.checkpoint_sha256) != 64:
            raise ValueError("alignment checkpoint must be a sha256 hex digest")
        if self.binding_sha256 and len(self.binding_sha256) != 64:
            raise ValueError("alignment binding must be a sha256 hex digest")
        return self


class HeroRenderInput(Versioned):
    """Facts for one Hero composition. Python already checked approval and alignment."""

    composition_id: Literal["HeroDraft"] = "HeroDraft"
    candidate_id: EntityId
    hero_set_id: EntityId
    video_path: str = Field(min_length=1, max_length=4096)
    audio_path: str = Field(min_length=1, max_length=4096)
    media_trim_frame: int = Field(ge=0)
    duration_in_frames: int = Field(ge=1)
    fps_numerator: Literal[30] = 30
    fps_denominator: Literal[1] = 1
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    source_width: int = Field(default=1920, ge=1)
    source_height: int = Field(default=1080, ge=1)
    video_fit: Literal["contain"] = "contain"
    background: Literal["neutral-dark-v1"] = "neutral-dark-v1"
    language: str = "en-US"
    alignment_quality: Literal["forced"] = "forced"
    alignment_sha256: str = Field(pattern=_SHA)
    edit_plan_sha256: str = Field(pattern=_SHA)
    time_map_sha256: str = Field(pattern=_SHA)
    review_id: EntityId
    review_digest: str = Field(pattern=_SHA)
    motion_library_version: Literal["motion-library-v1"] = "motion-library-v1"
    profile_fingerprint: str = Field(pattern=_SHA)
    captions: list[dict[str, object]] = Field(default_factory=list)
    motion_events: list[dict[str, object]] = Field(default_factory=list)

    @model_validator(mode="after")
    def local_media_only(self) -> Self:
        for label, path in (("video", self.video_path), ("audio", self.audio_path)):
            lowered = path.lower()
            if lowered.startswith(("http://", "https://")):
                raise ValueError(f"Hero {label} must be a local file, not an http URL")
            if ".." in path or "\x00" in path:
                raise ValueError(f"Hero {label} path must not contain a parent segment")
        return self


class HeroDraftOutput(Versioned):
    """One rendered Hero draft. Hashes point at files inside the Hero run."""

    candidate_id: EntityId
    rank: int = Field(ge=1)
    review_id: EntityId
    review_digest: str = Field(pattern=_SHA)
    time_map_sha256: str = Field(pattern=_SHA)
    alignment_sha256: str = Field(pattern=_SHA)
    edit_plan_sha256: str = Field(pattern=_SHA)
    render_input_sha256: str = Field(pattern=_SHA)
    preview_relative_path: str = Field(min_length=1, max_length=512)
    preview_sha256: str = Field(pattern=_SHA)
    preview_size_bytes: int = Field(ge=1)
    output_duration_us: Microseconds
    output_frame_count: int = Field(ge=1)
    caption_count: int = Field(ge=1)
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    output_fps_numerator: Literal[30] = 30
    output_fps_denominator: Literal[1] = 1
    detected_video_codec: str = Field(min_length=1, max_length=40)
    detected_pixel_format: str = Field(min_length=1, max_length=40)
    detected_audio_codec: str = Field(min_length=1, max_length=40)
    detected_duration_us: Microseconds
    duration_error_us: int

    @model_validator(mode="after")
    def path_is_contained(self) -> Self:
        parts = self.preview_relative_path.split("/")
        if len(parts) != 3 or parts[0] != "candidates" or parts[2] != "hero.mp4":
            raise ValueError("Hero preview path must be candidates/<id>/hero.mp4")
        if parts[1] != self.candidate_id or parts[1] in {"", ".", ".."}:
            raise ValueError("Hero preview path candidate id does not match")
        return self


class HeroDraftSetDocument(Versioned):
    """One immutable Hero draft run. It does not replace the rough preview set."""

    hero_set_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    created_at: AwareDatetime
    source_sha256: str = Field(pattern=_SHA)
    candidate_set_artifact_id: EntityId
    candidate_set_sha256: str = Field(pattern=_SHA)
    transcript_id: EntityId
    transcript_sha256: str = Field(pattern=_SHA)
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    analysis_proxy_sha256: str = Field(pattern=_SHA)
    asr_audio_sha256: str = Field(pattern=_SHA)
    rough_preview_artifact_id: EntityId
    rough_preview_set_id: EntityId
    rough_manifest_sha256: str = Field(pattern=_SHA)
    profile: HeroProfile
    profile_fingerprint: str = Field(pattern=_SHA)
    motion_library_version: Literal["motion-library-v1"] = "motion-library-v1"
    renderer_recipe_version: Literal["hero-draft-renderer-v1"] = "hero-draft-renderer-v1"
    caption_algorithm_version: Literal["hero-caption-v1"] = "hero-caption-v1"
    alignment_model: str = Field(min_length=1, max_length=80)
    whisperx_version: str = Field(min_length=1, max_length=40)
    alignment_config_sha256: str = Field(pattern=_SHA)
    hero_input_sha256: str = Field(pattern=_SHA)
    drafts: list[HeroDraftOutput] = Field(min_length=1)
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def set_is_consistent(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("Hero provenance must include source_asset_id")
        if self.provenance.inputs_sha256 != self.hero_input_sha256:
            raise ValueError("provenance input digest must be the Hero input digest")
        if self.profile.fingerprint() != self.profile_fingerprint:
            raise ValueError("Hero profile fingerprint does not match the stored profile")
        ids = [item.candidate_id for item in self.drafts]
        if len(set(ids)) != len(ids):
            raise ValueError("Hero candidate ids must be unique")
        ranks = [item.rank for item in self.drafts]
        if ranks != list(range(1, len(self.drafts) + 1)):
            raise ValueError("Hero ranks must be 1..n in list order")
        return self


class HeroCacheRecord(Versioned):
    """Sidecar for the current Hero draft set. ``created_at`` is not identity."""

    project_id: EntityId
    source_asset_id: EntityId
    hero_set_id: EntityId
    job_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    candidate_set_artifact_id: EntityId
    candidate_set_sha256: str = Field(pattern=_SHA)
    transcript_id: EntityId
    transcript_sha256: str = Field(pattern=_SHA)
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    analysis_proxy_sha256: str = Field(pattern=_SHA)
    asr_audio_sha256: str = Field(pattern=_SHA)
    rough_preview_artifact_id: EntityId
    rough_preview_set_id: EntityId
    rough_manifest_sha256: str = Field(pattern=_SHA)
    hero_input_sha256: str = Field(pattern=_SHA)
    profile_fingerprint: str = Field(pattern=_SHA)
    motion_library_version: Literal["motion-library-v1"] = "motion-library-v1"
    renderer_recipe_version: Literal["hero-draft-renderer-v1"] = "hero-draft-renderer-v1"
    caption_algorithm_version: Literal["hero-caption-v1"] = "hero-caption-v1"
    alignment_model: str = Field(min_length=1, max_length=80)
    whisperx_version: str = Field(min_length=1, max_length=40)
    alignment_config_sha256: str = Field(pattern=_SHA)
    manifest_sha256: str = Field(pattern=_SHA)
    manifest_size_bytes: int = Field(ge=1)
    rendered_count: int = Field(ge=1)
    validation_status: Literal["passed"]
    created_at: AwareDatetime


class HeroPlanDocument(Versioned):
    """The EditPlan plus the identities that made it eligible."""

    plan_id: EntityId
    edit_plan: EditPlan
    alignment_sha256: str = Field(pattern=_SHA)
    review_id: EntityId
    review_digest: str = Field(pattern=_SHA)
    rough_preview_artifact_id: EntityId
    motion_library_version: Literal["motion-library-v1"] = "motion-library-v1"
    profile_fingerprint: str = Field(pattern=_SHA)
    qa_requirements: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def plan_is_hero(self) -> Self:
        if self.edit_plan.stage != "hero":
            raise ValueError("a Hero plan document requires EditPlan.stage = hero")
        if self.edit_plan.broll_events or self.edit_plan.audio_events:
            raise ValueError("Hero draft v1 does not include B-roll, music, or sound effects")
        return self
