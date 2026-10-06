"""Whop provider factory. A live provider is built only when the operator enables it."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from clipforge.campaign.providers import CampaignError
from clipforge.campaign.whop_bridge import AuthenticatedBridgeProvider
from clipforge.campaign.whop_mcp import (
    PUBLIC_MCP_URL,
    Opener,
    WhopMcpReader,
    campaign_document,
    configured_connector,
    configured_url,
    live_smoke_enabled,
    official_endpoint,
)
from clipforge.campaign.whop_tools import load_tool_map, select_mapped_tool, validate_tool_output
from clipforge.schemas.whop_discovery import WhopLiveDiscoveryRequest


class AuthenticatedConnectorSession:
    """A connector that already holds the browser session outside Clipforge.

    The handle is ephemeral. This object has no password, cookie, or token field.
    """

    evidence_origin = "authenticated_connector"

    def __init__(self, handle: str, reader: Callable[[], dict[str, Any]]) -> None:
        self._handle = handle
        self._reader = reader

    def read_campaigns(self) -> dict[str, Any]:
        payload = self._reader()
        if not isinstance(payload, dict):
            raise CampaignError("whop provider response was malformed", code="invalid_document")
        return payload


class FixtureCatalogueReader:
    """In-process catalogue bytes. This is not a live Whop session."""

    evidence_origin = "test_double"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def read_campaigns(self) -> dict[str, Any]:
        return self.payload


class PublicWhopMcpProvider:
    """Public MCP discovery. The adapter assigns the live status, not the payload."""

    provider_id = "whop"
    provider_version = "official"
    live_status = "public_discovery"
    evidence_origin = "public_connector"
    mode = "live_connector"
    tool_name: str | None = None

    def __init__(
        self,
        url: str | None = None,
        *,
        timeout_s: float = 20,
        opener: Opener | None = None,
        tool_map: list[dict[str, Any]] | None = None,
        allow_fixture: bool = False,
        allow_loopback: bool = False,
    ) -> None:
        self.url = url
        self.timeout_s = timeout_s
        self.opener = opener
        self.tool_map = tool_map
        self.allow_fixture = allow_fixture
        self.allow_loopback = allow_loopback
        self.discovery_request: WhopLiveDiscoveryRequest | None = None

    def bind_request(self, request: WhopLiveDiscoveryRequest) -> None:
        self.discovery_request = request

    def discover(self) -> dict[str, Any]:
        reader = WhopMcpReader(
            self.url,
            timeout_s=self.timeout_s,
            opener=self.opener,
            allow_loopback=self.allow_loopback,
        )
        try:
            reader.initialize()
            mappings = self.tool_map if self.tool_map is not None else load_tool_map()
            tool, arguments = select_mapped_tool(
                reader.list_tools(),
                mappings,
                allow_fixture=self.allow_fixture,
                provider_version=reader.server_version or "",
                protocol_version=reader.protocol_version or "",
                request=self.discovery_request,
            )
            result = reader.call_tool(tool, arguments)
        finally:
            reader.close()
        self.tool_name = tool
        if reader.server_version:
            self.provider_version = reader.server_version
        document = campaign_document(result)
        validate_tool_output(document)
        return document


class OfficialGrokProvider(PublicWhopMcpProvider):
    """Official Grok connector. A loopback opener cannot become a live claim."""

    provider_id = "whop"
    provider_version = "official"
    live_status = "not_configured"
    evidence_origin = "test_double"
    mode = "live_connector"
    live_claim = "not_claimed"
    official_call_completed = False
    tool_map_sha256: str | None = None

    def discover(self) -> dict[str, Any]:
        document = super().discover()
        official = (
            self.url == PUBLIC_MCP_URL
            and self.opener is None
            and not self.allow_loopback
            and not self.allow_fixture
        )
        if official:
            self.evidence_origin = "authenticated_connector"
            self.live_status = "authenticated_discovery"
            self.live_claim = "claimed"
            self.official_call_completed = True
        return document


class AuthenticatedBrowserProvider:
    """Normalized metadata from a connector session. Login stays outside Clipforge."""

    provider_id = "whop"
    provider_version = "browser-session"
    mode = "browser_export"
    tool_name: str | None = None

    def __init__(self, reader: AuthenticatedConnectorSession | FixtureCatalogueReader) -> None:
        if isinstance(reader, AuthenticatedConnectorSession):
            self.evidence_origin = "authenticated_connector"
            self.live_status = "authenticated_discovery"
        elif isinstance(reader, FixtureCatalogueReader):
            self.evidence_origin = "test_double"
            self.live_status = "not_configured"
        else:
            raise CampaignError("whop provider status was forged", code="forged_status")
        self._reader = reader

    def discover(self) -> dict[str, Any]:
        return self._reader.read_campaigns()


_READERS: dict[str, AuthenticatedConnectorSession | FixtureCatalogueReader] = {}


def register_authenticated_reader(
    handle: str,
    reader: AuthenticatedConnectorSession | FixtureCatalogueReader,
) -> None:
    """Remember a process-local reader. The handle is not written to disk."""
    _READERS[handle] = reader


def clear_authenticated_readers() -> None:
    _READERS.clear()


def build_live_provider(kind: str | None = None) -> PublicWhopMcpProvider | AuthenticatedBridgeProvider:
    """Open a connector only after the live switch and an explicit connector name."""
    if not live_smoke_enabled():
        raise CampaignError("whop_live: not_configured", code="not_configured")
    selected = kind or configured_connector()
    if selected == "public":
        if not official_endpoint(configured_url()):
            raise CampaignError("whop_live: provider_unavailable", code="provider_unavailable")
        return PublicWhopMcpProvider(PUBLIC_MCP_URL)
    if selected == "authenticated":
        return AuthenticatedBridgeProvider.from_environment()
    if selected == "official-grok":
        from clipforge.campaign.whop_auth import _AUTH_REQUIRED, _doctor_state
        from clipforge.campaign.whop_tools import load_verified_tool_map

        if not official_endpoint(configured_url()):
            raise CampaignError("whop_live: provider_unavailable", code="provider_unavailable")
        if _doctor_state() != "authenticated":
            raise CampaignError(_AUTH_REQUIRED, code="auth_required")
        try:
            rows, digest = load_verified_tool_map()
        except CampaignError as exc:
            raise CampaignError("unsupported_tool", code="unsupported_tool") from exc
        if not rows:
            raise CampaignError("unsupported_tool", code="unsupported_tool")
        provider = OfficialGrokProvider(PUBLIC_MCP_URL, tool_map=rows, allow_fixture=False)
        provider.tool_map_sha256 = digest
        return provider
    raise CampaignError("whop_live: provider_unavailable", code="provider_unavailable")
