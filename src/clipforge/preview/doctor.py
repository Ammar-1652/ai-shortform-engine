"""Local rough-preview report. No browser launch and no render."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clipforge.errors import MediaError
from clipforge.media.disk import format_bytes, read_disk
from clipforge.media.tools import resolve_executable
from clipforge.preview.browser import browser_report
from clipforge.preview.constants import RECIPE_NAME, RECIPE_VERSION
from clipforge.preview.service import default_profile
from clipforge.storage.migrations import CURRENT_SCHEMA_VERSION

Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True, slots=True)
class DoctorLine:
    status: Status
    name: str
    detail: str


def preview_doctor(work_root: Path) -> list[DoctorLine]:
    profile = default_profile()
    lines = [
        DoctorLine("PASS", "schema_version", str(CURRENT_SCHEMA_VERSION)),
        DoctorLine("PASS", "recipe", f"{RECIPE_NAME} v{RECIPE_VERSION}"),
        DoctorLine("PASS", "dimensions", f"{profile.width}x{profile.height}"),
        DoctorLine("PASS", "fps", f"{profile.fps_numerator}/{profile.fps_denominator}"),
        DoctorLine("PASS", "caption_algorithm", profile.caption_algorithm_version),
        DoctorLine("PASS", "renderer_recipe", profile.renderer_recipe_version),
        DoctorLine("PASS", "profile_fingerprint", profile.fingerprint()),
    ]
    lines.append(_tool("node", "CLIPFORGE_NODE", "node"))
    lines.append(_tool("pnpm", "CLIPFORGE_PNPM", "pnpm"))
    lines.append(_tool("ffmpeg", "CLIPFORGE_FFMPEG", "ffmpeg"))
    lines.append(_tool("ffprobe", "CLIPFORGE_FFPROBE", "ffprobe"))
    status, detail = browser_report()
    browser_status: Status = "PASS" if status == "PASS" else "WARN"
    lines.append(DoctorLine(browser_status, "browser", detail))
    renderer = shutil.which("node")
    if renderer:
        lines.append(DoctorLine("PASS", "renderer_package", "node is available for the local Remotion script"))
    else:
        lines.append(DoctorLine("WARN", "renderer_package", "node is not on PATH"))
    try:
        disk = read_disk(work_root if work_root.exists() else work_root.parent)
    except MediaError as exc:
        lines.append(DoctorLine("WARN", "disk", str(exc)))
        return lines
    level: Status = "WARN" if disk.free_bytes <= disk.reserve_bytes else "PASS"
    lines.append(
        DoctorLine(
            level,
            "disk",
            f"free {format_bytes(disk.free_bytes)}; reserve {format_bytes(disk.reserve_bytes)}",
        )
    )
    return lines


def format_doctor(lines: list[DoctorLine]) -> str:
    return "\n".join(f"{line.status} {line.name}: {line.detail}" for line in lines)


def doctor_status(lines: list[DoctorLine]) -> Status:
    if any(line.status == "FAIL" for line in lines):
        return "FAIL"
    if any(line.status == "WARN" for line in lines):
        return "WARN"
    return "PASS"


def _tool(name: str, env_name: str, program: str) -> DoctorLine:
    try:
        path = resolve_executable(env_name, program)
    except MediaError as exc:
        return DoctorLine("WARN", name, str(exc))
    return DoctorLine("PASS", name, path)
