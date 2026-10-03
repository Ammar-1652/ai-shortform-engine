"""Loopback review server. No public bind and no filesystem paths in JSON."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.preview.backend import FakeRoughRenderBackend
from clipforge.review.server import open_review_server
from clipforge.review.service import LOOPBACK_HOST, parse_decision_body
from tests.candidate_support import SOURCE_ID
from tests.preview_support import isolated_segments, mine, ready_stack, render, short_profile

pytestmark = pytest.mark.review
_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")


def _rendered(tmp_path: Path):
    pieces, duration = isolated_segments(1)
    fixture = ready_stack(tmp_path, segments=pieces, duration_us=duration)
    mine(fixture, profile=short_profile())
    render(fixture, FakeRoughRenderBackend())
    return fixture


def _start(fixture):
    server = open_review_server(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, port


def _request(port: int, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes, str]:
    connection = HTTPConnection(LOOPBACK_HOST, port, timeout=10)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    content_type = response.getheader("Content-Type") or ""
    connection.close()
    return response.status, payload, content_type


def test_public_bind_is_rejected(tmp_path: Path) -> None:
    fixture = _rendered(tmp_path)
    for host in ("0.0.0.0", "192.168.1.20", "example.com"):
        with pytest.raises(MediaError, match=r"127\.0\.0\.1"):
            open_review_server(
                database=fixture.database,
                source_asset_id=SOURCE_ID,
                work_root=fixture.work,
                host=host,
                port=0,
            )


def test_api_media_and_post(tmp_path: Path) -> None:
    fixture = _rendered(tmp_path)
    server, port = _start(fixture)
    try:
        status, payload, content_type = _request(port, "GET", "/api/review")
        assert status == 200
        assert content_type.startswith("application/json")
        board = json.loads(payload)
        text = payload.decode("utf-8")
        assert "preview.mp4" not in text
        assert "http://" not in text
        assert "https://" not in text
        assert "/home/" not in text
        card = board["candidates"][0]
        assert card["preview_url"].startswith("/media/candidate/")
        media_status, media, media_type = _request(port, "GET", card["preview_url"])
        assert media_status == 200
        assert media_type == "video/mp4"
        assert media[4:8] == b"ftyp"
        missing, _body, _kind = _request(port, "GET", "/media/candidate/missing-candidate")
        assert missing == 404
        escaped, _body, _kind = _request(port, "GET", "/media/candidate/..")
        assert escaped == 404
        page, html, page_type = _request(port, "GET", "/")
        assert page == 200
        assert "text/html" in page_type
        assert b"autoplay" not in html
        body = {
            "source_asset_id": board["source_asset_id"],
            "project_id": board["project_id"],
            "artifact_id": board["artifact_id"],
            "preview_set_id": board["preview_set_id"],
            "manifest_sha256": board["manifest_sha256"],
            "candidate_id": card["candidate_id"],
            "decision": "approved",
            "reviewer_id": "ada",
            "notes": "<script>alert(1)</script>",
        }
        bad_json, _body, _kind = _request(port, "POST", "/api/review/decisions", b"{")
        assert bad_json == 400
        extra = dict(body)
        extra["html"] = "<b>"
        unknown, _body, _kind = _request(port, "POST", "/api/review/decisions", json.dumps(extra).encode())
        assert unknown == 400
        automated = dict(body)
        automated["automated"] = True
        rejected, _body, _kind = _request(port, "POST", "/api/review/decisions", json.dumps(automated).encode())
        assert rejected == 400
        stale = dict(body)
        stale["manifest_sha256"] = "c" * 64
        conflict, _body, _kind = _request(port, "POST", "/api/review/decisions", json.dumps(stale).encode())
        assert conflict == 409
        created, saved, _kind = _request(port, "POST", "/api/review/decisions", json.dumps(body).encode())
        assert created == 201
        first = json.loads(saved)
        assert first["notes"] == "<script>alert(1)</script>"
        again, second_body, _kind = _request(port, "POST", "/api/review/decisions", json.dumps(body).encode())
        assert again == 201
        second = json.loads(second_body)
        assert second["review_id"] != first["review_id"]
        assert first["notes"] == "<script>alert(1)</script>"
        remote_status, remote_body, _kind = _request(port, "GET", "/media/candidate/https%3A%2F%2Fevil.example")
        assert remote_status == 404
        assert remote_body.startswith(b'{"error":')
        linked = fixture.work.rglob("preview.mp4")
        preview = next(linked)
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"not-a-preview")
        preview.unlink()
        preview.symlink_to(outside)
        denied, denied_body, _kind = _request(port, "GET", card["preview_url"])
        assert denied != 200
        assert b"not-a-preview" not in denied_body
    finally:
        server.shutdown()
        server.server_close()


def test_static_bundle_has_no_remote_execution() -> None:
    static = _ROOT / "src" / "clipforge" / "review" / "static"
    names = sorted(path.name for path in static.iterdir() if path.is_file())
    combined = "\n".join((static / name).read_text(encoding="utf-8") for name in names)
    assert "http://" not in combined
    assert "https://" not in combined
    assert "eval(" not in combined
    assert "dangerouslySetInnerHTML" not in combined
    assert "innerHTML" not in combined
    with pytest.raises(MediaError, match="automated"):
        parse_decision_body({"decision": "approved", "reviewer_id": "ada", "automated": True})
    with pytest.raises(MediaError, match="unknown review fields"):
        parse_decision_body({"decision": "approved", "reviewer_id": "ada", "path": "/tmp/secret"})
