"""Validate and persist declarative editorial direction briefs.

The operator/skill may propose alternatives, but this module is the authority
that binds them to the current promoted candidate and canonical TimeMap before
the renderer can consume them.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import confine_work_path
from clipforge.hero.motion_style import production_style_ids, style_for_id
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.direction import DirectionDocument, DirectionOption
from clipforge.schemas.hero import AlignedWord
from clipforge.schemas.time import TimeMapDocument
from clipforge.storage import Database
from clipforge.transcription.io import publish_json


def load_direction(workspace: SourceWorkspace, candidate_id: str) -> tuple[DirectionDocument, str] | None:
    path = workspace.direction_file(candidate_id)
    path = confine_work_path(workspace.root, path.relative_to(workspace.root).as_posix(), label="direction")
    if not path.exists():
        return None
    try:
        document = DirectionDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise MediaError(f"direction document could not be read: {exc}") from exc
    return document, sha256_file(path)


def save_direction_brief(
    *,
    database: Database,
    source_asset_id: str,
    candidate_id: str,
    work_root: Path,
    brief_path: Path,
    style: str = "auto",
    allow_unapproved: bool = False,
) -> tuple[DirectionDocument, Path, str]:
    """Validate a skill-produced brief against the current Hero evidence."""

    root = work_root.resolve()
    try:
        document = DirectionDocument.model_validate_json(brief_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise MediaError(f"invalid direction brief: {exc}") from exc
    # Import lazily so the service remains usable by schema/CLI tooling without
    # creating a module cycle with advanced_service.
    from clipforge.hero.advanced_service import _context

    context = _context(
        database,
        source_asset_id,
        candidate_id,
        root,
        require_hero_approval=not allow_unapproved,
    )
    if document.project_id != context.project_id:
        raise MediaError("direction brief project does not match the promoted candidate")
    if document.source_asset_id != source_asset_id or document.candidate_id != candidate_id:
        raise MediaError("direction brief source or candidate does not match the promoted candidate")
    if document.source_sha256 != context.source_sha256:
        raise MediaError("direction brief is stale: source bytes changed")
    if document.hero_plan_sha256 != context.hero_plan_sha256:
        raise MediaError("direction brief is stale: Hero plan changed")
    if document.time_map_sha256 != context.hero_plan.edit_plan.time_map_sha256:
        raise MediaError("direction brief is stale: TimeMap changed")
    if document.alignment_sha256 != context.alignment_sha256:
        raise MediaError("direction brief is stale: alignment changed")
    if document.visual_analysis_sha256 != context.visual_sha256:
        raise MediaError("direction brief is stale: visual analysis changed")
    validate_source_evidence(
        document,
        context.alignment.words,
        context.hero_plan.edit_plan.time_map,
        {scene.scene_id for scene in context.visual.scenes},
    )
    selected = _select(document, style)
    profile = style_for_id(selected.style_id)
    # Selection is a controlled transformation, never model_copy of unchecked
    # user fields: the complete resulting document is validated again.
    payload = document.model_dump(mode="json")
    payload.update(
        selected_option_id=selected.option_id,
        selection_mode="operator_override" if style != "auto" else "automatic",
        style_id=selected.style_id,
        style_fingerprint=profile.fingerprint(),
    )
    document = DirectionDocument.model_validate(payload)
    destination = context.workspace.direction_file(candidate_id)
    context.workspace.prepare_advanced_file(destination)
    archive = destination.parent / "directions" / f"{document.direction_id}.json"
    context.workspace.prepare_advanced_file(archive)
    archive = confine_work_path(root, archive.relative_to(root).as_posix(), label="direction archive")
    if archive.exists():
        stored = DirectionDocument.model_validate_json(archive.read_text(encoding="utf-8"))
        if stored != document:
            raise MediaError("direction id is immutable; use a new direction_id for a changed brief")
    else:
        publish_json(archive, document, root, context.workspace.partial_for(archive))
    publish_json(destination, document, root, context.workspace.partial_for(destination))
    return document, destination, sha256_file(destination)


def _select(document: DirectionDocument, style: str) -> DirectionOption:
    if style == "auto":
        return sorted(document.options, key=lambda option: (-option.selection_score, option.option_id))[0]
    if style not in production_style_ids():
        raise MediaError(f"unsupported direction style {style}")
    matches = [option for option in document.options if option.style_id == style]
    if not matches:
        raise MediaError(f"direction brief has no option for style {style}")
    return sorted(matches, key=lambda option: (-option.selection_score, option.option_id))[0]


def validate_source_evidence(
    document: DirectionDocument,
    words: Sequence[AlignedWord],
    time_map: TimeMapDocument,
    scene_ids: set[str],
) -> None:
    """Bind exact evidence ids, text, intervals and segment order; never guess."""
    aligned = list(words)
    by_id = {word.word_id: word for word in aligned}
    positions = {word.word_id: index for index, word in enumerate(aligned)}
    segment_ids = [segment.segment_id for segment in time_map.segments]
    segment_positions = {segment_id: index for index, segment_id in enumerate(segment_ids)}
    for option in document.options:
        if any(segment_id not in segment_positions for segment_id in option.segment_order):
            raise MediaError("direction segment order names an unknown approved TimeMap segment")
        ordered_positions = [segment_positions[segment_id] for segment_id in option.segment_order]
        if ordered_positions != sorted(ordered_positions):
            raise MediaError("direction segment order must preserve approved TimeMap order")
        evidence_by_id = {item.evidence_id: item for item in option.evidence}
        for evidence in option.evidence:
            if any(word_id not in by_id for word_id in evidence.source_word_ids):
                raise MediaError(f"direction evidence {evidence.evidence_id} names an unknown aligned word")
            indices = [positions[word_id] for word_id in evidence.source_word_ids]
            if indices != list(range(indices[0], indices[-1] + 1)):
                raise MediaError("direction evidence word ids must be contiguous in output order")
            evidence_words = [by_id[word_id] for word_id in evidence.source_word_ids]
            segments = {
                segment.segment_id
                for segment in time_map.segments
                if any(
                    segment.source_start_us <= word.source_start_us
                    and word.source_end_us <= segment.source_end_us
                    for word in evidence_words
                )
            }
            if set(evidence.source_segment_ids) != segments or not segments:
                raise MediaError("direction evidence segment ids do not bind the aligned words")
            if _normalize(evidence.source_text) != _normalize("".join(word.text for word in evidence_words)):
                raise MediaError(f"direction evidence {evidence.evidence_id} text does not match its word ids")
            if any(scene_id not in scene_ids for scene_id in evidence.visual_scene_ids):
                raise MediaError("direction evidence names an unknown visual scene")
        beat_bounds: list[tuple[str, int, int]] = []
        for beat in option.beats:
            beat_evidence = [evidence_by_id[evidence_id] for evidence_id in beat.evidence_ids]
            beat_segments = {sid for item in beat_evidence for sid in item.source_segment_ids}
            if set(beat.source_segment_ids) != beat_segments:
                raise MediaError("direction beat segment ids do not match its evidence")
            if any(segment_id not in option.segment_order for segment_id in beat.source_segment_ids):
                raise MediaError("direction beat references a segment outside its option order")
            if beat.display_text is not None and not any(
                _normalize(beat.display_text) == _normalize(item.source_text) for item in beat_evidence
            ):
                raise MediaError(f"direction beat {beat.beat_id} display text must equal its bound evidence")
            beat_words = [by_id[word_id] for item in beat_evidence for word_id in item.source_word_ids]
            start = min(word.output_start_us for word in beat_words)
            end = max(word.output_end_us for word in beat_words)
            if beat.output_start_us is not None and (
                beat.output_start_us != start or beat.output_end_us != end
            ):
                raise MediaError("direction beat interval differs from forced-word timing")
            beat_bounds.append((beat.kind, start, end))
        kinds = [item[0] for item in beat_bounds]
        if (
            kinds[0] != "hook"
            or kinds[-1] != "punch"
            or any(kind != "body" for kind in kinds[1:-1])
            or any(left[2] > right[1] for left, right in pairwise(beat_bounds))
        ):
            raise MediaError("direction hook, body, and punch beats must be ordered and non-overlapping")
        duration = time_map.to_time_map().total_output_duration()
        for placement in option.asset_placements:
            if placement.interval.output_end_us > duration:
                raise MediaError("direction asset placement extends past the approved TimeMap")
            if any(evidence_id not in evidence_by_id for evidence_id in placement.source_evidence_ids):
                raise MediaError("direction asset placement references undeclared evidence")
            evidence_words = [
                by_id[word_id]
                for evidence_id in placement.source_evidence_ids
                for word_id in evidence_by_id[evidence_id].source_word_ids
            ]
            evidence_start = min(word.output_start_us for word in evidence_words)
            evidence_end = max(word.output_end_us for word in evidence_words)
            # Placement may cover a short lead/exit around a phrase, but must
            # overlap the phrase rather than being an arbitrary evenly-spaced
            # slot. This also keeps the relation deterministic after cuts.
            if (
                placement.interval.output_end_us <= evidence_start
                or placement.interval.output_start_us >= evidence_end
            ):
                raise MediaError("direction asset placement does not overlap its source evidence")
        for graphic in option.motion_graphics:
            if graphic.interval.output_end_us > duration:
                raise MediaError("direction motion graphic extends past the approved TimeMap")
            if any(evidence_id not in evidence_by_id for evidence_id in graphic.source_evidence_ids):
                raise MediaError("direction motion graphic references undeclared evidence")
            graphic_evidence = [evidence_by_id[item] for item in graphic.source_evidence_ids]
            if not any(
                _normalize(graphic.display_text) == _normalize(item.source_text) for item in graphic_evidence
            ):
                raise MediaError("direction motion graphic display text must equal its bound evidence")
            graphic_words = [by_id[word_id] for item in graphic_evidence for word_id in item.source_word_ids]
            graphic_start = min(word.output_start_us for word in graphic_words)
            graphic_end = max(word.output_end_us for word in graphic_words)
            if (
                graphic.interval.output_end_us <= graphic_start
                or graphic.interval.output_start_us >= graphic_end
            ):
                raise MediaError("direction motion graphic does not overlap its source evidence")
            # Templates are semantic illustrations, not generic decorations.
            # Keep their use tied to words which actually support the concept.
            evidence_text = " ".join(item.source_text for item in graphic_evidence).casefold()
            required_terms = {
                "credit_card": ("credit", "card"),
                "travel_postcard": ("philippines", "vacation", "beach", "tropical", "airbnb"),
                # A generic mention of a company is not evidence for a rising
                # trend chart. The source must name a business, founder, or
                # enterprise concept that the illustration actually depicts.
                "business_spotlight": ("business", "founder", "enterprise"),
            }[graphic.template]
            if graphic.template == "credit_card":
                supported = all(term in evidence_text for term in required_terms)
            else:
                supported = any(term in evidence_text for term in required_terms)
            if not supported:
                raise MediaError("direction motion graphic template is not supported by its source evidence")
        for native in option.source_native_text:
            if native.interval.output_end_us > duration:
                raise MediaError("source-native text interval extends past the approved TimeMap")
            if any(scene_id not in scene_ids for scene_id in native.visual_scene_ids):
                raise MediaError("source-native text names an unknown visual scene")


def _normalize(value: str) -> str:
    import re

    return re.sub(r"\s+", " ", value).strip()
