"""Build a deterministic advanced plan from forced alignment and cleared assets."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from clipforge.campaign.quran import canonicalize_quran_alignment
from clipforge.errors import MediaError, StorageError
from clipforge.hero.advanced_assets import binding_for, require_asset
from clipforge.hero.captions import hero_caption_pieces
from clipforge.hero.motion_style import style_for_id, style_for_renderer_version
from clipforge.hero.reframe import (
    ReframeError,
    build_face_follow,
    frame_period_tolerance_us,
)
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.advanced import (
    AdvancedHeroPlanDocument,
    AdvancedHeroProfile,
    AssetBinding,
    AudioMixEvent,
    CaptionWordTiming,
    DiagramEvent,
    EmphasisEvent,
    MotionGraphicEvent,
    ReframingWindow,
    TransitionEvent,
    TypographyEvent,
    advanced_fingerprint,
)
from clipforge.schemas.campaign import QuranCaptionReview
from clipforge.schemas.direction import DirectionAssetPlacement, DirectionDocument, SourceNativeText
from clipforge.schemas.editorial import BrollEvent, MotionPurpose, OutputInterval
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument, HeroPlanDocument
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.reframe import ReframePlanDocument
from clipforge.schemas.time import TimeMapDocument
from clipforge.schemas.vision import FaceDetectionSample, VisualAnalysisDocument
from clipforge.storage import Database, get_source_manifest
from clipforge.transcription.io import publish_json

_NAMESPACE = uuid.UUID("6f1d5e2a-9c4b-4f1a-8d3e-1a2b3c4d5e6f")
_SAFE = 48
_DIRECTION_ACCENT_TOP = 1_280


def stable_id(*parts: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, "|".join(parts)))


def build_advanced_plan(
    *,
    database: Database,
    workspace: SourceWorkspace,
    work_root: Path,
    profile: AdvancedHeroProfile,
    plan_id: str,
    project_id: str,
    source_asset_id: str,
    candidate_id: str,
    source_sha256: str,
    candidate_set_artifact_id: str,
    candidate_set_sha256: str,
    rough_artifact_id: str,
    rough_manifest_sha256: str,
    hero_artifact_id: str,
    hero_set_id: str,
    hero_manifest_sha256: str,
    review_id: str,
    review_digest: str,
    alignment: ForcedAlignmentDocument,
    alignment_sha256: str,
    hero_plan: HeroPlanDocument,
    hero_plan_sha256: str,
    visual: VisualAnalysisDocument,
    visual_sha256: str,
    duration_us: int,
    broll_asset_ids: list[str],
    sfx_asset_ids: list[str],
    actor: str,
    tool_version: str,
    direction: DirectionDocument | None = None,
    direction_sha256: str = "",
    editorial_arc_id: str = "",
    editorial_arc_sha256: str = "",
    quran_review_id: str = "",
    quran_review_sha256: str = "",
    quran_review: QuranCaptionReview | None = None,
    cut_transition_style: str = "",
    allow_unapproved: bool = False,
) -> AdvancedHeroPlanDocument:
    if profile.music_allowed:
        raise MediaError("advanced Hero profile cannot allow music")
    _require_forced(alignment)
    if len(broll_asset_ids) > profile.max_broll_events:
        raise MediaError("advanced plan has more B-roll events than the profile allows")
    if len(sfx_asset_ids) > profile.max_sfx_events:
        raise MediaError("advanced plan has more SFX events than the profile allows")
    windows, reframe = _windows(
        profile,
        visual,
        duration_us,
        candidate_id,
        hero_plan.edit_plan.time_map,
        hero_plan.edit_plan.time_map_sha256,
        source_sha256,
        source_asset_id,
        visual_sha256,
        database,
        actor,
        tool_version,
    )
    if profile.reframing.strategy_id == "manual_window":
        cursor_us = 0
        for window in windows:
            if (
                window.strategy_id.strategy_id != "manual_window"
                or window.output_start_us != cursor_us
                or window.frame_width != visual.proxy_width
                or window.frame_height != visual.proxy_height
                or window.source_width * 16 != window.source_height * 9
            ):
                raise MediaError("manual crop windows must be ordered, contiguous, source-bound, and 9:16")
            cursor_us = window.output_end_us
        if cursor_us != duration_us:
            raise MediaError("manual crop windows must cover the complete output without gaps")
    emphasis = _emphasis(alignment, candidate_id)
    caption_alignment = alignment
    if quran_review is not None:
        caption_alignment = canonicalize_quran_alignment(alignment, quran_review)
    captions = _captions(caption_alignment, candidate_id, style_id=direction.style_id if direction else "")
    if direction is not None:
        typography = _directed_typography(direction, alignment, candidate_id)
        typography = _drop_caption_duplicates(typography, captions)
    elif profile.renderer_recipe_version == "advanced-hero-renderer-v1":
        # Preserve immutable Round-30 behavior only when an operator
        # explicitly selects the legacy recipe. Clean production never
        # invents a hook/punch from word positions or non-ASCII heuristics.
        typography = _typography(alignment, emphasis, candidate_id)
    else:
        typography = []
    # A diagram is editorial evidence, not a decoration.  Until an operator
    # supplies a source-grounded diagram instruction, the safe plan is none.
    diagrams: list[DiagramEvent] = []
    motion_graphics = _motion_graphics(direction)
    source_native_text = _source_native_text(direction)
    # A directed clean-production recut gets a soft bridge by default. An
    # editorial arc that explicitly says `none` still retains that reviewed
    # hard-cut decision; legacy/no-direction plans remain unchanged.
    effective_transition_style = _effective_transition_style(cut_transition_style, direction is not None)
    transitions = _transitions(
        candidate_id, hero_plan.edit_plan.time_map, duration_us, effective_transition_style
    )
    typography = _drop_typography_graphic_collisions(typography, motion_graphics)
    assets: list[AssetBinding] = []
    selected_placements = _selected_asset_placements(direction)
    broll_placements = [item for item in selected_placements if item.kind == "graphic"]
    sfx_placements = [item for item in selected_placements if item.kind == "audio"]
    broll = _broll(
        database,
        workspace,
        work_root,
        project_id,
        candidate_id,
        duration_us,
        broll_asset_ids,
        assets,
        broll_placements,
    )
    sfx = _sfx(
        database,
        workspace,
        work_root,
        project_id,
        candidate_id,
        duration_us,
        sfx_asset_ids,
        assets,
        profile,
        sfx_placements,
    )
    manual = None if profile.manual_window is None else profile.manual_window.model_dump(mode="json")
    manual_windows = [item.model_dump(mode="json") for item in profile.manual_windows]
    motion_style = (
        style_for_id(direction.style_id)
        if direction is not None
        else style_for_renderer_version(profile.renderer_recipe_version)
    )
    config: dict[str, object] = {
        "manual_window": manual,
        "manual_windows": manual_windows,
        "strategy": profile.reframing.strategy_id,
        "windows": [item.model_dump(mode="json") for item in windows],
        "motion_style": asdict(motion_style),
    }
    if reframe is not None and reframe.trajectory_sha256:
        config["trajectory_sha256"] = reframe.trajectory_sha256
    now = datetime.now(UTC)
    with database.connect() as connection:
        from clipforge.storage import get_project

        campaign_profile_id = get_project(connection, project_id).profile_id
    campaign_qa = ["tarteel-quran-caption-v1"] if campaign_profile_id == "profile-tarteel-campaign" else []
    bound_review_id = review_id
    bound_review_digest = review_digest
    if allow_unapproved:
        bound_review_id = f"pending-{hero_artifact_id}"
        bound_review_digest = hashlib.sha256(
            f"pending:{hero_artifact_id}:{hero_manifest_sha256}".encode()
        ).hexdigest()
    document = AdvancedHeroPlanDocument(
        plan_id=plan_id,
        project_id=project_id,
        source_asset_id=source_asset_id,
        candidate_id=candidate_id,
        source_sha256=source_sha256,
        candidate_set_artifact_id=candidate_set_artifact_id,
        candidate_set_sha256=candidate_set_sha256,
        rough_preview_artifact_id=rough_artifact_id,
        rough_manifest_sha256=rough_manifest_sha256,
        hero_artifact_id=hero_artifact_id,
        hero_set_id=hero_set_id,
        hero_manifest_sha256=hero_manifest_sha256,
        hero_review_id=bound_review_id,
        hero_review_digest=bound_review_digest,
        hero_review_status="pending" if allow_unapproved else "approved",
        alignment_id=alignment.alignment_id,
        alignment_sha256=alignment_sha256,
        hero_plan_id=hero_plan.plan_id,
        hero_plan_sha256=hero_plan_sha256,
        visual_analysis_id=visual.analysis_id,
        visual_analysis_sha256=visual_sha256,
        time_map=hero_plan.edit_plan.time_map,
        time_map_sha256=hero_plan.edit_plan.time_map_sha256,
        editorial_arc_id=editorial_arc_id,
        editorial_arc_sha256=editorial_arc_sha256,
        quran_review_id=quran_review_id,
        quran_review_sha256=quran_review_sha256,
        profile_fingerprint=profile.fingerprint(),
        direction_id="" if direction is None else direction.direction_id,
        direction_sha256=direction_sha256,
        style_id=motion_style.style_id,
        style_fingerprint=motion_style.fingerprint(),
        safe_region_id="portrait-safe-v1",
        motion_style=motion_style.contract(),
        reframing_strategy=profile.reframing.strategy_id,
        reframing_config_sha256=advanced_fingerprint(config),
        windows=windows,
        captions=captions,
        typography=typography,
        diagrams=diagrams,
        motion_graphics=motion_graphics,
        source_native_text=source_native_text,
        emphasis=emphasis,
        transitions=transitions,
        broll=broll,
        sfx=sfx,
        assets=assets,
        qa_requirements=[
            "forced_alignment",
            "rights_cleared_assets",
            "no_speaker_inference",
            "no_music",
            *campaign_qa,
            *(["tarteel-editorial-arc-v1"] if editorial_arc_id else []),
        ],
        provenance=ArtifactProvenance(
            created_at=now,
            created_by=actor,
            tool="clipforge-advanced-hero",
            tool_version=tool_version,
            source_asset_ids=[source_asset_id],
        ),
    )
    if reframe is not None:
        destination = workspace.reframe_plan_file(candidate_id)
        workspace.prepare_advanced_file(destination)
        publish_json(destination, reframe, work_root, workspace.partial_for(destination))
    return document


def _require_forced(alignment: ForcedAlignmentDocument) -> None:
    if any(word.alignment_quality != "forced" for word in alignment.words):
        raise MediaError("advanced plan refuses provisional timing")


def _selected_asset_placements(direction: DirectionDocument | None) -> list[DirectionAssetPlacement]:
    if direction is None:
        return []
    option = next(item for item in direction.options if item.option_id == direction.selected_option_id)
    return list(option.asset_placements)


def _motion_graphics(direction: DirectionDocument | None) -> list[MotionGraphicEvent]:
    """Convert only validated selected-direction graphics into render events."""
    if direction is None:
        return []
    option = next(item for item in direction.options if item.option_id == direction.selected_option_id)
    return [
        MotionGraphicEvent(
            event_id=stable_id("direction-graphic", direction.direction_id, graphic.graphic_id),
            template=graphic.template,
            interval=graphic.interval,
            purpose=graphic.purpose,
            source_evidence_ids=graphic.source_evidence_ids,
            display_text=graphic.display_text,
            x=graphic.x,
            y=graphic.y,
            width=graphic.width,
            height=graphic.height,
        )
        for graphic in option.motion_graphics
    ]


def _source_native_text(direction: DirectionDocument | None) -> list[SourceNativeText]:
    """Carry reviewed source-native title annotations into the plan."""
    if direction is None:
        return []
    option = next(item for item in direction.options if item.option_id == direction.selected_option_id)
    return list(option.source_native_text)


def _drop_typography_graphic_collisions(
    typography: list[TypographyEvent], motion_graphics: list[MotionGraphicEvent]
) -> list[TypographyEvent]:
    """A graphic owns its source beat; don't stack a decorative rail over it."""
    if not motion_graphics:
        return list(typography)
    return [
        item
        for item in typography
        if item.component_id == "context-line-v1"
        or not any(
            item.interval.output_start_us < graphic.interval.output_end_us
            and graphic.interval.output_start_us < item.interval.output_end_us
            for graphic in motion_graphics
        )
    ]


