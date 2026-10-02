"""Read a visual-analysis sidecar and compare it with the current run settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from clipforge.media.hashing import sha256_file
from clipforge.schemas.vision import VisualAnalysisCacheRecord


def read_visual_cache(path: Path) -> VisualAnalysisCacheRecord | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return VisualAnalysisCacheRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None


def cache_identity_matches(
    record: VisualAnalysisCacheRecord,
    *,
    project_id: str,
    source_asset_id: str,
    source_sha256: str,
    proxy_sha256: str,
    proxy_recipe_name: str,
    proxy_recipe_version: str,
    recipe_name: str,
    recipe_version: str,
    pyscenedetect_version: str,
    scene_backend: str,
    scene_profile_fingerprint: str,
    pyav_version: str,
    opencv_version: str,
    mediapipe_version: str,
    face_model_sha256: str,
    face_profile_fingerprint: str,
    sampling_profile_fingerprint: str,
    tracking_profile_fingerprint: str,
    analysis_path: Path,
) -> bool:
    """True when the sidecar describes this source, proxy, and current profile.

    ``created_at`` is ignored. The analysis file hash is checked. Producer
    binding is a separate step because this function does not see the database.
    """
    if record.project_id != project_id or record.source_asset_id != source_asset_id:
        return False
    if record.source_sha256 != source_sha256 or record.proxy_sha256 != proxy_sha256:
        return False
    if record.proxy_recipe_name != proxy_recipe_name or record.proxy_recipe_version != proxy_recipe_version:
        return False
    if record.recipe_name != recipe_name or record.recipe_version != recipe_version:
        return False
    if record.pyscenedetect_version != pyscenedetect_version or record.scene_backend != scene_backend:
        return False
    if record.scene_profile_fingerprint != scene_profile_fingerprint:
        return False
    if record.pyav_version != pyav_version or record.opencv_version != opencv_version:
        return False
    if record.mediapipe_version != mediapipe_version or record.face_model_sha256 != face_model_sha256:
        return False
    if record.face_profile_fingerprint != face_profile_fingerprint:
        return False
    if record.sampling_profile_fingerprint != sampling_profile_fingerprint:
        return False
    if record.tracking_profile_fingerprint != tracking_profile_fingerprint:
        return False
    if not analysis_path.is_file() or analysis_path.is_symlink():
        return False
    try:
        digest = sha256_file(analysis_path)
        size = analysis_path.stat().st_size
    except OSError:
        return False
    return digest == record.analysis_artifact_sha256 and size == record.analysis_artifact_size
