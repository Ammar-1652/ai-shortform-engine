"""Chrome proofs for the advanced Hero composition and review page."""

from __future__ import annotations

import json
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.hero.advanced_service import (
    _context,
    default_advanced_profile,
    plan_advanced_candidate,
    render_advanced_drafts,
    select_advanced_backend,
)
from clipforge.hero.backend import FakeHeroRenderBackend
from clipforge.hero.direction_service import save_direction_brief
from clipforge.hero.motion_style import style_for_id
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
from clipforge.schemas.direction import (
    DirectionAssetPlacement,
    DirectionBeat,
    DirectionDocument,
    DirectionEvidence,
    DirectionMotionGraphic,
    DirectionOption,
)
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.provenance import ArtifactProvenance
from tests.candidate_support import SOURCE_ID, segment
from tests.preview_support import mine, ready_stack, render, short_profile
from tests.test_advanced_hero import _register_asset
from tests.test_hero_review_browser import DebugPage
from tests.test_hero_service import CountingAligner, _hero

pytestmark = [pytest.mark.preview, pytest.mark.browser]
_PHRASE = "A credit card costs $12.50, Café 説明."


def _persist_clean_direction(fixture, candidate_id: str, broll_id: str, sfx_id: str) -> None:
    """Create the same typed brief an operator would hand to the CLI."""
    context = _context(fixture.database, SOURCE_ID, candidate_id, fixture.work)
    words = list(context.alignment.words)
    assert len(words) >= 3
    groups = [words[:1], words[1:-1], words[-1:]]
    segment_order = [segment.segment_id for segment in context.hero_plan.edit_plan.time_map.segments]
    options: list[DirectionOption] = []
    styles = ("editorial-clean-v1", "kinetic-caption-v1", "premium-minimal-v1")
    for option_index, (option_id, style_id) in enumerate(
        zip(("option-a", "option-b", "option-c"), styles, strict=True)
    ):
        evidence: list[DirectionEvidence] = []
        beats: list[DirectionBeat] = []
        for beat_index, (kind, purpose, group) in enumerate(
            zip(("hook", "body", "punch"), ("context", "contrast", "payoff"), groups, strict=True)
        ):
            evidence_id = f"{option_id}-evidence-{beat_index}"
            evidence.append(
                DirectionEvidence(
                    evidence_id=evidence_id,
                    source_word_ids=[word.word_id for word in group],
                    source_segment_ids=segment_order,
                    source_text="".join(word.text for word in group),
                    note="Copied from the forced alignment.",
                )
            )
            beats.append(
                DirectionBeat(
                    beat_id=f"{option_id}-{kind}",
                    kind=kind,  # type: ignore[arg-type]
                    purpose=purpose,  # type: ignore[arg-type]
                    source_segment_ids=segment_order,
                    evidence_ids=[evidence_id],
                    display_text="".join(word.text for word in group).strip(),
                )
            )
        placements = [
            DirectionAssetPlacement(
                placement_id=f"{option_id}-broll",
                asset_id=broll_id,
                kind="graphic",
                interval=OutputInterval(
                    output_start_us=groups[0][0].output_start_us,
                    output_end_us=groups[0][-1].output_end_us,
                ),
                source_evidence_ids=[evidence[0].evidence_id],
                purpose=MotionPurpose.CONCEPT,
                relevance_note="The concept opening insert illustrates the exact opening phrase.",
                asset_tags=["concept"],
            ),
            DirectionAssetPlacement(
                placement_id=f"{option_id}-sfx",
                asset_id=sfx_id,
                kind="audio",
                interval=OutputInterval(
                    output_start_us=groups[0][0].output_start_us,
                    output_end_us=groups[0][-1].output_end_us,
                ),
                source_in_us=0,
                source_evidence_ids=[evidence[0].evidence_id],
                purpose=MotionPurpose.KEY_PHRASE,
                relevance_note="A restrained accent marks the source-grounded opening emphasis.",
                gain_db=-12,
            ),
        ]
        graphics = []
        if option_id == "option-b":
            graphic_evidence = DirectionEvidence(
                evidence_id=f"{option_id}-credit-card-evidence",
                source_word_ids=[word.word_id for word in words],
                source_segment_ids=segment_order,
                source_text="".join(word.text for word in words),
                note="The exact spoken phrase names a credit card.",
            )
            evidence.append(graphic_evidence)
            graphics.append(
                DirectionMotionGraphic(
                    graphic_id=f"{option_id}-credit-card",
                    template="credit_card",
                    interval=OutputInterval(output_start_us=400_000, output_end_us=1_100_000),
                    source_evidence_ids=[graphic_evidence.evidence_id],
                    purpose=MotionPurpose.NUMBER,
                    display_text=graphic_evidence.source_text,
                    x=80,
                    y=900,
                    width=420,
                    height=260,
                )
            )
        options.append(
            DirectionOption(
                option_id=option_id,
                style_id=style_id,  # type: ignore[arg-type]
                title="Source-grounded test direction",
                beats=beats,
                evidence=evidence,
                asset_placements=placements,
                motion_graphics=graphics,
                source_native_text_status="reviewed_absent",
                segment_order=segment_order,
                selection_score=(0.72, 0.91, 0.81)[option_index],
                selection_reason="Preserves the exact source sequence and uses one relevant opening accent.",
            )
        )
    document = DirectionDocument(
        direction_id="direction-chrome",
        project_id=context.project_id,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        source_sha256=context.source_sha256,
        hero_plan_sha256=context.hero_plan_sha256,
        time_map_sha256=context.hero_plan.edit_plan.time_map_sha256,
        alignment_sha256=context.alignment_sha256,
        visual_analysis_sha256=context.visual_sha256,
        options=options,
        selected_option_id="option-b",
        selection_mode="automatic",
        style_id="kinetic-caption-v1",
        style_fingerprint=style_for_id("kinetic-caption-v1").fingerprint(),
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="chrome-test",
            tool="test",
            tool_version="1",
            source_asset_ids=[SOURCE_ID],
        ),
    )
    brief = fixture.work / "direction-brief.json"
    brief.write_text(document.model_dump_json(indent=2), encoding="utf-8")
    save_direction_brief(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
        brief_path=brief,
    )


