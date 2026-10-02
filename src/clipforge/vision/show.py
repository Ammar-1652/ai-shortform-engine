"""Read a stored visual analysis. No model load, no decode, no network."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import ensure_within
from clipforge.schemas.vision import VisualAnalysisDocument
from clipforge.storage import Database, find_artifact, get_source_asset
from clipforge.vision.constants import KIND_VISUAL


def load_visual_analysis(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
) -> VisualAnalysisDocument:
    """Return the current document after checking project and source identity."""
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
        row = find_artifact(connection, source.project_id, source_asset_id, KIND_VISUAL)
    if row is None:
        raise MediaError(
            f"source {source_asset_id} has no visual analysis. "
            f"Run `clipforge vision analyze {source_asset_id}`."
        )
    try:
        path = path_from_file_uri(row.uri)
        ensure_within(work_root.resolve(), path)
        document = VisualAnalysisDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError, MediaError) as exc:
        raise MediaError(f"could not read the visual analysis for {source_asset_id}: {exc}") from exc
    if document.project_id != source.project_id or document.source_asset_id != source.source_asset_id:
        raise MediaError("stored visual analysis belongs to a different project or source")
    return document


def format_visual_analysis(document: VisualAnalysisDocument) -> str:
    summary = document.summary
    lines = [
        f"analysis_id: {document.analysis_id}",
        f"source_asset_id: {document.source_asset_id}",
        f"created_at: {document.created_at.isoformat()}",
        f"scene_count: {summary.scene_count}",
        f"representative_frames: {summary.representative_frame_count}",
        f"face_detections: {summary.face_detection_count}",
        f"face_tracks: {summary.face_track_count}",
        f"contact_sheets: {len(document.contact_sheets)}",
        f"pyscenedetect: {document.pyscenedetect_version}",
        f"scene_backend: {document.scene_backend}",
        f"mediapipe: {document.mediapipe_version}",
        f"face_model_sha256: {document.face_model_sha256}",
        "speaker_attribution: unknown",
        "candidate_mining: not performed",
    ]
    return "\n".join(lines)
