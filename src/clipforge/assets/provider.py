"""Asset discovery providers. Fake and dry-run providers do not invent catalog URLs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from clipforge.assets.filters import apply_post_filters, search_arguments, search_spec
from clipforge.assets.mcp_client import AssetError, EnvatoMcpClient, envato_enabled, envato_live


class AssetDiscoveryProvider(Protocol):
    """Search a catalog. Implementations must not download media."""

    def doctor(self) -> str:
        """Report connection state without secrets."""

    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, Any]]:
        """Return provider rows. Missing fields are omitted, not invented."""


@dataclass
class FakeAssetDiscoveryProvider:
    """No network and no fabricated item URLs."""

    calls: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)

    def doctor(self) -> str:
        return "provider: fake\nnetwork: none\ncredentials: not stored"

    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, Any]]:
        del query, filters
        self.calls += 1
        return list(self.rows)


@dataclass
class DryRunAssetDiscoveryProvider:
    """Validate that a search would be explicit. Return no items."""

    calls: int = 0

    def doctor(self) -> str:
        return "provider: dry_run\nnetwork: none\ndirect_download: unsupported"

    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, Any]]:
        if not query.strip():
            raise AssetError("search query is blank", code="invalid_query")
        del filters
        self.calls += 1
        return []


class FakeEnvatoMcpProvider:
    """In-memory Envato tool. It does not open a socket or invent a download URL."""

    def __init__(self, specs: list[dict[str, Any]], rows: list[dict[str, Any]] | None = None) -> None:
        self.tool_specs = specs
        self.rows = list(rows or [])
        self.calls = 0
        self.last_arguments: dict[str, Any] = {}
        self.last_report: dict[str, str] = {}
        self.last_deferred: dict[str, str] = {}

    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, Any]]:
        self.calls += 1
        tool = search_spec(self.tool_specs, filters)
        arguments, report, deferred = search_arguments(tool, query, filters)
        self.last_arguments = arguments
        self.last_report = report
        self.last_deferred = deferred
        return apply_post_filters(self.rows, deferred)


class EnvatoMcpDiscoveryProvider:
    """Official Envato MCP. Disabled unless CLIPFORGE_ENVATO_MCP_ENABLED=1."""

    def __init__(self, client: EnvatoMcpClient | None = None) -> None:
        self.client = client or EnvatoMcpClient()
        self.calls = 0
        self.tools: list[str] = []
        self.tool_specs: list[dict[str, Any]] = []

    def doctor(self) -> str:
        if not envato_enabled():
            return "\n".join(
                [
                    f"endpoint: {self.client.url}",
                    "enabled: 0",
                    "connection: not_configured",
                    "authentication: not stored",
                    "direct_download: unsupported",
                ]
            )
        if not envato_live():
            return "\n".join(
                [
                    f"endpoint: {self.client.url}",
                    "enabled: 1",
                    "connection: not_run",
                    "authentication: delegated",
                    "direct_download: unsupported",
                ]
            )
        try:
            self.client.initialize()
            self.tool_specs = [item for item in self.client.list_tools() if item.get("name")]
            self.tools = [str(item.get("name")) for item in self.tool_specs]
        except AssetError as exc:
            return "\n".join(
                [
                    f"endpoint: {self.client.url}",
                    "enabled: 1",
                    "connection: provider_unavailable",
                    f"reason: {exc}",
                    "authentication: delegated",
                    "direct_download: unsupported",
                ]
            )
        version = self.client.server_version or "unknown"
        names = ",".join(self.tools) if self.tools else "none"
        return "\n".join(
            [
                f"endpoint: {self.client.url}",
                "enabled: 1",
                "connection: connected",
                f"capabilities: {names}",
                "authentication: delegated",
                f"provider_version: {version}",
                "direct_download: unsupported",
            ]
        )

    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, Any]]:
        self.calls += 1
        if not envato_enabled() or not envato_live():
            raise AssetError("envato mcp live search is not enabled", code="not_configured")
        if not self.tool_specs:
            self.client.initialize()
            self.tool_specs = [item for item in self.client.list_tools() if item.get("name")]
            self.tools = [str(item.get("name")) for item in self.tool_specs]
        tool = search_spec(self.tool_specs, filters)
        arguments, report, deferred = search_arguments(tool, query, filters)
        self.last_arguments = arguments
        self.last_report = report
        self.last_deferred = deferred
        result = self.client.call_tool(str(tool.get("name")), arguments)
        return apply_post_filters(_rows_from_tool(result), deferred)


def _rows_from_tool(result: dict[str, Any]) -> list[dict[str, Any]]:
    content = result.get("content")
    rows: list[dict[str, Any]] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                rows.extend(_parse_text(item["text"]))
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        nested = structured.get("items") or structured.get("results")
        if isinstance(nested, list):
            rows.extend(entry for entry in nested if isinstance(entry, dict))
    return rows


def _parse_text(text: str) -> list[dict[str, Any]]:
    import json

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        nested = payload.get("items") or payload.get("results") or [payload]
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    return []
