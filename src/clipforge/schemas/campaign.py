"""Campaign policy, source acquisition, and operator actions.

Stored records may name a public https URL. They do not store credentials.
"""

from __future__ import annotations

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"
_SECRET = ("bearer ", "password=", "token=", "api_key", "authorization:", "cookie=", "secret=")
ImplementationMode = Literal[
    "external_black_box_ai_tool",
    "clipforge_native_editor",
    "human_supplied_asset",
    "voice_narration_provider",
]
PolicyOutcome = Literal[
    "allowed",
    "blocked",
    "needs_operator_confirmation",
    "needs_policy_clarification",
    "needs_operator_clarification",
    "rights_unverified",
    "unsupported_language",
    "unsupported_feature",
]
DownloadStatus = Literal[
    "not_selected_for_round_18",
    "planned",
    "provider_unavailable",
    "acquired",
    "manual_download_required",
    "rejected",
]


class QuranCanonicalSource(Versioned):
    provider: Literal["Quran.com"]
    url: str = Field(min_length=1, max_length=300)
    surah: int = Field(ge=1, le=114)
    ayah_start: int = Field(ge=1)
    ayah_end: int = Field(ge=1)
    text_uthmani: list[str] = Field(min_length=1)
    snapshot_relative_path: str = ""
    snapshot_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    snapshot_url: str = ""

    @model_validator(mode="after")
    def range_is_ordered(self) -> Self:
        if self.ayah_end < self.ayah_start:
            raise ValueError("Quran ayah range must be ordered")
        if len(self.text_uthmani) != self.ayah_end - self.ayah_start + 1:
            raise ValueError("Quran canonical text must contain exactly one entry per declared ayah")
        for url in (self.url, self.snapshot_url):
            if not url:
                continue
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.hostname not in {"quran.com", "api.quran.com"}:
                raise ValueError("Quran canonical evidence must use an official HTTPS Quran.com source")
            if parsed.username or parsed.password or parsed.port not in {None, 443}:
                raise ValueError("Quran canonical evidence URL cannot contain credentials or a custom port")
        if any((self.snapshot_relative_path, self.snapshot_sha256, self.snapshot_url)) and not all(
            (self.snapshot_relative_path, self.snapshot_sha256, self.snapshot_url)
        ):
            raise ValueError("Quran snapshot path, hash, and URL must be supplied together")
        if self.snapshot_relative_path:
            _relative(self.snapshot_relative_path)
        return self


class QuranAudioMapping(Versioned):
    source_start_us: Microseconds
    source_end_us: Microseconds
    ayah: int = Field(ge=1)

    @model_validator(mode="after")
    def interval_is_positive(self) -> Self:
        if self.source_end_us <= self.source_start_us:
            raise ValueError("Quran audio mapping interval must be positive")
        return self


class QuranVerificationPolicy(Versioned):
    quran_text: Literal["canonical_uthmani_only"]
    timing: Literal["forced_alignment_required"]
    pronunciation_status: Literal[
        "human_review_required",
        "canonical_match_verified",
        "human_reviewed",
    ]
    unverified_words_must_not_be_colored_green: Literal[True] = True
    incorrect_words_require_human_evidence: Literal[True] = True
    font_identity: Literal["amiri-quran-local-v1"]
    font_relative_path: str = Field(min_length=1, max_length=300)
    font_sha256: str = Field(pattern=_SHA)


class TarteelDisplayCorrection(Versioned):
    """Reviewed source-text replacement for one forced word interval."""

    source_word_id: EntityId
    display_text: str = Field(min_length=1, max_length=120)

    @field_validator("display_text")
    @classmethod
    def display_text_is_one_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("Tarteel display correction must be one line")
        return value


