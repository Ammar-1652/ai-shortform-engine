"""Loopback analytics page. It serves one project and does not listen on a public address."""

from __future__ import annotations

import json
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import ValidationError

from clipforge.analytics.compare import DIMENSIONS, ComparisonFilter
from clipforge.analytics.labels import set_labels
from clipforge.analytics.page import (
    comparison_document,
    labels_document,
    outcome_card,
    outcome_document,
    overview,
)
from clipforge.analytics.service import AnalyticsError
from clipforge.schemas.analytics import EditorialLabelAssignment
from clipforge.storage import Database

LOOPBACK_HOST = "127.0.0.1"
_STATIC = Path(__file__).resolve().parent / "static"
_STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_BODY_LIMIT = 64 * 1024
_FORBIDDEN_KEYS = {"automated", "approve", "approval", "publish", "rank", "score", "url", "uri"}
_BUNDLE_FORBIDDEN = ("eval(", "innerHTML", "http://", "https://", "cdn.", "fonts.googleapis")


def require_loopback(host: str) -> None:
    if host != LOOPBACK_HOST:
        raise AnalyticsError(
            f"analytics page binds to {LOOPBACK_HOST} only. Refusing host {host!r}. "
            "A public or LAN address is not accepted."
        )


def open_analytics_server(
    *,
    database: Database,
    project_id: str,
    work_root: Path,
    host: str = LOOPBACK_HOST,
    port: int = 8766,
) -> ThreadingHTTPServer:
    """Bind a loopback page for one project. Non-loopback hosts are refused first."""
    require_loopback(host)
    if port < 0 or port > 65535:
        raise AnalyticsError(f"port {port} is outside 0..65535")
    if not _ID.fullmatch(project_id):
        raise AnalyticsError("project id is not a safe identifier")
    handler = _handler(database, project_id, work_root.resolve())
    try:
        return ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise AnalyticsError(f"could not bind the analytics page on {host}:{port}") from exc


def verify_dashboard(database: Database, project_id: str) -> str:
    """Read the page bundle and confirm the project exists. This does not write."""
    from clipforge.storage import get_project

    with database.connect() as connection:
        get_project(connection, project_id)
    return static_bundle_text()


def static_bundle_text() -> str:
    """Read the packaged page. This does not write."""
    lines = ["PASS dashboard: loopback only", "PASS dashboard: local page"]
    for name in sorted(_STATIC_FILES):
        payload = _static(name).decode("utf-8")
        for token in _BUNDLE_FORBIDDEN:
            if token in payload:
                raise AnalyticsError(f"analytics page contains a forbidden token {token}")
        if ".." in payload or "\\" in payload:
            raise AnalyticsError("analytics page contains a path token")
    return "\n".join(lines)


