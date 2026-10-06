"""Checked tool map for Whop discovery. Official names stay empty until tools/list proves them."""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import os
from datetime import UTC, datetime
from pathlib import Path
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
        "payment",
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


_SAFE_ARGUMENTS = frozenset({"query", "language", "status", "category", "platform", "media_format"})
_SECRET_ARGUMENTS = frozenset(
    {"password", "token", "cookie", "authorization", "api_key", "secret", "session", "session_id"}
)
_UPLOAD_ARGUMENTS = frozenset({"file", "upload", "attachment", "filename", "content", "bytes"})
_UNSAFE_TEXT = ("bearer ", "token=", "cookie=", "password=", "api_key", "authorization:", "file:")
_OFFICIAL_ENDPOINT = "https://mcp.whop.com/mcp"


def verified_tool_map_path() -> Path:
    raw = os.environ.get("CLIPFORGE_WHOP_STATE_DIR", "").strip()
    base = Path(raw).expanduser() if raw else Path.home() / ".config" / "clipforge"
    return base / "whop" / "tool-map.json"


def load_verified_tool_map() -> tuple[list[dict[str, Any]], str]:
    """Load the operator-local map. A missing file has no verified tools."""
    path = verified_tool_map_path()
    _reject_map_symlink(path)
    if not path.is_file():
        return [], tool_map_sha256()
    if (path.stat().st_mode & 0o077) != 0:
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    if path.parent.is_dir() and (path.parent.stat().st_mode & 0o077) != 0:
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CampaignError("whop tool map could not be read", code="invalid_document") from exc
    if not isinstance(payload, dict):
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    if payload.get("endpoint") != _OFFICIAL_ENDPOINT or payload.get("read_only_verification") != "passed":
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    if _unsafe_text(json.dumps(payload)):
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    rows = payload.get("mappings")
    verified = payload.get("official_names_verified")
    if not isinstance(rows, list) or verified is not True:
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    parsed = [_validate_mapping(item) for item in rows if isinstance(item, dict)]
    if len(parsed) != len(rows) or not parsed:
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    return parsed, hashlib.sha256(path.read_bytes()).hexdigest()


def mappings_from_tools_list(
    tools: list[dict[str, Any]],
    *,
    provider_version: str,
    protocol_version: str,
) -> list[dict[str, Any]]:
    """Keep exact read-only campaign tools. A name substring is not evidence."""
    stamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    chosen: list[dict[str, Any]] = []
    for tool in tools:
        accepted = _accepted_tool(tool, provider_version, protocol_version, stamp)
        if accepted is not None:
            chosen.append(accepted)
    return [_validate_mapping(item) for item in chosen]


def public_descriptions(tools: list[dict[str, Any]]) -> dict[str, str]:
    """Keep short public descriptions. Secret-like text is omitted."""
    found: dict[str, str] = {}
    for tool in tools:
        name = tool.get("name")
        text = tool.get("description")
        if not isinstance(name, str) or not isinstance(text, str) or _unsafe_text(text):
            continue
        compact = " ".join(text.split())
        if compact:
            found[name] = compact[:240]
    return found


