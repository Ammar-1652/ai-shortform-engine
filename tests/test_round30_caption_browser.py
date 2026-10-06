"""Browser proof that caption fixtures keep direction and stay inside the frame."""

from __future__ import annotations

import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.preview.browser import resolve_browser
from tests.test_hero_review_browser import DebugPage, _free_port

pytestmark = pytest.mark.browser

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>captions</title></head>
<body>
<video id="preview" controls></video>
<p id="arabic"></p>
<p id="japanese"></p>
<p id="latin"></p>
<canvas id="plate" width="1080" height="240"></canvas>
<script>
const arabic = "مرحبا، 12!";
const japanese = "説明です。";
const latin = "Café costs $12.50 today.";
document.getElementById("arabic").textContent = arabic;
document.getElementById("japanese").textContent = japanese;
document.getElementById("latin").textContent = latin;
document.getElementById("arabic").style.direction = "rtl";
document.getElementById("japanese").style.direction = "ltr";
const video = document.getElementById("preview");
video.autoplay = false;
const canvas = document.getElementById("plate");
const context = canvas.getContext("2d");
context.fillStyle = "#000000";
context.fillRect(0, 0, 1080, 240);
context.fillStyle = "#ffffff";
context.font = "64px sans-serif";
context.direction = "rtl";
context.textAlign = "right";
context.fillText(arabic, 1016, 120);
window.__captionFacts = { arabic, japanese, latin };
</script>
</body>
</html>
"""


def test_browser_caption_fixtures_keep_direction(tmp_path: Path) -> None:
    try:
        browser = resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text(_PAGE, encoding="utf-8")
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = int(server.server_address[1])
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    debug_port = _free_port()
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
        page = DebugPage(debug_port, f"http://127.0.0.1:{port}/")
        facts = page.evaluate(
            """
            (async () => {
              const deadline = Date.now() + 8000;
              while (Date.now() < deadline && !document.getElementById("plate")) {
                await new Promise((resolve) => setTimeout(resolve, 100));
              }
              const arabic = document.getElementById("arabic");
              const japanese = document.getElementById("japanese");
              const latin = document.getElementById("latin");
              const video = document.getElementById("preview");
              const canvas = document.getElementById("plate");
              if (!canvas || !arabic || !video) {
                return { missing: true, href: location.href };
              }
              const pixels = canvas.getContext("2d").getImageData(0, 0, 1080, 240).data;
              let ink = 0;
              let weighted = 0;
              let left = 0;
              let right = 0;
              for (let y = 0; y < 240; y += 1) {
                for (let x = 0; x < 1080; x += 1) {
                  const offset = (y * 1080 + x) * 4;
                  const bright = pixels[offset] + pixels[offset + 1] + pixels[offset + 2];
                  if (bright > 30) {
                    ink += bright;
                    weighted += x * bright;
                    if (x < 64 || x > 1016 || y < 8) {
                      left += 1;
                    }
                    if (x >= 540) {
                      right += bright;
                    }
                  }
                }
              }
              return {
                arabic: arabic.textContent,
                japanese: japanese.textContent,
                latin: latin.textContent,
                direction: getComputedStyle(arabic).direction,
                controls: video.controls,
                autoplay: video.autoplay,
                ink,
                centroid: ink ? Math.round(weighted / ink) : 0,
                margin: left,
                rightInk: right
              };
            })()
            """
        )
        assert isinstance(facts, dict)
        assert facts["arabic"] == "مرحبا، 12!"
        assert facts["japanese"] == "説明です。"
        assert facts["latin"] == "Café costs $12.50 today."
        assert facts["direction"] == "rtl"
        assert facts["controls"] is True
        assert facts["autoplay"] is False
        assert int(facts["ink"]) > 0
        assert int(facts["centroid"]) > 540
        assert int(facts["margin"]) == 0
        assert int(facts["rightInk"]) > 0
        assert "eval(" not in _PAGE
        assert "innerHTML" not in _PAGE
        assert "http://" not in _PAGE.split("video", 1)[0]
    finally:
        chrome.terminate()
        chrome.wait(timeout=10)
        server.shutdown()
        server.server_close()