def _handler(database: Database, project_id: str, work_root: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            path, query = _split_target(self.path)
            try:
                _reject_path(path)
                if path == "/":
                    _send_bytes(self, 200, _STATIC_FILES["index.html"], _static("index.html"))
                elif path == "/app.js":
                    _send_bytes(self, 200, _STATIC_FILES["app.js"], _static("app.js"))
                elif path == "/styles.css":
                    _send_bytes(self, 200, _STATIC_FILES["styles.css"], _static("styles.css"))
                elif path == "/api/analytics/overview":
                    _send_json(self, 200, overview(database, work_root, project_id))
                elif path == "/api/analytics/outcomes":
                    board = overview(database, work_root, project_id)
                    _send_json(self, 200, {"outcomes": board["outcomes"]})
                elif path.startswith("/api/analytics/outcomes/"):
                    outcome_id = path.removeprefix("/api/analytics/outcomes/")
                    _reject_id(outcome_id)
                    outcome_document(database, project_id, outcome_id)
                    _send_json(self, 200, outcome_card(database, work_root, project_id, outcome_id))
                elif path == "/api/analytics/comparison":
                    chosen, dimension = _comparison_query(_query_pairs(query))
                    _send_json(
                        self,
                        200,
                        comparison_document(
                            database,
                            project_id,
                            dimension=dimension,
                            comparison_filter=chosen,
                        ),
                    )
                elif path.startswith("/api/analytics/labels/"):
                    artifact_id = path.removeprefix("/api/analytics/labels/")
                    _reject_id(artifact_id)
                    _send_json(self, 200, labels_document(database, work_root, project_id, artifact_id))
                else:
                    _send_json(self, 404, {"error": "not found"})
            except AnalyticsError as exc:
                status = 404 if str(exc).startswith("no outcome") else 400
                _send_json(self, status, {"error": _public_error(exc)})

        def do_POST(self) -> None:
            path, _query = _split_target(self.path)
            if path != "/api/analytics/labels":
                _send_json(self, 404, {"error": "not found"})
                return
            try:
                payload = _read_json(self)
                _reject_keys(payload)
                assignment = EditorialLabelAssignment.model_validate(payload)
                if assignment.project_id != project_id:
                    raise AnalyticsError("label set belongs to a different project")
                label_set = set_labels(database, work_root, assignment)
            except json.JSONDecodeError:
                _send_json(self, 400, {"error": "label body is not valid JSON"})
                return
            except ValidationError:
                _send_json(self, 400, {"error": "label set is not valid"})
                return
            except AnalyticsError as exc:
                text = _public_error(exc)
                status = 409 if "reload before saving" in text else 400
                _send_json(self, status, {"error": text})
                return
            _send_json(
                self,
                201,
                {
                    "label_set_id": label_set.label_set_id,
                    "artifact_id": label_set.artifact_id,
                    "notes": label_set.notes,
                },
            )

        def log_message(self, fmt: str, *args: object) -> None:
            del fmt, args

    return Handler


def _split_target(target: str) -> tuple[str, str]:
    path, _, query = target.partition("?")
    return _percent_decode(path), query


def _query_pairs(query: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    if not query:
        return found
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        found.setdefault(_percent_decode(key), []).append(_percent_decode(value))
    return found


def _percent_decode(value: str) -> str:
    characters: list[str] = []
    index = 0
    while index < len(value):
        current = value[index]
        if current == "%" and index + 2 < len(value):
            try:
                characters.append(chr(int(value[index + 1 : index + 3], 16)))
            except ValueError:
                characters.append(current)
                index += 1
                continue
            index += 3
            continue
        characters.append(" " if current == "+" else current)
        index += 1
    return "".join(characters)


def _comparison_query(query: dict[str, list[str]]) -> tuple[ComparisonFilter, str]:
    allowed = {
        "dimension",
        "platform",
        "campaign_id",
        "geography",
        "profile_id",
        "source_asset_id",
        "observed_from",
        "observed_to",
        "measurement_window",
        "duration_bucket",
        "hook_type",
        "topic_tag",
        "cta",
        "format_tag",
        "audience_tag",
        "caption_presence",
        "broll_presence",
        "sfx_presence",
        "typography_presence",
        "diagram_presence",
        "reframing_strategy",
        "motion_library_version",
        "rank_band",
    }
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise AnalyticsError("comparison filter has an unknown field")
    values = {key: items[0] for key, items in query.items() if items}
    dimension = values.pop("dimension", "platform")
    if dimension not in DIMENSIONS:
        raise AnalyticsError(f"unknown comparison dimension {dimension}")
    try:
        chosen = ComparisonFilter(
            platform=values.get("platform"),
            campaign_id=values.get("campaign_id"),
            geography=values.get("geography"),
            profile_id=values.get("profile_id"),
            source_asset_id=values.get("source_asset_id"),
            observed_from=_time(values.get("observed_from")),
            observed_to=_time(values.get("observed_to")),
            measurement_window=values.get("measurement_window"),
            duration_bucket=values.get("duration_bucket"),
            hook_type=values.get("hook_type"),
            topic_tag=values.get("topic_tag"),
            cta=values.get("cta"),
            format_tag=values.get("format_tag"),
            audience_tag=values.get("audience_tag"),
            caption_presence=values.get("caption_presence"),
            broll_presence=values.get("broll_presence"),
            sfx_presence=values.get("sfx_presence"),
            typography_presence=values.get("typography_presence"),
            diagram_presence=values.get("diagram_presence"),
            reframing_strategy=values.get("reframing_strategy"),
            motion_library_version=values.get("motion_library_version"),
            rank_band=values.get("rank_band"),
        )
    except ValueError as exc:
        raise AnalyticsError(str(exc)) from exc
    return chosen, dimension


def _time(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed


def _reject_path(path: str) -> None:
    if "\\" in path or "\x00" in path or ".." in path.split("/"):
        raise AnalyticsError("path is not allowed")


def _reject_id(value: str) -> None:
    if _ID.fullmatch(value) is None:
        raise AnalyticsError("identifier is not allowed")


def _reject_keys(payload: object) -> None:
    if not isinstance(payload, dict):
        raise AnalyticsError("label body must be an object")
    found = _FORBIDDEN_KEYS.intersection(payload)
    if found:
        raise AnalyticsError("automated approval fields are rejected")
    labels = payload.get("labels")
    if isinstance(labels, dict) and _FORBIDDEN_KEYS.intersection(labels):
        raise AnalyticsError("automated approval fields are rejected")


def _read_json(handler: BaseHTTPRequestHandler) -> object:
    length = int(handler.headers.get("Content-Length", "0"))
    if length < 0 or length > _BODY_LIMIT:
        raise AnalyticsError("label body is too large")
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def _static(name: str) -> bytes:
    if name not in _STATIC_FILES:
        raise AnalyticsError("unknown page")
    path = _STATIC / name
    if path.is_symlink() or not path.is_file():
        raise AnalyticsError("static file is not a regular file")
    resolved = path.resolve()
    if resolved.parent != _STATIC.resolve():
        raise AnalyticsError("static file escaped the package")
    return path.read_bytes()


def _send_bytes(handler: BaseHTTPRequestHandler, status: int, content_type: str, payload: bytes) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, object]) -> None:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    _send_bytes(handler, status, "application/json; charset=utf-8", body)


def _public_error(exc: BaseException) -> str:
    text = str(exc)
    if any(token in text for token in ("/tmp/", "/home/", "/Users/", "\\")):
        return "request was rejected"
    return text
