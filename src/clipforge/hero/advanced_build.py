"""Build a deterministic advanced plan from forced alignment and cleared assets."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from clipforge.errors import MediaError, StorageError
from clipforge.hero.advanced_assets import binding_for, require_asset
from clipforge.hero.reframe import ReframeError, build_face_follow
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.advanced import (
    AdvancedHeroPlanDocument,
    AdvancedHeroProfile,
    AssetBinding,
    AudioMixEvent,
    DiagramEvent,
    DiagramPayload,
    EmphasisEvent,
    ReframingWindow,
    TypographyEvent,
    advanced_fingerprint,
)
from clipforge.schemas.editorial import BrollEvent, MotionPurpose, OutputInterval
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument, HeroPlanDocument
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.reframe import ReframePlanDocument
from clipforge.schemas.time import TimeMapDocument
from clipforge.schemas.vision import FaceDetectionSample, VisualAnalysisDocument
from clipforge.storage import Database
from clipforge.transcription.io import publish_json

_NAMESPACE = uuid.UUID("6f1d5e2a-9c4b-4f1a-8d3e-1a2b3c4d5e6f")
_SAFE = 48


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
    emphasis = _emphasis(alignment, candidate_id)
    typography = _typography(alignment, emphasis, candidate_id)
    diagrams = _diagrams(emphasis, duration_us, candidate_id)
    assets: list[AssetBinding] = []
    broll = _broll(
        database,
        workspace,
        work_root,
        project_id,
        candidate_id,
        duration_us,
        broll_asset_ids,
        assets,
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
    )
    manual = None if profile.manual_window is None else profile.manual_window.model_dump(mode="json")
    config: dict[str, object] = {
        "manual_window": manual,
        "strategy": profile.reframing.strategy_id,
        "windows": [item.model_dump(mode="json") for item in windows],
    }
    if reframe is not None and reframe.trajectory_sha256:
        config["trajectory_sha256"] = reframe.trajectory_sha256
    now = datetime.now(UTC)
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
        hero_review_id=review_id,
        hero_review_digest=review_digest,
        alignment_id=alignment.alignment_id,
        alignment_sha256=alignment_sha256,
        hero_plan_id=hero_plan.plan_id,
        hero_plan_sha256=hero_plan_sha256,
        visual_analysis_id=visual.analysis_id,
        visual_analysis_sha256=visual_sha256,
        time_map_sha256=hero_plan.edit_plan.time_map_sha256,
        profile_fingerprint=profile.fingerprint(),
        reframing_strategy=profile.reframing.strategy_id,
        reframing_config_sha256=advanced_fingerprint(config),
        windows=windows,
        typography=typography,
        diagrams=diagrams,
        emphasis=emphasis,
        broll=broll,
        sfx=sfx,
        assets=assets,
        qa_requirements=["forced_alignment", "rights_cleared_assets", "no_speaker_inference", "no_music"],
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


def _typography(
    alignment: ForcedAlignmentDocument,
    emphasis: list[EmphasisEvent],
    candidate_id: str,
) -> list[TypographyEvent]:
    chosen: list[tuple[str, int, int, MotionPurpose]] = []
    seen: set[str] = set()
    for word in alignment.words:
        stripped = word.text.strip()
        non_ascii = any(ord(char) > 127 for char in stripped)
        numeric = any(char.isdigit() or char == "$" for char in stripped)
        interesting = non_ascii or numeric
        if not interesting or not stripped or stripped in seen:
            continue
        seen.add(stripped)
        chosen.append((stripped, word.output_start_us, word.output_end_us, MotionPurpose.KEY_PHRASE))
    if not chosen and emphasis:
        item = emphasis[0]
        chosen.append((item.text.strip(), item.output_start_us, item.output_end_us, item.purpose))
    events: list[TypographyEvent] = []
    for index, (text, start, end, purpose) in enumerate(chosen[:3]):
        events.append(
            TypographyEvent(
                event_id=stable_id("type", candidate_id, text, str(index)),
                interval=OutputInterval(output_start_us=start, output_end_us=end),
                purpose=purpose,
                component_id=f"typography-{index}",
                text=text,
                x=72,
                y=1480,
                font_size=64,
            )
        )
    return events


def _diagrams(emphasis: list[EmphasisEvent], duration_us: int, candidate_id: str) -> list[DiagramEvent]:
    label = emphasis[0].text.strip() if emphasis else "Step"
    other = emphasis[1].text.strip() if len(emphasis) > 1 else "Next"
    end = min(duration_us, 800_000)
    if end <= 0:
        raise MediaError("advanced diagram needs a positive time map")
    return [
        DiagramEvent(
            event_id=stable_id("diagram", candidate_id, "comparison"),
            interval=OutputInterval(output_start_us=0, output_end_us=end),
            purpose=MotionPurpose.COMPARISON,
            component_id="number-comparison-v1",
            payload=DiagramPayload(
                kind="number_comparison",
                left_label=label[:40],
                right_label=other[:40],
                left_value=_number(label),
                right_value=_number(other),
            ),
            x=120,
            y=280,
            width=840,
            height=360,
        )
    ]


def _number(text: str) -> int:
    digits = "".join(character for character in text if character.isdigit())
    if not digits:
        return 0
    return min(int(digits[:9]), 1_000_000_000)


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
        if profile.manual_window is None:
            raise MediaError("manual_window strategy requires a reframing window")
        return [profile.manual_window], None
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
) -> list[BrollEvent]:
    events: list[BrollEvent] = []
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
        assets.append(binding_for(entry, license_record, slot="graphic"))
        start = min(duration_us - 2, index * slot)
        end = min(duration_us, start + max(1, slot // 2))
        if end <= start:
            raise MediaError("B-roll interval is empty")
        events.append(
            BrollEvent(
                event_id=stable_id("broll", candidate_id, asset_id),
                interval=OutputInterval(output_start_us=start, output_end_us=end),
                asset_id=asset_id,
                broll_source_in_us=0,
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
) -> list[AudioMixEvent]:
    events: list[AudioMixEvent] = []
    for index, asset_id in enumerate(asset_ids):
        entry, license_record, _path = require_asset(
            database,
            workspace,
            project_id=project_id,
            asset_id=asset_id,
            expected_kind="audio",
            work_root=work_root,
        )
        assets.append(binding_for(entry, license_record, slot="audio"))
        start = min(duration_us - 2, 200_000 + (index * 100_000))
        end = min(duration_us, start + 300_000)
        if end <= start:
            raise MediaError("SFX interval is empty")
        gain = min(profile.max_gain_db, max(profile.min_gain_db, -6))
        events.append(
            AudioMixEvent(
                event_id=stable_id("sfx", candidate_id, asset_id),
                interval=OutputInterval(output_start_us=start, output_end_us=end),
                asset_id=asset_id,
                gain_db=gain,
            )
        )
    return events
