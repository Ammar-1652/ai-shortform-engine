"""Lightweight reads of a stored candidate set. These commands do not verify or score."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from clipforge.candidates.constants import KIND_CANDIDATE
from clipforge.errors import MediaError, StorageError
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import SourceWorkspace, ensure_within
from clipforge.schemas.candidates import CandidateMiningDocument
from clipforge.storage import Database, find_artifact, get_source_asset
from clipforge.transcription.io import read_text


def load_candidate_document(
    database: Database,
    source_asset_id: str,
    work_root: Path,
) -> CandidateMiningDocument:
    """Load the current candidate document when it names this source. This is not ``verify``."""
    root = work_root.resolve()
    try:
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
            row = find_artifact(connection, source.project_id, source_asset_id, KIND_CANDIDATE)
    except StorageError as exc:
        raise MediaError(str(exc)) from exc
    if row is None:
        raise MediaError(
            f"no candidate set for source {source_asset_id}. Run `clipforge candidate mine {source_asset_id}`."
        )
    try:
        path = path_from_file_uri(row.uri)
        ensure_within(root, path)
        document = CandidateMiningDocument.model_validate_json(read_text(path))
    except (OSError, ValidationError, ValueError, MediaError) as exc:
        raise MediaError(f"stored candidate set could not be read: {exc}") from exc
    if document.project_id != source.project_id or document.source_asset_id != source_asset_id:
        raise MediaError("stored candidate set names a different project or source")
    workspace = SourceWorkspace(root, source.project_id, source_asset_id)
    expected = workspace.candidate_run_dir(document.mining_id) / "candidates.json"
    if path != expected:
        raise MediaError("candidate artifact is outside this source's candidate runs")
    return document


def format_candidate_list(document: CandidateMiningDocument) -> str:
    if not document.candidates:
        return (
            f"selected: 0\nbelow_soft_target: {'yes' if document.summary.below_soft_target else 'no'}\n"
            "No candidates."
        )
    lines = ["candidate_id\tstart_us\tend_us\tduration_us\tquality_score\tedit_opportunity_score\texcerpt"]
    scores = {item.candidate_id: item for item in document.score_breakdowns}
    bundles = {item.candidate_id: item for item in document.evidence_bundles}
    for candidate in document.candidates:
        segment = candidate.time_map.segments[0]
        duration = segment.source_end_us - segment.source_start_us
        breakdown = scores[candidate.candidate_id]
        excerpt = bundles[candidate.candidate_id].transcript_excerpt.replace("\t", " ")
        lines.append(
            f"{candidate.candidate_id}\t{segment.source_start_us}\t{segment.source_end_us}\t"
            f"{duration}\t{breakdown.quality_score:.6f}\t{breakdown.edit_opportunity_score:.6f}\t{excerpt}"
        )
    return "\n".join(lines)


def format_candidate(document: CandidateMiningDocument, candidate_id: str) -> str:
    matches = [item for item in document.candidates if item.candidate_id == candidate_id]
    if not matches:
        raise MediaError(f"candidate {candidate_id} is not in the stored candidate set")
    candidate = matches[0]
    breakdown = next(item for item in document.score_breakdowns if item.candidate_id == candidate_id)
    bundle = next(item for item in document.evidence_bundles if item.candidate_id == candidate_id)
    segment = candidate.time_map.segments[0]
    lines = [
        f"candidate_id: {candidate.candidate_id}",
        f"source_start_us: {segment.source_start_us}",
        f"source_end_us: {segment.source_end_us}",
        f"duration_us: {segment.source_end_us - segment.source_start_us}",
        f"status: {candidate.status.value}",
        f"quality_score: {breakdown.quality_score:.6f}",
        f"edit_opportunity_score: {breakdown.edit_opportunity_score:.6f}",
        "creative_score: editorial heuristic; not a virality probability",
        f"timing_quality: {document.boundary_timing_quality}",
        "word timing remains provisional",
        f"duration_fit: {_fmt(breakdown.duration_fit)}",
        f"speech_coverage: {_fmt(breakdown.speech_coverage)}",
        f"boundary_completeness: {_fmt(breakdown.boundary_completeness)}",
        f"transcript_reliability: {_fmt(breakdown.transcript_reliability)}",
        f"information_density: {_fmt(breakdown.information_density)}",
        f"opening_structure: {_fmt(breakdown.opening_structure)}",
        f"visual_evidence_coverage: {_fmt(breakdown.visual_evidence_coverage)}",
        f"quality_weight_coverage: {breakdown.quality_weight_coverage:.6f}",
        f"scene_change_signal: {_fmt(breakdown.scene_change_signal)}",
        f"visual_difference_signal: {_fmt(breakdown.visual_difference_signal)}",
        f"face_layout_variation: {_fmt(breakdown.face_layout_variation)}",
        f"numeric_token_signal: {_fmt(breakdown.numeric_token_signal)}",
        f"punctuation_emphasis_signal: {_fmt(breakdown.punctuation_emphasis_signal)}",
        f"multi_scene_signal: {_fmt(breakdown.multi_scene_signal)}",
        f"edit_opportunity_weight_coverage: {breakdown.edit_opportunity_weight_coverage:.6f}",
        f"excerpt: {bundle.transcript_excerpt}",
        f"transcript_segments: {', '.join(bundle.transcript_segment_ids)}",
        f"visual_scenes: {', '.join(bundle.visual_scene_ids)}",
        f"frames: {', '.join(bundle.representative_frame_ids) if bundle.representative_frame_ids else 'none'}",
        f"face_observations: {len(bundle.face_observation_ids)}",
        f"time_map_segments: {len(candidate.time_map.segments)}",
        "compliance:",
    ]
    for result in candidate.compliance:
        lines.append(f"  {result.rule_id}: {result.status.value}")
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    if value is None:
        return "none"
    return f"{value:.6f}"