def write_verified_tool_map(
    mappings: list[dict[str, Any]],
    *,
    server_name: str,
    provider_version: str,
    protocol_version: str,
    descriptions: dict[str, str] | None = None,
) -> str:
    """Write the operator-local map. An empty selection is not stored."""
    path = verified_tool_map_path()
    _reject_map_symlink(path)
    if not mappings:
        if path.is_file():
            path.unlink()
        raise CampaignError("unsupported_tool", code="unsupported_tool")
    if _unsafe_text(server_name) or _unsafe_text(provider_version) or _unsafe_text(protocol_version):
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    safe_descriptions = {
        name: text
        for name, text in (descriptions or {}).items()
        if isinstance(name, str) and isinstance(text, str) and text and not _unsafe_text(text)
    }
    payload = {
        "schema_version": "1.0.0",
        "tool_map_version": "1",
        "official_names_verified": True,
        "read_only_verification": "passed",
        "endpoint": _OFFICIAL_ENDPOINT,
        "server_name": server_name,
        "provider_version": provider_version,
        "protocol_version": protocol_version,
        "descriptions": safe_descriptions,
        "mappings": mappings,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    partial = path.with_suffix(".json.partial")
    if partial.is_symlink():
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    descriptor = os.open(partial, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)
    os.chmod(partial, 0o600)
    os.replace(partial, path)
    os.chmod(path, 0o600)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def remove_verified_tool_map() -> None:
    """Remove the operator-local map. A symlink is unlinked and its target is kept."""
    path = verified_tool_map_path()
    if path.is_symlink() or path.is_file():
        path.unlink()
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        return
    if any(parent.iterdir()):
        return
    parent.rmdir()


def show_verified_tool_map() -> str:
    """Print tool names and hashes. The filesystem path is not included."""
    path = verified_tool_map_path()
    if path.is_symlink() or not path.is_file():
        return "tool_map: missing\nofficial_names_verified: false\nlive_claim: not_claimed"
    rows, digest = load_verified_tool_map()
    lines = [
        "tool_map: configured",
        f"endpoint: {_OFFICIAL_ENDPOINT}",
        f"tool_map_sha256: {digest}",
        "read_only_verification: passed",
        "live_claim: not_claimed",
        "credentials: not stored",
    ]
    for row in rows:
        lines.append(f"tool: {row['tool_name']} {row['input_schema_sha256']}")
    return "\n".join(lines)


def _accepted_tool(
    tool: dict[str, Any],
    provider_version: str,
    protocol_version: str,
    stamp: str,
) -> dict[str, Any] | None:
    name = tool.get("name")
    if not isinstance(name, str) or not name or _mutating_token(name) or _unsafe_text(name):
        return None
    description = tool.get("description")
    if isinstance(description, str) and _unsafe_text(description):
        return None
    annotations = tool.get("annotations")
    if not isinstance(annotations, dict) or annotations.get("readOnlyHint") is not True:
        return None
    if annotations.get("destructiveHint") is True:
        return None
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return None
    if not _campaign_output(tool.get("outputSchema")):
        return None
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    if not isinstance(properties, dict) or not properties or not isinstance(required, list):
        return None
    names = {str(item) for item in properties}
    if names - _SAFE_ARGUMENTS or names & _SECRET_ARGUMENTS or names & _UPLOAD_ARGUMENTS:
        return None
    if {str(item) for item in required} - _SAFE_ARGUMENTS:
        return None
    for spec in properties.values():
        if _uploads_bytes(spec):
            return None
    return {
        "tool_name": name,
        "provider_id": "whop",
        "provider_version": provider_version,
        "protocol_version": protocol_version,
        "read_only": True,
        "destructive": False,
        "input_schema_sha256": schema_sha256(schema),
        "output_schema_sha256": schema_sha256(CAMPAIGN_OUTPUT_SCHEMA),
        "output_model": "campaign_catalogue",
        "verification_origin": "tools_list",
        "verification_timestamp": stamp,
        "tool_map_version": "1",
    }


def _campaign_output(schema: object) -> bool:
    """True when the declared output is a campaign catalogue. The tool name is ignored."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return False
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return False
    campaigns = properties.get("campaigns")
    return isinstance(campaigns, dict) and campaigns.get("type") == "array"


def _uploads_bytes(spec: object) -> bool:
    if not isinstance(spec, dict):
        return False
    if spec.get("contentMediaType"):
        return True
    return spec.get("format") in {"binary", "byte", "password"}


def _unsafe_text(value: str) -> bool:
    lowered = value.lower()
    if any(token in lowered for token in _UNSAFE_TEXT):
        return True
    return value.startswith("/") or ":\\" in value


def _reject_map_symlink(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise CampaignError("whop tool map could not be read", code="invalid_document")
        if current.parent == current:
            return
        current = current.parent


def _mutating_token(name: str) -> bool:
    tokens = [part for part in name.lower().replace("-", "_").split("_") if part]
    return any(token in _MUTATING for token in tokens)
