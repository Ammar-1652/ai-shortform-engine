"""Translate operator search constraints against advertised Envato schemas."""

from __future__ import annotations

from typing import Any

from clipforge.assets.mcp_client import AssetError

_ITEM_TYPES = {
    "video": "stock-video",
    "audio": "music",
    "image": "photos",
    "graphic": "graphics",
    "template": "video-templates",
}
_ALIASES = {
    "category": ("categories",),
    "subcategory": ("subcategories",),
    "format": ("graphics_file_types", "three_d_file_types"),
    "compatible_software": (
        "applications_supported",
        "graphics_applications_supported",
        "graphic_templates_applications_supported",
        "presentation_templates_applications_supported",
        "add_ons_applications_supported",
    ),
    "min_duration": ("min_media_length",),
    "max_duration": ("max_media_length",),
}
_VALUES = {
    "resolution": {
        "720p": "720p (HD)",
        "1080p": "1080p (Full HD)",
        "4k": "4K (UHD)",
    },
    "categories": {"stock-footage": "Stock Footage", "motion-graphics": "Motion Graphics"},
}


def search_spec(specs: list[dict[str, Any]], filters: dict[str, str]) -> dict[str, Any]:
    """Route by item type; never send routing keys as refinement filters."""
    item_type = _item_type(filters)
    preferred = "search_" + item_type.replace("-", "_") if item_type else None
    for name in (preferred, "search_items"):
        if name is not None:
            for spec in specs:
                if spec.get("name") == name:
                    return spec
    raise AssetError("Envato did not advertise a compatible search tool", code="unsupported_asset_type")


def search_arguments(
    spec: dict[str, Any], query: str, filters: dict[str, str]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate native filters. Incompatible constraints fail before tools/call."""
    schema = spec.get("inputSchema", {})
    properties = _object_properties(schema)
    if "searchTerms" not in properties:
        raise AssetError("Envato search schema has no searchTerms", code="unsupported_schema")
    _validate(query, properties["searchTerms"], "searchTerms")
    arguments: dict[str, Any] = {"searchTerms": query}
    if "perPage" in properties:
        arguments["perPage"] = 5
    item_type = _item_type(filters)
    if "itemType" in properties:
        if item_type is None:
            raise AssetError("Envato search requires an item type", code="unsupported_asset_type")
        _validate(item_type, properties["itemType"], "itemType")
        arguments["itemType"] = item_type
    native_schema = _object_schema(properties.get("filters", {}))
    native_properties = _object_properties(native_schema)
    # The deprecated free-form search API still validates server-side. Refuse
    # to claim support without the typed schema for the requested item type.
    applied: dict[str, Any] = {}
    report: dict[str, str] = {}
    for key, raw in filters.items():
        if key in {"asset_type", "item_type"}:
            report[key] = "tool_selection"
            continue
        if key == "category" and raw == item_type:
            report[key] = "tool_selection"
            continue
        if key == "intended_use":
            report[key] = "local_context_only"
            continue
        if key == "duration":
            raise AssetError(
                "duration is ambiguous; use min_duration and max_duration in seconds",
                code="unsupported_filter",
            )
        candidates = (key, *_ALIASES.get(key, ()))
        target = next((name for name in candidates if name in native_properties), None)
        if target is None:
            raise AssetError(
                f"{key} is unsupported by {spec.get('name')}; supported filters: "
                + ", ".join(sorted(native_properties)),
                code="unsupported_filter",
            )
        value = _coerce(raw, native_properties[target], target)
        if target in applied and applied[target] != value:
            raise AssetError(f"conflicting values for {target}", code="invalid_filter")
        applied[target] = value
        report[key] = target
    lower = applied.get("min_media_length")
    upper = applied.get("max_media_length")
    if lower is not None and upper is not None and lower > upper:
        raise AssetError("minimum duration exceeds maximum duration", code="invalid_filter")
    if applied:
        arguments["filters"] = applied
    return arguments, report


def _item_type(filters: dict[str, str]) -> str | None:
    declared = filters.get("item_type")
    asset = filters.get("asset_type")
    if declared:
        return declared
    if asset:
        return _ITEM_TYPES.get(asset, asset)
    category = filters.get("category")
    if category in {"stock-video", "music", "sound-effects", "photos", "graphics", "video-templates"}:
        return category
    return None


def _branches(schema: dict[str, Any]) -> list[dict[str, Any]]:
    result = [schema]
    for key in ("anyOf", "oneOf"):
        for branch in schema.get(key, []):
            if isinstance(branch, dict):
                result.extend(_branches(branch))
    return result


def _object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return next(
        (branch for branch in _branches(schema) if branch.get("type") == "object" or "properties" in branch),
        {},
    )


def _object_properties(schema: dict[str, Any]) -> dict[str, Any]:
    result = _object_schema(schema).get("properties", {})
    return result if isinstance(result, dict) else {}


def _coerce(raw: str, schema: dict[str, Any], key: str) -> str | int | bool:
    enums = [value for branch in _branches(schema) for value in branch.get("enum", [])]
    value: str | int | bool = _VALUES.get(key, {}).get(raw.lower(), raw)
    if enums and isinstance(value, str):
        value = next((item for item in enums if isinstance(item, str) and item.lower() == value.lower()), value)
    types = {branch.get("type") for branch in _branches(schema)}
    if "integer" in types and "string" not in types:
        try:
            value = int(raw)
        except ValueError as exc:
            raise AssetError(f"{key} requires integer seconds", code="invalid_filter") from exc
        if key in {"min_media_length", "max_media_length"} and not 0 <= value <= 3600:
            raise AssetError(f"{key} must be between 0 and 3600 seconds", code="invalid_filter")
    elif "boolean" in types and "string" not in types:
        if raw.lower() not in {"true", "false"}:
            raise AssetError(f"{key} requires true or false", code="invalid_filter")
        value = raw.lower() == "true"
    _validate(value, schema, key)
    return value


def _validate(value: str | int | bool, schema: dict[str, Any], key: str) -> None:
    branches = _branches(schema)
    enums = [item for branch in branches for item in branch.get("enum", [])]
    if enums and value not in enums:
        raise AssetError(f"{key} has an unsupported value; inspect the advertised enum", code="invalid_filter")
    for branch in branches:
        if isinstance(value, str):
            if len(value) < branch.get("minLength", 0) or len(value) > branch.get("maxLength", 1_000_000):
                raise AssetError(f"{key} has an invalid length", code="invalid_filter")
        elif isinstance(value, int) and not isinstance(value, bool):
            if value < branch.get("minimum", value) or value > branch.get("maximum", value):
                raise AssetError(f"{key} is outside the supported range", code="invalid_filter")
