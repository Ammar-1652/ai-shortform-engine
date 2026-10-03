"""Read-only report for the local review surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clipforge.preview.constants import RECIPE_NAME, RECIPE_VERSION
from clipforge.review.service import LOOPBACK_HOST
from clipforge.schemas.governance import ReviewDecision
from clipforge.storage.migrations import CURRENT_SCHEMA_VERSION

Status = Literal["PASS", "WARN", "FAIL"]
_STATIC = Path(__file__).resolve().parent / "static"
_FILES = ("index.html", "app.js", "styles.css")


@dataclass(frozen=True, slots=True)
class DoctorLine:
    status: Status
    name: str
    detail: str


def review_doctor() -> list[DoctorLine]:
    lines = [
        DoctorLine("PASS", "schema_version", str(CURRENT_SCHEMA_VERSION)),
        DoctorLine(
            "PASS",
            "review_contract",
            "ReviewDecision fields: " + ", ".join(sorted(ReviewDecision.model_fields)),
        ),
        DoctorLine("PASS", "preview_recipe", f"{RECIPE_NAME} v{RECIPE_VERSION}"),
        DoctorLine("PASS", "loopback", f"review open binds to {LOOPBACK_HOST} only"),
        DoctorLine(
            "PASS",
            "preview_artifact",
            "pass a source id to review verify to check the current rough preview set",
        ),
    ]
    for name in _FILES:
        path = _STATIC / name
        if path.is_symlink() or not path.is_file():
            lines.append(DoctorLine("FAIL", "static", f"{name} is missing"))
        else:
            lines.append(DoctorLine("PASS", "static", name))
    return lines


def format_doctor(lines: list[DoctorLine]) -> str:
    return "\n".join(f"{line.status} {line.name}: {line.detail}" for line in lines)


def doctor_status(lines: list[DoctorLine]) -> Status:
    if any(line.status == "FAIL" for line in lines):
        return "FAIL"
    if any(line.status == "WARN" for line in lines):
        return "WARN"
    return "PASS"
