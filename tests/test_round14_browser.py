"""Open the analytics page in a local browser. This does not download a browser."""

from __future__ import annotations

import json
import subprocess
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from clipforge.analytics.server import LOOPBACK_HOST, open_analytics_server
from clipforge.analytics.service import import_observations
from clipforge.errors import MediaError
from clipforge.preview.browser import resolve_browser
from tests.test_round13 import _ready

pytestmark = pytest.mark.analytics


def test_browser_reviews_labels_and_rejects_a_stale_write(tmp_path: Path) -> None:
    try:
        browser = resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    database, work, digest = _ready(tmp_path)
    path = work / "browser.csv"
    path.write_text(
        "project_id,source_asset_id,artifact_id,artifact_kind,artifact_sha256,platform,observed_at,views\n"
        f"project-1,source-1,artifact-1,notes_json,{digest},tiktok,2026-10-04T00:00:00+00:00,\n",
        encoding="utf-8",
    )
    stored = import_observations(database, work, path, profile_id="generic-metrics-v1")
    outcome = stored[0]
    server = open_analytics_server(
        database=database,
        project_id="project-1",
        work_root=work,
        port=0,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    url = f"http://{LOOPBACK_HOST}:{port}/"
    try:
        page = _dump(browser, url, tmp_path / "chrome-1")
        assert outcome.outcome_id in page
        assert "not reported" in page
        assert "tiktok" in page
        assert "http://" not in page
        assert "https://" not in page
        connection = HTTPConnection(LOOPBACK_HOST, port, timeout=10)
        connection.request("GET", "/api/analytics/labels/artifact-1")
        loaded = json.loads(connection.getresponse().read())
        connection.close()
        body = {
            "project_id": "project-1",
            "source_asset_id": "source-1",
            "artifact_id": "artifact-1",
            "outcome_id": outcome.outcome_id,
            "snapshot_id": outcome.snapshot_id,
            "expected_label_set_id": loaded["effective_label_set_id"],
            "expected_artifact_sha256": loaded["artifact_sha256"],
            "reviewer_id": "ada",
            "notes": "Café 説明 $12.50",
            "labels": {"hook_type": "question", "topic_tags": ["coffee"], "cta": "unknown"},
        }
        connection = HTTPConnection(LOOPBACK_HOST, port, timeout=10)
        connection.request(
            "POST",
            "/api/analytics/labels",
            body=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        saved = connection.getresponse()
        assert saved.status == 201
        saved_body = json.loads(saved.read())
        connection.close()
        reloaded = _dump(browser, url, tmp_path / "chrome-2")
        assert "Café" in reloaded
        assert "説明" in reloaded
        assert "$12.50" in reloaded
        assert "http://" not in reloaded
        assert "https://" not in reloaded
        body["expected_label_set_id"] = loaded["effective_label_set_id"]
        body["notes"] = "stale note"
        connection = HTTPConnection(LOOPBACK_HOST, port, timeout=10)
        connection.request(
            "POST",
            "/api/analytics/labels",
            body=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        stale = connection.getresponse()
        stale_body = stale.read().decode("utf-8")
        assert stale.status == 409
        assert "reload before saving" in stale_body
        connection.close()
        assert saved_body["label_set_id"]
    finally:
        server.shutdown()
        server.server_close()


def _dump(browser: Path, url: str, profile: Path) -> str:
    profile.mkdir()
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
    return dumped.stdout
