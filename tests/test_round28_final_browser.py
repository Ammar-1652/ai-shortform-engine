"""Open the final review page in the local browser. This does not download one."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.preview.browser import resolve_browser
from clipforge.review.server import open_final_review_server
from clipforge.review.service import LOOPBACK_HOST
from tests.test_hero_review_browser import DebugPage, _free_port
from tests.test_round16 import _world

pytestmark = [pytest.mark.review, pytest.mark.browser]


def test_local_browser_saves_a_final_decision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")
    try:
        browser = resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    world = _world(tmp_path / "stack")
    server = open_final_review_server(
        database=world.database,
        source_asset_id="source-1",
        candidate_id="cand-1",
        work_root=world.work,
        port=0,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = int(server.server_address[1])
    url = f"http://{LOOPBACK_HOST}:{port}/final-review"
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
        page = DebugPage(debug_port, url)
        first = page.evaluate(
            """
            (async () => {
              const deadline = Date.now() + 8000;
              while (Date.now() < deadline && !document.body.innerText.includes("Café")) {
                await new Promise((resolve) => setTimeout(resolve, 100));
              }
              const video = document.querySelector("video");
              return {
                text: document.body.innerText,
                controls: Boolean(video && video.controls),
                autoplay: Boolean(video && video.autoplay)
              };
            })()
            """
        )
        assert isinstance(first, dict)
        assert first["controls"] is True
        assert first["autoplay"] is False
        assert "Café" in str(first["text"])
        assert "説明" in str(first["text"])
        assert "approved" in str(first["text"])
        saved = page.evaluate(
            """
            (async () => {
              document.getElementById("reviewer").value = "ada";
              document.getElementById("notes").value = "Café 説明 $12.50";
              document.querySelector("button[data-decision=changes_requested]").click();
              const deadline = Date.now() + 8000;
              while (Date.now() < deadline && !document.body.innerText.includes("$12.50")) {
                await new Promise((resolve) => setTimeout(resolve, 100));
              }
              return document.body.innerText;
            })()
            """
        )
        assert "changes_requested" in str(saved)
        assert "$12.50" in str(saved)
        assert "Café" in str(saved)
    finally:
        chrome.terminate()
        chrome.wait(timeout=10)
        server.shutdown()
        server.server_close()
