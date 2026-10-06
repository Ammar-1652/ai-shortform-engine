"""Read-only client for the official Whop MCP servers. No authorization header is sent."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from clipforge.campaign.providers import CampaignError

PUBLIC_MCP_URL = "https://mcp.whop.com/mcp"
DOCS_MCP_URL = "https://docs.whop.com/mcp"
_PROTOCOL = "2025-06-18"
_MUTATING = (
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
)
_READ = ("list", "search", "get", "discover", "read")
_SECRET_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "bearer",
    "session",
    "set-cookie",
}


def live_smoke_enabled() -> bool:
    return os.environ.get("CLIPFORGE_WHOP_LIVE_SMOKE", "").strip() == "1"


def configured_connector() -> str:
    return os.environ.get("CLIPFORGE_WHOP_CONNECTOR", "").strip()


def configured_url() -> str:
    value = os.environ.get("CLIPFORGE_WHOP_URL", "").strip()
    return value or PUBLIC_MCP_URL


def public_headers() -> dict[str, str]:
    """Headers for a public MCP call. Authorization is intentionally absent."""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "clipforge-whop",
    }


def tool_is_read_only(name: str) -> bool:
    lowered = name.lower()
    if any(token in lowered for token in _MUTATING):
        return False
    return any(token in lowered for token in _READ)


def redact(value: object) -> object:
    """Drop secret-like keys and strings before anything is stored."""
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                continue
            cleaned[str(key)] = redact(item)
        return cleaned
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and _secret_text(value):
        return None
    return value


class WhopMcpReader:
    """One read-only MCP session. The session id is not written to disk."""

    def __init__(self, url: str | None = None, *, opener: object | None = None) -> None:
        self.url = url or configured_url()
        self.opener = opener
        self._next_id = 1

    def capabilities(self) -> dict[str, object]:
        if not live_smoke_enabled():
            raise CampaignError("whop live is not configured", code="not_configured")
        if "://" not in self.url or not self.url.startswith("https://"):
            raise CampaignError("whop provider url is not https", code="provider_unavailable")
        try:
            self._rpc(
                "initialize",
                {
                    "protocolVersion": _PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "clipforge", "version": "0.1.0"},
                },
            )
            listed = self._rpc("tools/list", {})
        except CampaignError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise CampaignError("whop provider is unavailable", code="provider_unavailable") from exc
        tools = listed.get("tools") if isinstance(listed, dict) else None
        names = []
        if isinstance(tools, list):
            for item in tools:
                name = item.get("name") if isinstance(item, dict) else None
                if isinstance(name, str) and tool_is_read_only(name):
                    names.append(name)
        return {"read_only_tools": names, "mutating_operations": "disabled"}

    def _rpc(self, method: str, params: dict[str, object]) -> dict[str, object]:
        request_id = self._next_id
        self._next_id += 1
        body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        payload = self._post(body)
        if payload.get("error"):
            raise CampaignError("whop provider is unavailable", code="provider_unavailable")
        result = payload.get("result")
        return result if isinstance(result, dict) else {}

    def _post(self, body: dict[str, object]) -> dict[str, object]:
        data = json.dumps(body).encode("utf-8")
        request = Request(self.url, data=data, headers=public_headers())
        open_url = self.opener or urlopen
        try:
            with open_url(request, timeout=20) as response:  # type: ignore[operator]
                raw = response.read(1_000_000)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise CampaignError("whop provider is unavailable", code="provider_unavailable") from exc
        try:
            parsed = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise CampaignError("whop provider response was malformed", code="invalid_document") from exc
        if not isinstance(parsed, dict):
            raise CampaignError("whop provider response was malformed", code="invalid_document")
        redacted = redact(parsed)
        if not isinstance(redacted, dict):
            raise CampaignError("whop provider response was malformed", code="invalid_document")
        return redacted


def _secret_text(value: str) -> bool:
    lowered = value.lower()
    tokens = ("bearer ", "token=", "cookie=", "password=", "api_key", "api-key", "authorization:")
    return any(token in lowered for token in tokens)
