"""Deterministic campaign checks. Ambiguity stays unresolved."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from clipforge.campaign.antoine import antoine_policy
from clipforge.schemas.campaign import CampaignPolicy, ImplementationMode, PolicyOutcome

_BLOCKED_EFFECTS = ("aura", "glow", "skull", "emoji")
_BLACK_BOX = ("opus clip", "opus clips", "vizard", "black-box", "black box")
_MISLEADING = ("guaranteed income", "get rich quick", "risk free", "risk-free")


@dataclass(frozen=True, slots=True)
class ModeDecision:
    mode: ImplementationMode
    decision: PolicyOutcome
    rule_id: str


def evaluate_mode(
    mode: ImplementationMode,
    *,
    rights_evidenced: bool = False,
    operator_confirmed: bool = False,
    external_media: bool = False,
    policy: CampaignPolicy | None = None,
) -> ModeDecision:
    """Apply the campaign's implementation-mode rule. This does not approve a Hero."""
    active = policy or antoine_policy()
    rule = next(item for item in active.rules if item.implementation_mode == mode)
    if mode == "external_black_box_ai_tool":
        return ModeDecision(mode, "blocked", rule.rule_id)
    if mode == "clipforge_native_editor":
        return ModeDecision(mode, "allowed", "native-editor")
    if mode == "human_supplied_asset":
        if external_media:
            return ModeDecision(mode, "blocked", "outside-media")
        if not rights_evidenced:
            return ModeDecision(mode, "rights_unverified", "human-asset")
        return ModeDecision(mode, "allowed", "human-asset")
    if operator_confirmed:
        return ModeDecision(mode, "allowed", "voice-narration")
    return ModeDecision(mode, "needs_operator_confirmation", "voice-narration")


def footage_priority(policy: CampaignPolicy | None = None) -> PolicyOutcome:
    """The guide does not say when the linked folder replaces newest footage."""
    active = policy or antoine_policy()
    rule = next(item for item in active.rules if item.rule_id == "newest-footage")
    return rule.outcome


def language_decision(language: str, *, policy: CampaignPolicy | None = None) -> PolicyOutcome:
    active = policy or antoine_policy()
    if language == active.default_language or language.startswith("en-") or language == "en":
        return "allowed"
    known = {"fr-FR", "es-ES", "de-DE", "ar", "ja", "en-GB", active.default_language}
    if language not in known and not _language_shape(language):
        return "unsupported_language"
    return "needs_operator_confirmation"


def _language_shape(language: str) -> bool:
    parts = language.split("-")
    if len(parts) == 1:
        return len(parts[0]) == 2 and parts[0].isalpha() and parts[0].islower()
    if len(parts) != 2:
        return False
    return len(parts[0]) == 2 and parts[0].isalpha() and len(parts[1]) == 2 and parts[1].isalpha()


def tool_name_decision(name: str) -> PolicyOutcome:
    lowered = name.lower()
    if any(token in lowered for token in _BLACK_BOX):
        return "blocked"
    if "clipforge" in lowered:
        return "allowed"
    return "needs_operator_confirmation"


def caption_decision(
    text: str,
    *,
    effects: tuple[str, ...] = (),
    reviewed: bool = False,
) -> PolicyOutcome:
    """Native captions are allowed only when the text is clean and a person reviewed it."""
    lowered = text.lower()
    if any(token in lowered for token in _MISLEADING):
        return "blocked"
    if any(effect.lower() in _BLOCKED_EFFECTS for effect in effects):
        return "blocked"
    if _has_emoji(text) or any(token in lowered for token in ("aura", "glow", "skull")):
        return "blocked"
    if "@antoinesallis" not in lowered or "antoine sallis" not in lowered:
        return "blocked"
    if "#antoinesallis" not in lowered:
        return "blocked"
    tags = [token for token in text.split() if token.startswith("#")]
    if not 3 <= len(tags) <= 5:
        return "needs_operator_confirmation"
    if len(text) > 100:
        return "needs_operator_confirmation"
    if not reviewed:
        return "needs_operator_confirmation"
    return "allowed"


def _has_emoji(text: str) -> bool:
    return any(unicodedata.category(character) in {"So", "Sk"} for character in text)
