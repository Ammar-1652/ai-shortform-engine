"""Deterministic per-beat treatment planning.

This module decides whether a direction needs a visual/audio treatment. It
does not download assets or render media. Provider adapters and Remotion stay
behind their existing typed boundaries.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

from clipforge.errors import MediaError
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.editorial_preset import PresetDefinition
from clipforge.schemas.hero import AlignedWord
from clipforge.schemas.time import TimeMapDocument
from clipforge.schemas.treatment import (
    BeatTreatmentDecision,
    BrollTreatmentDecision,
    CameraTreatmentDecision,
    MotionGraphicsTreatmentDecision,
    SfxTreatmentDecision,
    TransitionTreatmentDecision,
    TreatmentAssetRequest,
    TreatmentLayer,
    TreatmentPlanSummary,
    TreatmentRegion,
    TreatmentVisualEvidence,
)
from clipforge.schemas.vision import VisualAnalysisDocument

if TYPE_CHECKING:
    from clipforge.schemas.direction import DirectionOption, DirectionTransitionSpec

BrollRole = Literal[
    "context",
    "proof",
    "process",
    "reaction",
    "result",
    "contrast",
    "atmosphere",
    "product_detail",
]


def treatment_fingerprint(option: DirectionOption) -> str:
    """Hash all treatment decisions and event references for cache identity."""
    decisions = []
    for item in option.treatment_decisions:
        payload = item.model_dump(mode="json")
        payload["dependency_fingerprint"] = ""
        decisions.append(payload)
    payload = {
        "option_id": option.option_id,
        "treatment_decisions": decisions,
        "asset_requests": [
            request.model_dump(mode="json")
            for decision in option.treatment_decisions
            for request in decision.asset_requests
        ],
        "camera_motion": [item.model_dump(mode="json") for item in option.camera_motion],
        "transitions": [item.model_dump(mode="json") for item in option.transitions],
        "asset_placements": [item.model_dump(mode="json") for item in option.asset_placements],
    }
    raw = repr(_stable(payload)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def materialize_treatment(
    option: DirectionOption,
    words: Sequence[AlignedWord],
    preset: PresetDefinition,
    *,
    restricted_profile: bool = False,
    require_asset_selection: bool = True,
    time_map: TimeMapDocument | None = None,
    visual: VisualAnalysisDocument | None = None,
) -> DirectionOption:
    """Create explicit treatment decisions for an existing direction option.

    The function is deterministic and source-bound. It generates bounded camera
    moves for meaningful hook/punch beats, creates provider requests when a
    preset prefers an asset, and records policy blocks/omissions. It never
    selects a remote asset or invents a visual claim.
    """
    by_id = {word.word_id: word for word in words}
    evidence = {item.evidence_id: item for item in option.evidence}
    if any(word_id not in by_id for item in option.evidence for word_id in item.source_word_ids):
        raise MediaError("treatment planning requires all direction evidence words")
    placements = tuple(option.asset_placements)
    cameras = list(option.camera_motion)
    transitions = list(option.transitions)
    if not transitions and time_map is not None and preset.treatment_policy.transitions.mode != "blocked":
        transitions = _auto_transitions(option, words, time_map, preset)
    planning_option = option.model_copy(update={"transitions": transitions})
    decisions: list[BeatTreatmentDecision] = []
    for beat in option.beats:
        beat_evidence = [evidence[item] for item in beat.evidence_ids]
        beat_words = [by_id[word_id] for item in beat_evidence for word_id in item.source_word_ids]
        if not beat_words:
            raise MediaError(f"treatment beat has no aligned words: {beat.beat_id}")
        start = min(item.output_start_us for item in beat_words)
        end = max(item.output_end_us for item in beat_words)
        interval = OutputInterval(output_start_us=start, output_end_us=end)
        source_ids = list(beat.evidence_ids)

        beat_placements = [item for item in placements if _overlap(item.interval, interval)]
        broll_placements = [item for item in beat_placements if item.kind == "graphic"]
        sfx_placements = [item for item in beat_placements if item.kind == "audio"]
        requests: list[TreatmentAssetRequest] = []

        if restricted_profile:
            broll = BrollTreatmentDecision(
                state="blocked_by_policy",
                rationale="campaign policy prohibits outside editing footage",
                source_evidence_ids=source_ids,
                fallback="source_footage",
            )
            sfx = SfxTreatmentDecision(
                state="blocked_by_policy",
                rationale="campaign policy prohibits added SFX/music",
                source_evidence_ids=source_ids,
                fallback="silence",
            )
        elif broll_placements:
            placement_ids = [item.placement_id for item in broll_placements]
            broll = BrollTreatmentDecision(
                state="use",
                purpose=MotionPurpose.CONCEPT,
                rationale="selected asset is bound to this beat and overlaps its source evidence",
                source_evidence_ids=source_ids,
                event_ids=placement_ids,
                asset_ids=[item.asset_id for item in broll_placements],
                role=_broll_role(preset, beat.kind),
                relevance_note=broll_placements[0].relevance_note,
                fallback="source_footage",
            )
        elif (
            preset.treatment_policy.broll.mode == "preferred"
            and require_asset_selection
            and _broll_requested(preset, beat.kind)
        ):
            request = _broll_request(option, beat, interval, source_ids, preset)
            requests.append(request)
            broll = BrollTreatmentDecision(
                state="needs_review",
                rationale="preset prefers relevant B-roll, but no cleared asset was selected",
                source_evidence_ids=source_ids,
                asset_request_ids=[request.request_id],
                fallback="source_footage",
            )
        else:
            broll = BrollTreatmentDecision(
                state="omit_with_reason",
                rationale="no cleared B-roll is needed for this source-supported beat",
                source_evidence_ids=source_ids,
                omission_reason="no_relevant_asset",
                fallback="source_footage",
            )

        if restricted_profile:
            sfx = SfxTreatmentDecision(
                state="blocked_by_policy",
                rationale="campaign policy prohibits added SFX/music",
                source_evidence_ids=source_ids,
                fallback="silence",
            )
        elif sfx_placements:
            placement_ids = [item.placement_id for item in sfx_placements]
            sfx = SfxTreatmentDecision(
                state="use",
                purpose=MotionPurpose.VISUAL_REVEAL,
                rationale="selected SFX is bound to a declared editorial event",
                source_evidence_ids=source_ids,
                event_ids=placement_ids,
                asset_ids=[item.asset_id for item in sfx_placements],
                role="accent" if beat.kind != "punch" else "reveal",
                gain_db=min(preset.treatment_policy.sfx.max_gain_db, -18.0),
                duck_db=preset.treatment_policy.sfx.speech_duck_db,
                fallback="silence",
            )
        elif (
            require_asset_selection
            and preset.treatment_policy.sfx.mode in {"accent_only", "allowed"}
            and beat.kind in {"hook", "punch"}
        ):
            request = _sfx_request(option, beat, interval, source_ids, preset)
            requests.append(request)
            sfx = SfxTreatmentDecision(
                state="needs_review",
                rationale="preset allows a restrained accent, but no cleared SFX was selected",
                source_evidence_ids=source_ids,
                asset_request_ids=[request.request_id],
                fallback="silence",
            )
        else:
            sfx = SfxTreatmentDecision(
                state="omit_with_reason",
                rationale="speech remains clearer without an audio accent on this beat",
                source_evidence_ids=source_ids,
                omission_reason="dialogue_clarity",
                fallback="silence",
            )

        camera = _camera_decision(option, beat, interval, source_ids, cameras, preset, restricted_profile)
        visual_evidence = _visual_evidence(option, beat, visual, interval)
        if broll.state == "use" and visual_evidence.relevance_status == "unknown":
            threshold = preset.treatment_policy.broll.relevance_threshold
            relevance_status, relevance_score = _placement_relevance_status(
                option, beat, broll_placements, threshold
            )
            visual_evidence = visual_evidence.model_copy(
                update={
                    "relevance_status": relevance_status,
                    "relevance_score": relevance_score,
                    "relevance_threshold": threshold,
                    "evidence_ids": source_ids,
                }
            )
        if camera.state == "use" and (
            visual_evidence.collision_status == "blocked"
            or _camera_collides_regions(cameras, camera.event_ids, visual_evidence.regions)
        ):
            rejected_event_ids = set(camera.event_ids)
            cameras[:] = [item for item in cameras if item.motion_id not in rejected_event_ids]
            camera = CameraTreatmentDecision(
                state="omit_with_reason",
                rationale="camera move would leave a protected visual subject unsafe",
                source_evidence_ids=source_ids,
                omission_reason="protected_region_collision",
                protected_regions=visual_evidence.protected_region_ids,
                fallback="hold",
            )
        transition = _transition_decision(planning_option, beat, interval, source_ids, preset)
        graphics = MotionGraphicsTreatmentDecision(
            state="blocked_by_policy",
            rationale="motion graphics are disabled by the current production policy",
            source_evidence_ids=source_ids,
            fallback="none",
        )
        decision = BeatTreatmentDecision(
            beat_id=beat.beat_id,
            output_interval=interval,
            narrative_purpose=_narrative_purpose(beat.purpose),
            source_evidence_ids=source_ids,
            broll=broll,
            camera=camera,
            transition=transition,
            sfx=sfx,
            motion_graphics=graphics,
            asset_requests=requests,
            visual_evidence=visual_evidence,
            dependency_fingerprint="0" * 64,
        )
        decisions.append(decision)

    # The fingerprint is calculated after the full decision list exists. The
    # temporary placeholder is replaced by a second validated model pass.
    candidate = planning_option.model_copy(update={"treatment_decisions": decisions, "camera_motion": cameras})
    digest = treatment_fingerprint(candidate)
    decisions = [item.model_copy(update={"dependency_fingerprint": digest}) for item in decisions]
    return candidate.model_copy(update={"treatment_decisions": decisions, "camera_motion": cameras})


def _visual_evidence(
    option: DirectionOption,
    beat: Any,
    visual: VisualAnalysisDocument | None,
    interval: OutputInterval,
) -> TreatmentVisualEvidence:
    evidence = {item.evidence_id: item for item in option.evidence}
    scene_ids = sorted(
        {scene_id for evidence_id in beat.evidence_ids for scene_id in evidence[evidence_id].visual_scene_ids}
    )
    base_regions = [
        TreatmentRegion(
            region_id="platform-safe-region",
            role="platform_safe",
            interval=interval,
            x=96,
            y=270,
            width=824,
            height=1290,
            source="platform_profile",
        ),
        TreatmentRegion(
            region_id="caption-lane",
            role="caption",
            interval=interval,
            x=96,
            y=1540,
            width=824,
            height=284,
            source="render_input",
        ),
    ]
    native_regions = [
        TreatmentRegion(
            region_id=item.region_id,
            role="source_text",
            interval=item.interval,
            x=96,
            y=300,
            width=824,
            height=180,
            source="visual_analysis",
        )
        for item in option.source_native_text
        if any(scene_id in scene_ids for scene_id in item.visual_scene_ids)
    ]
    broll_regions = [
        TreatmentRegion(
            region_id=f"broll:{item.placement_id}",
            role="broll",
            interval=item.interval,
            x=item.output_region.x,
            y=item.output_region.y,
            width=item.output_region.width,
            height=item.output_region.height,
            source="render_input",
        )
        for item in option.asset_placements
        if item.kind == "graphic"
        and item.output_region is not None
        and _intervals_overlap(item.interval, interval)
    ]
    if visual is None or not scene_ids:
        return TreatmentVisualEvidence(
            visual_scene_ids=scene_ids,
            protected_region_ids=[item.region_id for item in base_regions + native_regions],
            collision_status="unknown",
            relevance_status="unknown",
            regions=[*base_regions, *native_regions, *broll_regions],
            note="visual geometry was not available for deterministic treatment planning",
        )
    faces = [item for item in visual.face_detection_samples if item.scene_id in scene_ids]
    protected = [
        "platform-safe-region",
        "caption-lane",
        *[item.region_id for item in native_regions],
        *[item.region_id for item in broll_regions],
    ]
    protected.extend(f"face:{scene_id}" for scene_id in sorted({item.scene_id for item in faces}))
    if not faces:
        return TreatmentVisualEvidence(
            visual_scene_ids=scene_ids,
            protected_region_ids=protected,
            collision_status="clear",
            relevance_status="unknown",
            regions=[*base_regions, *native_regions, *broll_regions],
            note="reviewed scenes contain no detected face geometry",
        )
    edge_face = any(
        item.bounding_box.x < 0.12
        or item.bounding_box.y < 0.12
        or item.bounding_box.x + item.bounding_box.width > 0.88
        or item.bounding_box.y + item.bounding_box.height > 0.88
        for item in faces
    )
    return TreatmentVisualEvidence(
        visual_scene_ids=scene_ids,
        protected_region_ids=protected,
        collision_status="blocked" if edge_face else "clear",
        relevance_status="unknown",
        regions=[
            *base_regions,
            *native_regions,
            *broll_regions,
            *[
                TreatmentRegion(
                    region_id=f"face:{sample.scene_id}",
                    role="face",
                    interval=interval,
                    x=round(sample.bounding_box.x * 1080),
                    y=round(sample.bounding_box.y * 1920),
                    width=max(1, round(sample.bounding_box.width * 1080)),
                    height=max(1, round(sample.bounding_box.height * 1920)),
                    source="visual_analysis",
                )
                for sample in faces
            ],
        ],
        note=(
            "face geometry is too close to a frame edge for a bounded camera move"
            if edge_face
            else "face geometry remains inside the camera protection envelope"
        ),
    )


def _camera_collides_regions(
    cameras: Sequence[Any], event_ids: Sequence[str], regions: Sequence[TreatmentRegion]
) -> bool:
    """Conservatively reject a camera envelope that can crop protected pixels."""
    selected = [item for item in cameras if item.motion_id in set(event_ids)]
    protected = [
        item
        for item in regions
        if item.role in {"face", "active_subject", "source_text", "logo", "cta", "broll"}
    ]
    for event in selected:
        scale_delta = max(event.scale_start_permille, event.scale_end_permille) / 1000 - 1
        expansion = event.travel_px + round(max(1080, 1920) * scale_delta / 2)
        for region in protected:
            if not _intervals_overlap(event.interval, region.interval):
                continue
            if (
                region.x - expansion < 0
                or region.y - expansion < 0
                or region.x + region.width + expansion > 1080
                or region.y + region.height + expansion > 1920
            ):
                return True
    return False


def _intervals_overlap(left: OutputInterval, right: OutputInterval) -> bool:
    return left.output_start_us < right.output_end_us and right.output_start_us < left.output_end_us


def _placement_relevance_status(
    option: DirectionOption,
    beat: Any,
    placements: Sequence[Any],
    threshold: float,
) -> tuple[Literal["related", "unrelated", "unknown"], float | None]:
    if not placements:
        return "unknown", None
    evidence = {item.evidence_id: item for item in option.evidence}
    source_terms = set(_terms(" ".join(evidence[item].source_text for item in beat.evidence_ids)))
    asset_terms = {term.casefold() for placement in placements for term in placement.asset_tags if term.strip()}
    if not source_terms or not asset_terms:
        return "unknown", None
    score = len(source_terms.intersection(asset_terms)) / len(source_terms)
    return ("related" if score >= threshold else "unrelated"), score


def summarize_treatment(option: DirectionOption) -> TreatmentPlanSummary:
    used: list[TreatmentLayer] = []
    blocked: list[TreatmentLayer] = []
    omitted: list[TreatmentLayer] = []
    requests = 0
    for decision in option.treatment_decisions:
        requests += len(decision.asset_requests)
        for layer in (
            decision.broll,
            decision.camera,
            decision.transition,
            decision.sfx,
            decision.motion_graphics,
        ):
            if layer.state == "use":
                used.append(layer.layer)
            elif layer.state == "blocked_by_policy":
                blocked.append(layer.layer)
            elif layer.state == "omit_with_reason":
                omitted.append(layer.layer)
    return TreatmentPlanSummary(
        treatment_fingerprint=treatment_fingerprint(option),
        beat_count=len(option.treatment_decisions),
        used_layers=sorted(set(used)),
        blocked_layers=sorted(set(blocked)),
        omitted_layers=sorted(set(omitted)),
        provider_request_count=requests,
    )


def _camera_decision(
    option: DirectionOption,
    beat: Any,
    interval: OutputInterval,
    source_ids: list[str],
    cameras: list[Any],
    preset: PresetDefinition,
    restricted: bool,
) -> CameraTreatmentDecision:
    from clipforge.schemas.direction import DirectionCameraMotion

    existing = [item for item in cameras if _overlap(item.interval, interval)]
    if existing:
        return CameraTreatmentDecision(
            state="use",
            purpose=MotionPurpose.KEY_PHRASE,
            rationale="bounded camera path is bound to the beat evidence",
            source_evidence_ids=source_ids,
            event_ids=[item.motion_id for item in existing],
            mode=_camera_mode(existing[0].path),
            intensity=existing[0].intensity,
            protected_regions=["faces", "captions", "source_branding"],
            fallback="hold",
        )
    policy = preset.treatment_policy.camera
    if restricted and policy.mode != "blocked":
        # Tarteel permits camera movement but still gets the same bounded
        # source-grounded treatment. Policy restrictions target outside media.
        pass
    if policy.mode == "blocked":
        return CameraTreatmentDecision(
            state="blocked_by_policy",
            rationale="the selected preset blocks camera movement",
            source_evidence_ids=source_ids,
            fallback="hold",
        )
    if beat.kind not in {"hook", "punch"} or interval.output_end_us - interval.output_start_us < 400_000:
        return CameraTreatmentDecision(
            state="omit_with_reason",
            rationale="a clean hold protects speech and caption readability on this beat",
            source_evidence_ids=source_ids,
            omission_reason="dialogue_clarity" if beat.kind == "body" else "short_interval",
            fallback="hold",
        )
    motion_id = _event_id(option.option_id, beat.beat_id, "camera")
    path = "push_in"
    # settle is represented by a small push that comes to rest; the renderer's
    # existing camera adapter accepts the bounded push_in event.
    cameras.append(
        DirectionCameraMotion(
            motion_id=motion_id,
            intent="orient" if beat.kind == "hook" else "settle",
            path=cast(Literal["push_in"], path),
            interval=interval,
            source_evidence_ids=source_ids,
            scale_start_permille=1000,
            scale_end_permille=1040 if beat.kind == "hook" else 1030,
            travel_px=24 if beat.kind == "hook" else 16,
            intensity="gentle",
            fallback="hold",
        )
    )
    return CameraTreatmentDecision(
        state="use",
        purpose=MotionPurpose.KEY_PHRASE,
        rationale="a bounded movement gives the opening/payoff a visual focus without masking captions",
        source_evidence_ids=source_ids,
        event_ids=[motion_id],
        mode="push_in",
        intensity="gentle",
        protected_regions=["faces", "captions", "source_branding"],
        fallback="hold",
    )


def _transition_decision(
    option: DirectionOption,
    beat: Any,
    interval: OutputInterval,
    source_ids: list[str],
    preset: PresetDefinition,
) -> TransitionTreatmentDecision:
    existing = [item for item in option.transitions if _overlap(item.interval, interval)]
    if existing:
        item = existing[0]
        return TransitionTreatmentDecision(
            state="use",
            purpose=MotionPurpose.VISUAL_REVEAL,
            rationale="transition is supplied by the direction and bound to an interior cut",
            source_evidence_ids=source_ids,
            event_ids=[item.transition_id],
            style=item.style,
            cut_boundary_us=item.interval.output_start_us,
            fallback="clean_cut",
        )
    return TransitionTreatmentDecision(
        state="omit_with_reason",
        rationale="no semantic interior cut is present in this beat",
        source_evidence_ids=source_ids,
        omission_reason="no_semantic_cut",
        fallback="clean_cut",
    )


def _auto_transitions(
    option: DirectionOption,
    words: Sequence[AlignedWord],
    time_map: TimeMapDocument,
    preset: PresetDefinition,
) -> list[DirectionTransitionSpec]:
    """Add sparse bridges only when an interior cut starts a reviewed beat."""
    from clipforge.schemas.direction import DirectionTransitionSpec

    by_id = {word.word_id: word for word in words}
    evidence = {item.evidence_id: item for item in option.evidence}
    segments = time_map.to_time_map().segments
    transitions: list[DirectionTransitionSpec] = []
    for index, segment in enumerate(segments[1:], start=1):
        previous = segments[index - 1]
        if previous.source_end_us == segment.source_start_us:
            continue
        cut = segment.output_start_us
        for beat in option.beats:
            beat_words = [
                by_id[word_id]
                for evidence_id in beat.evidence_ids
                for word_id in evidence[evidence_id].source_word_ids
            ]
            if not beat_words:
                continue
            beat_start = min(word.output_start_us for word in beat_words)
            beat_end = max(word.output_end_us for word in beat_words)
            if beat_start <= cut < beat_end:
                # A transition may bridge a reviewed segment cut, but it must
                # never bisect a spoken word. The canonical aligned-word
                # intervals are the only timing authority here.
                if any(word.output_start_us < cut < word.output_end_us for word in beat_words):
                    continue
                transitions.append(
                    DirectionTransitionSpec(
                        transition_id=_event_id(option.option_id, beat.beat_id, f"transition-{index}"),
                        interval=OutputInterval(
                            output_start_us=cut,
                            output_end_us=min(time_map.to_time_map().total_output_duration(), cut + 133_333),
                        ),
                        purpose="reveal" if beat.kind == "punch" else "cut",
                        style="concat_blur_dissolve_v1",
                        source_evidence_ids=beat.evidence_ids,
                        cut_boundary_us=cut,
                    )
                )
                break
        if len(transitions) >= preset.treatment_policy.transitions.max_per_30s:
            break
    return transitions


def _broll_request(
    option: DirectionOption,
    beat: Any,
    interval: OutputInterval,
    source_ids: list[str],
    preset: PresetDefinition,
) -> TreatmentAssetRequest:
    terms = _terms(" ".join(item.source_text for item in option.evidence if item.evidence_id in source_ids))
    role = _broll_role(preset, beat.kind)
    return TreatmentAssetRequest(
        request_id=_event_id(option.option_id, beat.beat_id, "broll-request"),
        beat_id=beat.beat_id,
        kind="graphic",
        role=role,
        query_terms=[role, *terms[:6]],
        negative_terms=["unrelated", "watermark", "logo"],
        provider_classes=["local", "envato", "openverse"],
        interval=interval,
        source_evidence_ids=source_ids,
        relevance_threshold=preset.treatment_policy.broll.relevance_threshold,
    )


def _sfx_request(
    option: DirectionOption,
    beat: Any,
    interval: OutputInterval,
    source_ids: list[str],
    preset: PresetDefinition,
) -> TreatmentAssetRequest:
    role = "reveal" if beat.kind == "punch" else "accent"
    return TreatmentAssetRequest(
        request_id=_event_id(option.option_id, beat.beat_id, "sfx-request"),
        beat_id=beat.beat_id,
        kind="audio",
        role=role,
        query_terms=["subtle", role, "short", "speech-safe"],
        negative_terms=["loud", "horror", "music", "siren"],
        provider_classes=["local", "envato", "openverse"],
        interval=interval,
        source_evidence_ids=source_ids,
        relevance_threshold=0.9,
    )


def _broll_role(preset: PresetDefinition, kind: str) -> BrollRole:
    roles = preset.treatment_policy.broll.roles
    if kind == "punch" and "result" in roles:
        return "result"
    return cast(BrollRole, roles[0] if roles else "context")


def _broll_requested(preset: PresetDefinition, kind: str) -> bool:
    """Keep conversational body beats readable while treating semantic peaks."""
    if kind in {"hook", "punch"}:
        return True
    return preset.preset_id in {"proof_comparison", "transformation"}


def _narrative_purpose(
    purpose: str,
) -> Literal["orient", "explain", "prove", "react", "contrast", "reveal", "resolve", "settle"]:
    return cast(
        Literal["orient", "explain", "prove", "react", "contrast", "reveal", "resolve", "settle"],
        {
            "context": "orient",
            "contrast": "contrast",
            "consequence": "explain",
            "payoff": "resolve",
        }.get(purpose, "explain"),
    )


def _camera_mode(path: str) -> Literal["static", "push_in", "pull_out", "follow_subject", "reframe", "settle"]:
    return cast(
        Literal["static", "push_in", "pull_out", "follow_subject", "reframe", "settle"],
        {"push_in": "push_in", "pull_out": "pull_out", "pan_x": "reframe", "pan_y": "reframe"}.get(
            path, "static"
        ),
    )


def _terms(text: str) -> list[str]:
    terms = [item for item in re.findall(r"[\w\u0600-\u06ff]+", text.casefold()) if len(item) > 1]
    return list(dict.fromkeys(terms))


def _event_id(option_id: str, beat_id: str, suffix: str) -> str:
    digest = hashlib.sha256(f"{option_id}|{beat_id}|{suffix}".encode()).hexdigest()[:24]
    return f"treat-{digest}"


def _overlap(left: OutputInterval, right: OutputInterval) -> bool:
    return left.output_start_us < right.output_end_us and right.output_start_us < left.output_end_us


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple((key, _stable(item)) for key, item in sorted(value.items()))
    if isinstance(value, list):
        return tuple(_stable(item) for item in value)
    return value
