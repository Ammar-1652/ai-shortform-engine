"""Read-only client for the official Whop MCP server. Credentials are not stored."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import NoReturn, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from clipforge.campaign.providers import CampaignError
from clipforge.schemas.campaign import _plain

PUBLIC_MCP_URL = "https://mcp.whop.com/mcp"
DOCS_MCP_URL = "https://docs.whop.com/mcp"
_PROTOCOL = "2025-06-18"
_MAX_BYTES = 1_000_000
_SESSION_HEADER = "Mcp-Session-Id"
# Exact tool names. Selection does not use a substring match.
DISCOVERY_TOOL_ALLOWLIST: tuple[str, ...] = (
    "list_public_campaigns",
    "search_public_campaigns",
    "get_public_campaign",
    "discover_public_campaigns",
    "read_public_campaigns",
)
_MUTATING_TOKENS = frozenset(
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
_SECRET_KEYS = frozenset(
    {
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
        "session_id",
        "set-cookie",
    }
)
_FORGED_KEYS = frozenset(
    {
        "live_status",
        "mode",
        "provider_id",
        "provider_version",
        "evidence_origin",
        "authenticated",
        "verification",
        "live_claim",
        "session_id",
        "mcp_session_id",
    }
)
_SECRET_TEXT = (
    "bearer ",
    "token=",
    "cookie=",
    "password=",
    "api_key",
    "api-key",
    "authorization:",
)


class _Response(Protocol):
    headers: object

    def read(self, size: int = -1) -> bytes: ...

    def __enter__(self) -> _Response: ...

    def __exit__(self, *args: object) -> object: ...


Opener = Callable[..., _Response]


def live_smoke_enabled() -> bool:
    return os.environ.get("CLIPFORGE_WHOP_LIVE_SMOKE", "").strip() == "1"


def configured_connector() -> str:
    return os.environ.get("CLIPFORGE_WHOP_CONNECTOR", "").strip()


def configured_url() -> str:
    value = os.environ.get("CLIPFORGE_WHOP_URL", "").strip()
    return value or PUBLIC_MCP_URL


def session_handle() -> str | None:
    """Return an opaque handle. A secret-like value is ignored and not logged."""
    value = os.environ.get("CLIPFORGE_WHOP_SESSION_HANDLE", "").strip()
    if not value or len(value) > 80:
        return None
    lowered = value.lower()
    if any(token in lowered for token in _SECRET_TEXT):
        return None
    if any(not (character.isalnum() or character in "._:-") for character in value):
        return None
    return value


def public_headers() -> dict[str, str]:
    """Headers for a public MCP call. Authorization is absent."""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "clipforge-whop",
    }


def url_is_allowed(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.query:
        return False
    host = parsed.hostname or ""
    if parsed.scheme == "https" and host:
        return True
    return parsed.scheme == "http" and host in {"127.0.0.1", "localhost"}


def select_discovery_tool(names: list[str]) -> str:
    """Pick one exact allowlisted name. Mutating tools are never called."""
    available = set(names)
    for candidate in DISCOVERY_TOOL_ALLOWLIST:
        if _mutating_token(candidate):
            continue
        if candidate in available:
            return candidate
    raise CampaignError("whop discovery tool is not allowlisted", code="unsupported_tool")


def reject_untrusted_document(payload: dict[str, object]) -> None:
    """Reject forged provenance and secret material. Do not blank public fields."""
    _walk_untrusted(payload)


class WhopMcpReader:
    """One read-only MCP session. The session id stays on this object."""

    def __init__(
        self,
        url: str | None = None,
        *,
        timeout_s: float = 20,
        opener: Opener | None = None,
    ) -> None:
        self.url = url or configured_url()
        self.timeout_s = timeout_s
        self.opener = opener
        self.server_name: str | None = None
        self.server_version: str | None = None
        self.session_id: str | None = None
        self._next_id = 1

    def initialize(self) -> None:
        self._require_url()
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
            if isinstance(name, str) and _label(name):
                self.server_name = name
            if isinstance(version, str) and _label(version):
                self.server_version = version
        self._notify("notifications/initialized", {})

    def list_tool_names(self) -> list[str]:
        listed = self._rpc("tools/list", {})
        tools = listed.get("tools") if isinstance(listed, dict) else None
        names: list[str] = []
        if isinstance(tools, list):
            for item in tools:
                name = item.get("name") if isinstance(item, dict) else None
                if isinstance(name, str):
                    names.append(name)
        return names

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        if name not in DISCOVERY_TOOL_ALLOWLIST or _mutating_token(name):
            raise CampaignError("whop discovery tool is not allowlisted", code="unsupported_tool")
        return self._rpc("tools/call", {"name": name, "arguments": arguments})

    def _require_url(self) -> None:
        if not url_is_allowed(self.url):
            raise CampaignError("whop provider url is not https", code="provider_unavailable")

    def _notify(self, method: str, params: dict[str, object]) -> None:
        payload = self._post({"jsonrpc": "2.0", "method": method, "params": params}, allow_empty=True)
        if payload.get("error"):
            _raise_rpc(payload)

    def _rpc(self, method: str, params: dict[str, object]) -> dict[str, object]:
        request_id = self._next_id
        self._next_id += 1
        payload = self._post(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            allow_empty=False,
        )
        _raise_rpc(payload)
        result = payload.get("result")
        if not isinstance(result, dict):
            raise CampaignError("whop provider response was malformed", code="malformed_response")
        return result

    def _post(self, body: dict[str, object], *, allow_empty: bool) -> dict[str, object]:
        data = json.dumps(body).encode("utf-8")
        headers = public_headers()
        if self.session_id:
            headers[_SESSION_HEADER] = self.session_id
        request = Request(self.url, data=data, headers=headers)
        opener = self.opener or cast(Opener, urlopen)
        try:
            with opener(request, timeout=self.timeout_s) as response:
                content_type = _header(response.headers, "Content-Type")
                session = _header(response.headers, _SESSION_HEADER)
                raw = response.read(_MAX_BYTES + 1)
        except TimeoutError as exc:
            raise CampaignError("whop provider timed out", code="timeout") from exc
        except HTTPError as exc:
            self._raise_http(exc)
        except (URLError, OSError) as exc:
            raise CampaignError("whop provider is unavailable", code="provider_unavailable") from exc
        if isinstance(session, str) and _safe_session(session):
            self.session_id = session
        if len(raw) > _MAX_BYTES:
            raise CampaignError("whop provider response was too large", code="oversized_response")
        if allow_empty and not raw.strip():
            return {}
        return _decode(raw, content_type or "")

    def _raise_http(self, exc: HTTPError) -> NoReturn:
        if exc.code in {400, 404} and self.session_id:
            raise CampaignError("whop session expired", code="stale_session") from exc
        raise CampaignError("whop provider is unavailable", code="provider_unavailable") from exc


def campaign_document(result: dict[str, object]) -> dict[str, object]:
    """Read a tools/call result. The RPC envelope is not stored."""
    if result.get("isError") is True:
        raise CampaignError("whop provider is unavailable", code="provider_unavailable")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return cast(dict[str, object], structured)
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise CampaignError(
                    "whop provider response was malformed",
                    code="malformed_response",
                ) from exc
            if isinstance(parsed, dict):
                return cast(dict[str, object], parsed)
    if "campaigns" in result:
        return result
    raise CampaignError("whop provider response was malformed", code="malformed_response")


def _raise_rpc(payload: dict[str, object]) -> None:
    error = payload.get("error")
    if not error:
        return
    code = error.get("code") if isinstance(error, dict) else None
    if code == -32001:
        raise CampaignError("whop session expired", code="stale_session")
    raise CampaignError("whop provider is unavailable", code="provider_unavailable")


def _decode(raw: bytes, content_type: str) -> dict[str, object]:
    if "text/event-stream" in content_type.lower():
        text = _sse_payload(raw)
    else:
        text = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CampaignError("whop provider response was malformed", code="malformed_response") from exc
    if not isinstance(parsed, dict):
        raise CampaignError("whop provider response was malformed", code="malformed_response")
    return cast(dict[str, object], parsed)


def _sse_payload(raw: bytes) -> str:
    messages: list[str] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        payload = line.removeprefix("data:").strip()
        if payload and payload != "[DONE]":
            messages.append(payload)
    if not messages:
        raise CampaignError("whop provider response was malformed", code="malformed_response")
    return messages[-1]


def _header(headers: object, name: str) -> str | None:
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    value = getter(name)
    return value if isinstance(value, str) else None


def _safe_session(value: str) -> bool:
    if not value or len(value) > 200:
        return False
    lowered = value.lower()
    if any(token in lowered for token in ("bearer", "token", "cookie", "password", "api_key")):
        return False
    return all(32 < ord(character) < 127 for character in value)


def _mutating_token(name: str) -> bool:
    tokens = [part for part in name.lower().replace("-", "_").split("_") if part]
    return any(token in _MUTATING_TOKENS for token in tokens)


def _label(value: str) -> bool:
    try:
        _plain(value, label="whop provider")
    except ValueError:
        return False
    return len(value) <= 40


def _walk_untrusted(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _FORGED_KEYS:
                raise CampaignError("whop provider status was forged", code="forged_status")
            if lowered in _SECRET_KEYS:
                raise CampaignError("whop provider response contained a secret", code="secret_rejected")
            _walk_untrusted(item)
        return
    if isinstance(value, list):
        for item in value:
            _walk_untrusted(item)
        return
    if isinstance(value, str) and _secret_text(value):
        raise CampaignError("whop provider response contained a secret", code="secret_rejected")


def _secret_text(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in _SECRET_TEXT)
