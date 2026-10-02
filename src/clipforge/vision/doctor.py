"""Visual-analysis runtime report. This command does not download or load a model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clipforge.errors import MediaError
from clipforge.media.disk import format_bytes, read_disk
from clipforge.paths import resolve_work_dir
from clipforge.vision.constants import (
    ADAPTIVE_THRESHOLD,
    FACE_MODEL_FILENAME,
    FACE_SAMPLE_INTERVAL_US,
    MIN_DETECTION_CONFIDENCE,
    SCENE_BACKEND,
    SCENE_DETECTOR,
)
from clipforge.vision.models import face_model_is_cached, face_model_path, face_model_sha256
from clipforge.vision.runtime import cv2_file, installed_versions

Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True, slots=True)
class DoctorLine:
    status: Status
    name: str
    detail: str


def vision_doctor(model_root: Path, work_root: Path | None = None) -> list[DoctorLine]:
    lines: list[DoctorLine] = []
    try:
        scene, pyav, opencv, mediapipe = installed_versions()
    except MediaError as exc:
        lines.append(DoctorLine("FAIL", "imports", str(exc)))
        return lines
    lines.append(DoctorLine("PASS", "pyscenedetect", scene))
    lines.append(DoctorLine("PASS", "pyav", pyav))
    lines.append(DoctorLine("PASS", "opencv", f"{opencv} at {cv2_file()}"))
    lines.append(DoctorLine("PASS", "mediapipe", mediapipe))
    lines.append(
        DoctorLine(
            "PASS",
            "profile",
            f"{SCENE_DETECTOR} backend {SCENE_BACKEND} threshold {ADAPTIVE_THRESHOLD} "
            f"face interval {FACE_SAMPLE_INTERVAL_US} us confidence {MIN_DETECTION_CONFIDENCE}",
        )
    )
    if model_root.is_symlink():
        lines.append(DoctorLine("WARN", "model_root", f"{model_root} is a symlink and was not followed"))
    elif not model_root.exists():
        lines.append(DoctorLine("WARN", "face_model", f"face detector model is not cached under {model_root}"))
    else:
        lines.append(DoctorLine("PASS", "model_root", str(model_root.resolve())))
        if face_model_is_cached(model_root):
            digest = face_model_sha256(model_root) or "unreadable"
            lines.append(DoctorLine("PASS", "face_model", f"{face_model_path(model_root)} sha256 {digest}"))
        else:
            lines.append(
                DoctorLine(
                    "WARN",
                    "face_model",
                    f"{FACE_MODEL_FILENAME} is not cached. "
                    "Run `clipforge vision model fetch face-detector --allow-model-download`.",
                )
            )
    work = work_root if work_root is not None else resolve_work_dir(None)
    try:
        disk = read_disk(work if work.exists() else work.parent)
    except MediaError as exc:
        lines.append(DoctorLine("WARN", "disk", str(exc)))
    else:
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
