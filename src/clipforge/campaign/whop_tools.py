"""Checked tool map for Whop discovery. Official names stay empty until tools/list proves them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clipforge.campaign.providers import CampaignError

_MUTATING = frozenset(
    {
        "create",
        "update",
        "delete",
        "join",
        "apply",
        "submit",
        "upload",
        "message",
        "charge",
        "pay",
        "purchase",
        "checkout",
    }
)


def packaged_tool_map_path() -> Path:
    return Path(__file__).resolve().parents[3] / "docs" / "operations" / "assets" / "whop" / "tool-map.json"


def load_tool_map(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or packaged_tool_map_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CampaignError("whop tool map could not be read", code="invalid_document") from exc
    if not isinstance(payload, dict):
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    rows = payload.get("mappings")
    if not isinstance(rows, list):
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    return [item for item in rows if isinstance(item, dict)]


def select_mapped_tool(
    tools: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    *,
    allow_fixture: bool = False,
) -> str:
    """Return one exact mapped name. Substring matches are not accepted."""
    by_name = {}
    for tool in tools:
        name = tool.get("name")
        if isinstance(name, str):
            by_name[name] = tool
    for mapping in mappings:
        name = mapping.get("tool_name")
        if not isinstance(name, str) or name not in by_name:
            continue
        if _mutating_token(name):
            continue
        if mapping.get("read_only") is not True or mapping.get("destructive") is True:
            continue
        verification = mapping.get("verification")
        if verification == "fixture_only" and not allow_fixture:
            continue
        if verification not in {"fixture_only", "verified"}:
            continue
        annotations = by_name[name].get("annotations")
        if isinstance(annotations, dict) and annotations.get("destructiveHint") is True:
            continue
        if verification == "verified" and (
            not isinstance(annotations, dict) or annotations.get("readOnlyHint") is not True
        ):
            continue
        return name
    raise CampaignError("unsupported_tool", code="unsupported_tool")


def _mutating_token(name: str) -> bool:
    tokens = [part for part in name.lower().replace("-", "_").split("_") if part]
    return any(token in _MUTATING for token in tokens)