@pytest.mark.parametrize("clean_direction", [False, True], ids=["legacy", "clean-direction"])
def test_chrome_advanced_render_shows_reviewed_broll_and_caption(
    clean_direction: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    # The production staging contract now rejects a speech track that ends
    # before the selected picture span. Keep this fixture synchronized with
    # the 1.2-second candidate used below.
    _audio(speech, "flac", duration=1.2)
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
    if clean_direction:
        _persist_clean_direction(fixture, candidate_id, "broll-1", "sfx-1")
        profile = default_advanced_profile()
    else:
        profile = default_advanced_profile().model_copy(
            update={
                "caption_algorithm_version": "advanced-caption-v1",
                "typography_version": "advanced-typography-v1",
                "diagram_version": "advanced-diagram-v1",
                "renderer_recipe_version": "advanced-hero-renderer-v1",
                "motion_library_version": "advanced-motion-v1",
            }
        )
    plan = plan_advanced_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=candidate_id,
        work_root=fixture.work,
        broll_asset_ids=["broll-1"],
        sfx_asset_ids=["sfx-1"],
        profile=profile,
    )
    from clipforge.hero.advanced_backend import RemotionAdvancedRenderBackend

    assert isinstance(select_advanced_backend(None), RemotionAdvancedRenderBackend)
    result = render_advanced_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        profile=profile,
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
    assert rendered["sfx"][0]["gain_db"] == (-18 if clean_direction else -6)
    assert rendered["sfx"][0]["role"] == "sfx"
    if clean_direction:
        assert rendered["direction_id"] == "direction-chrome"
        assert rendered["sfx"][0]["sfx_source_in_us"] == 0
        assert rendered["motion_graphics"][0]["template"] == "credit_card"
    broll_start = plan.broll[0].interval.output_start_us / 1_000_000
    broll_end = plan.broll[0].interval.output_end_us / 1_000_000
    during = (broll_start + broll_end) / 2
    after = min(probe["duration"] - 0.05, broll_end + 0.2)
    pixel = _pixel(video, during, 540, 960)
    assert pixel == "red" or (pixel.count(",") == 2 and int(pixel.split(",")[0]) > 140)
    assert _pixel(video, after, 540, 960) == "green"
    assert _pixel(video, after, 540, 40) != "dark"
    assert _pixel(video, after, 200, 400) != "magenta"
    assert _pixel(video, after, 600, 400) != "cyan"
    if clean_direction:
        assert _motion_graphic_ink(video, 0.7) > 100, "native motion graphic did not reach encoded MP4"
    assert _caption_ink(video, after), "caption glyphs were not visible in the safe area"
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
        assert "number_comparison" not in first["text"]
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


def _audio(path: Path, codec: str, *, duration: float = 1.0) -> None:
    argv = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=880:sample_rate=48000:d={duration}",
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


def _caption_ink(path: Path, seconds: float) -> bool:
    """True when the production caption plate leaves bright pixels in the safe area."""
    frame = path.parent / f"caption-{int(seconds * 1000)}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{seconds:.3f}", "-i", str(path), "-frames:v", "1", str(frame)],
        check=True,
    )
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(frame), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    )
    width = 1080
    for y in range(1500, 1860):
        for x in range(64, 1016, 4):
            offset = (y * width + x) * 3
            red, green, blue = raw[offset], raw[offset + 1], raw[offset + 2]
            if red > 200 and green > 200 and blue > 200:
                return True
    return False


def _motion_graphic_ink(path: Path, seconds: float) -> int:
    """Count card-blue pixels in its declared safe graphic box after encoding."""
    frame = path.parent / f"motion-graphic-{int(seconds * 1000)}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{seconds:.3f}", "-i", str(path), "-frames:v", "1", str(frame)],
        check=True,
    )
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(frame), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    )
    blue_ink = 0
    for y in range(920, 1140, 4):
        for x in range(100, 480, 4):
            offset = (y * 1080 + x) * 3
            red, green, blue = raw[offset], raw[offset + 1], raw[offset + 2]
            if blue > green + 25 and blue > red + 25:
                blue_ink += 1
    return blue_ink


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
