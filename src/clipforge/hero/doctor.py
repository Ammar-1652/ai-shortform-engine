"""Local Hero alignment report. No model download, no browser launch, and no render."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clipforge.errors import MediaError
from clipforge.hero.constants import MOTION_LIBRARY_VERSION, RECIPE_NAME, RECIPE_VERSION
from clipforge.hero.service import default_hero_profile
from clipforge.media.disk import format_bytes, read_disk
from clipforge.media.tools import resolve_executable
from clipforge.preview.browser import browser_report

Status = Literal["PASS", "WARN", "FAIL"]
_ALIGN_MODEL = "facebook/wav2vec2-base-960h"


@dataclass(frozen=True, slots=True)
class DoctorLine:
    status: Status
    name: str
    detail: str


def hero_doctor(work_root: Path) -> list[DoctorLine]:
    """Report WhisperX, the alignment model, and whether a normal run stays offline."""
    profile = default_hero_profile()
    lines = [
        DoctorLine("PASS", "python", platform.python_version()),
        DoctorLine("PASS", "implementation", platform.python_implementation()),
        DoctorLine("PASS", "recipe", f"{RECIPE_NAME} v{RECIPE_VERSION}"),
        DoctorLine("PASS", "profile", f"{profile.profile_id} {profile.width}x{profile.height}"),
        DoctorLine("PASS", "fps", f"{profile.fps_numerator}/{profile.fps_denominator}"),
        DoctorLine("PASS", "profile_fingerprint", profile.fingerprint()),
        DoctorLine("PASS", "motion_library", MOTION_LIBRARY_VERSION),
        DoctorLine("PASS", "caption_algorithm", profile.caption_algorithm_version),
        DoctorLine("PASS", "renderer_recipe", profile.renderer_recipe_version),
        DoctorLine(
            "PASS",
            "offline",
            "a normal align sets HF_HUB_OFFLINE=1 and does not download a model",
        ),
    ]
    lines.append(DoctorLine("PASS", "python_compatibility", "project requires Python 3.11 or newer"))
    lines.extend(_whisperx())
    lines.append(_tool("ffmpeg", "CLIPFORGE_FFMPEG", "ffmpeg"))
    lines.append(_tool("ffprobe", "CLIPFORGE_FFPROBE", "ffprobe"))
    lines.append(_tool("node", "CLIPFORGE_NODE", "node"))
    status, detail = browser_report()
    browser_status: Status = "PASS" if status == "PASS" else "WARN"
    lines.append(DoctorLine(browser_status, "browser", detail))
    lines.append(_model())
    lines.append(_device())
    lines.append(DoctorLine("PASS", "work_root", str(work_root)))
    try:
        disk = read_disk(work_root if work_root.exists() else work_root.parent)
    except MediaError as exc:
        lines.append(DoctorLine("WARN", "disk", str(exc)))
        return lines
    level: Status = "WARN" if disk.free_bytes <= disk.reserve_bytes else "PASS"
    free = format_bytes(disk.free_bytes)
    reserve = format_bytes(disk.reserve_bytes)
    lines.append(DoctorLine(level, "disk", f"free {free}; reserve {reserve}"))
    return lines


def format_doctor(lines: list[DoctorLine]) -> str:
    return "\n".join(f"{line.status} {line.name}: {line.detail}" for line in lines)


def doctor_status(lines: list[DoctorLine]) -> Status:
    if any(line.status == "FAIL" for line in lines):
        return "FAIL"
    if any(line.status == "WARN" for line in lines):
        return "WARN"
    return "PASS"


def _whisperx() -> list[DoctorLine]:
    try:
        import whisperx  # type: ignore[import-not-found]
    except ImportError:
        return [
            DoctorLine(
                "WARN",
                "whisperx",
                "not installed. Hero align fails closed and does not use provisional timings.",
            )
        ]
    version = getattr(whisperx, "__version__", "")
    if not isinstance(version, str) or not version:
        version = "unknown"
    return [DoctorLine("PASS", "whisperx", version)]


def _model() -> DoctorLine:
    roots: list[Path] = []
    home = os.environ.get("HF_HOME")
    if home:
        roots.append(Path(home) / "hub")
    hub = os.environ.get("HUGGINGFACE_HUB_CACHE")
    if hub:
        roots.append(Path(hub))
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    needle = "models--" + _ALIGN_MODEL.replace("/", "--")
    for root in roots:
        if (root / needle).exists():
            return DoctorLine("PASS", "alignment_model", f"{_ALIGN_MODEL} is present under {root}")
    return DoctorLine(
        "WARN",
        "alignment_model",
        f"{_ALIGN_MODEL} was not found in the local Hugging Face cache. A normal align will not download it.",
    )


def _device() -> DoctorLine:
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError:
        return DoctorLine("PASS", "device", "cpu. torch is not installed, so CUDA was not selected")
    cuda = bool(getattr(getattr(torch, "cuda", None), "is_available", lambda: False)())
    if cuda:
        return DoctorLine("PASS", "device", "cuda is available. Hero alignment v1 still requests cpu")
    return DoctorLine("PASS", "device", "cpu")


def _tool(name: str, env_name: str, program: str) -> DoctorLine:
    try:
        resolved = resolve_executable(env_name, program)
    except MediaError as exc:
        return DoctorLine("WARN", name, str(exc))
    return DoctorLine("PASS", name, resolved)
