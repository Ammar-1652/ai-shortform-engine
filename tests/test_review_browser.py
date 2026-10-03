"""Open the review page in the local browser. This does not download a browser."""

from __future__ import annotations

import json
import subprocess
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.preview.backend import FakeRoughRenderBackend
from clipforge.preview.browser import resolve_browser
from clipforge.review.server import open_review_server
from clipforge.review.service import LOOPBACK_HOST
from tests.candidate_support import SOURCE_ID, segment
from tests.preview_support import mine, ready_stack, render, short_profile

pytestmark = pytest.mark.review


def test_local_browser_can_review_a_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")
    try:
        browser = resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    spoken = segment(0, 0, 1_200_000, "Café numbers 42 stay visible here.")
    fixture = ready_stack(
        tmp_path / "stack",
        segments=[spoken],
        duration_us=3_000_000,
        proxy_bytes=b"proxy-bytes",
        asr_bytes=b"asr-bytes",
    )
    mined = mine(
        fixture,
        profile=short_profile(preferred_max_duration_us=2_000_000, hard_max_duration_us=2_500_000),
    )
    assert mined.selected_count == 1
    render(fixture, FakeRoughRenderBackend())
    server = open_review_server(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    url = f"http://{LOOPBACK_HOST}:{port}/"
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    try:
        dumped = subprocess.run(
            [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--disable-background-networking",
                f"--user-data-dir={profile}",
                "--virtual-time-budget=8000",
                "--dump-dom",
                url,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert dumped.returncode == 0, dumped.stderr
        page = dumped.stdout
        assert "<video" in page
        assert "autoplay" not in page
        assert "heuristic" in page
        assert "provisional" in page
        assert "http://" not in page
        assert "https://" not in page
        connection = HTTPConnection(LOOPBACK_HOST, port, timeout=10)
        connection.request("GET", "/api/review")
        board = json.loads(connection.getresponse().read())
        connection.close()
        card = board["candidates"][0]
        body = json.dumps(
            {
                "source_asset_id": board["source_asset_id"],
                "project_id": board["project_id"],
                "artifact_id": board["artifact_id"],
                "preview_set_id": board["preview_set_id"],
                "manifest_sha256": board["manifest_sha256"],
                "candidate_id": card["candidate_id"],
                "decision": "approved",
                "reviewer_id": "ada",
                "notes": "Café stays text",
            }
        ).encode()
        connection = HTTPConnection(LOOPBACK_HOST, port, timeout=10)
        connection.request(
            "POST",
            "/api/review/decisions",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        assert connection.getresponse().status == 201
        connection.close()
        profile_two = tmp_path / "chrome-profile-2"
        profile_two.mkdir()
        reloaded = subprocess.run(
            [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--disable-background-networking",
                f"--user-data-dir={profile_two}",
                "--virtual-time-budget=8000",
                "--dump-dom",
                url,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert reloaded.returncode == 0, reloaded.stderr
        assert "approved" in reloaded.stdout
        assert "ada" in reloaded.stdout
        assert "Café stays text" in reloaded.stdout
    finally:
        server.shutdown()
        server.server_close()
