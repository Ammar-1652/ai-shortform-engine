"""Local candidate-mining report. No model load, no network, and no mining."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clipforge.candidates.constants import RECIPE_NAME, RECIPE_VERSION
from clipforge.candidates.service import default_profile
from clipforge.errors import MediaError
from clipforge.media.disk import format_bytes, read_disk
from clipforge.storage.migrations import CURRENT_SCHEMA_VERSION

Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True, slots=True)
class DoctorLine:
    status: Status
    name: str
    detail: str


def candidate_doctor(work_root: Path) -> list[DoctorLine]:
    profile = default_profile()
    lines = [
        DoctorLine("PASS", "schema_version", str(CURRENT_SCHEMA_VERSION)),
        DoctorLine("PASS", "recipe", f"{RECIPE_NAME} v{RECIPE_VERSION}"),
        DoctorLine("PASS", "profile_fingerprint", profile.fingerprint()),
        DoctorLine(
            "PASS",
            "duration",
            (
                f"hard {profile.hard_min_duration_us}-{profile.hard_max_duration_us} us; "
                f"preferred {profile.preferred_min_duration_us}-{profile.preferred_max_duration_us} us; "
                f"padding {profile.boundary_padding_us} us"
            ),
        ),
        DoctorLine(
            "PASS",
            "limits",
            (
                f"max_candidates {profile.max_candidates}; soft_target_min {profile.soft_target_min}; "
                f"minimum_words {profile.minimum_transcript_words}; "
                f"raw_cap {profile.maximum_raw_hypotheses}"
            ),
        ),
        DoctorLine("PASS", "scoring_version", profile.scoring_version),
        DoctorLine("PASS", "dedupe_version", profile.dedupe_version),
        DoctorLine("PASS", "work_root", str(work_root)),
    ]
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
