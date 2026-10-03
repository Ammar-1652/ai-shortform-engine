"""Lightweight reads of a stored rough preview set."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError, StorageError
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import SourceWorkspace, ensure_within
from clipforge.preview.constants import KIND_PREVIEW
from clipforge.schemas.preview import RoughPreviewSetDocument
from clipforge.storage import Database, find_artifact, get_source_asset
from clipforge.transcription.io import read_text


def load_preview_document(database: Database, source_asset_id: str, work_root: Path) -> RoughPreviewSetDocument:
    root = work_root.resolve()
    try:
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
            row = find_artifact(connection, source.project_id, source_asset_id, KIND_PREVIEW)
    except StorageError as exc:
        raise MediaError(str(exc)) from exc
    if row is None:
        raise MediaError(
            f"no rough preview set for source {source_asset_id}. "
            f"Run `clipforge preview render {source_asset_id}`."
        )
    try:
        path = path_from_file_uri(row.uri)
        ensure_within(root, path)
        document = RoughPreviewSetDocument.model_validate_json(read_text(path))
    except (OSError, ValidationError, ValueError, MediaError) as exc:
        raise MediaError(f"stored rough preview set could not be read: {exc}") from exc
    if document.project_id != source.project_id or document.source_asset_id != source_asset_id:
        raise MediaError("stored rough preview set names a different project or source")
    workspace = SourceWorkspace(root, source.project_id, source_asset_id)
    expected = workspace.preview_run_dir(document.preview_set_id)
    if path.parent != expected:
        raise MediaError("preview manifest is outside this source's preview runs")
    return document


def format_preview_list(document: RoughPreviewSetDocument) -> str:
    if not document.previews:
        return "rendered: 0\nNo previews."
    lines = ["rank\tcandidate_id\tstart_us\tend_us\tduration_us\tcaptions\tpreview\tsha256"]
    for item in document.previews:
        lines.append(
            f"{item.rank}\t{item.candidate_id}\t{item.source_start_us}\t{item.source_end_us}\t"
            f"{item.output_duration_us}\t{item.caption_count}\t{item.preview_relative_path}\t"
            f"{item.preview_sha256[:12]}"
        )
    return "\n".join(lines)


def format_preview(document: RoughPreviewSetDocument, candidate_id: str) -> str:
    matches = [item for item in document.previews if item.candidate_id == candidate_id]
    if not matches:
        raise MediaError(f"candidate {candidate_id} is not in the stored preview set")
    item = matches[0]
    return "\n".join(
        [
            f"candidate_id: {item.candidate_id}",
            f"rank: {item.rank}",
            f"source_start_us: {item.source_start_us}",
            f"source_end_us: {item.source_end_us}",
            f"output_duration_us: {item.output_duration_us}",
            f"output_frame_count: {item.output_frame_count}",
            f"caption_count: {item.caption_count}",
            f"timing_quality: {item.timing_quality}",
            "word timing remains provisional",
            f"width: {item.width}",
            f"height: {item.height}",
            f"fps: {item.output_fps_numerator}/{item.output_fps_denominator}",
            f"preview: {item.preview_relative_path}",
            f"sha256: {item.preview_sha256}",
            f"video_codec: {item.detected_video_codec}",
            f"pixel_format: {item.detected_pixel_format}",
            f"audio_codec: {item.detected_audio_codec}",
            f"detected_duration_us: {item.detected_duration_us}",
            f"duration_error_us: {item.duration_error_us}",
            "quality_score and edit_opportunity_score are editorial heuristics and do not affect this file",
        ]
    )
