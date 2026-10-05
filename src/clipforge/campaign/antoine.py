"""Antoine Sallis campaign catalogue. Only two files are selected for this round."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from clipforge.schemas.campaign import CampaignPolicy, CampaignPolicyRule, CampaignSource

CAMPAIGN_ID = "antoine-sallis"
POLICY_ID = "antoine-sallis-guide"
GUIDE_NAME = "Antoine Sallis Clipping - Full Guide.docx"
EVALUATOR_VERSION = "campaign-policy-1"
_MAX_BYTES = 200_000_000


@dataclass(frozen=True, slots=True)
class DriveFile:
    """One Drive catalogue row. Selection is explicit."""

    source_id: str
    drive_id: str
    display_name: str
    size_bytes: int
    selected: bool

    @property
    def source_url(self) -> str:
        return f"https://drive.google.com/file/d/{self.drive_id}/view"

    @property
    def download_status(self) -> str:
        if not self.selected:
            return "not_selected_for_round_18"
        return "planned"


FILES: tuple[DriveFile, ...] = (
    DriveFile(
        source_id="src-before-famous",
        drive_id="12RKu2wuIgCccBpcwjhlbzEUM7lEt8vwN",
        display_name=(
            "Copy of YTDown.com_YouTube_Antoine-Sallis-Before-They-Were-Famous-B_"
            "Media_4-M7M422zek_001_1080p.mp4"
        ),
        size_bytes=180_882_018,
        selected=True,
    ),
    DriveFile(
        source_id="src-american-secret",
        drive_id="1IzZ6Klx6_y6stfhpa2q2Cf9qIK92eeim",
        display_name=(
            "Copy of YTDown.com_YouTube_The-Great-American-Secret-Antoine-Sallis_"
            "Media_Re-tozF_gHw_001_1080p.mp4"
        ),
        size_bytes=163_530_208,
        selected=True,
    ),
    DriveFile(
        source_id="src-og-cuicide",
        drive_id="1XNL03ZU4XPxeFxJMkiDeeLMnA-fqt9fu",
        display_name=(
            "Copy of YTDown.com_YouTube_OG-Cuicide-In-The-Building-with-Antoine-_"
            "Media_9UQaKdtK0bM_001_1080p.mp4"
        ),
        size_bytes=0,
        selected=False,
    ),
    DriveFile(
        source_id="src-sept-1",
        drive_id="1VFb8LWdMnsJYultiTSH74trSDFW635hi",
        display_name="Antoine - Sept 1.mp4",
        size_bytes=0,
        selected=False,
    ),
    DriveFile(
        source_id="src-sept-3",
        drive_id="1Cd7D2CR8_bMuGL9NcLDMnS2QXJ1eKxZC",
        display_name="Antoine Septemberr 3.mp4",
        size_bytes=0,
        selected=False,
    ),
)

# The three unselected rows are identified by display name. Their Drive ids were
# not used because those files must not be fetched. Placeholder ids stay local.


def selected_files() -> tuple[DriveFile, ...]:
    chosen = tuple(item for item in FILES if item.selected)
    for item in chosen:
        if item.size_bytes <= 0 or item.size_bytes >= _MAX_BYTES:
            raise RuntimeError("a selected source is not below 200 MB")
    return chosen


def file_by_id(source_id: str) -> DriveFile | None:
    for item in FILES:
        if item.source_id == source_id or item.drive_id == source_id:
            return item
    return None


def policy_rules() -> list[CampaignPolicyRule]:
    """Rules taken from the campaign guide. The newest-footage line is not guessed."""
    rows: tuple[tuple[str, str, str, str, str], ...] = (
        (
            "external-black-box",
            "No external black-box AI editors",
            "Opus Clips and other opaque editors are blocked. Clipforge is the editor.",
            "external_black_box_ai_tool",
            "blocked",
        ),
        (
            "native-editor",
            "Native Clipforge editing",
            "Trims, candidates, Remotion, typography, diagrams, transitions, and mixing are allowed.",
            "clipforge_native_editor",
            "allowed",
        ),
        (
            "native-captions",
            "Native captions need review",
            "Clipforge captions are allowed only when they are accurate and a person has reviewed them.",
            "clipforge_native_editor",
            "needs_operator_confirmation",
        ),
        (
            "unsafe-caption-effects",
            "No aura, glow, skull, or emoji",
            "Those effects are blocked on captions and overlays.",
            "clipforge_native_editor",
            "blocked",
        ),
        (
            "human-asset",
            "Human supplied assets",
            "A supplied asset is allowed only with campaign-guide and operator rights evidence.",
            "human_supplied_asset",
            "rights_unverified",
        ),
        (
            "voice-narration",
            "Optional narration",
            "VoiceStudio runs only after an explicit operator decision for that clip.",
            "voice_narration_provider",
            "needs_operator_confirmation",
        ),
        (
            "outside-media",
            "No outside footage",
            "Stock video, outside audio, and unrelated clips are blocked for this campaign.",
            "human_supplied_asset",
            "blocked",
        ),
        (
            "newest-footage",
            "Newest footage priority",
            "The guide is ambiguous about newest-footage priority and when the linked folder is used.",
            "clipforge_native_editor",
            "needs_operator_clarification",
        ),
        (
            "english-default",
            "English is the campaign language",
            "A non-English output needs an explicit policy extension.",
            "clipforge_native_editor",
            "needs_operator_confirmation",
        ),
    )
    return [
        CampaignPolicyRule(
            rule_id=rule_id,
            name=name,
            description=description,
            implementation_mode=mode,  # type: ignore[arg-type]
            outcome=outcome,  # type: ignore[arg-type]
        )
        for rule_id, name, description, mode, outcome in rows
    ]


def policy_sha256() -> str:
    body = json.dumps(
        [rule.model_dump(mode="json") for rule in policy_rules()],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def antoine_policy() -> CampaignPolicy:
    return CampaignPolicy(
        policy_id=POLICY_ID,
        campaign_id=CAMPAIGN_ID,
        policy_sha256=policy_sha256(),
        source_name=GUIDE_NAME,
        rules=policy_rules(),
        allowed_platforms=["tiktok", "instagram_reels", "facebook_reels", "youtube_shorts"],
        default_language="en-US",
    )


def inventory_sources() -> list[CampaignSource]:
    rows: list[CampaignSource] = []
    for item in FILES:
        rights = "rights_unverified"
        priority = "round_18_selected" if item.selected else "not_selected_for_round_18"
        rows.append(
            CampaignSource(
                source_id=item.source_id,
                campaign_id=CAMPAIGN_ID,
                provider="google_drive",
                provider_file_id=item.drive_id,
                display_name=item.display_name,
                source_url=item.source_url,
                mime_type="video/mp4",
                size_bytes=item.size_bytes,
                priority=priority,
                download_status=item.download_status,  # type: ignore[arg-type]
                rights_state=rights,  # type: ignore[arg-type]
            )
        )
    return rows
