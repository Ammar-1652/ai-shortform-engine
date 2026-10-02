"""ASR runtime report. This command does not download a model or load weights."""

from __future__ import annotations

import importlib.metadata
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clipforge.media.disk import format_bytes
from clipforge.transcription.constants import BEAM_SIZE, DEFAULT_LANGUAGE, DEFAULT_MODEL, TEMPERATURE
from clipforge.transcription.models import model_is_cached, model_root_status
from clipforge.transcription.runtime import RuntimeFacts, probe_runtime

Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True, slots=True)
class DoctorLine:
    status: Status
    name: str
    detail: str


def transcription_doctor(model_root: Path) -> list[DoctorLine]:
    lines: list[DoctorLine] = []
    lines.extend(_packages())
    try:
        root, free_bytes, reserve_bytes = model_root_status(model_root)
    except Exception as exc:
        lines.append(DoctorLine("FAIL", "model_root", str(exc)))
        root = model_root
        free_bytes = 0
        reserve_bytes = 0
    else:
        lines.append(DoctorLine("PASS", "model_root", str(root)))
        disk_status: Status = "WARN" if free_bytes <= reserve_bytes else "PASS"
        lines.append(
            DoctorLine(
                disk_status,
                "model_disk",
                f"free {format_bytes(free_bytes)}; reserve {format_bytes(reserve_bytes)}",
            )
        )
    facts = _facts(lines)
    if facts is not None:
        if facts.cpu_compute_types:
            lines.append(DoctorLine("PASS", "cpu", f"compute types {', '.join(facts.cpu_compute_types)}"))
        else:
            lines.append(DoctorLine("FAIL", "cpu", "CTranslate2 reported no CPU compute types"))
        if facts.cuda_usable:
            lines.append(
                DoctorLine(
                    "PASS",
                    "cuda",
                    f"devices {facts.cuda_device_count}; compute types {', '.join(facts.cuda_compute_types)}",
                )
            )
        else:
            reason = facts.cuda_error or f"device count {facts.cuda_device_count}"
            lines.append(
                DoctorLine(
                    "WARN",
                    "cuda",
                    f"CUDA is not usable ({reason}). CPU transcription still works. "
                    "This is not a failed transcription install.",
                )
            )
    gpu = _nvidia()
    if gpu is not None:
        lines.append(gpu)
    cached = False
    try:
        cached = model_is_cached(DEFAULT_MODEL, root)
    except Exception as exc:
        lines.append(DoctorLine("WARN", "default_model", f"could not inspect the cache: {exc}"))
    else:
        if cached:
            lines.append(DoctorLine("PASS", "default_model", f"{DEFAULT_MODEL} is in the local cache"))
        else:
            lines.append(
                DoctorLine(
                    "WARN",
                    "default_model",
                    f"{DEFAULT_MODEL} is not cached. "
                    "`transcript run` will not download it unless --allow-model-download is set.",
                )
            )
    lines.append(
        DoctorLine(
            "PASS",
            "profile",
            f"model {DEFAULT_MODEL}; language {DEFAULT_LANGUAGE}; task transcribe; beam {BEAM_SIZE}; "
            f"word timestamps on; VAD off; temperature {TEMPERATURE}",
        )
    )
    return lines


def doctor_status(lines: list[DoctorLine]) -> Status:
    if any(line.status == "FAIL" for line in lines):
        return "FAIL"
    if any(line.status == "WARN" for line in lines):
        return "WARN"
    return "PASS"


def format_doctor(lines: list[DoctorLine]) -> str:
    rendered = [f"[{line.status}] {line.name}: {line.detail}" for line in lines]
    rendered.append(f"summary: {doctor_status(lines)}")
    return "\n".join(rendered)


def _packages() -> list[DoctorLine]:
    lines: list[DoctorLine] = []
    for dist, label in (
        ("faster-whisper", "faster_whisper"),
        ("ctranslate2", "ctranslate2"),
        ("av", "pyav"),
        ("huggingface-hub", "huggingface_hub"),
    ):
        try:
            version = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            lines.append(DoctorLine("FAIL", label, f"{dist} is not installed"))
        else:
            lines.append(DoctorLine("PASS", label, version))
    return lines


def _facts(lines: list[DoctorLine]) -> RuntimeFacts | None:
    try:
        return probe_runtime()
    except Exception as exc:
        lines.append(DoctorLine("FAIL", "ctranslate2_runtime", str(exc)))
        return None


def _nvidia() -> DoctorLine | None:
    if shutil.which("nvidia-smi") is None:
        return DoctorLine(
            "WARN",
            "nvidia_smi",
            "nvidia-smi is not on PATH. This does not by itself disable CPU ASR.",
        )
    import subprocess

    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DoctorLine("WARN", "nvidia_smi", str(exc))
    if completed.returncode != 0:
        return DoctorLine("WARN", "nvidia_smi", (completed.stderr or completed.stdout or "no output").strip())
    row = (completed.stdout or "").strip().splitlines()
    if not row:
        return DoctorLine("WARN", "nvidia_smi", "no GPU rows")
    return DoctorLine("PASS", "nvidia_smi", row[0] + ". This is not proof that CTranslate2 can use CUDA.")
