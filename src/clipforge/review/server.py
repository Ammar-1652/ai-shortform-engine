"""Loopback review server. It serves the page, review JSON, and preview MP4s."""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.review.service import (
    LOOPBACK_HOST,
    candidate_card,
    decision_json,
    parse_decision_body,
    preview_media_path,
    record_decision,
    record_hero_decision,
    review_board,
)
from clipforge.storage import Database

_STATIC = Path(__file__).resolve().parent / "static"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BODY_LIMIT = 64 * 1024


def require_loopback(host: str) -> None:
    if host != LOOPBACK_HOST:
        raise MediaError(
            f"review server binds to {LOOPBACK_HOST} only. Refusing host {host!r}. "
            "A public or LAN address is not accepted."
        )


def open_hero_review_server(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    host: str = LOOPBACK_HOST,
    port: int = 8765,
) -> ThreadingHTTPServer:
    """Validate the current Hero set, then bind a loopback server."""
    from clipforge.review.hero_board import hero_review_board

    require_loopback(host)
    if port < 0 or port > 65535:
        raise MediaError(f"port {port} is outside 0..65535")
    hero_review_board(database, source_asset_id, work_root)
    handler = _handler(database, source_asset_id, work_root.resolve(), surface="hero")
    try:
        return ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise MediaError(f"could not bind the review server on {host}:{port}: {exc}") from exc


def open_review_server(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    host: str = LOOPBACK_HOST,
    port: int = 8765,
) -> ThreadingHTTPServer:
    """Validate the preview set, then bind a loopback server. The caller serves it."""
    require_loopback(host)
    if port < 0 or port > 65535:
        raise MediaError(f"port {port} is outside 0..65535")
    review_board(database, source_asset_id, work_root)
    handler = _handler(database, source_asset_id, work_root.resolve(), surface="rough")
    try:
        return ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise MediaError(f"could not bind the review server on {host}:{port}: {exc}") from exc