def _emphasis(alignment: ForcedAlignmentDocument, candidate_id: str) -> list[EmphasisEvent]:
    events: list[EmphasisEvent] = []
    for word in alignment.words:
        rule = _rule(word)
        if rule is None:
            continue
        purpose = MotionPurpose.NUMBER if rule == "number_or_currency" else MotionPurpose.KEY_PHRASE
        events.append(
            EmphasisEvent(
                event_id=stable_id("emphasis", candidate_id, word.word_id, rule),
                word_id=word.word_id,
                text=word.text,
                output_start_us=word.output_start_us,
                output_end_us=word.output_end_us,
                output_start_frame=word.output_start_frame,
                output_end_frame_exclusive=word.output_end_frame_exclusive,
                purpose=purpose,
                rule_id=rule,  # type: ignore[arg-type]
            )
        )
    return events


def _rule(word: AlignedWord) -> str | None:
    stripped = word.text.strip()
    if not stripped:
        return None
    if any(character.isdigit() for character in stripped) or "$" in stripped:
        return "number_or_currency"
    if stripped[-1] in ".?!…。？！:":  # noqa: RUF001
        return "terminal_punctuation"
    return None


def _directed_typography(
    direction: DirectionDocument,
    alignment: ForcedAlignmentDocument,
    candidate_id: str,
) -> list[TypographyEvent]:
    """Optional cards use only selected, exact source-bound words and timing."""
    option = next(item for item in direction.options if item.option_id == direction.selected_option_id)
    evidence = {item.evidence_id: item for item in option.evidence}
    words = {word.word_id: word for word in alignment.words}
    events: list[TypographyEvent] = []
    context_line = getattr(option, "context_line", None)
    if context_line is not None:
        events.append(
            TypographyEvent(
                event_id=stable_id(
                    "context-line", candidate_id, direction.direction_id, context_line.context_id
                ),
                interval=context_line.interval,
                purpose=MotionPurpose.KEY_PHRASE,
                component_id="context-line-v1",
                text=context_line.text,
                x=72,
                y=280 if getattr(direction, "style_id", "") == "quran-readable-v2" else 120,
                font_size=64 if getattr(direction, "style_id", "") == "quran-readable-v2" else 48,
                emoji=context_line.emoji,
            )
        )
    for beat in option.beats:
        if beat.display_text is None:
            continue
        bound_words = [
            words[word_id]
            for evidence_id in beat.evidence_ids
            for word_id in evidence[evidence_id].source_word_ids
        ]
        start = min(word.output_start_us for word in bound_words)
        end = max(word.output_end_us for word in bound_words)
        events.append(
            TypographyEvent(
                event_id=stable_id("direction-type", candidate_id, direction.direction_id, beat.beat_id),
                interval=OutputInterval(output_start_us=start, output_end_us=end),
                purpose=MotionPurpose.KEY_PHRASE,
                component_id=f"{beat.kind}-card-v1",
                text=beat.display_text,
                x=230 if beat.kind == "hook" else 160 if beat.kind == "punch" else 280,
                # Duplicate text is suppressed in Remotion and represented by
                # its accent track. Keep that track with the caption stack,
                # below face space, rather than over a subject's forehead.
                y=_DIRECTION_ACCENT_TOP + 34 if beat.kind == "punch" else _DIRECTION_ACCENT_TOP - 68,
                font_size=64,
            )
        )
    return events


