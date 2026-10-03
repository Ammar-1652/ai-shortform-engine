"""Open the Hero review page in the local browser. This does not download one."""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.hero.alignment import FakeForcedAlignment
from clipforge.hero.backend import FakeHeroRenderBackend
from clipforge.hero.service import render_hero_drafts
from clipforge.preview.browser import resolve_browser
from clipforge.review.server import open_hero_review_server
from clipforge.review.service import LOOPBACK_HOST
from tests.candidate_support import SOURCE_ID
from tests.test_hero_review import _PHRASE, _hero_stack

pytestmark = [pytest.mark.hero, pytest.mark.review]


def test_local_browser_reviews_a_hero_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")
    try:
        browser = resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    fixture = _hero_stack(tmp_path / "stack", (_PHRASE,))
    server = open_hero_review_server(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        port=0,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = int(server.server_address[1])
    url = f"http://{LOOPBACK_HOST}:{port}/"
    debug_port = _free_port()
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    chrome = subprocess.Popen(
        [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-background-networking",
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        page = _page_socket(debug_port, url)
        first = _eval(
            page,
            """
            (async () => {
              const deadline = Date.now() + 8000;
              while (Date.now() < deadline && !document.body.innerText.includes("Café")) {
                await new Promise((resolve) => setTimeout(resolve, 100));
              }
              const video = document.querySelector("video");
              const style = video ? getComputedStyle(video) : null;
              return {
                text: document.body.innerText,
                controls: Boolean(video && video.controls),
                autoplay: Boolean(video && video.autoplay),
                aspect: style ? style.aspectRatio : "",
                width: video ? video.clientWidth : 0,
                height: video ? video.clientHeight : 0,
                images: document.querySelectorAll("img").length
              };
            })()
            """,
        )
        assert first["controls"] is True
        assert first["autoplay"] is False
        assert first["height"] > first["width"]
        aspect = str(first["aspect"])
        assert "9" in aspect and "16" in aspect
        assert "Café" in first["text"]
        assert "説明" in first["text"]
        assert "$12.50" in first["text"]
        assert "unavailable" in first["text"]
        assert first["images"] == 0
        render_hero_drafts(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            work_root=fixture.work,
            force=True,
            backend=FakeHeroRenderBackend(),
            alignment_backend=FakeForcedAlignment(),
        )
        stale = _eval(
            page,
            """
            (async () => {
              const article = document.querySelector("article");
              article.querySelector("input").value = "ada";
              article.querySelector("textarea").value = "Café 説明 $12.50 <unsafe>&\\\"quoted\\\"";
              article.querySelector("input[value=changes_requested]").checked = true;
              article.querySelector("button").click();
              const deadline = Date.now() + 8000;
              const status = document.querySelector("#status");
              while (Date.now() < deadline && !status.textContent) {
                await new Promise((resolve) => setTimeout(resolve, 100));
              }
              return status.textContent;
            })()
            """,
        )
        assert "reload before saving" in stale
        _call(page, "Page.reload", {"ignoreCache": True})
        saved = _eval(
            page,
            """
            (async () => {
              const deadline = Date.now() + 8000;
              while (Date.now() < deadline && !document.body.innerText.includes("Café")) {
                await new Promise((resolve) => setTimeout(resolve, 100));
              }
              const article = document.querySelector("article");
              article.querySelector("input").value = "ada";
              article.querySelector("textarea").value = "<unsafe>&\\\"quoted\\\" Café 説明 $12.50";
              article.querySelector("input[value=approved]").checked = true;
              article.querySelector("button").click();
              const status = document.querySelector("#status");
              while (Date.now() < deadline && !status.textContent.includes("Saved")) {
                await new Promise((resolve) => setTimeout(resolve, 100));
              }
              return status.textContent;
            })()
            """,
        )
        assert "Saved hero approved" in saved
        _call(page, "Page.reload", {"ignoreCache": True})
        reloaded = _eval(
            page,
            """
            (async () => {
              const deadline = Date.now() + 8000;
              while (Date.now() < deadline && !document.body.innerText.includes("approved")) {
                await new Promise((resolve) => setTimeout(resolve, 100));
              }
              return {
                text: document.body.innerText,
                images: document.querySelectorAll("img").length,
                scripts: document.querySelectorAll("script").length
              };
            })()
            """,
        )
        assert "approved by ada" in reloaded["text"]
        assert "current artifact" in reloaded["text"]
        assert "Café" in reloaded["text"]
        assert "説明" in reloaded["text"]
        assert "$12.50" in reloaded["text"]
        assert "<unsafe>" in reloaded["text"]
        assert reloaded["images"] == 0
    finally:
        chrome.terminate()
        chrome.wait(timeout=10)
        server.shutdown()
        server.server_close()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind((LOOPBACK_HOST, 0))
        return int(probe.getsockname()[1])


def _page_socket(debug_port: int, url: str) -> socket.socket:
    deadline = _seconds() + 15
    version = ""
    while _seconds() < deadline:
        try:
            version_url = f"http://{LOOPBACK_HOST}:{debug_port}/json/version"
            with urllib.request.urlopen(version_url, timeout=1) as response:
                version = response.read().decode("utf-8")
            break
        except OSError:
            continue
    if "Browser" not in version and "webSocketDebuggerUrl" not in version:
        pytest.skip("Chrome remote debugging did not start")
    target = _new_target(debug_port, url)
    debugger = str(target["webSocketDebuggerUrl"])
    return _connect(debugger)


def _new_target(debug_port: int, url: str) -> dict[str, object]:
    endpoint = f"http://{LOOPBACK_HOST}:{debug_port}/json/new?{url}"
    request = urllib.request.Request(endpoint, method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except OSError:
        quoted = urllib.parse.quote(url, safe="")
        request = urllib.request.Request(
            f"http://{LOOPBACK_HOST}:{debug_port}/json/new?{quoted}",
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    assert isinstance(payload, dict)
    return payload


def _eval(page: socket.socket, expression: str) -> object:
    last = "Chrome did not evaluate the page"
    for _ in range(20):
        try:
            result = _call(
                page,
                "Runtime.evaluate",
                {"expression": expression, "awaitPromise": True, "returnByValue": True},
            )
        except AssertionError as exc:
            last = str(exc)
            if "destroyed" not in last and "Cannot find context" not in last:
                raise
            time.sleep(0.25)
            continue
        value = result["result"]
        assert isinstance(value, dict)
        if value.get("subtype") == "error":
            description = str(value.get("description"))
            if "destroyed" in description:
                time.sleep(0.25)
                last = description
                continue
            raise AssertionError(description)
        return value.get("value")
    raise AssertionError(last)


def _call(page: socket.socket, method: str, params: dict[str, object]) -> dict[str, object]:
    call_id = _call.next_id
    _call.next_id += 1
    _send(page, {"id": call_id, "method": method, "params": params})
    while True:
        message = _recv(page)
        if message.get("id") == call_id:
            if "error" in message:
                raise AssertionError(message["error"])
            found = message.get("result")
            assert isinstance(found, dict)
            return found


_call.next_id = 1  # type: ignore[attr-defined]


def _connect(url: str) -> socket.socket:
    host_path = url.removeprefix("ws://")
    host_port, _, path = host_path.partition("/")
    host, _, raw_port = host_port.partition(":")
    sock = socket.create_connection((host, int(raw_port)), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET /{path} HTTP/1.1\r\n"
        f"Host: {host_port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode("ascii"))
    header = b""
    while b"\r\n\r\n" not in header:
        chunk = sock.recv(4096)
        if not chunk:
            break
        header += chunk
    if b" 101 " not in header.split(b"\r\n", 1)[0]:
        raise AssertionError(header.decode("utf-8", errors="replace"))
    return sock


def _send(sock: socket.socket, payload: dict[str, object]) -> None:
    raw = json.dumps(payload).encode("utf-8")
    mask = os.urandom(4)
    header = bytes([0x81])
    length = len(raw)
    if length < 126:
        header += bytes([0x80 | length])
    else:
        header += bytes([0x80 | 126]) + struct.pack("!H", length)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(raw))
    sock.sendall(header + mask + masked)


def _recv(sock: socket.socket) -> dict[str, object]:
    frame = _read_exact(sock, 2)
    length = frame[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(sock, 8))[0]
    payload = _read_exact(sock, length)
    message = json.loads(payload.decode("utf-8"))
    assert isinstance(message, dict)
    return message


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        part = sock.recv(size - len(chunks))
        if not part:
            break
        chunks.extend(part)
    return bytes(chunks)


def _seconds() -> float:
    return time.monotonic()
