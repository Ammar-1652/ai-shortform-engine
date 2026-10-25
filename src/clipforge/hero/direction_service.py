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

from clipforge.editorial.knowledge import KnowledgeError, load_context
from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import confine_work_path
from clipforge.hero.motion_style import production_style_ids, style_for_id
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.direction import DirectionDocument, DirectionOption
from clipforge.schemas.editorial_knowledge import EditorialDecisionTrace
from clipforge.schemas.hero import AlignedWord
from clipforge.schemas.time import TimeMapDocument
from clipforge.storage import Database
from clipforge.transcription.io import publish_json


def load_direction(
    workspace: SourceWorkspace, candidate_id: str, *, review_only: bool = False
) -> tuple[DirectionDocument, str] | None:
    path = (
        workspace.advanced_review_direction_file(candidate_id)
        if review_only
        else workspace.direction_file(candidate_id)
    )
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
    knowledge_context_path: Path | None = None,
    knowledge_decision_trace_path: Path | None = None,
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
    # Recipe ids are references to the verified local catalog.  A direction
    # may only name approved, offline-capable components; the renderer never
    # resolves a free-form component string from the brief.
    from clipforge.editorial.motion_catalog import MotionCatalog

    catalog = MotionCatalog.load()
    for option in document.options:
        for recipe_id in option.motion_recipe_ids:
            recipe = catalog.find(recipe_id)
            if recipe.state != "approved":
                raise MediaError(f"direction recipe is not approved: {recipe_id}")
    selected = _select(document, style)
    profile = style_for_id(selected.style_id)
    knowledge_context = None
    knowledge_trace = None
    knowledge_trace_sha256 = None
    if knowledge_context_path is not None:
        try:
            knowledge_context, _ = load_context(knowledge_context_path.absolute())
        except KnowledgeError as exc:
            raise MediaError(str(exc)) from exc
        if (
            knowledge_context.project_id != context.project_id
            or knowledge_context.source_asset_id != source_asset_id
            or knowledge_context.candidate_id != candidate_id
            or knowledge_context.source_sha256 != context.source_sha256
        ):
            raise MediaError("knowledge context does not match the promoted candidate and source")
    if knowledge_decision_trace_path is not None:
        if knowledge_context is None:
            raise MediaError("knowledge decision trace requires --knowledge-context")
        if knowledge_decision_trace_path.is_symlink() or not knowledge_decision_trace_path.is_file():
            raise MediaError("knowledge decision trace must be a regular file")
        try:
            knowledge_trace = EditorialDecisionTrace.model_validate_json(
                knowledge_decision_trace_path.absolute().read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            raise MediaError(f"invalid knowledge decision trace: {exc}") from exc
        if (
            knowledge_trace.context_id != knowledge_context.context_id
            or knowledge_trace.context_sha256 != knowledge_context.context_sha256
        ):
            raise MediaError("knowledge decision trace does not match the context bundle")
        knowledge_trace_sha256 = sha256_file(knowledge_decision_trace_path.absolute())
    # Selection is a controlled transformation, never model_copy of unchecked
    # user fields: the complete resulting document is validated again.
    payload = document.model_dump(mode="json")
    payload.update(
        operator_role=document.operator_role or "codex_operator",
        selected_option_id=selected.option_id,
        selection_mode="operator_override" if style != "auto" else "automatic",
        style_id=selected.style_id,
        style_fingerprint=profile.fingerprint(),
        preset_id=selected.preset_id,
        direction_recipe_version="direction-v2",
        # Every new directed production uses the shared platform-safe inner
        # band unless the operator explicitly selected the legacy region in a
        # reviewed document.
        safe_region_id=document.safe_region_id,
        motion_catalog_sha256=catalog.fingerprint(),
    )
    if knowledge_context is not None:
        payload.update(
            knowledge_context_id=knowledge_context.context_id,
            knowledge_release_id=knowledge_context.knowledge_release_id,
            knowledge_context_sha256=knowledge_context.context_sha256,
        )
    if knowledge_trace is not None:
        payload.update(
            knowledge_decision_trace_id=knowledge_trace.trace_id,
            knowledge_decision_trace_sha256=knowledge_trace_sha256,
        )
    document = DirectionDocument.model_validate(payload)
    validate_motion_recipe_bindings(document)
    validate_preset_binding(document)
    destination = (
        context.workspace.advanced_review_direction_file(candidate_id)
        if allow_unapproved
        else context.workspace.direction_file(candidate_id)
    )
    prepare = (
        context.workspace.prepare_advanced_review_file
        if allow_unapproved
        else context.workspace.prepare_advanced_file
    )
    prepare(destination)
    archive = destination.parent / "directions" / f"{document.direction_id}.json"
    prepare(archive)
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
        return sorted(document.options, key=lambda option: (-_editorial_score(option), option.option_id))[0]
    if style not in production_style_ids():
        raise MediaError(f"unsupported direction style {style}")
    matches = [option for option in document.options if option.style_id == style]
    if not matches:
        raise MediaError(f"direction brief has no option for style {style}")
    return sorted(matches, key=lambda option: (-option.selection_score, option.option_id))[0]


def validate_motion_recipe_bindings(document: DirectionDocument) -> None:
    """Verify the selected direction against the current local recipe catalog."""
    if document.motion_catalog_sha256 is None and not any(
        option.motion_recipe_ids for option in document.options
    ):
        return
    from clipforge.editorial.motion_catalog import MotionCatalog, MotionCatalogError

    try:
        catalog = MotionCatalog.load()
    except MotionCatalogError as exc:
        raise MediaError(str(exc)) from exc
    if document.motion_catalog_sha256 is not None and document.motion_catalog_sha256 != catalog.fingerprint():
        raise MediaError("direction motion catalog fingerprint is stale")
    if any(option.motion_recipe_ids for option in document.options) and document.motion_catalog_sha256 is None:
        raise MediaError("direction motion recipes require a catalog fingerprint")
    for option in document.options:
        for recipe_id in option.motion_recipe_ids:
            try:
                recipe = catalog.find(recipe_id)
            except MotionCatalogError as exc:
                raise MediaError(str(exc)) from exc
            if recipe.state != "approved":
                raise MediaError(f"direction recipe is not approved: {recipe_id}")


def validate_preset_binding(document: DirectionDocument) -> None:
    if document.preset_id is None:
        return
    from clipforge.editorial.presets import PresetCatalog, PresetCatalogError

    try:
        preset = PresetCatalog.load().find(document.preset_id)
    except PresetCatalogError as exc:
        raise MediaError(str(exc)) from exc
    selected = next(item for item in document.options if item.option_id == document.selected_option_id)
    if selected.style_id not in preset.allowed_style_ids:
        raise MediaError("direction preset does not allow the selected style")
    missing = sorted(set(preset.motion_recipe_ids) - set(selected.motion_recipe_ids))
    if missing:
        raise MediaError(f"direction preset recipes are missing from the selected option: {missing}")


def _editorial_score(option: DirectionOption) -> float:
    """Prefer source-complete, restrained options over decoration counts.

    The submitted score remains an editorial input, but deterministic penalties
    prevent an attractive preset from overpowering incomplete evidence or a
    pile of optional layers. These are heuristics, never retention guarantees.
    """
    evidence_by_id = {item.evidence_id: item for item in option.evidence}
    punctuation = (".", "?", "!", "\u3002", "\uff1f", "\uff01")
    complete = sum(
        any(evidence_by_id[item].source_text.rstrip().endswith(punctuation) for item in beat.evidence_ids)
        for beat in option.beats
    )
    layer_count = len(option.motion_graphics) + len(option.asset_placements)
    clutter_penalty = max(0, layer_count - 2) * 0.04
    native_penalty = 0.0 if option.source_native_text_status != "unavailable" else 0.15
    return option.selection_score + complete * 0.02 - clutter_penalty - native_penalty


def validate_source_evidence(
    document: DirectionDocument,
    words: Sequence[AlignedWord],
    time_map: TimeMapDocument,
    scene_ids: set[str],
    *,
    selected_only: bool = False,
) -> None:
    """Bind exact evidence ids, text, intervals and segment order; never guess."""
    aligned = list(words)
    by_id = {word.word_id: word for word in aligned}
    positions = {word.word_id: index for index, word in enumerate(aligned)}
    segment_ids = [segment.segment_id for segment in time_map.segments]
    segment_positions = {segment_id: index for index, segment_id in enumerate(segment_ids)}
    for option in document.options:
        if selected_only and option.option_id != document.selected_option_id:
            continue
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
        duration = time_map.to_time_map().total_output_duration()
        context_line = option.context_line
        if context_line is not None:
            if any(evidence_id not in evidence_by_id for evidence_id in context_line.evidence_ids):
                raise MediaError("context line references undeclared evidence")
            context_evidence = [evidence_by_id[item] for item in context_line.evidence_ids]
            context_words = [
                by_id[word_id] for evidence in context_evidence for word_id in evidence.source_word_ids
            ]
            if not context_words:
                raise MediaError("context line must bind at least one aligned word")
            if context_line.interval.output_start_us != 0 or context_line.interval.output_end_us != duration:
                raise MediaError("context line must cover the complete approved output")
            if context_line.copy_mode == "exact_evidence":
                if not any(
                    _normalize(context_line.text) == _normalize(evidence.source_text)
                    for evidence in context_evidence
                ):
                    raise MediaError("exact context line text must equal its bound evidence")
            elif any(
                _normalize(context_line.text) == _normalize(evidence.source_text)
                for evidence in context_evidence
            ):
                raise MediaError("reviewed context summary must not duplicate its evidence phrase")
        kinds = [item[0] for item in beat_bounds]
        if (
            kinds[0] != "hook"
            or kinds[-1] != "punch"
            or any(kind != "body" for kind in kinds[1:-1])
            or any(left[2] > right[1] for left, right in pairwise(beat_bounds))
        ):
            raise MediaError("direction hook, body, and punch beats must be ordered and non-overlapping")
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
                "business_identity": ("business", "founder", "enterprise"),
                # A rising chart requires quantitative evidence. A founder or
                # company mention alone supports an identity card, never a
                # trend visualization.
                "business_spotlight": ("$", "million", "valued", "growth", "increase", "%"),
                "quran_challenge": (
                    "quran",
                    "قرآن",
                    "آية",
                    "آيات",
                    "يكمل",
                    "حفظ",
                    "ترتيل",
                    "يلفظ",
                    "رقيب",
                    "عتيد",
                ),
            }[graphic.template]
            if graphic.template == "credit_card":
                supported = all(term in evidence_text for term in required_terms)
            elif graphic.template == "business_spotlight":
                supported = sum(term in evidence_text for term in required_terms) >= 2
            elif graphic.template == "quran_challenge":
                supported = any(term in evidence_text for term in required_terms)
            else:
                supported = any(term in evidence_text for term in required_terms)
            if not supported:
                raise MediaError("direction motion graphic template is not supported by its source evidence")
        for camera in option.camera_motion:
            if camera.interval.output_end_us > duration:
                raise MediaError("direction camera motion extends past the approved TimeMap")
            if any(evidence_id not in evidence_by_id for evidence_id in camera.source_evidence_ids):
                raise MediaError("direction camera motion references undeclared evidence")
            camera_words = [
                by_id[word_id]
                for evidence_id in camera.source_evidence_ids
                for word_id in evidence_by_id[evidence_id].source_word_ids
            ]
            camera_start = min(word.output_start_us for word in camera_words)
            camera_end = max(word.output_end_us for word in camera_words)
            if camera.interval.output_end_us <= camera_start or camera.interval.output_start_us >= camera_end:
                raise MediaError("direction camera motion does not overlap its source evidence")
        mapped_segments = time_map.to_time_map().segments
        interior_cut_starts = {segment.output_start_us for segment in mapped_segments[1:]}
        for transition in option.transitions:
            if transition.interval.output_end_us > duration:
                raise MediaError("direction transition extends past the approved TimeMap")
            if transition.interval.output_start_us not in interior_cut_starts:
                raise MediaError("direction transition must start at an interior TimeMap cut")
            if any(evidence_id not in evidence_by_id for evidence_id in transition.source_evidence_ids):
                raise MediaError("direction transition references undeclared evidence")
            transition_words = [
                by_id[word_id]
                for evidence_id in transition.source_evidence_ids
                for word_id in evidence_by_id[evidence_id].source_word_ids
            ]
            evidence_start = min(word.output_start_us for word in transition_words)
            evidence_end = max(word.output_end_us for word in transition_words)
            if (
                transition.interval.output_end_us <= evidence_start
                or transition.interval.output_start_us >= evidence_end
            ):
                raise MediaError("direction transition does not overlap its source evidence")
            if transition.sfx_placement_id is not None:
                placement_ref = next(
                    (
                        item
                        for item in option.asset_placements
                        if item.placement_id == transition.sfx_placement_id
                    ),
                    None,
                )
                if placement_ref is None or placement_ref.kind != "audio":
                    raise MediaError("direction transition SFX placement is missing or not audio")
                if (
                    placement_ref.interval.output_end_us <= transition.interval.output_start_us
                    or placement_ref.interval.output_start_us >= transition.interval.output_end_us
                ):
                    raise MediaError("direction transition SFX must overlap its transition")
        for native in option.source_native_text:
            if native.interval.output_end_us > duration:
                raise MediaError("source-native text interval extends past the approved TimeMap")
            if any(scene_id not in scene_ids for scene_id in native.visual_scene_ids):
                raise MediaError("source-native text names an unknown visual scene")


def _normalize(value: str) -> str:
    import re

    return re.sub(r"\s+", " ", value).strip()