def _typography(
    alignment: ForcedAlignmentDocument,
    emphasis: list[EmphasisEvent],
    candidate_id: str,
) -> list[TypographyEvent]:
    words = [word for word in alignment.words if word.text.strip()]
    if not words:
        return []
    chosen: list[tuple[str, int, int, MotionPurpose, str]] = []
    hook_index = next(
        (
            index
            for index, word in enumerate(words)
            if word.text.strip().lower() in {"never", "secret", "surprise"}
        ),
        0,
    )
    hook_end = min(len(words), hook_index + 5)
    hook_text = _phrase(words[hook_index:hook_end])
    punch_words = words[-3:]
    punch_text = _phrase(punch_words)
    hook_end_us = min(1_400_000, max(600_000, words[0].output_end_us))
    if punch_words and punch_words[0].output_start_us <= hook_end_us:
        hook_end_us = max(1, punch_words[0].output_start_us - 1)
    chosen.append(
        (
            hook_text,
            0,
            hook_end_us,
            MotionPurpose.KEY_PHRASE,
            "hook-card-v1",
        )
    )

    seen: set[str] = set()
    for word in words:
        stripped = word.text.strip()
        non_ascii = any(ord(char) > 127 for char in stripped)
        numeric = any(char.isdigit() or char == "$" for char in stripped)
        interesting = non_ascii or numeric
        if not interesting or not stripped or stripped in seen:
            continue
        seen.add(stripped)
        chosen.append(
            (stripped, word.output_start_us, word.output_end_us, MotionPurpose.KEY_PHRASE, "typography-card-v1")
        )
    if not chosen and emphasis:
        item = emphasis[0]
        chosen.append(
            (item.text.strip(), item.output_start_us, item.output_end_us, item.purpose, "typography-card-v1")
        )
    if punch_text and punch_text.lower() != hook_text.lower() and punch_words[0].output_start_us > hook_end_us:
        chosen.append(
            (
                punch_text,
                punch_words[0].output_start_us,
                punch_words[-1].output_end_us,
                MotionPurpose.KEY_PHRASE,
                "punch-card-v1",
            )
        )
    hooks = [item for item in chosen if item[4] == "hook-card-v1"][:1]
    punches = [item for item in chosen if item[4] == "punch-card-v1"][:1]
    middle = [item for item in chosen if item[4] == "typography-card-v1"]
    middle.sort(key=lambda item: (0 if any(char.isdigit() or char == "$" for char in item[0]) else 1, item[1]))
    ordered = sorted(hooks + middle[:2] + punches, key=lambda item: (item[1], item[4]))
    selected: list[tuple[str, int, int, MotionPurpose, str]] = []
    for candidate in ordered:
        if selected and candidate[1] < selected[-1][2]:
            if candidate[4] == "punch-card-v1":
                while selected and candidate[1] < selected[-1][2]:
                    selected.pop()
            else:
                continue
        selected.append(candidate)
    events: list[TypographyEvent] = []
    for index, (text, start, end, purpose, component_id) in enumerate(selected):
        # Punch cards are now positioned by the renderer in final portrait
        # coordinates.  Keep the default in the lower safe region while
        # leaving room for the baseline caption plate beneath it.
        y = 220 if component_id == "hook-card-v1" else 1450 if component_id == "punch-card-v1" else 360
        events.append(
            TypographyEvent(
                event_id=stable_id("type", candidate_id, text, str(index)),
                interval=OutputInterval(output_start_us=start, output_end_us=end),
                purpose=purpose,
                component_id=component_id,
                text=text,
                x=72,
                y=y,
                font_size=64,
            )
        )
    return events