def _handler(
    database: Database,
    source_asset_id: str,
    work_root: Path,
    *,
    surface: str,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            try:
                if path == "/":
                    page = "hero.html" if surface == "hero" else "index.html"
                    _send_bytes(self, 200, "text/html; charset=utf-8", _static(page))
                elif path == "/app.js":
                    _send_bytes(self, 200, "text/javascript; charset=utf-8", _static("app.js"))
                elif path == "/hero.js":
                    _send_bytes(self, 200, "text/javascript; charset=utf-8", _static("hero.js"))
                elif path == "/styles.css":
                    _send_bytes(self, 200, "text/css; charset=utf-8", _static("styles.css"))
                elif path == "/api/review":
                    _send_json(self, 200, review_board(database, source_asset_id, work_root))
                elif path == "/api/hero-review":
                    _send_hero_board(self, database, source_asset_id, work_root)
                elif path.startswith("/api/hero-review/hero/"):
                    hero_id = path.removeprefix("/api/hero-review/hero/")
                    _reject_id(hero_id)
                    _send_hero_card(self, database, source_asset_id, hero_id, work_root)
                elif path.startswith("/api/review/candidates/"):
                    candidate_id = path.removeprefix("/api/review/candidates/")
                    _reject_id(candidate_id)
                    _send_json(self, 200, candidate_card(database, source_asset_id, candidate_id, work_root))
                elif path.startswith("/media/candidate/"):
                    candidate_id = path.removeprefix("/media/candidate/")
                    _reject_id(candidate_id)
                    _send_media(self, preview_media_path(database, source_asset_id, candidate_id, work_root))
                elif path.startswith("/media/hero/"):
                    from clipforge.hero.show import hero_media_path

                    candidate_id = path.removeprefix("/media/hero/")
                    _reject_id(candidate_id)
                    _send_media(self, hero_media_path(database, source_asset_id, candidate_id, work_root))
                else:
                    _send_json(self, 404, {"error": "not found"})
            except MediaError as exc:
                status = 404 if str(exc).startswith("unknown candidate") else 409
                _send_json(self, status, {"error": str(exc)})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/api/review/decisions":
                _send_json(self, 404, {"error": "not found"})
                return
            try:
                payload = _read_json(self)
                context, decision, reviewer, notes = parse_decision_body(payload)
                if context.source_asset_id != source_asset_id:
                    raise MediaError(
                        "the preview set changed while this review page was open; reload before saving"
                    )
                if context.subject_kind == "hero":
                    review = record_hero_decision(
                        database=database,
                        work_root=work_root,
                        context=context,
                        decision=decision,
                        reviewer_id=reviewer,
                        notes=notes,
                    )
                else:
                    review = record_decision(
                        database=database,
                        work_root=work_root,
                        context=context,
                        decision=decision,
                        reviewer_id=reviewer,
                        notes=notes,
                    )
            except json.JSONDecodeError:
                _send_json(self, 400, {"error": "review body is not valid JSON"})
                return
            except ValidationError as exc:
                _send_json(self, 400, {"error": f"review decision is not valid: {exc}"})
                return
            except MediaError as exc:
                status = 400
                text = str(exc)
                if text.startswith("unknown candidate"):
                    status = 404
                elif "reload before saving" in text or "not reviewable" in text:
                    status = 409
                _send_json(self, status, {"error": text})
                return
            _send_json(self, 201, decision_json(review))

        def log_message(self, fmt: str, *args: object) -> None:
            del fmt, args

    return Handler


def _send_hero_board(
    handler: BaseHTTPRequestHandler,
    database: Database,
    source_asset_id: str,
    work_root: Path,
) -> None:
    from clipforge.review.hero_board import hero_review_board

    _send_json(handler, 200, hero_review_board(database, source_asset_id, work_root))


def _send_hero_card(
    handler: BaseHTTPRequestHandler,
    database: Database,
    source_asset_id: str,
    hero_id: str,
    work_root: Path,
) -> None:
    from clipforge.review.hero_board import hero_review_card

    _send_json(handler, 200, hero_review_card(database, source_asset_id, hero_id, work_root))


def _reject_id(candidate_id: str) -> None:
    if not _ID.fullmatch(candidate_id) or candidate_id in {".", ".."}:
        raise MediaError(f"unknown candidate {candidate_id}")


def _static(name: str) -> bytes:
    path = _STATIC / name
    if path.is_symlink() or not path.is_file():
        raise MediaError(f"review static file {name} is missing")
    return path.read_bytes()


def _read_json(handler: BaseHTTPRequestHandler) -> object:
    raw_length = handler.headers.get("Content-Length", "0")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise MediaError("Content-Length is not an integer") from exc
    if length < 0 or length > _BODY_LIMIT:
        raise MediaError("review body is too large")
    body = handler.rfile.read(length)
    return json.loads(body.decode("utf-8"))


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, object]) -> None:
    _send_bytes(handler, status, "application/json; charset=utf-8", json.dumps(payload).encode("utf-8"))


def _send_bytes(handler: BaseHTTPRequestHandler, status: int, content_type: str, payload: bytes) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(payload)


def _send_media(handler: BaseHTTPRequestHandler, path: Path) -> None:
    size = path.stat().st_size
    start, end = 0, size - 1
    status = 200
    requested = handler.headers.get("Range")
    if requested:
        if not requested.startswith("bytes=") or "," in requested:
            _send_json(handler, 416, {"error": "only a single byte range is accepted"})
            return
        span = requested.removeprefix("bytes=")
        left, _, right = span.partition("-")
        try:
            start = int(left) if left else 0
            end = int(right) if right else size - 1
        except ValueError:
            _send_json(handler, 416, {"error": "byte range is not valid"})
            return
        if start < 0 or end < start or start >= size:
            handler.send_response(416)
            handler.send_header("Content-Range", f"bytes */{size}")
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        end = min(end, size - 1)
        status = 206
    length = end - start + 1
    with path.open("rb") as handle:
        handle.seek(start)
        chunk = handle.read(length)
    handler.send_response(status)
    handler.send_header("Content-Type", "video/mp4")
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Content-Length", str(len(chunk)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    if status == 206:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    handler.end_headers()
    handler.wfile.write(chunk)
