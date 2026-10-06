"""Bind an acquired local file to a Whop selection. A declared hash is not local proof."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from clipforge.campaign.providers import CampaignError
from clipforge.campaign.whop_live import _SELECTION_ROOT
from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg, resolve_ffprobe
from clipforge.schemas.whop_discovery import WhopSelectionEvidence


def record_acquired_file(
    work_root: Path,
    evidence_id: str,
    source_id: str,
    relative_file: str,
) -> dict[str, object]:
    """Hash and probe a file the operator already placed. This does not download."""
    root = work_root.resolve()
    evidence_path = root.joinpath(*_SELECTION_ROOT, evidence_id, "evidence.json")
    if evidence_path.is_symlink() or not evidence_path.is_file():
        raise CampaignError("whop selection is missing", code="missing_selection")
    evidence = WhopSelectionEvidence.model_validate_json(evidence_path.read_text(encoding="utf-8"))
    if source_id not in evidence.source_ids:
        raise CampaignError("whop source is missing", code="missing_source")
    if relative_file.startswith("/") or "\\" in relative_file or ".." in relative_file.split("/"):
        raise CampaignError("whop acquisition path is not relative", code="invalid_document")
    target = root / relative_file
    if target.is_symlink() or not target.is_file():
        raise CampaignError("whop acquisition file is missing", code="missing_source")
    acquired = sha256_file(target)
    declared = evidence.source_hashes[evidence.source_ids.index(source_id)]
    status = "acquired" if acquired == declared else "hash_mismatch"
    probe_fingerprint = None
    probe_error: Exception | None = None
    try:
        probe_fingerprint = _probe_fingerprint(target)
        _decode(target)
    except (MediaError, OSError) as exc:
        probe_error = exc
        if status == "acquired":
            status = "probe_failed"
    record = {
        "source_id": source_id,
        "declared_content_sha256": declared,
        "acquired_file_sha256": acquired,
        "acquired_file_size": target.stat().st_size,
        "acquired_ffprobe_fingerprint": probe_fingerprint,
        "acquisition_status": status,
        "hash_basis": "acquired",
        "render_allowed": status == "acquired",
    }
    path = evidence_path.parent / "acquired.json"
    existing: list[dict[str, object]] = []
    if path.is_file() and not path.is_symlink():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            existing = [
                item for item in loaded if isinstance(item, dict) and item.get("source_id") != source_id
            ]
    existing.append(record)
    path.write_text(json.dumps(existing, sort_keys=True) + "\n", encoding="utf-8")
    if status == "hash_mismatch":
        raise CampaignError("whop acquired hash does not match the declaration", code="hash_mismatch")
    if probe_error is not None:
        raise CampaignError("whop acquisition probe failed", code="probe_failed") from probe_error
    return record


def _probe_fingerprint(path: Path) -> str:
    runner = ProcessRunner()
    result = runner.run(
        [resolve_ffprobe(), "-v", "error", "-print_format", "json", "-show_format", str(path)],
        log_path=None,
        check=True,
    )
    return hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()


def _decode(path: Path) -> None:
    runner = ProcessRunner()
    runner.run(
        [resolve_ffmpeg(), "-v", "error", "-i", str(path), "-f", "null", "-"],
        log_path=None,
        check=True,
    )