def _drop_caption_duplicates(
    typography: list[TypographyEvent], captions: list[TypographyEvent]
) -> list[TypographyEvent]:
    """Retain directed events so Remotion can draw their non-text treatment.

    Directed cards are source-bound to the same words as captions. The
    renderer therefore suppresses duplicate glyphs while still drawing the
    declarative card geometry. Dropping the event here discarded the intended
    motion graphic before the render-input boundary and made a valid direction
    visually inert.
    """
    del captions
    return list(typography)


def _phrase(words: list[AlignedWord]) -> str:
    """Join exact aligned words into a readable teaser without changing wording."""
    text = " ".join(word.text.strip() for word in words if word.text.strip())
    return re.sub(r"\s+([,.;?!…。？！:])", r"\1", text).strip()  # noqa: RUF001


def _captions(
    alignment: ForcedAlignmentDocument, candidate_id: str, *, style_id: str = ""
) -> list[TypographyEvent]:
    """Persist grouped forced captions separately from optional typography cards."""
    events: list[TypographyEvent] = []
    for index, piece in enumerate(hero_caption_pieces(alignment.words)):
        text = piece.cue.text.strip()
        if not text:
            continue
        events.append(
            TypographyEvent(
                event_id=stable_id("caption", candidate_id, str(index)),
                interval=piece.cue.interval,
                purpose=MotionPurpose.KEY_PHRASE,
                component_id=f"caption-{index}",
                text=text,
                x=72,
                y=1560 if style_id == "quran-readable-v2" else 1540,
                font_size=120 if style_id == "quran-readable-v2" else 54,
                words=[
                    CaptionWordTiming(
                        word_id=word.word_id,
                        text=word.text,
                        output_start_us=word.output_start_us,
                        output_end_us=word.output_end_us,
                        output_start_frame=word.output_start_frame,
                        output_end_frame_exclusive=word.output_end_frame_exclusive,
                        verification_status=word.verification_status,
                        source_word_ids=word.source_word_ids or [word.word_id],
                    )
                    for word in piece.words
                ],
            )
        )
    return events


