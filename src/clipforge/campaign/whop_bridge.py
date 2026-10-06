"""Loopback bridge for an already authenticated Whop connector.

The bridge process keeps any browser session. Clipforge sends one nonce and
receives sanitized campaign metadata. The nonce is not written by Clipforge.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from clipforge.campaign.providers import CampaignError
from clipforge.campaign.whop_mcp import reject_untrusted_document, session_handle

_SECRET_MARKERS = ("bearer ", "token=", "cookie=", "password=", "api_key", "authorization:")


class AuthenticatedBridgeProvider:
    """Read one sanitized envelope from a 127.0.0.1 connector."""

    provider_id = "whop"
    provider_version = "connector-1"
    mode = "browser_export"
    evidence_origin = "authenticated_connector"
    live_status = "authenticated_discovery"
    tool_name = "connector_handoff"

    def __init__(self, url: str, handle: str) -> None:
        self.url = url
        self._handle = handle

    @classmethod
    def from_environment(cls) -> AuthenticatedBridgeProvider:
        handle = session_handle()
        url = os.environ.get("CLIPFORGE_WHOP_CONNECTOR_URL", "").strip()
        if handle is None or not _loopback(url):
            raise CampaignError("whop_live: provider_unavailable", code="provider_unavailable")
        return cls(url, handle)

    def discover(self) -> dict[str, Any]:
        if not _loopback(self.url):
            raise CampaignError("whop_live: provider_unavailable", code="provider_unavailable")
        payload = json.dumps({"discover": "read_only"}).encode("utf-8")
        request = Request(
            self.url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "clipforge-whop",
                "X-Clipforge-Nonce": self._handle,
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read(1_000_000)
        except HTTPError as exc:
            if exc.code == 410:
                raise CampaignError(
                    "whop connector handle expired: stale_session",
                    code="stale_session",
                ) from exc
            raise CampaignError("whop_live: provider_unavailable", code="provider_unavailable") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise CampaignError("whop_live: provider_unavailable", code="provider_unavailable") from exc
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignError("whop provider response was malformed", code="malformed_response") from exc
        if not isinstance(parsed, dict):
            raise CampaignError("whop provider response was malformed", code="malformed_response")
        return _campaigns_from_envelope(self, parsed)


def serve_catalogue(bind: str, port: int, catalogue_path: Path, nonce: str, *, prove_session: bool) -> None:
    """Serve one sanitized catalogue on 127.0.0.1. The nonce is not logged."""
    if bind != "127.0.0.1":
        raise SystemExit(2)
    catalogue = json.loads(catalogue_path.read_text(encoding="utf-8"))
    if not isinstance(catalogue, dict) or not isinstance(catalogue.get("campaigns"), list):
        raise SystemExit(2)
    reject_untrusted_document(catalogue)
    used = False

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:
            nonlocal used
            if used:
                self._send(410, b"{}")
                return
            if self.headers.get("X-Clipforge-Nonce") != nonce:
                self._send(403, b"{}")
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8", errors="replace").lower()
            if any(marker in body for marker in _SECRET_MARKERS):
                self._send(422, b"{}")
                return
            used = True
            envelope = {
                "provider": {
                    "id": "whop",
                    "version": "connector-1",
                    "mode": "authenticated_connector",
                    "tool_name": "connector_handoff",
                    "session_proven": prove_session,
                },
                "account_context": {
                    "business_id": _plain_context(catalogue.get("business_id")),
                    "business_name": _plain_context(catalogue.get("business_name")),
                },
                "campaigns": catalogue["campaigns"],
            }
            encoded = json.dumps(envelope).encode("utf-8")
            self._send(200, encoded)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((bind, port), Handler)
    print(f"port={server.server_address[1]}", flush=True)
    server.serve_forever()


def _campaigns_from_envelope(provider: AuthenticatedBridgeProvider, payload: dict[str, Any]) -> dict[str, Any]:
    info = payload.get("provider")
    campaigns = payload.get("campaigns")
    if not isinstance(campaigns, list) or not campaigns:
        raise CampaignError("whop discovery was empty", code="empty_discovery")
    reject_untrusted_document({"campaigns": campaigns})
    if not isinstance(info, dict) or info.get("session_proven") is not True:
        raise CampaignError("whop_live: auth_required", code="auth_required")
    if info.get("mode") != "authenticated_connector":
        raise CampaignError("whop provider status was forged", code="forged_status")
    version = info.get("version")
    tool_name = info.get("tool_name")
    if isinstance(version, str):
        provider.provider_version = version
    if isinstance(tool_name, str):
        provider.tool_name = tool_name
    provider.evidence_origin = "authenticated_connector"
    provider.live_status = "authenticated_discovery"
    return {"campaigns": campaigns}


def _loopback(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
    )


def _plain_context(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 80:
        return "unknown"
    if any(marker in value.lower() for marker in _SECRET_MARKERS):
        return "unknown"
    return value


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Loopback Whop campaign bridge")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--catalogue", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--prove-session", action="store_true")
    args = parser.parse_args()
    serve_catalogue(
        args.bind,
        args.port,
        Path(args.catalogue),
        args.nonce,
        prove_session=args.prove_session,
    )


if __name__ == "__main__":
    main()
