"""Production Hero caption render. This does not use a hand-written HTML page."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.hero.backend import RemotionHeroRenderBackend
from clipforge.preview.browser import resolve_browser

pytestmark = pytest.mark.browser

_SHA = "a" * 64


def _media(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    video = directory / "analysis.mp4"
    audio = directory / "asr.flac"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1080x1920:d=4",
            "-frames:v",
            "120",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "4", str(audio)],
        check=True,
        capture_output=True,
    )


def _cue(cue_id: str, text: str, start: int, language: str) -> dict[str, object]:
    return {
        "language": language,
        "cue_id": cue_id,
        "text": text,
        "source_start_us": start * 1_000_000 // 30,
        "source_end_us": (start + 30) * 1_000_000 // 30,
        "output_start_us": start * 1_000_000 // 30,
        "output_end_us": (start + 30) * 1_000_000 // 30,
        "output_start_frame": start,
        "output_end_frame_exclusive": start + 30,
        "alignment_quality": "forced",
        "words": [{"text": text, "output_start_frame": start, "output_end_frame_exclusive": start + 30}],
    }


def _input() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "composition_id": "HeroDraft",
        "candidate_id": "cand-caption",
        "hero_set_id": "hero-caption",
        "video_path": "analysis.mp4",
        "audio_path": "asr.flac",
        "media_trim_frame": 0,
        "duration_in_frames": 120,
        "fps_numerator": 30,
        "fps_denominator": 1,
        "width": 1080,
        "height": 1920,
        "video_fit": "contain",
        "background": "neutral-dark-v1",
        "language": "en-US",
        "alignment_quality": "forced",
        "alignment_sha256": _SHA,
        "edit_plan_sha256": _SHA,
        "time_map_sha256": _SHA,
        "review_id": "review-caption",
        "review_digest": _SHA,
        "motion_library_version": "motion-library-v1",
        "profile_fingerprint": _SHA,
        "captions": [
            _cue("ar", "مرحبا بالعالم", 0, "ar"),
            _cue("ja", "説明です", 30, "ja"),
            _cue("fr", "bonjour le monde", 60, "fr-FR"),
            _cue("en", "Café costs $12.50 today.", 90, "en-US"),
        ],
        "motion_events": [],
    }


def _advanced_input() -> dict[str, object]:
    events = [
        ("ar", "مرحبا بالعالم", 0),
        ("ja", "説明です", 1_000_000),
        ("fr-FR", "bonjour le monde", 2_000_000),
        ("en-US", "Café costs $12.50 today.", 3_000_000),
    ]
    return {
        "composition_id": "AdvancedHeroDraft",
        "duration_in_frames": 120,
        "reframing_strategy": "contain",
        "base_video_name": "analysis.mp4",
        "speech_name": "asr.flac",
        "language": "en-US",
        "typography": [
            {
                "component_id": f"type-{language}",
                "text": text,
                "language": language,
                "purpose": "caption",
                "interval": {"output_start_us": start, "output_end_us": start + 1_000_000},
            }
            for language, text, start in events
        ],
    }


def _assert_decoded_captions(run: Path, output: Path, *, hero: bool) -> None:
    """Decoded frames must show caption ink inside the safe area."""
    del hero
    ocr = shutil.which("tesseract")
    packs = _tesseract_packs(ocr)
    frames = {
        5: ("ar", "مرحبا", "ara"),
        35: ("ja", "説明", "jpn"),
        65: ("fr", "bonjour", "fra"),
        95: ("en", "12", "eng"),
    }
    for index, (label, token, pack) in frames.items():
        frame = _decode_frame(output, run / f"frame-{index}.raw", index)
        assert _ink(frame, x0=0, y0=0, x1=64, y1=64) == 0
        assert _ink(frame, x0=1016, y0=0, x1=1080, y1=64) == 0
        band = _samples(frame, x0=64, y0=1400, x1=1016, y1=1900)
        assert band
        assert sum(band) > 0
        mean = sum(band) / len(band)
        variance = sum((item - mean) ** 2 for item in band) / len(band)
        assert variance > 20, f"{label} caption is blank or a flat rectangle"
        if label == "ar":
            left = _ink(frame, x0=64, y0=1400, x1=540, y1=1900)
            right = _ink(frame, x0=540, y0=1400, x1=1016, y1=1900)
            assert right > left
        if ocr and pack in packs:
            png = run / f"frame-{label}.png"
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{index / 30:.3f}", "-i", str(output), "-frames:v", "1", str(png)],
                check=True,
                capture_output=True,
            )
            completed = subprocess.run([ocr, str(png), "stdout", "-l", pack], capture_output=True, text=True)
            if completed.returncode == 0:
                found = completed.stdout.lower()
                assert token.lower() in found or (label == "en" and "12" in found)
                if label == "ja":
                    assert " " not in completed.stdout.strip()


def _tesseract_packs(ocr: str | None) -> set[str]:
    if ocr is None:
        return set()
    completed = subprocess.run([ocr, "--list-langs"], capture_output=True, text=True)
    if completed.returncode != 0:
        return set()
    names = completed.stdout.splitlines()
    return {line.strip() for line in names if line.strip() and not line.startswith("List")}


def _decode_frame(output: Path, raw: Path, index: int) -> bytes:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{index / 30:.3f}",
            "-i",
            str(output),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            str(raw),
        ],
        check=True,
        capture_output=True,
    )
    frame = raw.read_bytes()
    assert len(frame) == 1080 * 1920 * 3
    return frame


def _samples(frame: bytes, *, x0: int, y0: int, x1: int, y1: int, width: int = 1080) -> list[int]:
    values: list[int] = []
    for y in range(y0, y1):
        row = y * width * 3
        for x in range(x0, x1):
            offset = row + x * 3
            values.append(frame[offset] + frame[offset + 1] + frame[offset + 2])
    return values


def _ink(frame: bytes, *, x0: int, y0: int, x1: int, y1: int, width: int = 1080) -> int:
    total = 0
    for y in range(y0, y1):
        row = y * width * 3
        for x in range(x0, x1):
            offset = row + x * 3
            total += frame[offset] + frame[offset + 1] + frame[offset + 2]
    return total


def test_production_hero_render_keeps_caption_glyphs_inside_the_safe_area(tmp_path: Path) -> None:
    try:
        resolve_browser()
    except MediaError as exc:
        pytest.skip(str(exc))
    root = Path(__file__).resolve().parents[1]
    hero = (root / "apps/renderer/src/hero/HeroDraft.tsx").read_text(encoding="utf-8")
    advanced = (Path(__file__).resolve().parents[1] / "apps/renderer/src/hero/AdvancedHeroDraft.tsx").read_text(
        encoding="utf-8"
    )
    assert "CaptionPlate" in hero
    assert "CaptionPlate" in advanced
    run = tmp_path / "run"
    _media(run / "staging")
    output = run / "candidates" / "cand-caption" / "hero.mp4"
    output.parent.mkdir(parents=True)
    batch = run / "batch.json"
    import json

    batch.write_text(
        json.dumps({"items": [{"outputPath": str(output), "h264Crf": 23, "input": _input()}]}),
        encoding="utf-8",
    )
    RemotionHeroRenderBackend().render_batch(batch, log_path=run / "render.log")
    _assert_decoded_captions(run, output, hero=True)
    advanced_run = tmp_path / "advanced"
    _media(advanced_run / "staging")
    advanced_output = advanced_run / "candidates" / "cand-caption" / "advanced.mp4"
    advanced_output.parent.mkdir(parents=True)
    advanced_batch = advanced_run / "batch.json"
    advanced_batch.write_text(
        json.dumps(
            {"items": [{"outputPath": str(advanced_output), "h264Crf": 23, "input": _advanced_input()}]}
        ),
        encoding="utf-8",
    )
    from clipforge.hero.advanced_backend import RemotionAdvancedRenderBackend

    RemotionAdvancedRenderBackend().render_batch(advanced_batch, log_path=advanced_run / "render.log")
    _assert_decoded_captions(advanced_run, advanced_output, hero=False)
