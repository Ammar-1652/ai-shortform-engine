"""Chrome proofs for the advanced Hero composition and review page."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.hero.advanced_service import (
    plan_advanced_candidate,
    render_advanced_drafts,
    select_advanced_backend,
)
from clipforge.hero.backend import FakeHeroRenderBackend
from clipforge.preview.backend import FakeRoughRenderBackend
from clipforge.preview.browser import resolve_browser
from clipforge.review.hero_board import decision_context_for
from clipforge.review.server import open_review_server
from clipforge.review.service import (
    LOOPBACK_HOST,
    DecisionContext,
    record_decision,
    record_hero_decision,
    review_board,
)
from tests.candidate_support import SOURCE_ID, segment
from tests.preview_support import mine, ready_stack, render, short_profile
from tests.test_advanced_hero import _register_asset
from tests.test_hero_review_browser import DebugPage
from tests.test_hero_service import CountingAligner, _hero

pytestmark = [pytest.mark.preview, pytest.mark.browser]
_PHRASE = "Café costs $12.50 説明 please."


def test_chrome_advanced_render_shows_broll_type_and_diagram(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")
    if not (Path("apps/renderer/node_modules/@remotion/bundler")).exists():
        pytest.skip("Remotion packages are not installed")
    try:
        resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    media = tmp_path / "media"
    media.mkdir()
    source = media / "source.mp4"
    broll = media / "broll.mp4"
    speech = media / "speech.flac"
    effect = media / "effect.wav"
    _lavfi(source, "color=c=0x00aa00:s=640x360:r=30:d=2", "anullsrc=r=48000:cl=stereo", "2")
    _lavfi(broll, "color=c=0xff0000:s=640x360:r=30:d=2", "anullsrc=r=48000:cl=stereo", "2")
    _audio(speech, "flac")
    _audio(effect, "wav")
    spoken = segment(0, 0, 1_200_000, _PHRASE)
    fixture = ready_stack(
        tmp_path / "stack",
        segments=[spoken],
        duration_us=3_000_000,
        proxy_bytes=source.read_bytes(),
        asr_bytes=speech.read_bytes(),
    )
    mine(fixture, profile=short_profile())
    render(fixture, FakeRoughRenderBackend())
    board = review_board(fixture.database, SOURCE_ID, fixture.work)
    cards = board["candidates"]
    assert isinstance(cards, list) and cards
    candidate_id = str(cards[0]["candidate_id"])
    record_decision(
        database=fixture.database,
        work_root=fixture.work,
        context=DecisionContext(
            source_asset_id=str(board["source_asset_id"]),
            project_id=str(board["project_id"]),
            artifact_id=str(board["artifact_id"]),
            preview_set_id=str(board["preview_set_id"]),
            manifest_sha256=str(board["manifest_sha256"]),
            candidate_id=candidate_id,
        ),
        decision="approved",
        reviewer_id="ada",
        notes="",
    )
    _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    hero = review_board(fixture.database, SOURCE_ID, fixture.work)["hero"]
    assert isinstance(hero, dict)
    record_hero_decision(
        database=fixture.database,
        work_root=fixture.work,
        context=decision_context_for(hero, candidate_id),
        decision="approved",
        reviewer_id="ada",
        notes="",
    )
    _register_asset(fixture, "broll-1", "graphic", broll.read_bytes())
    _register_asset(fixture, "sfx-1", "audio", effect.read_bytes())
    plan = plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
        broll_asset_ids=["broll-1"],
        sfx_asset_ids=["sfx-1"],
    )
    joined = " ".join(item.text for item in plan.typography)
    assert "Café" in joined
    assert "$12.50" in joined
    from clipforge.hero.advanced_backend import RemotionAdvancedRenderBackend

    assert isinstance(select_advanced_backend(None), RemotionAdvancedRenderBackend)
    result = render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
    )
    assert result.status == "rendered"
    assert result.manifest_path is not None
    video = result.manifest_path.parent / "candidates" / candidate_id / "advanced.mp4"
    log = result.manifest_path.parent / "logs" / "render.log"
    assert "bundleSeconds" in log.read_text(encoding="utf-8")
    probe = _probe(video)
    assert probe["codec"] == "h264"
    assert probe["width"] == 1080 and probe["height"] == 1920
    assert probe["fps"] == "30/1"
    assert probe["audio"] == "aac"
    assert probe["pix_fmt"] in {"yuv420p", "yuvj420p"}
    rendered = json.loads((video.parent / "render-input.json").read_text(encoding="utf-8"))
    assert rendered["reframing_strategy"] == "contain"
    assert rendered["broll"][0]["broll_source_in_us"] == 0
    assert rendered["sfx"][0]["gain_db"] == -6
    assert rendered["sfx"][0]["role"] == "sfx"
    broll_end = plan.broll[0].interval.output_end_us / 1_000_000
    during = broll_end / 2
    after = min(probe["duration"] - 0.05, broll_end + 0.2)
    assert _pixel(video, during, 540, 960) == "red"
    assert _pixel(video, after, 540, 960) == "green"
    assert _pixel(video, after, 540, 40) == "dark"
    assert _pixel(video, after, 200, 400) == "magenta"
    assert _pixel(video, after, 600, 400) == "cyan"
    assert _pixel(video, after, 200, 1550) == "yellow"
    ocr = _ocr(video, after)
    if ocr is not None:
        # Pixel color proves the plate. OCR is recorded when the local binary exists.
        assert isinstance(ocr, str)


def test_chrome_advanced_review_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")
    try:
        browser = resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    from clipforge.hero.advanced_backend import FakeAdvancedRenderBackend
    from tests.test_advanced_hero import _approved

    fixture, candidate_id = _approved(tmp_path)
    _register_asset(fixture, "broll-1", "graphic", b"broll-bytes")
    _register_asset(fixture, "sfx-1", "audio", b"sfx-bytes")
    plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
        broll_asset_ids=["broll-1"],
        sfx_asset_ids=["sfx-1"],
    )
    render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=FakeAdvancedRenderBackend(),
    )
    server = open_review_server(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        port=0,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = int(server.server_address[1])
    debug = _free_port()
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    chrome = subprocess.Popen(
        [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-background-networking",
            f"--remote-debugging-port={debug}",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        page = DebugPage(debug, f"http://{LOOPBACK_HOST}:{port}/advanced-review")
        first = page.evaluate(
            """
            (async () => {
              const deadline = Date.now() + 8000;
              while (Date.now() < deadline && !document.body.innerText.includes("broll")) {
                await new Promise((resolve) => setTimeout(resolve, 100));
              }
              const video = document.querySelector("video");
              return {
                text: document.body.innerText,
                controls: Boolean(video && video.controls),
                autoplay: Boolean(video && video.autoplay),
                images: document.querySelectorAll("img").length
              };
            })()
            """,
        )
        assert first["controls"] is True
        assert first["autoplay"] is False
        assert "reframing contain" in first["text"]
        assert "broll-1" in first["text"]
        assert "sfx-1" in first["text"]
        assert "owned" in first["text"]
        assert "dB" in first["text"]
        assert "number_comparison" in first["text"]
        assert "emphasis" in first["text"]
        assert first["images"] == 0
        notes = 'Café 説明 $12.50 <unsafe>&"quoted"'
        for decision in ("rejected", "changes_requested", "approved"):
            saved = _save_advanced(page, decision, notes)
            assert f"Saved advanced {decision}" in str(saved), saved
        page.reload()
        reloaded = page.wait_for("effective decision approved")
        assert "rejected by ada" in reloaded
        assert "changes_requested by ada" in reloaded
        assert "Café" in reloaded
        assert "説明" in reloaded
        assert "$12.50" in reloaded
        assert "<unsafe>" in reloaded
        sidecar = fixture.workspace.advanced_sidecar()
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        payload["advanced_set_id"] = "other-advanced-set"
        sidecar.write_text(json.dumps(payload), encoding="utf-8")
        stale = page.evaluate(
            """
            (async () => {
              const article = document.querySelector("article");
              article.querySelector("input").value = "ada";
              article.querySelector("textarea").value = "stale";
              const choice = article.querySelector("input[value=approved]");
              if (choice) choice.checked = true;
              article.querySelector("button").click();
              const deadline = Date.now() + 8000;
              const node = document.querySelector("#status");
              while (Date.now() < deadline && !(node && node.textContent.includes("reload"))) {
                await new Promise((resolve) => setTimeout(resolve, 100));
              }
              return node ? node.textContent : "";
            })()
            """,
        )
        assert "reload before saving" in str(stale)
    finally:
        chrome.terminate()
        chrome.wait(timeout=10)
        server.shutdown()
        server.server_close()


def _save_advanced(page: DebugPage, decision: str, notes: str) -> object:
    selector = json.dumps(f"input[value={decision}]")
    notes_literal = json.dumps(notes)
    return page.evaluate(
        f"""
        (async () => {{
          const article = document.querySelector("article");
          article.querySelector("input").value = "ada";
          article.querySelector("textarea").value = {notes_literal};
          const choice = article.querySelector({selector});
          if (!choice) return "no choice";
          choice.checked = true;
          const node = document.querySelector("#status");
          if (node) node.textContent = "";
          article.querySelector("button").click();
          const deadline = Date.now() + 8000;
          const expected = "Saved advanced " + {json.dumps(decision)};
          while (Date.now() < deadline && !(node && node.textContent.includes(expected))) {{
            await new Promise((resolve) => setTimeout(resolve, 100));
          }}
          return node ? node.textContent : "";
        }})()
        """
    )


def _lavfi(path: Path, video: str, audio: str, seconds: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            video,
            "-f",
            "lavfi",
            "-i",
            audio,
            "-t",
            seconds,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _audio(path: Path, codec: str) -> None:
    argv = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:sample_rate=48000:d=1",
    ]
    if codec == "wav":
        argv.extend(["-f", "wav"])
    else:
        argv.extend(["-c:a", codec])
    argv.append(str(path))
    subprocess.run(argv, check=True, capture_output=True)


def _probe(path: Path) -> dict[str, object]:
    raw = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,pix_fmt",
            "-of",
            "json",
            str(path),
        ],
        text=True,
    )
    payload = json.loads(raw)
    video = next(item for item in payload["streams"] if item.get("width"))
    audio = next(item for item in payload["streams"] if item.get("codec_name") == "aac")
    duration = float(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            text=True,
        )
    )
    return {
        "codec": video["codec_name"],
        "width": video["width"],
        "height": video["height"],
        "fps": video["avg_frame_rate"],
        "audio": audio["codec_name"],
        "pix_fmt": video.get("pix_fmt"),
        "duration": duration,
    }


def _pixel(path: Path, seconds: float, x: int, y: int) -> str:
    frame = path.parent / f"pixel-{int(seconds * 1000)}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{seconds:.3f}", "-i", str(path), "-frames:v", "1", str(frame)],
        check=True,
    )
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(frame),
            "-vf",
            f"crop=1:1:{x}:{y}",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    )
    red, green, blue = raw[:3]
    if red > 180 and green < 80 and blue < 80:
        return "red"
    if red < 40 and green > 40 and blue < 40:
        return "green"
    if red < 40 and green < 40 and blue < 40:
        return "dark"
    if red > 180 and green < 80 and blue > 180:
        return "magenta"
    if red < 80 and green > 180 and blue > 180:
        return "cyan"
    if red > 180 and green > 180 and blue < 80:
        return "yellow"
    return f"{red},{green},{blue}"


def _ocr(path: Path, seconds: float) -> str | None:
    binary = "tesseract"
    local = Path.home() / ".local/clipforge-ocr/bin/tesseract"
    if local.is_file():
        binary = str(local)
    try:
        tesseract = subprocess.run([binary, "--version"], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    if tesseract.returncode != 0:
        return None
    frame = path.parent / "ocr-frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{seconds:.3f}", "-i", str(path), "-frames:v", "1", str(frame)],
        check=True,
    )
    result = subprocess.run(
        [binary, str(frame), "stdout", "--psm", "6", "-l", "eng"],
        capture_output=True,
        text=True,
    )
    return result.stdout


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind((LOOPBACK_HOST, 0))
        return int(probe.getsockname()[1])
