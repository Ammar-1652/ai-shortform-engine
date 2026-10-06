"""Checked tool map for Whop discovery. Official names stay empty until tools/list proves them."""

from __future__ import annotations

import hashlib
import importlib.resources
import json
from datetime import datetime
from typing import Any

from clipforge.campaign.providers import CampaignError
from clipforge.schemas.whop_discovery import WhopLiveDiscoveryRequest

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
_ROW_FIELDS = (
    "tool_name",
    "provider_id",
    "provider_version",
    "protocol_version",
    "read_only",
    "destructive",
    "input_schema_sha256",
    "output_schema_sha256",
    "output_model",
    "verification_origin",
    "verification_timestamp",
    "tool_map_version",
)
_DOCUMENT_FIELDS = {
    "schema_version",
    "tool_map_version",
    "official_names_verified",
    "notes",
    "mappings",
}
_SHA = set("0123456789abcdef")
CAMPAIGN_OUTPUT_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {"campaigns": {"items": {"type": "object"}, "type": "array"}},
    "required": ["campaigns"],
    "type": "object",
}


def tool_map_sha256() -> str:
    """Hash the packaged map. A missing package resource is invalid_document."""
    return hashlib.sha256(_map_bytes()).hexdigest()


def load_tool_map() -> list[dict[str, Any]]:
    """Load the packaged map. A malformed row rejects the whole file."""
    try:
        payload = json.loads(_map_bytes().decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CampaignError("whop tool map could not be read", code="invalid_document") from exc
    if not isinstance(payload, dict) or set(payload) - _DOCUMENT_FIELDS:
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    rows = payload.get("mappings")
    verified = payload.get("official_names_verified")
    if not isinstance(rows, list) or verified not in {True, False}:
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    if verified is True and not rows:
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    if verified is False and rows:
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    parsed: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            raise CampaignError("whop tool map could not be read", code="invalid_document")
        parsed.append(_validate_mapping(item))
    return parsed


def validate_tool_output(document: dict[str, Any]) -> None:
    """Require the catalogue shape. The output hash is checked before the call."""
    campaigns = document.get("campaigns")
    if not isinstance(campaigns, list):
        raise CampaignError("whop provider response was malformed", code="malformed_response")
    for item in campaigns:
        if not isinstance(item, dict) or not isinstance(item.get("campaign_id"), str):
            raise CampaignError("whop provider response was malformed", code="malformed_response")


def schema_sha256(schema: dict[str, Any]) -> str:
    raw = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def arguments_for_tool(
    tool: dict[str, Any],
    request: WhopLiveDiscoveryRequest | None,
) -> dict[str, object]:
    """Build the call body from the tool schema. Missing required fields are unsupported."""
    schema = tool.get("inputSchema")
    if schema is None:
        schema = {"type": "object", "properties": {}}
    if not isinstance(schema, dict):
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    known = _known_arguments(request)
    arguments: dict[str, object] = {}
    for name in properties:
        if name in known:
            arguments[str(name)] = known[name]
    for name in required:
        if name not in arguments:
            raise CampaignError("unsupported_tool", code="unsupported_tool")
    return arguments


def select_mapped_tool(
    tools: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    *,
    allow_fixture: bool = False,
    provider_version: str,
    protocol_version: str,
    request: WhopLiveDiscoveryRequest | None = None,
) -> tuple[str, dict[str, object]]:
    """Return one exact mapped name and its arguments. Substring matches are not accepted."""
    checked = [_validate_mapping(item) for item in mappings]
    by_name: dict[str, dict[str, Any]] = {}
    for tool in tools:
        name = tool.get("name")
        if isinstance(name, str):
            by_name[name] = tool
    for mapping in checked:
        name = str(mapping["tool_name"])
        matched = by_name.get(name)
        if matched is None:
            continue
        if _mutating_token(name):
            raise CampaignError("unsupported_tool", code="unsupported_tool")
        if mapping["read_only"] is not True or mapping["destructive"] is True:
            raise CampaignError("unsupported_tool", code="unsupported_tool")
        origin = mapping["verification_origin"]
        if origin == "fixture_only" and not allow_fixture:
            continue
        if origin != "fixture_only" and origin != "tools_list":
            raise CampaignError("whop tool map could not be read", code="invalid_document")
        if mapping["provider_version"] != provider_version or mapping["protocol_version"] != protocol_version:
            continue
        annotations = matched.get("annotations")
        if not isinstance(annotations, dict) or annotations.get("readOnlyHint") is not True:
            raise CampaignError("unsupported_tool", code="unsupported_tool")
        if annotations.get("destructiveHint") is True:
            raise CampaignError("unsupported_tool", code="unsupported_tool")
        observed = matched.get("inputSchema")
        if not isinstance(observed, dict):
            raise CampaignError("schema_mismatch", code="schema_mismatch")
        if schema_sha256(observed) != mapping["input_schema_sha256"]:
            raise CampaignError("schema_mismatch", code="schema_mismatch")
        if schema_sha256(CAMPAIGN_OUTPUT_SCHEMA) != mapping["output_schema_sha256"]:
            raise CampaignError("schema_mismatch", code="schema_mismatch")
        return name, arguments_for_tool(matched, request)
    raise CampaignError("unsupported_tool", code="unsupported_tool")


def _map_bytes() -> bytes:
    try:
        resource = importlib.resources.files("clipforge.campaign.data").joinpath("whop-tool-map.json")
        return resource.read_bytes()
    except (FileNotFoundError, OSError, ModuleNotFoundError, TypeError) as exc:
        raise CampaignError("whop tool map could not be read", code="invalid_document") from exc


def _validate_mapping(item: dict[str, Any]) -> dict[str, Any]:
    if set(item) != set(_ROW_FIELDS):
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    name = item.get("tool_name")
    if not isinstance(name, str) or not name or _mutating_token(name):
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    for key in ("provider_id", "provider_version", "protocol_version", "tool_map_version", "output_model"):
        value = item.get(key)
        if not isinstance(value, str) or not value or len(value) > 80:
            raise CampaignError("whop tool map could not be read", code="invalid_document")
    if item.get("read_only") is not True or item.get("destructive") is not False:
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    if item.get("output_model") != "campaign_catalogue":
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    if item.get("verification_origin") not in {"fixture_only", "tools_list"}:
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    for key in ("input_schema_sha256", "output_schema_sha256"):
        digest = item.get(key)
        if not isinstance(digest, str) or len(digest) != 64 or set(digest) - _SHA:
            raise CampaignError("whop tool map could not be read", code="invalid_document")
    stamp = item.get("verification_timestamp")
    if not isinstance(stamp, str):
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    try:
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CampaignError("whop tool map could not be read", code="invalid_document") from exc
    return item


def _known_arguments(request: WhopLiveDiscoveryRequest | None) -> dict[str, object]:
    if request is None:
        return {}
    known: dict[str, object] = {}
    if request.query is not None:
        known["query"] = request.query
    if request.language is not None:
        known["language"] = request.language
    if request.media_format is not None:
        known["media_format"] = request.media_format
    return known


def _mutating_token(name: str) -> bool:
    tokens = [part for part in name.lower().replace("-", "_").split("_") if part]
    return any(token in _MUTATING for token in tokens)
