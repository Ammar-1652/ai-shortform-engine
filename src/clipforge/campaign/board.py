"""Loopback campaign board. It does not listen on a public address."""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from clipforge.campaign.acquisition import (
    board_acquisition,
    board_acquisitions,
    board_envato,
    board_policy,
)
from clipforge.campaign.aggregate import (
    board_production,
    board_production_delivery,
    board_production_source,
    board_productions,
)
from clipforge.campaign.operator import (
    board_campaign,
    board_campaigns,
    board_run,
    board_runs,
    board_source,
    board_sources,
)
from clipforge.campaign.providers import CampaignError
from clipforge.errors import ClipforgeError
from clipforge.storage import Database

LOOPBACK_HOST = "127.0.0.1"
_STATIC = Path(__file__).resolve().parent / "board_static"
_STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BUNDLE_FORBIDDEN = ("eval(", "innerHTML", "http://", "https://", "cdn.", "fonts.googleapis", "autoplay")


def require_loopback(host: str) -> None:
    if host != LOOPBACK_HOST:
        raise CampaignError(
            f"campaign board binds to {LOOPBACK_HOST} only",
            code="loopback_required",
        )


def open_campaign_board(
    *,
    work_root: Path,
    host: str = LOOPBACK_HOST,
    port: int = 8772,
    database: Database | None = None,
) -> ThreadingHTTPServer:
    """Bind the board. A non-loopback host is refused before the socket is created."""
    require_loopback(host)
    if port < 0 or port > 65535:
        raise CampaignError("port is outside 0..65535", code="invalid_document")
    static_bundle_text()
    handler = _handler(work_root.resolve(), database)
    try:
        return ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise CampaignError("could not bind the campaign board", code="loopback_required") from exc


def static_bundle_text() -> str:
    for name in sorted(_STATIC_FILES):
        payload = (_STATIC / name).read_text(encoding="utf-8")
        for token in _BUNDLE_FORBIDDEN:
            if token in payload:
                raise CampaignError(
                    f"campaign board contains a forbidden token {token}",
                    code="invalid_document",
                )
    return "PASS campaign board"


def _handler(work_root: Path, database: Database | None) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if ".." in path or "\\" in path:
                _send(self, 400, b"bad path")
                return
            try:
                if path == "/":
                    _send(self, 200, (_STATIC / "index.html").read_bytes(), _STATIC_FILES["index.html"])
                elif path == "/app.js":
                    _send(self, 200, (_STATIC / "app.js").read_bytes(), _STATIC_FILES["app.js"])
                elif path == "/styles.css":
                    _send(self, 200, (_STATIC / "styles.css").read_bytes(), _STATIC_FILES["styles.css"])
                elif path == "/api/campaigns":
                    _send_json(self, board_campaigns())
                elif path.startswith("/api/campaign-productions/") and path.endswith("/delivery"):
                    run_id = path.removeprefix("/api/campaign-productions/").removesuffix("/delivery")
                    _reject_id(run_id)
                    _send_json(self, board_production_delivery(work_root, run_id))
                elif path.startswith("/api/campaign-productions/") and "/source/" in path:
                    rest = path.removeprefix("/api/campaign-productions/")
                    run_id, source_id = rest.split("/source/", 1)
                    _reject_id(run_id)
                    _reject_id(source_id)
                    _send_json(self, board_production_source(work_root, run_id, source_id))
                elif path.startswith("/api/campaign-productions/"):
                    run_id = path.removeprefix("/api/campaign-productions/")
                    _reject_id(run_id)
                    _send_json(self, board_production(work_root, run_id))
                elif path.startswith("/api/campaign-runs/"):
                    _send_run(self, work_root, path.removeprefix("/api/campaign-runs/"))
                elif path.startswith("/api/acquisitions/"):
                    acquisition_id = path.removeprefix("/api/acquisitions/")
                    _reject_id(acquisition_id)
                    _send_json(self, board_acquisition(work_root, acquisition_id))
                elif path.startswith("/api/campaigns/") and path.endswith("/sources"):
                    campaign_id = path.removeprefix("/api/campaigns/").removesuffix("/sources")
                    _reject_id(campaign_id)
                    _send_json(self, board_sources(campaign_id, database))
                elif path.startswith("/api/campaigns/") and path.endswith("/runs"):
                    campaign_id = path.removeprefix("/api/campaigns/").removesuffix("/runs")
                    _reject_id(campaign_id)
                    _send_json(self, board_runs(work_root, campaign_id))
                elif path.startswith("/api/campaigns/") and path.endswith("/acquisitions"):
                    campaign_id = path.removeprefix("/api/campaigns/").removesuffix("/acquisitions")
                    _reject_id(campaign_id)
                    _send_json(self, board_acquisitions(work_root, campaign_id))
                elif path.startswith("/api/campaigns/") and path.endswith("/envato"):
                    campaign_id = path.removeprefix("/api/campaigns/").removesuffix("/envato")
                    _reject_id(campaign_id)
                    _send_json(self, board_envato(work_root, campaign_id))
                elif path.startswith("/api/campaigns/") and path.endswith("/productions"):
                    campaign_id = path.removeprefix("/api/campaigns/").removesuffix("/productions")
                    _reject_id(campaign_id)
                    _send_json(self, board_productions(work_root, campaign_id))
                elif path.startswith("/api/campaigns/") and path.endswith("/policy"):
                    campaign_id = path.removeprefix("/api/campaigns/").removesuffix("/policy")
                    _reject_id(campaign_id)
                    _send_json(self, board_policy(campaign_id))
                elif path.startswith("/api/campaigns/"):
                    campaign_id = path.removeprefix("/api/campaigns/").strip("/")
                    _reject_id(campaign_id)
                    _send_json(self, board_campaign(campaign_id, work_root, database))
                else:
                    _send(self, 404, b"not found")
            except ClipforgeError as exc:
                code = getattr(exc, "code", "invalid_document")
                _send(self, 400, str(code).encode("utf-8"))

        def do_POST(self) -> None:
            _send(self, 405, b"read only")

        def do_PUT(self) -> None:
            _send(self, 405, b"read only")

        def do_DELETE(self) -> None:
            _send(self, 405, b"read only")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def _send_run(handler: BaseHTTPRequestHandler, work_root: Path, rest: str) -> None:
    marker = "/source/"
    if marker in rest:
        run_id, source_id = rest.split(marker, 1)
        _reject_id(run_id)
        _reject_id(source_id)
        _send_json(handler, board_source(work_root, run_id, source_id))
        return
    _reject_id(rest)
    _send_json(handler, board_run(work_root, rest))


def _reject_id(value: str) -> None:
    if not _ID.fullmatch(value):
        raise CampaignError("id is not safe", code="malformed_id")


def _send_json(handler: BaseHTTPRequestHandler, payload: dict[str, object]) -> None:
    _send(handler, 200, json.dumps(payload).encode("utf-8"), "application/json")


def _send(handler: BaseHTTPRequestHandler, status: int, body: bytes, content_type: str = "text/plain") -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)
