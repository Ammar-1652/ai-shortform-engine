"""Loopback page for one benchmark. It does not listen on a public address."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from clipforge.benchmark.service import BenchmarkError, readiness_report, show_run
from clipforge.storage import Database

LOOPBACK_HOST = "127.0.0.1"
_STATIC = Path(__file__).resolve().parent / "static"
_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
}
_FORBIDDEN = ("eval(", "innerHTML", "http://", "https://")


def require_loopback(host: str) -> None:
    if host != LOOPBACK_HOST:
        raise BenchmarkError(f"benchmark page binds to {LOOPBACK_HOST} only. Refusing host {host!r}.")


def open_benchmark_server(
    *,
    database: Database,
    work_root: Path,
    benchmark_id: str,
    host: str = LOOPBACK_HOST,
    port: int = 8767,
) -> ThreadingHTTPServer:
    require_loopback(host)
    if port < 0 or port > 65535:
        raise BenchmarkError(f"port {port} is outside 0..65535")
    handler = _handler(database, work_root.resolve(), benchmark_id)
    try:
        return ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise BenchmarkError("could not bind the benchmark page") from exc


def static_bundle_text() -> str:
    for name in _FILES:
        payload = (_STATIC / name).read_text(encoding="utf-8")
        for token in _FORBIDDEN:
            if token in payload:
                raise BenchmarkError(f"benchmark page contains a forbidden token {token}")
    return "PASS benchmark page: local only"


def _handler(database: Database, work_root: Path, benchmark_id: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            try:
                if ".." in path or "\\" in path:
                    raise BenchmarkError("path is not allowed")
                if path == "/":
                    _send(self, 200, _FILES["index.html"], (_STATIC / "index.html").read_bytes())
                elif path == "/app.js":
                    _send(self, 200, _FILES["app.js"], (_STATIC / "app.js").read_bytes())
                elif path == "/styles.css":
                    _send(self, 200, _FILES["styles.css"], (_STATIC / "styles.css").read_bytes())
                elif path == "/api/benchmark":
                    document = json.loads(show_run(database, work_root, benchmark_id))
                    report = readiness_report(database, work_root, benchmark_id).model_dump(mode="json")
                    payload = {"run": document, "readiness": report, "narration": _narration_labels(work_root)}
                    _send(self, 200, "application/json; charset=utf-8", json.dumps(payload).encode())
                else:
                    _send(self, 404, "application/json; charset=utf-8", b'{"error":"not found"}')
            except BenchmarkError as exc:
                error_body = json.dumps({"error": str(exc)}).encode("utf-8")
                _send(self, 400, "application/json; charset=utf-8", error_body)

        def log_message(self, fmt: str, *args: object) -> None:
            del fmt, args

    return Handler


def _narration_labels(work_root: Path) -> list[str]:
    folder = work_root / "voice" / "audio"
    if not folder.is_dir() or folder.is_symlink():
        return []
    labels: list[str] = []
    for path in sorted(folder.glob("*.json")):
        if path.is_symlink():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("script_label"), str):
            labels.append(str(payload["script_label"]))
    return labels


def _send(handler: BaseHTTPRequestHandler, status: int, content_type: str, payload: bytes) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)
