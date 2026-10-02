"""Candidate-set cache identity. ``created_at`` is not part of it."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from clipforge.media.hashing import sha256_file
from clipforge.schemas.candidates import CandidateMiningCacheRecord, CandidateMiningProfile


def read_candidate_cache(path: Path) -> CandidateMiningCacheRecord | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return CandidateMiningCacheRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, UnicodeError, ValueError):
        return None


def cache_identity_matches(
    record: CandidateMiningCacheRecord,
    *,
    project_id: str,
    source_asset_id: str,
    source_sha256: str,
    transcript_id: str,
    transcript_sha256: str,
    visual_analysis_id: str,
    visual_analysis_sha256: str,
    candidate_input_sha256: str,
    profile: CandidateMiningProfile,
    candidate_path: Path,
) -> bool:
    """True when the sidecar describes this source, both upstream artifacts, and this profile."""
    if record.project_id != project_id or record.source_asset_id != source_asset_id:
        return False
    if record.source_sha256 != source_sha256:
        return False
    if record.transcript_id != transcript_id or record.transcript_sha256 != transcript_sha256:
        return False
    if (
        record.visual_analysis_id != visual_analysis_id
        or record.visual_analysis_sha256 != visual_analysis_sha256
    ):
        return False
    if record.candidate_input_sha256 != candidate_input_sha256:
        return False
    if record.profile_fingerprint != profile.fingerprint():
        return False
    # Algorithm versions are Literal fields on both models and are inside the fingerprint.
    if not candidate_path.is_file() or candidate_path.is_symlink():
        return False
    try:
        digest = sha256_file(candidate_path)
        size = candidate_path.stat().st_size
    except OSError:
        return False
    return digest == record.candidate_artifact_sha256 and size == record.candidate_artifact_size