class TarteelArabicCorrection(Versioned):
    """A reviewed spelling correction that keeps the observed source word."""

    correction_id: EntityId
    source_word_id: EntityId
    source_window_us: tuple[Microseconds, Microseconds]
    original_text: str = Field(min_length=1, max_length=200)
    corrected_text: str = Field(min_length=1, max_length=200)
    locale: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    evidence_kind: Literal["listening_context", "campaign_subtitle", "canonical_quran"]
    reviewer: str = Field(min_length=1, max_length=120)
    review_note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def correction_is_bounded(self) -> Self:
        if self.source_window_us[1] <= self.source_window_us[0]:
            raise ValueError("Arabic correction source window must be positive")
        if "\n" in self.corrected_text or "\r" in self.corrected_text:
            raise ValueError("Arabic correction must stay one line")
        return self


class TarteelArabicCorrectionDocument(Versioned):
    """Immutable source-bound ordinary-Arabic correction evidence."""

    correction_set_id: EntityId
    campaign: Literal["tarteel"]
    source_asset_id: EntityId
    candidate_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    raw_asr_sha256: str = Field(pattern=_SHA)
    transcript_sha256: str = Field(pattern=_SHA)
    locale: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    corrections: list[TarteelArabicCorrection] = Field(default_factory=list)
    reviewer: str = Field(min_length=1, max_length=120)
    reviewer_role: Literal["codex_operator", "human_reviewer"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    reviewed_at: AwareDatetime
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def is_source_bound(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("Arabic correction provenance must include its source")
        ids = [item.correction_id for item in self.corrections]
        if len(ids) != len(set(ids)):
            raise ValueError("Arabic correction ids must be unique")
        return self


class TarteelSpeechInterval(Versioned):
    """Reviewed inventory of audible source material for caption coverage."""

    span_id: EntityId
    source_start_us: Microseconds
    source_end_us: Microseconds
    kind: Literal["dialogue", "recitation", "reaction", "nasheed", "silence", "uncertain"]
    caption_decision: Literal["captioned", "reviewed_excluded"]
    observed_text: str = ""
    review_note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def interval_is_reviewed(self) -> Self:
        if self.source_end_us <= self.source_start_us:
            raise ValueError("speech inventory interval must be positive")
        if self.caption_decision == "reviewed_excluded" and not self.review_note.strip():
            raise ValueError("excluded speech requires a review note")
        if (
            self.kind in {"dialogue", "recitation", "reaction", "nasheed"}
            and self.caption_decision == "captioned"
            and not self.observed_text.strip()
        ):
            raise ValueError("captioned audible speech requires observed text")
        return self


class SpeechVerification(Versioned):
    """Codex evidence for text that must not be guessed."""

    verification_id: EntityId
    subject_kind: Literal["quran", "quotation", "proper_noun", "number", "factual_claim"]
    source_url: str = Field(default="", max_length=500)
    snapshot_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    note: str = Field(min_length=1, max_length=500)
    status: Literal["verified"] = "verified"

    @model_validator(mode="after")
    def has_reliable_source(self) -> Self:
        if not self.source_url and not self.snapshot_sha256:
            raise ValueError("sensitive text verification requires a source URL or hashed snapshot")
        if self.source_url and not (
            self.source_url.startswith("https://") or self.source_url.startswith("http://")
        ):
            raise ValueError("sensitive text verification URL must be http(s)")
        return self


class TarteelSpeechReview(Versioned):
    """Codex-reviewed source speech inventory used to upgrade caption coverage.

    The historical class name is retained for stored Tarteel documents. The
    same source-bound contract is also valid for generic campaigns when
    ``campaign="generic"`` and ``reviewer_role="codex_operator"``.
    """

    review_id: EntityId
    campaign: Literal["tarteel", "generic"]
    source_asset_id: EntityId
    candidate_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    raw_asr_sha256: str = Field(pattern=_SHA)
    transcript_sha256: str = Field(pattern=_SHA)
    locale: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    intervals: list[TarteelSpeechInterval] = Field(min_length=1)
    verifications: list[SpeechVerification] = Field(default_factory=list, max_length=32)
    reviewer: str = Field(min_length=1, max_length=120)
    reviewer_role: Literal["codex_operator", "human_reviewer"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    reviewed_at: AwareDatetime
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def intervals_are_ordered(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("speech review provenance must include its source")
        ids = [item.span_id for item in self.intervals]
        if len(ids) != len(set(ids)):
            raise ValueError("speech review span ids must be unique")
        previous = -1
        for item in sorted(self.intervals, key=lambda value: value.source_start_us):
            if item.source_start_us < previous:
                raise ValueError("speech review intervals must not overlap")
            previous = item.source_end_us
        return self


class QuranCaptionReview(Versioned):
    review_kind: Literal["source_grounded_quran_caption"]
    campaign: Literal["tarteel"]
    source_asset_id: EntityId
    candidate_id: EntityId
    source_window_us: tuple[Microseconds, Microseconds]
    source_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    transcript_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    display_evidence_relative_path: str = ""
    display_evidence_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    canonical_source: QuranCanonicalSource
    source_audio_mapping: list[QuranAudioMapping] = Field(min_length=1)
    display_corrections: list[TarteelDisplayCorrection] = Field(default_factory=list)
    verification_policy: QuranVerificationPolicy
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def window_is_positive(self) -> Self:
        if self.source_window_us[1] <= self.source_window_us[0]:
            raise ValueError("Quran review source window must be positive")
        if any((self.display_evidence_relative_path, self.display_evidence_sha256)) and not all(
            (self.display_evidence_relative_path, self.display_evidence_sha256)
        ):
            raise ValueError("display evidence path and hash must be supplied together")
        if self.display_evidence_relative_path:
            _relative(self.display_evidence_relative_path)
        previous_end = self.source_window_us[0]
        for mapping in self.source_audio_mapping:
            if not self.canonical_source.ayah_start <= mapping.ayah <= self.canonical_source.ayah_end:
                raise ValueError("Quran audio mapping names an ayah outside the canonical range")
            if mapping.source_start_us < previous_end or mapping.source_end_us > self.source_window_us[1]:
                raise ValueError(
                    "Quran audio mappings must be ordered, non-overlapping, and inside the source window"
                )
            previous_end = mapping.source_end_us
        return self


def _plain(value: str, *, label: str, allow_https: bool = False) -> str:
    stripped = value.strip()
    if stripped != value or not stripped:
        raise ValueError(f"{label} must not be blank or padded")
    lowered = stripped.lower()
    if any(token in lowered for token in _SECRET) or "<" in stripped or ">" in stripped:
        raise ValueError(f"{label} contains markup or a secret-like token")
    if "\\" in stripped or stripped.startswith("/") or ".." in stripped.split("/"):
        raise ValueError(f"{label} contains a path")
    if "://" in lowered and not (allow_https and lowered.startswith("https://")):
        raise ValueError(f"{label} contains a URL")
    return stripped


def _relative(value: str) -> str:
    stripped = value.strip()
    if stripped != value or not stripped:
        raise ValueError("relative path must not be blank or padded")
    if "\\" in stripped or stripped.startswith("/") or ".." in stripped.split("/"):
        raise ValueError("relative path escapes the work root")
    lowered = stripped.lower()
    if "://" in lowered or any(token in lowered for token in _SECRET):
        raise ValueError("relative path contains a URL or a secret")
    return stripped


class Campaign(Versioned):
    """One operator campaign. A URL is a public page, not a credential."""

    campaign_id: EntityId
    title: str = Field(min_length=1, max_length=200)
    campaign_url: str | None = Field(default=None, max_length=300)
    policy_id: EntityId
    policy_sha256: str = Field(pattern=_SHA)
    default_language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")

    @field_validator("title")
    @classmethod
    def title_is_plain(cls, value: str) -> str:
        return _plain(value, label="campaign title")

    @field_validator("campaign_url")
    @classmethod
    def url_is_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="campaign url", allow_https=True)


class CampaignOverlaySpec(Versioned):
    """Source-bound branding required by a campaign delivery profile.

    The renderer receives safe staging names only. Asset ids and hashes stay
    in the typed plan/catalogue, so an overlay cannot be swapped after QA.
    Tarteel CTA clips are green-screen files; ``chroma_key_v1`` records that
    the green background was removed before Remotion compositing.
    """

    campaign_id: Literal["tarteel"] = "tarteel"
    cta_asset_id: EntityId
    cta_asset_sha256: str = Field(pattern=_SHA)
    cta_asset_name: str = Field(min_length=1, max_length=80)
    cta_background_removal: Literal["chroma_key_v1"] = "chroma_key_v1"
    # Production uses the original animated CTA as an alpha video.  The PNG
    # sequence value remains readable for old review sidecars, but is not
    # accepted by the Tarteel delivery policy.
    cta_render_mode: Literal["alpha_video_v1", "alpha_png_sequence_v1"] = "alpha_video_v1"
    cta_frame_prefix: str | None = Field(default=None, min_length=1, max_length=64)
    cta_frame_count: int | None = Field(default=None, ge=1, le=600)
    cta_frame_rate: Literal[30] = 30
    # New campaign renders place both brand layers inside the contained source
    # picture. The old value remains readable for immutable pre-checkpoint
    # artifacts, but policy and new staging require the foreground space.
    cta_position: Literal["foreground_attention_v1", "top_left_brand_rail_v1"] = "foreground_attention_v1"
    overlay_coordinate_space: Literal["foreground_v1", "canvas_v1"] = "foreground_v1"
    cta_clearance: Literal["faces_and_captions_clear_v1"] = "faces_and_captions_clear_v1"
    # These coordinates are relative to the original foreground picture, not
    # the blurred portrait canvas. Permille values keep the placement
    # deterministic across review and delivery resolutions.
    cta_left_permille: int = Field(default=80, ge=0, le=1000)
    cta_top_permille: int = Field(default=360, ge=0, le=1000)
    # This is intentionally capped. The campaign CTA is a small brand cue,
    # never a foreground card over a child or a caption.
    # New renders use a measured ratio from the source-native CTA. The wider
    # legacy range remains readable for immutable historical artifacts.
    cta_width_permille: int = Field(default=240, ge=80, le=600)
    cta_start_us: int = Field(ge=0)
    cta_end_us: int = Field(gt=0)
    watermark_asset_id: EntityId
    watermark_asset_sha256: str = Field(pattern=_SHA)
    watermark_asset_name: str = Field(min_length=1, max_length=80)
    watermark_mode: Literal["alpha_v1"] = "alpha_v1"
    watermark_position: Literal["foreground_top_right_v1", "top_right"] = "foreground_top_right_v1"
    watermark_visibility: Literal["overlay_required_v1", "source_visible_v1"] = "overlay_required_v1"
    watermark_width_permille: int = Field(default=55, ge=24, le=280)
    sizing_method: Literal["source_frame_scan_v1", "legacy_fixed_v1"] = "legacy_fixed_v1"
    sizing_measurement_sha256: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    first_post_caption_line: Literal["اشترك في قناة ترتيل على اليوتيوب: @tarteelarabic"] = (
        "اشترك في قناة ترتيل على اليوتيوب: @tarteelarabic"
    )

    @model_validator(mode="after")
    def interval_and_names_are_safe(self) -> Self:
        if self.cta_end_us <= self.cta_start_us:
            raise ValueError("campaign CTA interval must be positive")
        names = [("CTA", self.cta_asset_name), ("watermark", self.watermark_asset_name)]
        if self.cta_render_mode == "alpha_png_sequence_v1":
            if self.cta_frame_prefix is None or self.cta_frame_count is None:
                raise ValueError("PNG CTA overlays require a frame prefix and count")
            names.append(("CTA frame prefix", self.cta_frame_prefix))
        elif self.cta_frame_prefix is not None or self.cta_frame_count is not None:
            raise ValueError("alpha video CTA overlays must not declare PNG frames")
        if self.cta_render_mode == "alpha_video_v1" and not self.cta_asset_name.lower().endswith(
            (".mov", ".webm")
        ):
            raise ValueError("alpha video CTA must use a transparent video staging filename")
        if self.cta_clearance != "faces_and_captions_clear_v1":
            raise ValueError("Tarteel CTA must declare face and caption clearance")
        if self.sizing_method == "source_frame_scan_v1" and not self.sizing_measurement_sha256:
            raise ValueError("source-measured campaign overlays require a measurement digest")
        if self.overlay_coordinate_space != "foreground_v1" and self.cta_position == "foreground_attention_v1":
            raise ValueError("foreground CTA placement requires foreground coordinate space")
        for label, name in names:
            if (
                name != name.strip()
                or "/" in name
                or "\\" in name
                or ".." in name
                or not all(character.isalnum() or character in ".-_" for character in name)
            ):
                raise ValueError(f"campaign {label} asset name must be a safe staging filename")
        return self


class OverlayExclusionRegion(Versioned):
    """One transformed region that a campaign overlay must avoid."""

    kind: Literal[
        "face",
        "child_body",
        "tablet",
        "caption",
        "context_line",
        "source_logo",
        "watermark",
        "platform_rail",
    ]
    status: Literal["present", "absent_reviewed", "unknown"]
    left: int | None = Field(default=None, ge=0, le=1080)
    top: int | None = Field(default=None, ge=0, le=1920)
    width: int | None = Field(default=None, ge=1, le=1080)
    height: int | None = Field(default=None, ge=1, le=1920)
    annotation_id: EntityId | None = None

    @model_validator(mode="after")
    def bounds_match_status(self) -> Self:
        bounds = (self.left, self.top, self.width, self.height)
        if self.status == "present":
            if any(value is None for value in bounds):
                raise ValueError("present overlay exclusion requires output bounds")
            assert self.left is not None and self.top is not None
            assert self.width is not None and self.height is not None
            if self.left + self.width > 1080 or self.top + self.height > 1920:
                raise ValueError("overlay exclusion extends past the portrait output")
        elif any(value is not None for value in bounds):
            raise ValueError("absent or unknown overlay exclusion cannot declare bounds")
        if self.status == "unknown" and self.annotation_id is not None:
            raise ValueError("unknown overlay exclusion cannot claim an annotation")
        return self


class OverlayExclusionSample(Versioned):
    """One decoded or reviewed sample over the complete CTA animation."""

    sample_id: EntityId
    phase: Literal["entrance", "hold", "exit", "maximum_extent"]
    output_frame_index: int = Field(ge=0)
    output_time_us: Microseconds
    sample_frame_sha256: str = Field(pattern=_SHA)
    sample_frame_relative_path: str = Field(default="", max_length=512)
    cta_left: int = Field(ge=0, le=1080)
    cta_top: int = Field(ge=0, le=1920)
    cta_width: int = Field(ge=1, le=1080)
    cta_height: int = Field(ge=1, le=1920)
    exclusions: list[OverlayExclusionRegion] = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def sample_is_complete(self) -> Self:
        if self.cta_left + self.cta_width > 1080 or self.cta_top + self.cta_height > 1920:
            raise ValueError("CTA sample extends past the portrait output")
        kinds = [item.kind for item in self.exclusions]
        required = {
            "face",
            "child_body",
            "tablet",
            "caption",
            "context_line",
            "source_logo",
            "watermark",
            "platform_rail",
        }
        if set(kinds) != required:
            raise ValueError("overlay exclusion sample must account for every required region kind")
        for kind in required:
            regions = [region for region in self.exclusions if region.kind == kind]
            if len(regions) > 1:
                ids = [region.annotation_id for region in regions]
                if (
                    any(region.status != "present" for region in regions)
                    or None in ids
                    or len(ids) != len(set(ids))
                ):
                    raise ValueError("multiple exclusion regions need unique present annotations")
        if self.sample_frame_relative_path:
            _relative(self.sample_frame_relative_path)
        return self


class OverlayExclusionEvidence(Versioned):
    """Source-bound clearance proof for a moving campaign overlay."""

    evidence_id: EntityId
    campaign: Literal["tarteel"] = "tarteel"
    source_asset_id: EntityId
    candidate_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    time_map_sha256: str = Field(pattern=_SHA)
    overlay_spec_sha256: str = Field(pattern=_SHA)
    transform_sha256: str = Field(pattern=_SHA)
    cta_start_us: Microseconds
    cta_end_us: Microseconds
    samples: list[OverlayExclusionSample] = Field(min_length=4, max_length=32)
    decision: Literal["clear", "blocked"]
    reviewer: str = Field(min_length=1, max_length=120)
    reviewed_at: AwareDatetime
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def clearance_is_safe(self) -> Self:
        if self.cta_end_us <= self.cta_start_us:
            raise ValueError("overlay exclusion CTA interval must be positive")
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("overlay exclusion provenance must include its source")
        phases = [sample.phase for sample in self.samples]
        if set(phases) != {"entrance", "hold", "exit", "maximum_extent"}:
            raise ValueError("overlay exclusion evidence needs entrance, hold, exit, and maximum samples")
        if len({sample.sample_id for sample in self.samples}) != len(self.samples):
            raise ValueError("overlay exclusion sample ids must be unique")
        for sample in self.samples:
            if not self.cta_start_us <= sample.output_time_us < self.cta_end_us:
                raise ValueError("overlay exclusion sample lies outside the CTA interval")
            if self.decision == "clear":
                if any(region.status == "unknown" for region in sample.exclusions):
                    raise ValueError("clear overlay exclusion evidence cannot contain unknown regions")
                cta = (
                    sample.cta_left,
                    sample.cta_top,
                    sample.cta_width,
                    sample.cta_height,
                )
                for region in sample.exclusions:
                    if region.status != "present":
                        continue
                    assert region.left is not None and region.top is not None
                    assert region.width is not None and region.height is not None
                    if _rectangles_overlap(cta, (region.left, region.top, region.width, region.height)):
                        raise ValueError(f"clear overlay exclusion intersects {region.kind}")
        return self


def _rectangles_overlap(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    left_x, left_y, left_width, left_height = left
    right_x, right_y, right_width, right_height = right
    return max(left_x, right_x) < min(left_x + left_width, right_x + right_width) and max(
        left_y, right_y
    ) < min(left_y + left_height, right_y + right_height)


class CampaignPolicyRule(Versioned):
    """One hard rule. Ambiguous rules ask the operator instead of guessing."""

    rule_id: EntityId
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    implementation_mode: ImplementationMode
    outcome: PolicyOutcome

    @field_validator("name", "description")
    @classmethod
    def text_is_plain(cls, value: str) -> str:
        return _plain(value, label="policy rule")


class CampaignPolicy(Versioned):
    """The hash-bound policy snapshot for one campaign."""

    policy_id: EntityId
    campaign_id: EntityId
    policy_sha256: str = Field(pattern=_SHA)
    source_name: str = Field(min_length=1, max_length=200)
    rules: list[CampaignPolicyRule] = Field(min_length=1)
    allowed_platforms: list[str] = Field(min_length=1)
    default_language: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")

    @field_validator("source_name")
    @classmethod
    def source_name_is_plain(cls, value: str) -> str:
        return _plain(value, label="policy source")

    @field_validator("allowed_platforms")
    @classmethod
    def platforms_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(item, label="platform") for item in values]

    @model_validator(mode="after")
    def hash_matches_rules(self) -> Self:
        import hashlib
        import json

        body = json.dumps(
            [rule.model_dump(mode="json") for rule in self.rules],
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if digest != self.policy_sha256:
            raise ValueError("policy hash does not match the rules")
        return self


class CampaignSource(Versioned):
    """One catalogued file. Folder membership is not rights evidence."""

    source_id: EntityId
    campaign_id: EntityId
    provider: str = Field(min_length=1, max_length=40)
    provider_file_id: EntityId
    display_name: str = Field(min_length=1, max_length=300)
    source_url: str = Field(min_length=1, max_length=300)
    mime_type: str = Field(min_length=1, max_length=80)
    size_bytes: int = Field(ge=0)
    priority: str = Field(min_length=1, max_length=80)
    download_status: DownloadStatus
    rights_state: PolicyOutcome

    @field_validator("provider", "display_name", "mime_type", "priority")
    @classmethod
    def labels_are_plain(cls, value: str) -> str:
        return _plain(value, label="campaign source")

    @field_validator("source_url")
    @classmethod
    def source_url_is_https(cls, value: str) -> str:
        return _plain(value, label="source url", allow_https=True)


class SourceRightsEvidence(Versioned):
    """Why a source may be edited. A Drive folder listing is not enough."""

    evidence_id: EntityId
    campaign_id: EntityId
    source_id: EntityId
    evidence_kind: Literal["campaign_guide", "operator_authorization"]
    statement: str = Field(min_length=1, max_length=2000)
    recorded_by: str = Field(min_length=1, max_length=80)

    @field_validator("statement", "recorded_by")
    @classmethod
    def evidence_is_plain(cls, value: str) -> str:
        return _plain(value, label="rights evidence")


class SourceAcquisition(Versioned):
    """One explicit acquisition. A plan is not a download."""

    acquisition_id: EntityId
    campaign_id: EntityId
    source_id: EntityId
    provider: str = Field(min_length=1, max_length=40)
    download_status: DownloadStatus
    local_relative_path: str | None = None
    sha256: str | None = Field(default=None, pattern=_SHA)
    size_bytes: int | None = Field(default=None, ge=0)
    probe_facts: dict[str, str | int | None] | None = None
    acquired_at: AwareDatetime | None = None
    operator_confirmation: bool = False
    error_code: str = Field(default="none", max_length=80)

    @field_validator("provider", "error_code")
    @classmethod
    def codes_are_plain(cls, value: str) -> str:
        return _plain(value, label="acquisition")

    @field_validator("local_relative_path")
    @classmethod
    def path_is_relative(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _relative(value)


class OperatorAction(Versioned):
    """A recorded operator step. Secrets are not fields."""

    action_id: EntityId
    campaign_id: EntityId
    action: str = Field(min_length=1, max_length=80)
    result: str = Field(min_length=1, max_length=80)
    error_code: str = Field(default="none", max_length=80)
    selected_source_ids: list[EntityId] = Field(default_factory=list)
    created_at: AwareDatetime

    @field_validator("action", "result", "error_code")
    @classmethod
    def action_is_plain(cls, value: str) -> str:
        return _plain(value, label="operator action")


class PolicyDecision(Versioned):
    """One append-only decision bound to a policy hash."""

    decision_id: EntityId
    campaign_id: EntityId
    policy_id: EntityId
    policy_sha256: str = Field(pattern=_SHA)
    rule_id: EntityId
    decision: PolicyOutcome
    implementation_mode: ImplementationMode
    evidence_ids: list[EntityId] = Field(default_factory=list)
    evaluator_version: str = Field(min_length=1, max_length=40)
    human_confirmation: Literal["unconfirmed", "confirmed", "not_required"]
    created_at: AwareDatetime

    @field_validator("evaluator_version")
    @classmethod
    def version_is_plain(cls, value: str) -> str:
        return _plain(value, label="evaluator")


class SourceInventoryManifest(Versioned):
    """The catalogue for one campaign. Unselected files stay unselected."""

    manifest_id: EntityId
    campaign_id: EntityId
    policy_sha256: str = Field(pattern=_SHA)
    sources: list[CampaignSource] = Field(min_length=1)
    acquisitions: list[SourceAcquisition] = Field(default_factory=list)
    rights: list[SourceRightsEvidence] = Field(default_factory=list)
    decisions: list[PolicyDecision] = Field(default_factory=list)
    created_at: AwareDatetime


class ProbeSummary(Versioned):
    """Public ffprobe facts. Paths and raw command lines are not stored."""

    sha256: str = Field(pattern=_SHA)
    size_bytes: int = Field(ge=1)
    duration_us: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    video_codec: str = Field(min_length=1, max_length=40)
    audio_codec: str | None = Field(default=None, max_length=40)
    ffprobe_version: str = Field(min_length=1, max_length=80)

    @field_validator("video_codec", "audio_codec", "ffprobe_version")
    @classmethod
    def probe_text_is_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="probe")
