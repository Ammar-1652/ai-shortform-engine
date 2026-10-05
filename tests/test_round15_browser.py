"""Open the readiness page in a local browser."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import pytest

from clipforge.benchmark.server import LOOPBACK_HOST, open_benchmark_server
from clipforge.benchmark.service import run_benchmark
from clipforge.errors import MediaError
from clipforge.preview.browser import resolve_browser
from clipforge.voice.provider import FakeVoiceProvider
from clipforge.voice.service import generate_narration
from tests.test_round15 import _chain, _narration

pytestmark = [pytest.mark.benchmark, pytest.mark.browser]


def test_browser_shows_readiness_and_narration_text(tmp_path: Path) -> None:
    try:
        browser = resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    database, work = _chain(tmp_path)
    generate_narration(database, work, _narration("Café 説明 $12.50"), FakeVoiceProvider())
    document = run_benchmark(database, work, "source-1", fixture_kind="deterministic_synthetic")
    server = open_benchmark_server(
        database=database,
        work_root=work,
        benchmark_id=document.benchmark_run_id,
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    url = f"http://{LOOPBACK_HOST}:{port}/"
    profile = tmp_path / "chrome"
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
        assert document.benchmark_run_id in page
        assert "blocked" in page
        assert "Café" in page
        assert "説明" in page
        assert "$12.50" in page
        assert "http://" not in page
        assert "https://" not in page
        assert "eval(" not in page
        assert "innerHTML" not in page
    finally:
        server.shutdown()
        server.server_close()
