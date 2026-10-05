"""Minimal MCP client for the official Envato endpoint. Credentials are not stored."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from clipforge.errors import ClipforgeError

DEFAULT_URL = "https://mcp.envato.com/mcp"
_ENABLED = "CLIPFORGE_ENVATO_MCP_ENABLED"
_URL = "CLIPFORGE_ENVATO_MCP_URL"
_LIVE = "CLIPFORGE_ENVATO_MCP_LIVE_SMOKE"
_PROTOCOL = "2025-06-18"


class AssetError(ClipforgeError):
    """An asset discovery call failed closed."""

    def __init__(self, message: str, *, code: str = "asset_error") -> None:
        super().__init__(message)
        self.code = code


def envato_enabled() -> bool:
    return os.environ.get(_ENABLED, "0").strip() == "1"


def envato_live() -> bool:
    return os.environ.get(_LIVE, "0").strip() == "1"


def envato_url() -> str:
    return os.environ.get(_URL, DEFAULT_URL).strip() or DEFAULT_URL


class EnvatoMcpClient:
    """JSON-RPC over the configured MCP URL. Authorization headers are not logged."""

    def __init__(self, url: str | None = None, *, timeout_s: float = 20, opener: object | None = None) -> None:
        self.url = url or envato_url()
        self.timeout_s = timeout_s
        self.opener = opener
        self.session_id: str | None = None
        self.server_name: str | None = None
        self.server_version: str | None = None
        self._next_id = 1

    def initialize(self) -> dict[str, Any]:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": _PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "clipforge", "version": "0.1.0"},
            },
        )
        info = result.get("serverInfo") if isinstance(result, dict) else None
        if isinstance(info, dict):
            name = info.get("name")
            version = info.get("version")
            self.server_name = name if isinstance(name, str) else None
            self.server_version = version if isinstance(version, str) else None
        self._notify("notifications/initialized", {})
        return result if isinstance(result, dict) else {}

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._rpc("tools/list", {})
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            return []
        return [item for item in tools if isinstance(item, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        return result if isinstance(result, dict) else {}

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            self._post(body)
        except AssetError:
            return

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload = self._post({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        if payload.get("error"):
            raise AssetError("envato mcp returned an error", code="provider_unavailable")
        result = payload.get("result")
        return result if isinstance(result, dict) else {}

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "clipforge-assets",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = Request(self.url, data=data, headers=headers)
        open_url = self.opener or urlopen
        try:
            with open_url(request, timeout=self.timeout_s) as response:  # type: ignore[operator]
                session = response.headers.get("Mcp-Session-Id")
                if isinstance(session, str) and session and _safe_session(session):
                    self.session_id = session
                raw = response.read(1_000_000)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise AssetError(_public_network_error(exc), code="provider_unavailable") from exc
        return _decode(raw)


def _safe_session(value: str) -> bool:
    lowered = value.lower()
    return "bearer" not in lowered and "token" not in lowered and len(value) <= 200


def _public_network_error(exc: BaseException) -> str:
    text = str(exc)
    lowered = text.lower()
    if any(token in lowered for token in ("bearer", "token", "authorization", "cookie", "password")):
        return "envato mcp connection failed"
    if isinstance(exc, HTTPError):
        return f"envato mcp http {exc.code}"
    return "envato mcp connection failed"


def _decode(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if line.startswith("data:"):
            text = line.removeprefix("data:").strip()
            break
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AssetError("envato mcp response was not json", code="malformed_response") from exc
    if not isinstance(payload, dict):
        raise AssetError("envato mcp response was not an object", code="malformed_response")
    return payload
