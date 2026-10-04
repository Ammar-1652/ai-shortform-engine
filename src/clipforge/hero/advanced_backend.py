"""Advanced Hero render backends. Tests use ffmpeg. Production uses Remotion."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from clipforge.errors import MediaError
from clipforge.media.clock import us_to_seconds_str
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_executable, resolve_ffmpeg
from clipforge.paths import find_repo_root
from clipforge.preview.browser import resolve_browser


class AdvancedRenderBackend(Protocol):
    @property
    def requires_browser(self) -> bool:
        """True when this backend launches the local browser."""

    def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
        """Write one batch of advanced Hero MP4s."""


@dataclass(frozen=True, slots=True)
class RemotionAdvancedRenderBackend:
    requires_browser: bool = True

    def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
        browser = resolve_browser()
        node = resolve_executable("CLIPFORGE_NODE", "node")
        script = find_repo_root() / "apps" / "renderer" / "scripts" / "render-advanced-hero.mjs"
        if not script.is_file():
            raise MediaError(f"advanced Hero renderer script is missing at {script}")
        ProcessRunner().run([node, str(script), str(batch_path), str(browser)], log_path=log_path, check=True)


@dataclass
class FakeAdvancedRenderBackend:
    """Write a portrait MP4 with colored overlays. No browser and no remote media."""

    requires_browser: bool = False
    calls: int = 0

    def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
        self.calls += 1
        payload = json.loads(batch_path.read_text(encoding="utf-8"))
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise MediaError("advanced Hero render batch is missing items")
        ffmpeg = resolve_ffmpeg()
        for item in items:
            if not isinstance(item, dict):
                raise MediaError("advanced Hero render batch item was not an object")
            rendered = item.get("input")
            output = item.get("outputPath")
            if not isinstance(rendered, dict) or not isinstance(output, str):
                raise MediaError("advanced Hero render batch item is missing an output or input")
            if rendered.get("composition_id") != "AdvancedHeroDraft":
                raise MediaError("advanced render refuses a Hero v1 composition")
            _reject_remote(rendered)
            frames = rendered.get("duration_in_frames")
            if isinstance(frames, bool) or not isinstance(frames, int) or frames < 1:
                raise MediaError("advanced duration_in_frames must be a positive integer")
            seconds = us_to_seconds_str((frames * 1_000_000) // 30)
            destination = Path(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            ProcessRunner().run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=0x16301a:s=1080x1920:r=30:d={seconds}",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency=440:sample_rate=48000:d={seconds}",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=red:s=1080x1920:r=30:d={seconds}",
                    "-filter_complex",
                    _filters(rendered, seconds),
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-preset",
                    "ultrafast",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(destination),
                ],
                log_path=log_path,
                check=True,
            )


def _filters(rendered: dict[str, object], seconds: str) -> str:
    broll = rendered.get("broll")
    start = "0"
    end = seconds
    if isinstance(broll, list) and broll and isinstance(broll[0], dict):
        interval = broll[0].get("interval")
        if isinstance(interval, dict):
            start = _seconds(interval.get("output_start_us"))
            end = _seconds(interval.get("output_end_us"))
    video = f"[0:v][2:v]overlay=enable='between(t,{start},{end})'[v]"
    audio = "[1:a]volume=-6dB[a]"
    return f"{video};{audio}"


def _seconds(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        return "0"
    return us_to_seconds_str(value)


def _reject_remote(rendered: dict[str, object]) -> None:
    raw = json.dumps(rendered)
    if "http://" in raw or "https://" in raw:
        raise MediaError("advanced render rejects remote media URLs")
    events = rendered.get("sfx")
    if not isinstance(events, list):
        return
    for event in events:
        if isinstance(event, dict) and event.get("role") == "music":
            raise MediaError("advanced render rejects music")
