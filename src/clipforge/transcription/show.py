"""Read a stored transcript. This does not load a model, decode media, or use the network."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.media import Transcript
from clipforge.storage import Database, find_artifact, get_source_asset
from clipforge.transcription.constants import KIND_TRANSCRIPT
from clipforge.transcription.document import display_text
from clipforge.transcription.io import read_text


def load_transcript(*, database: Database, source_asset_id: str, work_root: Path) -> Transcript:
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
        row = find_artifact(connection, source.project_id, source_asset_id, KIND_TRANSCRIPT)
    if row is None:
        raise MediaError(
            f"source {source_asset_id} has no transcript artifact. "
            "Run `clipforge transcript run` after `clipforge media prepare`."
        )
    workspace = SourceWorkspace(work_root.resolve(), source.project_id, source_asset_id)
    path = path_from_file_uri(row.uri) if row.uri.startswith("file:") else workspace.transcript_file()
    if not path.is_file():
        path = workspace.transcript_file()
    if not path.is_file():
        raise MediaError(f"transcript file is missing at {path}")
    try:
        document = Transcript.model_validate_json(read_text(path))
    except (OSError, ValidationError, UnicodeError) as exc:
        raise MediaError(f"transcript file is not a valid Clipforge transcript: {exc}") from exc
    if document.source_asset_id != source_asset_id or document.project_id != source.project_id:
        raise MediaError("transcript file does not belong to this source and project")
    return document


def format_transcript(document: Transcript, *, as_json: bool) -> str:
    if as_json:
        return read_json(document)
    text = display_text(document)
    header = [
        f"source_asset_id: {document.source_asset_id}",
        f"transcript_id: {document.transcript_id}",
        f"language: {document.detected_language or document.language_requested}",
        f"model: {document.asr_model}",
        f"revision: {document.model_revision}",
        f"device: {document.device}",
        f"compute_type: {document.compute_type}",
        f"segments: {len(document.segments)}",
        f"words: {sum(len(segment.words) for segment in document.segments)}",
        f"created_at: {document.provenance.created_at.isoformat()}",
        f"timing_quality: {document.timing_quality}",
        "",
        text,
    ]
    return "\n".join(header)


def read_json(document: Transcript) -> str:
    from clipforge.transcription.io import dump_json

    return dump_json(document)
