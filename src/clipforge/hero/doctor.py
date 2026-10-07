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
            "a normal align sets HF_HUB_OFFLINE, TRANSFORMERS_OFFLINE, and HF_DATASETS_OFFLINE to 1",
        ),
    ]
    lines.append(DoctorLine("PASS", "python_compatibility", "project requires Python 3.11 or newer"))
    lines.extend(_whisperx())
    lines.append(_speech_evidence())
    lines.append(_package("torch"))
    lines.append(_package("torchaudio"))
    lines.append(_package("nltk"))
    lines.append(_punkt())
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
    from clipforge.language.model_manifest import measured_whisperx_version

    measured = measured_whisperx_version()
    if measured:
        configured = os.environ.get("CLIPFORGE_ALIGN_PYTHON", "").strip()
        source = configured or str(Path.home() / ".local" / "clipforge-hero-align" / "bin" / "python")
        return [DoctorLine("PASS", "whisperx", f"{measured} via {source}")]
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
    del whisperx
    try:
        from importlib.metadata import version

        found = version("whisperx")
    except Exception:
        found = ""
    if not found:
        found = "unknown"
    return [DoctorLine("PASS", "whisperx", found)]


def _package(name: str) -> DoctorLine:
    try:
        module = __import__(name)
    except ImportError:
        return DoctorLine(
            "WARN",
            name,
            "not installed. It is not part of the default Clipforge environment.",
        )
    version = getattr(module, "__version__", "")
    if not isinstance(version, str) or not version:
        version = "unknown"
    return DoctorLine("PASS", name, version)


def _speech_evidence() -> DoctorLine:
    """Explain the exact operator action needed for a live Hero alignment."""
    from clipforge.language.model_manifest import speech_evidence_root
    from clipforge.language.providers import provider_for

    root = speech_evidence_root()
    if root is None:
        return DoctorLine(
            "WARN",
            "speech_evidence",
            "not configured; export CLIPFORGE_SPEECH_EVIDENCE_ROOT to the measured WAV directory",
        )
    status = provider_for("en-US").live_status
    if status == "verified_live":
        return DoctorLine("PASS", "speech_evidence", f"en-US verified_live ({root})")
    return DoctorLine("WARN", "speech_evidence", f"en-US {status} ({root})")


def _punkt() -> DoctorLine:
    try:
        import nltk  # type: ignore[import-not-found]
    except ImportError:
        return DoctorLine("WARN", "nltk_punkt", "NLTK is not installed, so punkt data was not checked")
    found: list[str] = []
    for resource in ("tokenizers/punkt_tab/english/", "tokenizers/punkt/english.pickle"):
        try:
            found.append(str(nltk.data.find(resource)))
        except LookupError:
            continue
    if found:
        return DoctorLine("PASS", "nltk_punkt", found[0])
    return DoctorLine(
        "WARN",
        "nltk_punkt",
        "English punkt data is not cached. A normal align will not download it.",
    )


def _model() -> DoctorLine:
    hf_roots: list[Path] = []
    home = os.environ.get("HF_HOME")
    if home:
        hf_roots.append(Path(home) / "hub")
    hub = os.environ.get("HUGGINGFACE_HUB_CACHE")
    if hub:
        hf_roots.append(Path(hub))
    hf_roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    needle = "models--" + _ALIGN_MODEL.replace("/", "--")
    for root in hf_roots:
        if (root / needle).exists():
            return DoctorLine("PASS", "alignment_model", f"{_ALIGN_MODEL} is present under {root}")
    torch_home = Path(os.environ.get("TORCH_HOME", str(Path.home() / ".cache" / "torch")))
    checkpoints = torch_home / "hub" / "checkpoints"
    cached = sorted(checkpoints.glob("wav2vec2*.pth")) if checkpoints.is_dir() else []
    if cached:
        return DoctorLine(
            "PASS",
            "alignment_model",
            f"WAV2VEC2_ASR_BASE_960H checkpoint {cached[0].name} is present under {checkpoints}",
        )
    return DoctorLine(
        "WARN",
        "alignment_model",
        f"{_ALIGN_MODEL} and the torchaudio WAV2VEC2 checkpoint were not found. "
        "A normal align will not download them.",
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
