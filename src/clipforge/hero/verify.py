"""Read-only Hero verification. This does not align, render, repair, or rescore."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clipforge.errors import MediaError
from clipforge.hero.show import load_current_hero
from clipforge.storage import Database

Status = Literal["PASS", "FAIL"]


@dataclass(frozen=True, slots=True)
class VerifyLine:
    status: Status
    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class HeroVerifyReport:
    source_asset_id: str
    lines: tuple[VerifyLine, ...]

    @property
    def status(self) -> Status:
        if any(line.status == "FAIL" for line in self.lines):
            return "FAIL"
        return "PASS"


def verify_hero(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
) -> HeroVerifyReport:
    """Check the current Hero draft set without creating files or jobs."""
    try:
        current = load_current_hero(database, source_asset_id, work_root)
    except MediaError as exc:
        return HeroVerifyReport(
            source_asset_id,
            (VerifyLine("FAIL", "hero", str(exc)),),
        )
    return HeroVerifyReport(
        source_asset_id,
        (
            VerifyLine(
                "PASS",
                "hero",
                f"hero set {current.document.hero_set_id} drafts {len(current.document.drafts)}",
            ),
            VerifyLine("PASS", "manifest", current.manifest_sha256),
            VerifyLine(
                "PASS",
                "approval",
                f"rough preview artifact {current.document.rough_preview_artifact_id}",
            ),
        ),
    )
