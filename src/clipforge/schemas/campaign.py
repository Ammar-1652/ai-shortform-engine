"""Campaign policy, source acquisition, and operator actions.

Stored records may name a public https URL. They do not store credentials.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.common import EntityId, Versioned

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
    cta_render_mode: Literal["alpha_png_sequence_v1"] = "alpha_png_sequence_v1"
    cta_frame_prefix: str = Field(min_length=1, max_length=64)
    cta_frame_count: int = Field(ge=1, le=600)
    cta_frame_rate: Literal[30] = 30
    cta_start_us: int = Field(ge=0)
    cta_end_us: int = Field(gt=0)
    watermark_asset_id: EntityId
    watermark_asset_sha256: str = Field(pattern=_SHA)
    watermark_asset_name: str = Field(min_length=1, max_length=80)
    watermark_mode: Literal["alpha_v1"] = "alpha_v1"
    watermark_position: Literal["top_right"] = "top_right"
    watermark_width_permille: int = Field(default=170, ge=80, le=280)
    first_post_caption_line: Literal["اشترك في قناة ترتيل على اليوتيوب: @tarteelarabic"] = (
        "اشترك في قناة ترتيل على اليوتيوب: @tarteelarabic"
    )

    @model_validator(mode="after")
    def interval_and_names_are_safe(self) -> Self:
        if self.cta_end_us <= self.cta_start_us:
            raise ValueError("campaign CTA interval must be positive")
        for label, name in (
            ("CTA", self.cta_asset_name),
            ("CTA frame prefix", self.cta_frame_prefix),
            ("watermark", self.watermark_asset_name),
        ):
            if (
                name != name.strip()
                or "/" in name
                or "\\" in name
                or ".." in name
                or not all(character.isalnum() or character in ".-_" for character in name)
            ):
                raise ValueError(f"campaign {label} asset name must be a safe staging filename")
        return self


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
