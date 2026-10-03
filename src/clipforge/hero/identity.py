"""Stable Hero cache identity. Output file hashes are checked beside this digest."""

from __future__ import annotations

import hashlib
import json

from clipforge.hero.alignment import alignment_config_sha256
from clipforge.schemas.editorial import CandidateClip


def digest_model(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def digest_candidate(candidate: CandidateClip) -> str:
    return digest_model(candidate.model_dump(mode="json"))


def alignment_identity_config(*, model_name: str, whisperx_version: str, device: str) -> str:
    return alignment_config_sha256(model_name=model_name, whisperx_version=whisperx_version, device=device)


def hero_input_digest(
    *,
    source_sha256: str,
    candidate_set_artifact_id: str,
    candidate_set_sha256: str,
    transcript_id: str,
    transcript_sha256: str,
    visual_analysis_id: str,
    visual_analysis_sha256: str,
    analysis_proxy_sha256: str,
    asr_audio_sha256: str,
    rough_preview_artifact_id: str,
    rough_preview_set_id: str,
    rough_manifest_sha256: str,
    profile_fingerprint: str,
    motion_library_version: str,
    renderer_recipe_version: str,
    caption_algorithm_version: str,
    alignment_model: str,
    whisperx_version: str,
    alignment_config_sha256: str,
    approvals: list[dict[str, str]],
) -> str:
    """Digest of everything that must match before a Hero render can be reused."""
    payload = {
        "alignment_config_sha256": alignment_config_sha256,
        "alignment_model": alignment_model,
        "analysis_proxy_sha256": analysis_proxy_sha256,
        "approvals": approvals,
        "asr_audio_sha256": asr_audio_sha256,
        "candidate_set_artifact_id": candidate_set_artifact_id,
        "candidate_set_sha256": candidate_set_sha256,
        "caption_algorithm_version": caption_algorithm_version,
        "motion_library_version": motion_library_version,
        "profile_fingerprint": profile_fingerprint,
        "renderer_recipe_version": renderer_recipe_version,
        "rough_manifest_sha256": rough_manifest_sha256,
        "rough_preview_artifact_id": rough_preview_artifact_id,
        "rough_preview_set_id": rough_preview_set_id,
        "source_sha256": source_sha256,
        "transcript_id": transcript_id,
        "transcript_sha256": transcript_sha256,
        "visual_analysis_id": visual_analysis_id,
        "visual_analysis_sha256": visual_analysis_sha256,
        "whisperx_version": whisperx_version,
    }
    return digest_model(payload)
