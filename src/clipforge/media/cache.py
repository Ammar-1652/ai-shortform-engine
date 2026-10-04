"""A derived file is reusable only when the sidecar, the bytes, and the recipe agree."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import atomic_replace, ensure_within
from clipforge.schemas.ingest import DerivativeCacheRecord


def read_cache_record(path: Path) -> DerivativeCacheRecord | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        return DerivativeCacheRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, UnicodeError):
        return None


def cache_identity_matches(
    record: DerivativeCacheRecord,
    *,
    recipe_name: str,
    recipe_version: str,
    source_sha256: str,
    project_id: str,
    source_asset_id: str,
    video_stream_index: int,
    audio_stream_index: int | None,
    artifact_path: Path,
) -> bool:
    if record.recipe_name != recipe_name or record.recipe_version != recipe_version:
        return False
    if record.project_id != project_id or record.source_asset_id != source_asset_id:
        return False
    if record.source_sha256 != source_sha256:
        return False
    if record.video_stream_index != video_stream_index:
        return False
    if record.audio_stream_index != audio_stream_index:
        return False
    if artifact_path.is_symlink() or not artifact_path.is_file():
        return False
    try:
        size = artifact_path.stat().st_size
    except OSError:
        return False
    if size != record.size_bytes:
        return False
    try:
        digest = sha256_file(artifact_path)
    except MediaError:
        return False
    return digest == record.artifact_sha256


def write_cache_record(path: Path, record: DerivativeCacheRecord, root: Path) -> None:
    ensure_within(root, path)
    partial = path.with_name(f"{path.name}.partial.{os.getpid()}")
    ensure_within(root, partial)
    partial.write_text(json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n", encoding="utf-8")
    atomic_replace(partial, path, root)