def _transitions(
    candidate_id: str,
    time_map: TimeMapDocument,
    duration_us: int,
    style: str,
) -> list[TransitionEvent]:
    """Create restrained bridges only where the reviewed TimeMap actually cuts."""
    mapped = time_map.to_time_map().segments
    events: list[TransitionEvent] = []
    if style not in {"none", "clean_cut_v1", "concat_push_v1", "concat_blur_dissolve_v1"}:
        raise MediaError(f"unsupported cut transition style: {style}")
    if style == "none":
        return events
    for index, segment in enumerate(mapped[1:], start=1):
        if mapped[index - 1].source_end_us == segment.source_start_us:
            continue
        start = segment.output_start_us
        end = min(duration_us, start + 133_333)
        if end <= start:
            continue
        events.append(
            TransitionEvent(
                event_id=stable_id("transition", candidate_id, str(index), str(start)),
                interval=OutputInterval(output_start_us=start, output_end_us=end),
            )
        )
    return events


def _effective_transition_style(style: str, directed: bool) -> str:
    """Resolve a new-plan default without overriding an explicit arc choice."""
    if style:
        return style
    return "concat_blur_dissolve_v1" if directed else "none"


def _windows(
    profile: AdvancedHeroProfile,
    visual: VisualAnalysisDocument,
    duration_us: int,
    candidate_id: str,
    time_map: TimeMapDocument,
    time_map_sha256: str,
    source_sha256: str,
    source_asset_id: str,
    visual_sha256: str,
    database: Database,
    actor: str,
    tool_version: str,
) -> tuple[list[ReframingWindow], ReframePlanDocument | None]:
    strategy = profile.reframing.strategy_id
    width = visual.proxy_width
    height = visual.proxy_height
    if strategy == "face_follow":
        return _face_follow_windows(
            visual,
            candidate_id,
            time_map,
            time_map_sha256,
            source_sha256,
            source_asset_id,
            visual_sha256,
            database,
            profile,
            actor,
            tool_version,
        )
    if strategy == "contain":
        box = (0, 0, width, height)
    elif strategy == "center_crop":
        box = _center_crop(width, height)
    elif strategy == "manual_window":
        windows = profile.manual_windows
        if not windows and profile.manual_window is not None:
            windows = [profile.manual_window]
        if not windows:
            raise MediaError("manual_window strategy requires reviewed crop windows")
        return windows, None
    else:
        boxes = _face_boxes(visual, width, height)
        if strategy == "multi_face_safe_window" and len(boxes) < 2:
            raise MediaError(
                "multi_face_safe_window needs at least two face boxes and does not infer a speaker"
            )
        if strategy in {"visual_safe_window", "saliency_window"} and not boxes:
            raise MediaError(f"{strategy} has no visual evidence and does not fall back to another strategy")
        box = _union(boxes, width, height)
    return [
        ReframingWindow(
            window_id=stable_id("window", candidate_id, strategy),
            strategy_id=profile.reframing,
            output_start_us=0,
            output_end_us=duration_us,
            source_x=box[0],
            source_y=box[1],
            source_width=box[2],
            source_height=box[3],
            frame_width=width,
            frame_height=height,
        )
    ], None


