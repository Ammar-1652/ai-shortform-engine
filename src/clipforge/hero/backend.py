"""Hero render backends. Tests use ffmpeg. Production uses Remotion."""

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


class HeroRenderBackend(Protocol):
    @property
    def requires_browser(self) -> bool:
        """True when this backend launches the local browser."""

    def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
        """Write one batch of Hero MP4s. Partial outputs stay unpromoted."""


@dataclass(frozen=True, slots=True)
class RemotionHeroRenderBackend:
    requires_browser: bool = True

    def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
        browser = resolve_browser()
        node = resolve_executable("CLIPFORGE_NODE", "node")
        script = find_repo_root() / "apps" / "renderer" / "scripts" / "render-hero.mjs"
        if not script.is_file():
            raise MediaError(f"Hero renderer script is missing at {script}")
        ProcessRunner().run([node, str(script), str(batch_path), str(browser)], log_path=log_path, check=True)


@dataclass
class FakeHeroRenderBackend:
    """Write a valid portrait MP4 without Chromium."""

    requires_browser: bool = False
    calls: int = 0

    def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
        self.calls += 1
        payload = json.loads(batch_path.read_text(encoding="utf-8"))
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise MediaError("Hero render batch is missing items")
        ffmpeg = resolve_ffmpeg()
        for item in items:
            if not isinstance(item, dict):
                raise MediaError("Hero render batch item was not an object")
            output = item.get("outputPath")
            rendered = item.get("input")
            if not isinstance(output, str) or not isinstance(rendered, dict):
                raise MediaError("Hero render batch item is missing an output path or input")
            frames = rendered.get("duration_in_frames")
            if isinstance(frames, bool) or not isinstance(frames, int) or frames < 1:
                raise MediaError("Hero duration_in_frames must be a positive integer")
            if rendered.get("alignment_quality") != "forced":
                raise MediaError("Hero render refuses alignment that is not forced")
            seconds = us_to_seconds_str((frames * 1_000_000) // 30)
            destination = Path(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            color = f"color=c=0x16301a:s=1080x1920:r=30:d={seconds}"
            tone = f"sine=frequency=440:sample_rate=48000:d={seconds}"
            ProcessRunner().run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    color,
                    "-f",
                    "lavfi",
                    "-i",
                    tone,
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
