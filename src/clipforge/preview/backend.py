"""Render backends. Tests use ffmpeg stand-ins. Production uses Remotion."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from clipforge.errors import MediaError
from clipforge.media.clock import us_to_seconds_str
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_executable, resolve_ffmpeg
from clipforge.paths import find_repo_root
from clipforge.preview.browser import resolve_browser


class RoughRenderBackend(Protocol):
    @property
    def requires_browser(self) -> bool: ...

    def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
        """Write every partial MP4 named by the batch. Raise on failure."""


@dataclass(frozen=True, slots=True)
class RemotionRoughRenderBackend:
    """One Node process bundles Remotion once and renders the batch sequentially."""

    requires_browser: bool = True

    def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
        browser = resolve_browser()
        node = resolve_executable("CLIPFORGE_NODE", "node")
        script = find_repo_root() / "apps" / "renderer" / "scripts" / "render-rough.mjs"
        if not script.is_file():
            raise MediaError(f"rough preview renderer script is missing at {script}")
        ProcessRunner().run(
            [node, str(script), str(batch_path), str(browser)],
            log_path=log_path,
            check=True,
        )


@dataclass
class FakeRoughRenderBackend:
    """Write technically valid review MP4s without Chromium. Calls are counted."""

    requires_browser: bool = False
    calls: int = 0

    def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
        self.calls += 1
        payload = json.loads(batch_path.read_text(encoding="utf-8"))
        items = payload.get("items")
        if not isinstance(items, list):
            raise MediaError("render batch is missing items")
        ffmpeg = resolve_ffmpeg()
        for item in items:
            if not isinstance(item, dict):
                raise MediaError("render batch item was not an object")
            output = item.get("outputPath")
            rendered = item.get("input")
            if not isinstance(output, str) or not isinstance(rendered, dict):
                raise MediaError("render batch item is missing an output path or input")
            frames = rendered.get("duration_in_frames")
            if isinstance(frames, bool) or not isinstance(frames, int) or frames < 1:
                raise MediaError("render batch duration_in_frames must be a positive integer")
            duration_us = (frames * 1_000_000) // 30
            seconds = us_to_seconds_str(duration_us)
            destination = Path(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            ProcessRunner().run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=0x111111:s=720x1280:r=30:d={seconds}",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency=440:sample_rate=48000:d={seconds}",
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


def node_available() -> str | None:
    return shutil.which("node")