def _face_follow_gap_tolerance_us(database: Database, source_asset_id: str) -> int:
    """Allow the nearest decoded frame's one-frame PTS quantization error."""
    try:
        with database.connect() as connection:
            manifest = get_source_manifest(connection, source_asset_id)
    except StorageError as exc:
        raise MediaError("face_track_gap_tolerance_unavailable") from exc
    video = next(
        (item for item in manifest.probe.video_streams if item.index == manifest.video_stream_index),
        None,
    )
    if video is None:
        raise MediaError("face_track_gap_tolerance_unavailable")
    rate = video.avg_frame_rate or video.r_frame_rate
    if rate is None:
        raise MediaError("face_track_gap_tolerance_unavailable")
    return frame_period_tolerance_us(rate.numerator, rate.denominator)


def _face_follow_windows(
    visual: VisualAnalysisDocument,
    candidate_id: str,
    time_map: TimeMapDocument,
    time_map_sha256: str,
    source_sha256: str,
    source_asset_id: str,
    visual_sha256: str,
    database: Database,
    profile: AdvancedHeroProfile,
    actor: str,
    tool_version: str,
) -> tuple[list[ReframingWindow], ReframePlanDocument]:
    from clipforge.storage.repository import get_job

    job_id = visual.provenance.job_id or ""
    succeeded = False
    if job_id:
        try:
            with database.connect() as connection:
                succeeded = get_job(connection, job_id).status.value == "succeeded"
        except StorageError:
            succeeded = False
    try:
        document = build_face_follow(
            samples=list(visual.face_detection_samples),
            source_width=visual.proxy_width,
            source_height=visual.proxy_height,
            time_map=time_map,
            time_map_sha256=time_map_sha256,
            source_sha256=source_sha256,
            analysis_source_sha256=visual.source_sha256,
            analysis_present=bool(visual.face_detection_samples),
            producer_succeeded=succeeded,
            visual_analysis_id=visual.analysis_id,
            visual_analysis_sha256=visual_sha256,
            producer_job_id=job_id,
            plan_id=stable_id("reframe", candidate_id),
            source_asset_id=source_asset_id,
            created_by=actor,
            tool_version=tool_version,
            profile_fingerprint=profile.fingerprint(),
            face_sample_interval_us=visual.face_sample_interval_us,
            gap_tolerance_us=_face_follow_gap_tolerance_us(database, source_asset_id),
        )
    except ReframeError as exc:
        raise MediaError(exc.code) from exc
    if document.trajectory is None:
        raise MediaError("visual_analysis_missing")
    from clipforge.hero.reframe import window_end_us

    windows: list[ReframingWindow] = []
    samples = document.trajectory.samples
    duration_us = time_map.to_time_map().total_output_duration()
    for index, sample in enumerate(samples):
        end = window_end_us(document, index, duration_us)
        windows.append(
            ReframingWindow(
                window_id=stable_id("window", candidate_id, "face_follow", str(index)),
                strategy_id=profile.reframing,
                output_start_us=sample.output_us,
                output_end_us=end,
                source_x=sample.crop_x,
                source_y=sample.crop_y,
                source_width=sample.crop_width,
                source_height=sample.crop_height,
                frame_width=sample.frame_width,
                frame_height=sample.frame_height,
            )
        )
    return windows, document


