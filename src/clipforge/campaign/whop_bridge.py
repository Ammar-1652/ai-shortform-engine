"""Loopback handoff for a local Whop catalogue.

The process serves one sanitized file. It does not create an account session
and it does not accept a flag that would label the file as authenticated.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from clipforge.campaign.providers import CampaignError
from clipforge.campaign.whop_mcp import reject_untrusted_document, session_handle

_SECRET_MARKERS = ("bearer ", "token=", "cookie=", "password=", "api_key", "authorization:", "<", ">")
_PATH_MARKERS = ("/home/", "/tmp/", "/users/", "file:", "..", "\\")
_MAX_BODY = 1_000_000
_PATH = "/handoff"
_FORBIDDEN_PROVIDER_KEYS = {"session_proven", "live_status", "evidence_origin", "session_id", "authorization"}


class AuthenticatedBridgeProvider:
    """Read one sanitized envelope from a 127.0.0.1 connector.

    This handoff is a test double. It cannot promote itself to authenticated discovery.
    """

    provider_id = "whop"
    provider_version = "connector-1"
    mode = "browser_export"
    evidence_origin = "test_double"
    live_status = "not_configured"
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
        parsed = urlsplit(self.url)
        payload = json.dumps({"discover": "read_only"}).encode("utf-8")
        request = Request(
            self.url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Content-Length": str(len(payload)),
                "User-Agent": "clipforge-whop",
                "Origin": f"http://127.0.0.1:{parsed.port}",
                "X-Clipforge-Nonce": self._handle,
            },
            method="POST",
        )
        try:
            with _no_redirect().open(request, timeout=20) as response:
                status = getattr(response, "status", 200)
                raw = response.read(_MAX_BODY + 1)
        except CampaignError:
            raise
        except HTTPError as exc:
            if exc.code in {409, 410}:
                message = "whop connector handle expired: stale_session"
                raise CampaignError(message, code="stale_session") from exc
            raise CampaignError("whop_live: provider_unavailable", code="provider_unavailable") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise CampaignError("whop_live: provider_unavailable", code="provider_unavailable") from exc
        if status in {301, 302, 303, 307, 308}:
            raise CampaignError("whop provider redirect was rejected", code="provider_unavailable")
        if len(raw) > _MAX_BODY:
            raise CampaignError("whop provider response was too large", code="oversized_response")
        try:
            parsed_body = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignError("whop provider response was malformed", code="malformed_response") from exc
        if not isinstance(parsed_body, dict):
            raise CampaignError("whop provider response was malformed", code="malformed_response")
        return _campaigns_from_envelope(self, parsed_body)


def serve_catalogue(
    bind: str,
    port: int,
    catalogue_path: Path,
    nonce: str,
    *,
    expires_at: float,
    work_root: Path | None = None,
) -> None:
    """Serve one sanitized catalogue on 127.0.0.1. The nonce is not logged."""
    if bind != "127.0.0.1":
        raise SystemExit(2)
    if not math.isfinite(expires_at) or expires_at > time.time() + 86_400:
        raise SystemExit(2)
    if not _nonce_ok(nonce):
        raise SystemExit(2)
    root = work_root or catalogue_path.parent
    _confine(root, catalogue_path)
    try:
        catalogue = json.loads(catalogue_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(2) from exc
    if not isinstance(catalogue, dict) or not isinstance(catalogue.get("campaigns"), list):
        raise SystemExit(2)
    try:
        reject_untrusted_document(catalogue)
        rendered = json.dumps(catalogue)
        _reject_markers(rendered)
        lowered = rendered.lower()
        if any(marker in lowered for marker in _PATH_MARKERS):
            raise CampaignError("whop provider response contained a secret", code="secret_rejected")
    except CampaignError as exc:
        raise SystemExit(2) from exc
    state = {"used": False, "inflight": False}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server: _BridgeServer

        def do_POST(self) -> None:
            if urlsplit(self.path).path != _PATH:
                self._send(404, b"{}")
                return
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin", "")
            expected_host = f"127.0.0.1:{self.server.server_address[1]}"
            expected_origin = f"http://{expected_host}"
            if host != expected_host or origin != expected_origin:
                self._send(403, b"{}")
                return
            if _chunked(self.headers.get("Transfer-Encoding")):
                self._send(411, b"{}")
                return
            content_type = self.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].strip().lower() != "application/json":
                self._send(415, b"{}")
                return
            lengths = self.headers.get_all("Content-Length") or []
            if not lengths:
                self._send(411, b"{}")
                return
            if len(lengths) != 1:
                self._send(400, b"{}")
                return
            length = _content_length(lengths[0])
            if length is None:
                self._send(400, b"{}")
                return
            if length > _MAX_BODY:
                self._send(413, b"{}")
                return
            presented = self.headers.get("X-Clipforge-Nonce", "")
            now = time.time()
            with lock:
                if now > expires_at:
                    self._send(410, b"{}")
                    return
                if presented != nonce or not _nonce_ok(presented):
                    self._send(403, b"{}")
                    return
                if state["used"] or state["inflight"]:
                    self._send(410, b"{}")
                    return
                state["inflight"] = True
            try:
                body = self.rfile.read(length)
                if len(body) != length:
                    self._send(400, b"{}")
                    return
                try:
                    json.loads(body)
                except json.JSONDecodeError:
                    self._send(400, b"{}")
                    return
                lowered = body.decode("utf-8", errors="replace").lower()
                if any(marker in lowered for marker in _SECRET_MARKERS):
                    self._send(422, b"{}")
                    return
                envelope = _envelope(catalogue)
                encoded = json.dumps(envelope).encode("utf-8")
                self._send(200, encoded)
            finally:
                with lock:
                    state["inflight"] = False
                    state["used"] = True
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def do_GET(self) -> None:
            self._send(405, b"{}")

        def do_PUT(self) -> None:
            self._send(405, b"{}")

        def do_DELETE(self) -> None:
            self._send(405, b"{}")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class _BridgeServer(ThreadingHTTPServer):
        pass

    server = _BridgeServer((bind, port), Handler)
    print(f"port={server.server_address[1]}", flush=True)
    server.serve_forever()


def _envelope(catalogue: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": {
            "id": "whop",
            "version": "connector-1",
            "mode": "test_double",
            "tool_name": "connector_handoff",
        },
        "account_context": {
            "business_id": _plain_context(catalogue.get("business_id")),
            "business_name": _plain_context(catalogue.get("business_name")),
        },
        "request_id": "handoff-1",
        "exported_at": catalogue.get("exported_at") if isinstance(catalogue.get("exported_at"), str) else None,
        "campaigns": catalogue["campaigns"],
    }


def _campaigns_from_envelope(provider: AuthenticatedBridgeProvider, payload: dict[str, Any]) -> dict[str, Any]:
    info = payload.get("provider")
    campaigns = payload.get("campaigns")
    if not isinstance(info, dict) or not isinstance(campaigns, list):
        raise CampaignError("whop provider response was malformed", code="malformed_response")
    if _FORBIDDEN_PROVIDER_KEYS.intersection(info):
        raise CampaignError("whop provider status was forged", code="forged_status")
    if info.get("mode") != "test_double":
        raise CampaignError("whop provider status was forged", code="forged_status")
    reject_untrusted_document({"campaigns": campaigns})
    version = info.get("version")
    tool_name = info.get("tool_name")
    if isinstance(version, str) and version:
        provider.provider_version = version
    if isinstance(tool_name, str) and tool_name:
        provider.tool_name = tool_name
    provider.evidence_origin = "test_double"
    provider.live_status = "not_configured"
    exported = payload.get("exported_at")
    document: dict[str, Any] = {"campaigns": _with_business(campaigns, payload.get("account_context"))}
    if isinstance(exported, str):
        document["exported_at"] = exported
    return document


def _with_business(campaigns: list[object], context: object) -> list[object]:
    business_id = "unknown"
    if isinstance(context, dict):
        business_id = _plain_context(context.get("business_id"))
    copied: list[object] = []
    for item in campaigns:
        if not isinstance(item, dict):
            raise CampaignError("whop provider response was malformed", code="malformed_response")
        row = dict(item)
        if "business_id" not in row and business_id != "unknown":
            row["business_id"] = business_id
        copied.append(row)
    return copied


def _loopback(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and parsed.path == _PATH
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and parsed.port is not None
    )


def _nonce_ok(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    return all(character.isalnum() or character in "._:-" for character in value)


def _plain_context(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 80:
        return "unknown"
    if any(marker in value.lower() for marker in _SECRET_MARKERS):
        return "unknown"
    return value


def _reject_markers(text: str) -> None:
    lowered = text.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        raise CampaignError("whop provider response contained a secret", code="secret_rejected")


def _chunked(value: str | None) -> bool:
    if not value:
        return False
    return "chunked" in value.lower()


def _confine(root: Path, candidate: Path) -> None:
    current = candidate
    while True:
        if current.is_symlink():
            raise SystemExit(2)
        if current.parent == current:
            break
        current = current.parent
    if root.is_symlink():
        raise SystemExit(2)
    try:
        contained = candidate.resolve()
        base = root.resolve()
    except OSError as exc:
        raise SystemExit(2) from exc
    if contained != base and base not in contained.parents:
        raise SystemExit(2)


def _content_length(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed


def _no_redirect() -> OpenerDirector:
    class _Reject(HTTPRedirectHandler):
        def redirect_request(
            self,
            req: object,
            fp: object,
            code: int,
            msg: object,
            headers: object,
            newurl: str,
        ) -> None:
            raise CampaignError("whop provider redirect was rejected", code="provider_unavailable")

    return build_opener(_Reject)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Loopback Whop campaign handoff")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--catalogue", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--nonce-fd", type=int, required=True)
    parser.add_argument("--expires-in", type=float, default=30)
    args = parser.parse_args()
    nonce = os.read(args.nonce_fd, 200).decode("utf-8").strip()
    os.close(args.nonce_fd)
    serve_catalogue(
        args.bind,
        args.port,
        Path(args.catalogue),
        nonce,
        expires_at=time.time() + args.expires_in,
        work_root=Path(args.work_dir),
    )


if __name__ == "__main__":
    main()
