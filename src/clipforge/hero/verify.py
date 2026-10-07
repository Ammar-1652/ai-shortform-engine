"""Read-only Hero verification. This does not align, render, repair, or rescore."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clipforge.errors import MediaError
from clipforge.hero.show import CurrentHero, load_current_hero
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
    lines = [
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
    ]
    lines.extend(_alignment_lines(current))
    return HeroVerifyReport(source_asset_id, tuple(lines))


def _alignment_lines(current: CurrentHero) -> list[VerifyLine]:
    from clipforge.language.evidence import validate_current_alignment_evidence
    from clipforge.schemas.hero import ForcedAlignmentDocument

    workspace = current.inputs.pair.workspace
    source_sha = current.inputs.pair.manifest.content_sha256
    lines: list[VerifyLine] = []
    for draft in current.document.drafts:
        path = workspace.hero_alignment_file(draft.candidate_id)
        if path.is_symlink() or not path.is_file():
            continue
        try:
            document = ForcedAlignmentDocument.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        if document.alignment_status != "verified_live":
            continue
        evidence = validate_current_alignment_evidence(
            document=document,
            candidate_id=draft.candidate_id,
            source_sha256=source_sha,
        )
        if evidence.status == "verified_live":
            lines.append(VerifyLine("PASS", "alignment", evidence.evidence_digest))
        else:
            lines.append(VerifyLine("FAIL", "alignment", evidence.blocker or evidence.status))
    return lines