def _face_boxes(visual: VisualAnalysisDocument, width: int, height: int) -> list[tuple[int, int, int, int]]:
    boxes: list[tuple[int, int, int, int]] = []
    for sample in visual.face_detection_samples:
        boxes.append(_pixel_box(sample, width, height))
    return boxes


def _pixel_box(sample: FaceDetectionSample, width: int, height: int) -> tuple[int, int, int, int]:
    box = sample.bounding_box
    x = max(0, int(box.x * width))
    y = max(0, int(box.y * height))
    w = max(1, int(box.width * width))
    h = max(1, int(box.height * height))
    if x + w > width:
        w = width - x
    if y + h > height:
        h = height - y
    return x, y, w, h


def _union(boxes: list[tuple[int, int, int, int]], width: int, height: int) -> tuple[int, int, int, int]:
    left = min(item[0] for item in boxes)
    top = min(item[1] for item in boxes)
    right = min(width, max(item[0] + item[2] for item in boxes))
    bottom = min(height, max(item[1] + item[3] for item in boxes))
    return left, top, max(1, right - left), max(1, bottom - top)


def _center_crop(width: int, height: int) -> tuple[int, int, int, int]:
    target = 9 / 16
    current = width / height
    if current > target:
        crop_w = max(1, int(height * target))
        return (width - crop_w) // 2, 0, crop_w, height
    crop_h = max(1, int(width / target))
    return 0, (height - crop_h) // 2, width, crop_h


