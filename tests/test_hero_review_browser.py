"""Open the Hero review page in the local browser. This does not download one."""

from __future__ import annotations

import base64
import contextlib
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
        page = DebugPage(debug_port, url)
        first = page.evaluate(
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
        stale = page.evaluate(
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
        page.reload()
        page.wait_for("Café")
        saved = page.evaluate(
            """
            (async () => {
              const article = document.querySelector("article");
              if (!article) {
                return "no article";
              }
              article.querySelector("input").value = "ada";
              const notes = "<unsafe>&\\"quoted\\" Café 説明 $12.50";
              article.querySelector("textarea").value = notes;
              article.querySelector("input[value=approved]").checked = true;
              article.querySelector("button").click();
              const deadline = Date.now() + 8000;
              const status = document.querySelector("#status");
              while (Date.now() < deadline && !(status && status.textContent.includes("Saved"))) {
                await new Promise((resolve) => setTimeout(resolve, 100));
              }
              return status ? status.textContent : "no status";
            })()
            """,
        )
        assert "Saved hero approved" in str(saved), saved
        page.reload()
        reloaded = page.wait_for("approved by ada")
        assert "current artifact" in reloaded
        assert "Café" in reloaded
        assert "説明" in reloaded
        assert "$12.50" in reloaded
        assert "<unsafe>" in reloaded
        images = page.evaluate("document.querySelectorAll('img').length")
        assert images == 0
    finally:
        chrome.terminate()
        chrome.wait(timeout=10)
        server.shutdown()
        server.server_close()


class NavigationError(AssertionError):
    """The Chrome page debugger socket did not survive navigation."""


class DebugPage:
    """One local Chrome tab. Reload closes that debugger socket, so reconnect."""

    def __init__(self, debug_port: int, url: str) -> None:
        self.debug_port = debug_port
        self.url = url
        self.socket = _page_socket(debug_port, url)

    def evaluate(self, expression: str) -> object:
        last: object = "Chrome did not evaluate the page"
        for _ in range(12):
            try:
                value = _eval(self.socket, expression)
            except (NavigationError, ConnectionError, OSError, json.JSONDecodeError) as exc:
                last = str(exc)
                self.reattach()
                time.sleep(0.25)
                continue
            if value is None or value == {}:
                last = value
                time.sleep(0.25)
                continue
            return value
        raise AssertionError(repr(last))

    def reload(self) -> None:
        self.evaluate("window.__clipforgeReload = 'old'")
        with contextlib.suppress(NavigationError, ConnectionError, OSError, json.JSONDecodeError):
            _call(self.socket, "Page.reload", {"ignoreCache": True})
        deadline = _seconds() + 15
        while _seconds() < deadline:
            try:
                marker = _eval(self.socket, "window.__clipforgeReload || ''")
            except (NavigationError, ConnectionError, OSError, json.JSONDecodeError):
                time.sleep(0.2)
                self.reattach()
                continue
            if marker != "old":
                return
            time.sleep(0.2)
        raise AssertionError("Chrome did not finish reloading the review page")

    def wait_for(self, needle: str, timeout: float = 20) -> str:
        deadline = _seconds() + timeout
        last: object = ""
        while _seconds() < deadline:
            try:
                value = _eval(self.socket, "document.body ? document.body.innerText : ''")
            except (NavigationError, ConnectionError, OSError, json.JSONDecodeError):
                time.sleep(0.2)
                self.reattach()
                continue
            last = value
            if isinstance(value, str) and needle in value:
                return value
            time.sleep(0.2)
        raise AssertionError(f"{needle!r} not visible after reload: {last!r}")

    def reattach(self) -> None:
        _PENDING.pop(id(self.socket), None)
        with contextlib.suppress(OSError):
            self.socket.close()
        deadline = _seconds() + 10
        last = "Chrome page target disappeared after navigation"
        while _seconds() < deadline:
            try:
                targets = _list_targets(self.debug_port)
            except (OSError, json.JSONDecodeError) as exc:
                last = str(exc)
                time.sleep(0.2)
                continue
            for target in targets:
                if target.get("type") != "page":
                    continue
                if not _same_page(str(target.get("url", "")), self.url):
                    continue
                debugger = target.get("webSocketDebuggerUrl")
                if not isinstance(debugger, str):
                    continue
                try:
                    self.socket = _connect(debugger)
                except (OSError, ConnectionError, AssertionError) as exc:
                    last = str(exc)
                    continue
                return
            time.sleep(0.2)
        raise NavigationError(last)


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
    result = _call(
        page,
        "Runtime.evaluate",
        {"expression": expression, "awaitPromise": True, "returnByValue": True},
    )
    details = result.get("exceptionDetails")
    if isinstance(details, dict):
        text = str(details.get("text") or details)
        if _navigation_error(text):
            raise NavigationError(text)
        raise AssertionError(text)
    value = result["result"]
    assert isinstance(value, dict)
    if value.get("subtype") == "error":
        description = str(value.get("description"))
        if _navigation_error(description):
            raise NavigationError(description)
        raise AssertionError(description)
    if "value" not in value:
        raise NavigationError("Chrome returned no evaluation value")
    return value.get("value")


def _navigation_error(message: str) -> bool:
    folded = message.lower()
    needles = ("destroyed", "navigated", "cannot find context", "execution context", "inspected target")
    return any(needle in folded for needle in needles)


def _call(page: socket.socket, method: str, params: dict[str, object]) -> dict[str, object]:
    call_id = _call.next_id
    _call.next_id += 1
    _send(page, {"id": call_id, "method": method, "params": params})
    while True:
        message = _recv(page)
        if message.get("id") == call_id:
            if "error" in message:
                err = message["error"]
                text = str(err)
                if _navigation_error(text):
                    raise NavigationError(text)
                raise AssertionError(err)
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
    marker = header.find(b"\r\n\r\n")
    if marker < 0 or b" 101 " not in header[:marker].split(b"\r\n", 1)[0]:
        raise AssertionError(header.decode("utf-8", errors="replace"))
    _PENDING[id(sock)] = header[marker + 4 :]
    return sock


_PENDING: dict[int, bytes] = {}


def _send(sock: socket.socket, payload: dict[str, object]) -> None:
    _send_frame(sock, 0x1, json.dumps(payload).encode("utf-8"))


def _send_frame(sock: socket.socket, opcode: int, raw: bytes) -> None:
    mask = os.urandom(4)
    header = bytes([0x80 | opcode])
    length = len(raw)
    if length < 126:
        header += bytes([0x80 | length])
    elif length < 65536:
        header += bytes([0x80 | 126]) + struct.pack("!H", length)
    else:
        header += bytes([0x80 | 127]) + struct.pack("!Q", length)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(raw))
    sock.sendall(header + mask + masked)


def _recv(sock: socket.socket) -> dict[str, object]:
    while True:
        frame = _read_exact(sock, 2)
        opcode = frame[0] & 0x0F
        length = frame[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", _read_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _read_exact(sock, 8))[0]
        payload = _read_exact(sock, length)
        if opcode == 0x9:
            _send_frame(sock, 0xA, payload)
            continue
        if opcode == 0x8:
            raise ConnectionError("Chrome closed the debugger websocket")
        if opcode != 0x1:
            continue
        message = json.loads(payload.decode("utf-8"))
        assert isinstance(message, dict)
        return message


def _read_exact(sock: socket.socket, size: int) -> bytes:
    pending = _PENDING.get(id(sock), b"")
    if pending:
        _PENDING[id(sock)] = pending[size:]
        chunks = bytearray(pending[:size])
    else:
        chunks = bytearray()
    while len(chunks) < size:
        part = sock.recv(size - len(chunks))
        if not part:
            raise ConnectionError("Chrome closed the debugger socket")
        chunks.extend(part)
    return bytes(chunks)


def _list_targets(debug_port: int) -> list[dict[str, object]]:
    with urllib.request.urlopen(
        f"http://{LOOPBACK_HOST}:{debug_port}/json/list",
        timeout=2,
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert isinstance(payload, list)
    return [item for item in payload if isinstance(item, dict)]


def _same_page(found: str, wanted: str) -> bool:
    left = urllib.parse.urlsplit(found)
    right = urllib.parse.urlsplit(wanted)
    return (
        left.hostname == right.hostname
        and left.port == right.port
        and left.path.rstrip("/") == right.path.rstrip("/")
    )


def _seconds() -> float:
    return time.monotonic()