def _broll(
    database: Database,
    workspace: SourceWorkspace,
    work_root: Path,
    project_id: str,
    candidate_id: str,
    duration_us: int,
    asset_ids: list[str],
    assets: list[AssetBinding],
    placements: list[DirectionAssetPlacement] | None = None,
) -> list[BrollEvent]:
    events: list[BrollEvent] = []
    if placements:
        placement_ids = [item.asset_id for item in placements]
        if asset_ids and asset_ids != placement_ids:
            raise MediaError("B-roll asset ids do not match the reviewed direction placements")
        asset_ids = placement_ids
    elif asset_ids:
        # Keep old documents readable, but make the unsafe behavior explicit
        # in the event. The browser production gate rejects these events.
        placements = None
    slot = max(1, duration_us // (len(asset_ids) + 1)) if asset_ids else duration_us
    for index, asset_id in enumerate(asset_ids):
        entry, license_record, _path = require_asset(
            database,
            workspace,
            project_id=project_id,
            asset_id=asset_id,
            expected_kind="graphic",
            work_root=work_root,
        )
        if not any(item.asset_id == asset_id for item in assets):
            assets.append(binding_for(entry, license_record, slot="graphic"))
        # Placement order is part of the declarative direction contract.  Do
        # not look up by asset id: one asset may intentionally be reused at
        # different output times or source in-points.
        placement = (placements or [])[index] if placements is not None else None
        if placement is None:
            start = min(duration_us - 2, index * slot)
            end = min(duration_us, start + max(1, slot // 2))
            source_in_us = 0
            evidence_ids: list[str] = []
            note = "legacy_auto_spacing: no reviewed source-grounded placement"
        else:
            start = placement.interval.output_start_us
            end = placement.interval.output_end_us
            source_in_us = placement.source_in_us
            evidence_ids = list(placement.source_evidence_ids)
            note = placement.relevance_note
            catalog_tags = tuple(entry.reference.content_tags)
            placement_tags = tuple(
                sorted({item.casefold().strip() for item in placement.asset_tags if item.strip()})
            )
            if not catalog_tags:
                raise MediaError(
                    f"B-roll asset {asset_id} has no reviewed content tags; "
                    "tag the local asset before selecting it"
                )
            if placement_tags != tuple(sorted(catalog_tags)):
                raise MediaError(
                    f"B-roll asset {asset_id} placement tags do not match its reviewed catalog tags"
                )
            if not _tags_support_note(catalog_tags, note):
                raise MediaError(
                    f"B-roll asset {asset_id} relevance note does not mention a reviewed content tag"
                )
        if end <= start:
            raise MediaError("B-roll interval is empty")
        events.append(
            BrollEvent(
                event_id=stable_id(
                    "broll", candidate_id, asset_id, placement.placement_id if placement else str(index)
                ),
                interval=OutputInterval(output_start_us=start, output_end_us=end),
                asset_id=asset_id,
                broll_source_in_us=source_in_us,
                source_evidence_ids=evidence_ids,
                relevance_note=note,
            )
        )
    return events


def _sfx(
    database: Database,
    workspace: SourceWorkspace,
    work_root: Path,
    project_id: str,
    candidate_id: str,
    duration_us: int,
    asset_ids: list[str],
    assets: list[AssetBinding],
    profile: AdvancedHeroProfile,
    placements: list[DirectionAssetPlacement] | None = None,
) -> list[AudioMixEvent]:
    events: list[AudioMixEvent] = []
    if placements:
        placement_ids = [item.asset_id for item in placements]
        if asset_ids and asset_ids != placement_ids:
            raise MediaError("SFX asset ids do not match the reviewed direction placements")
        asset_ids = placement_ids
    elif asset_ids:
        placements = None
    for index, asset_id in enumerate(asset_ids):
        entry, license_record, _path = require_asset(
            database,
            workspace,
            project_id=project_id,
            asset_id=asset_id,
            expected_kind="audio",
            work_root=work_root,
        )
        if not any(item.asset_id == asset_id for item in assets):
            assets.append(binding_for(entry, license_record, slot="audio"))
        placement = (placements or [])[index] if placements is not None else None
        gain: float
        if placement is None:
            start = min(duration_us - 2, 200_000 + (index * 100_000))
            end = min(duration_us, start + 300_000)
            gain = min(
                profile.max_gain_db,
                max(
                    profile.min_gain_db,
                    -6 if profile.renderer_recipe_version == "advanced-hero-renderer-v1" else -12,
                ),
            )
            evidence_ids: list[str] = []
            purpose = None
            note = "legacy_auto_spacing: no reviewed source-grounded placement"
            source_in_us = 0
        else:
            start = placement.interval.output_start_us
            end = placement.interval.output_end_us
            gain = float(placement.gain_db if placement.gain_db is not None else profile.sfx_default_gain_db)
            evidence_ids = list(placement.source_evidence_ids)
            purpose = placement.purpose
            note = placement.relevance_note
            source_in_us = placement.source_in_us
        if end <= start:
            raise MediaError("SFX interval is empty")
        sfx_limit = (
            profile.max_gain_db
            if profile.renderer_recipe_version == "advanced-hero-renderer-v1"
            else profile.sfx_max_gain_db
        )
        gain = min(profile.max_gain_db, sfx_limit, max(profile.min_gain_db, gain))
        events.append(
            AudioMixEvent(
                event_id=stable_id(
                    "sfx", candidate_id, asset_id, placement.placement_id if placement else str(index)
                ),
                interval=OutputInterval(output_start_us=start, output_end_us=end),
                asset_id=asset_id,
                gain_db=gain,
                sfx_source_in_us=source_in_us,
                fade_in_us=profile.sfx_fade_in_us,
                fade_out_us=profile.sfx_fade_out_us,
                source_evidence_ids=evidence_ids,
                purpose=purpose,
                relevance_note=note,
            )
        )
    return events


def _tags_support_note(tags: tuple[str, ...], note: str) -> bool:
    """Require an explicit reviewed label in the placement explanation.

    Tags are operator-confirmed metadata, not an automated relevance claim.
    The deterministic check prevents a direction from silently substituting an
    unrelated stock clip; human review remains the final editorial authority.
    """
    normalized = re.sub(r"[^\w%$']+", " ", note.casefold())
    tokens = set(normalized.split())
    return any(set(re.sub(r"[^\w%$']+", " ", tag.casefold()).split()) <= tokens for tag in tags)
