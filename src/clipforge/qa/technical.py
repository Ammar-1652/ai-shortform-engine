"""Technical QA for the current advanced Hero artifact. Evidence omits filesystem paths."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import confine_work_path, require_asset
from clipforge.hero.advanced_service import _require_usable_audio
from clipforge.hero.constants import DURATION_TOLERANCE_US, OUTPUT_HEIGHT, OUTPUT_WIDTH
from clipforge.hero.editorial_arc import remap_direction_intervals
from clipforge.hero.motion_style import style_for_id
from clipforge.hero.probe import probe_hero
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.advanced import AdvancedHeroDraftSetDocument, AdvancedHeroPlanDocument
from clipforge.schemas.direction import DirectionDocument
from clipforge.schemas.hero import ForcedAlignmentDocument, HeroPlanDocument
from clipforge.schemas.jobs import QACheck, QAStatus
from clipforge.storage import Database


@dataclass(frozen=True, slots=True)
class TechnicalInputs:
    database: Database
    workspace: SourceWorkspace
    root: Path
    document: AdvancedHeroDraftSetDocument
    artifact_id: str
    manifest_sha256: str
    plans: tuple[AdvancedHeroPlanDocument, ...]
    source_sha256: str
    hero_artifact_id: str
    hero_manifest_sha256: str
    hero_alignment_sha256: dict[str, str]
    hero_plan_sha256: dict[str, str]
    visual_sha256: str
    duration_us: int


def technical_checks(inputs: TechnicalInputs) -> list[QACheck]:
    """Return one evidence-backed check per technical fact. Paths stay out of the text."""
    document = inputs.document
    checks = [
        _check(
            "artifact-kind",
            True,
            f"artifact {inputs.artifact_id} kind advanced_hero_draft_set_json set {document.advanced_set_id}",
        ),
        _provenance(inputs),
        _source_binding(inputs),
        _hero_binding(inputs),
        _manifest(inputs),
        _media(inputs),
        _probe(inputs),
        _audio(inputs),
        _intervals(inputs),
        _producers(inputs),
        _remote(inputs),
        _reframing(inputs),
        _direction(inputs),
        _assets(inputs),
        _viewer_quality(inputs),
    ]
    return checks


def _provenance(inputs: TechnicalInputs) -> QACheck:
    provenance = inputs.document.provenance
    ok = inputs.document.source_asset_id in provenance.source_asset_ids and bool(provenance.tool)
    return _check(
        "provenance",
        ok,
        f"artifact {inputs.artifact_id} provenance tool {provenance.tool}",
    )


def _source_binding(inputs: TechnicalInputs) -> QACheck:
    ok = inputs.document.source_sha256 == inputs.source_sha256
    return _check(
        "source-binding",
        ok,
        f"source {inputs.document.source_asset_id} sha256 {inputs.source_sha256}",
    )


def _hero_binding(inputs: TechnicalInputs) -> QACheck:
    ok = (
        inputs.document.hero_artifact_id == inputs.hero_artifact_id
        and inputs.document.hero_manifest_sha256 == inputs.hero_manifest_sha256
    )
    return _check(
        "hero-binding",
        ok,
        f"hero artifact {inputs.hero_artifact_id} manifest sha256 {inputs.hero_manifest_sha256}",
    )


def _manifest(inputs: TechnicalInputs) -> QACheck:
    return _check(
        "manifest",
        len(inputs.manifest_sha256) == 64 and bool(inputs.document.drafts),
        f"manifest sha256 {inputs.manifest_sha256} drafts {len(inputs.document.drafts)}",
    )


def _media(inputs: TechnicalInputs) -> QACheck:
    problems: list[str] = []
    for draft in inputs.document.drafts:
        lexical = (
            inputs.workspace.advanced_run_dir(inputs.document.advanced_set_id) / draft.preview_relative_path
        )
        try:
            path = confine_work_path(
                inputs.root,
                lexical.relative_to(inputs.root).as_posix(),
                label="advanced media",
            )
        except (MediaError, ValueError):
            problems.append(f"candidate {draft.candidate_id} media is a symlink or escapes the work root")
            continue
        if not path.is_file():
            problems.append(f"candidate {draft.candidate_id} media is missing")
            continue
        if path.stat().st_size == 0:
            problems.append(f"candidate {draft.candidate_id} media is zero bytes")
            continue
        if sha256_file(path) != draft.preview_sha256 or path.stat().st_size != draft.preview_size_bytes:
            problems.append(f"candidate {draft.candidate_id} media hash does not match the manifest")
    if problems:
        return _check("media-file", False, "; ".join(problems))
    count = len(inputs.document.drafts)
    return _check("media-file", True, f"{count} advanced media files match the manifest hashes")


def _probe(inputs: TechnicalInputs) -> QACheck:
    facts: list[str] = []
    for draft in inputs.document.drafts:
        lexical = (
            inputs.workspace.advanced_run_dir(inputs.document.advanced_set_id) / draft.preview_relative_path
        )
        try:
            path = confine_work_path(
                inputs.root,
                lexical.relative_to(inputs.root).as_posix(),
                label="advanced media",
            )
        except (MediaError, ValueError):
            return _check("media-probe", False, f"candidate {draft.candidate_id} media is not a regular file")
        if not path.is_file() or path.stat().st_size == 0:
            return _check("media-probe", False, f"candidate {draft.candidate_id} media cannot be probed")
        try:
            probed = probe_hero(path, expected_duration_us=draft.output_duration_us)
        except MediaError as exc:
            text = str(exc).replace(str(inputs.root), "work")
            return _check("media-probe", False, f"candidate {draft.candidate_id} {text}")
        facts.append(
            f"candidate {draft.candidate_id} h264 {probed.pixel_format} aac "
            f"{OUTPUT_WIDTH}x{OUTPUT_HEIGHT} 30/1 duration_error_us {probed.duration_error_us} "
            f"tolerance_us {DURATION_TOLERANCE_US}"
        )
    return _check("media-probe", True, "; ".join(facts))


def _audio(inputs: TechnicalInputs) -> QACheck:
    """Re-measure encoded audio so an old or manually replaced MP4 cannot pass on duration alone."""
    problems: list[str] = []
    profile = inputs.document.profile
    for draft in inputs.document.drafts:
        lexical = (
            inputs.workspace.advanced_run_dir(inputs.document.advanced_set_id) / draft.preview_relative_path
        )
        try:
            path = confine_work_path(
                inputs.root,
                lexical.relative_to(inputs.root).as_posix(),
                label="advanced audio",
            )
            _require_usable_audio(
                path,
                path.parent / f"{draft.candidate_id}.qa-audio.log",
                target_lufs=profile.audio_loudness_lufs,
                true_peak_limit=profile.audio_true_peak_dbfs,
            )
        except (MediaError, OSError) as exc:
            problems.append(f"candidate {draft.candidate_id} {str(exc).replace(str(inputs.root), 'work')}")
    if problems:
        return _check("audio-loudness", False, "; ".join(problems))
    return _check(
        "audio-loudness",
        True,
        f"encoded audio is within {profile.audio_loudness_lufs:.1f} LUFS and "
        f"{profile.audio_true_peak_dbfs:.1f} dBFS true-peak policy",
    )


def _intervals(inputs: TechnicalInputs) -> QACheck:
    problems: list[str] = []
    for plan in inputs.plans:
        events = [("broll", item.interval.output_start_us, item.interval.output_end_us) for item in plan.broll]
        events.extend(("sfx", item.interval.output_start_us, item.interval.output_end_us) for item in plan.sfx)
        events.extend(
            ("typography", item.interval.output_start_us, item.interval.output_end_us)
            for item in plan.typography
        )
        events.extend(
            ("diagram", item.interval.output_start_us, item.interval.output_end_us) for item in plan.diagrams
        )
        events.extend(
            ("motion_graphic", item.interval.output_start_us, item.interval.output_end_us)
            for item in plan.motion_graphics
        )
        events.extend(
            ("caption", item.interval.output_start_us, item.interval.output_end_us) for item in plan.captions
        )
        events.extend(
            ("transition", item.interval.output_start_us, item.interval.output_end_us)
            for item in plan.transitions
        )
        for label, start, end in events:
            if start < 0 or end <= start or end > inputs.duration_us:
                problems.append(
                    f"candidate {plan.candidate_id} {label} interval {start}-{end} "
                    f"is outside duration {inputs.duration_us}"
                )
        broll_spans = [(item.interval.output_start_us, item.interval.output_end_us) for item in plan.broll]
        _overlap(plan.candidate_id, "broll", broll_spans, problems)
        _overlap(
            plan.candidate_id,
            "typography",
            [(item.interval.output_start_us, item.interval.output_end_us) for item in plan.typography],
            problems,
        )
    if problems:
        return _check("intervals", False, "; ".join(problems))
    return _check("intervals", True, f"intervals stay inside the {inputs.duration_us} us time map")


def _overlap(candidate_id: str, label: str, spans: list[tuple[int, int]], problems: list[str]) -> None:
    ordered = sorted(spans)
    previous = -1
    for start, end in ordered:
        if start < previous:
            problems.append(f"candidate {candidate_id} {label} intervals overlap")
            return
        previous = end


def _producers(inputs: TechnicalInputs) -> QACheck:
    problems: list[str] = []
    for plan in inputs.plans:
        if plan.source_sha256 != inputs.source_sha256:
            problems.append(f"candidate {plan.candidate_id} source hash is stale")
        if plan.hero_artifact_id != inputs.hero_artifact_id:
            problems.append(f"candidate {plan.candidate_id} hero artifact is stale")
        if plan.hero_manifest_sha256 != inputs.hero_manifest_sha256:
            problems.append(f"candidate {plan.candidate_id} hero manifest is stale")
        if plan.visual_analysis_sha256 != inputs.visual_sha256:
            problems.append(f"candidate {plan.candidate_id} visual analysis is stale")
        alignment = inputs.hero_alignment_sha256.get(plan.candidate_id)
        hero_plan = inputs.hero_plan_sha256.get(plan.candidate_id)
        if plan.editorial_arc_id:
            advanced_alignment = inputs.workspace.advanced_alignment_file(plan.candidate_id)
            if (
                advanced_alignment.is_symlink()
                or not advanced_alignment.is_file()
                or sha256_file(advanced_alignment) != plan.alignment_sha256
            ):
                problems.append(f"candidate {plan.candidate_id} editorial alignment is stale")
        elif alignment is None or plan.alignment_sha256 != alignment:
            problems.append(f"candidate {plan.candidate_id} alignment is stale")
        if hero_plan is None or plan.hero_plan_sha256 != hero_plan:
            problems.append(f"candidate {plan.candidate_id} hero plan is stale")
    if problems:
        return _check("producer-hashes", False, "; ".join(problems))
    return _check(
        "producer-hashes",
        True,
        "source, hero, alignment, plan, and visual hashes match the current producers",
    )


def _remote(inputs: TechnicalInputs) -> QACheck:
    for plan in inputs.plans:
        raw = json.dumps(plan.model_dump(mode="json"))
        if "http://" in raw or "https://" in raw:
            return _check("remote-media", False, f"candidate {plan.candidate_id} plan contains a remote URL")
    return _check("remote-media", True, "advanced plans contain no remote media URL")


def _reframing(inputs: TechnicalInputs) -> QACheck:
    strategy = inputs.document.reframing_strategy
    if strategy == "contain":
        if any(plan.reframing_strategy != "contain" for plan in inputs.plans):
            return _check("reframing", False, "reframing strategy contain was not applied")
        return _check("reframing", True, "reframing strategy contain")
    if strategy != "face_follow":
        return _check("reframing", False, f"reframing strategy {strategy} is not supported")
    from pydantic import ValidationError

    from clipforge.hero.reframe import facts_line, windows_follow_trajectory
    from clipforge.schemas.reframe import ReframePlanDocument

    lines: list[str] = []
    for plan in inputs.plans:
        if plan.reframing_strategy != "face_follow":
            return _check(
                "reframing",
                False,
                "requested=face_follow applied=none fallback=not_eligible "
                "blocker=face_follow_requires_one_track",
            )
        path = inputs.workspace.reframe_plan_file(plan.candidate_id)
        if path.is_symlink():
            return _check("reframing", False, "requested=face_follow applied=none blocker=unsafe_path")
        if not path.is_file():
            return _check(
                "reframing", False, "requested=face_follow applied=none blocker=visual_analysis_missing"
            )
        try:
            document = ReframePlanDocument.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, ValueError):
            return _check(
                "reframing", False, "requested=face_follow applied=none blocker=visual_analysis_missing"
            )
        if (
            document.source_sha256 != inputs.source_sha256
            or document.visual_analysis_sha256 != inputs.visual_sha256
        ):
            return _check("reframing", False, f"{facts_line(document, blocker='visual_analysis_stale')}")
        if document.time_map_sha256 != plan.time_map_sha256:
            return _check("reframing", False, f"{facts_line(document, blocker='time_map_stale')}")
        followed = windows_follow_trajectory(document, list(plan.windows), inputs.duration_us)
        if document.applied_strategy != "face_follow" or not followed:
            return _check("reframing", False, f"{facts_line(document, blocker='visual_analysis_stale')}")
        lines.append(facts_line(document))
    return _check("reframing", True, " ".join(lines))


def _direction(inputs: TechnicalInputs) -> QACheck:
    """Bind the direction artifact and style recipe into the QA evidence."""
    lines: list[str] = []
    for plan in inputs.plans:
        if not plan.direction_id:
            if inputs.document.profile.renderer_recipe_version in {
                "advanced-hero-renderer-directed-v2",
                "advanced-hero-renderer-directed-v3",
                "advanced-hero-renderer-directed-v4",
            }:
                return _check(
                    "direction",
                    False,
                    f"candidate={plan.candidate_id} blocker=direction_missing_for_clean_production",
                )
            lines.append(f"candidate={plan.candidate_id} direction=none")
            continue
        path = inputs.workspace.direction_file(plan.candidate_id)
        if path.is_symlink() or not path.is_file():
            return _check("direction", False, f"candidate={plan.candidate_id} blocker=direction_missing")
        try:
            direction = DirectionDocument.model_validate_json(path.read_text(encoding="utf-8"))
            style = style_for_id(plan.style_id)
        except (OSError, UnicodeError, ValidationError, ValueError):
            return _check("direction", False, f"candidate={plan.candidate_id} blocker=direction_invalid")
        if sha256_file(path) != plan.direction_sha256:
            return _check("direction", False, f"candidate={plan.candidate_id} blocker=direction_stale")
        if (
            direction.direction_id != plan.direction_id
            or direction.style_id != plan.style_id
            or direction.style_fingerprint != plan.style_fingerprint
            or style.fingerprint() != plan.style_fingerprint
        ):
            return _check("direction", False, f"candidate={plan.candidate_id} blocker=style_stale")
        if plan.editorial_arc_id:
            try:
                if plan.time_map is None:
                    raise MediaError("editorial arc is missing its effective TimeMap")
                original_alignment = ForcedAlignmentDocument.model_validate_json(
                    inputs.workspace.hero_alignment_file(plan.candidate_id).read_text(encoding="utf-8")
                )
                editorial_alignment = ForcedAlignmentDocument.model_validate_json(
                    inputs.workspace.advanced_alignment_file(plan.candidate_id).read_text(encoding="utf-8")
                )
                direction = remap_direction_intervals(
                    direction,
                    original_alignment,
                    editorial_alignment,
                    HeroPlanDocument.model_validate_json(
                        inputs.workspace.hero_plan_file(plan.candidate_id).read_text(encoding="utf-8")
                    ).edit_plan.time_map,
                    plan.time_map,
                )
            except (OSError, UnicodeError, ValidationError, ValueError, MediaError):
                return _check(
                    "direction",
                    False,
                    f"candidate={plan.candidate_id} blocker=editorial_alignment_invalid",
                )
        selected = next(
            (option for option in direction.options if option.option_id == direction.selected_option_id),
            None,
        )
        if selected is None:
            return _check("direction", False, f"candidate={plan.candidate_id} blocker=selection_missing")
        expected_broll = [item for item in selected.asset_placements if item.kind == "graphic"]
        expected_sfx = [item for item in selected.asset_placements if item.kind == "audio"]
        if len(plan.broll) != len(expected_broll) or any(
            event.asset_id != placement.asset_id
            or event.interval != placement.interval
            or event.broll_source_in_us != placement.source_in_us
            or event.source_evidence_ids != placement.source_evidence_ids
            or event.relevance_note != placement.relevance_note
            for event, placement in zip(plan.broll, expected_broll, strict=True)
        ):
            return _check("direction", False, f"candidate={plan.candidate_id} blocker=broll_placement_stale")
        if len(plan.sfx) != len(expected_sfx) or any(
            event.asset_id != placement.asset_id
            or event.interval != placement.interval
            or event.sfx_source_in_us != placement.source_in_us
            or event.source_evidence_ids != placement.source_evidence_ids
            or event.purpose != placement.purpose
            or event.relevance_note != placement.relevance_note
            for event, placement in zip(plan.sfx, expected_sfx, strict=True)
        ):
            return _check("direction", False, f"candidate={plan.candidate_id} blocker=sfx_placement_stale")
        expected_graphics = selected.motion_graphics
        if len(plan.motion_graphics) != len(expected_graphics) or any(
            event.template != graphic.template
            or event.interval != graphic.interval
            or event.purpose != graphic.purpose
            or event.source_evidence_ids != graphic.source_evidence_ids
            or event.display_text != graphic.display_text
            or (event.x, event.y, event.width, event.height)
            != (graphic.x, graphic.y, graphic.width, graphic.height)
            for event, graphic in zip(plan.motion_graphics, expected_graphics, strict=True)
        ):
            return _check("direction", False, f"candidate={plan.candidate_id} blocker=motion_graphics_stale")
        if any(not event.source_evidence_ids or not event.relevance_note for event in plan.broll):
            return _check(
                "direction",
                False,
                f"candidate={plan.candidate_id} blocker=broll_relevance_missing",
            )
        if any(
            not event.source_evidence_ids or not event.relevance_note or event.purpose is None
            for event in plan.sfx
        ):
            return _check(
                "direction",
                False,
                f"candidate={plan.candidate_id} blocker=sfx_relevance_missing",
            )
        lines.append(
            f"candidate={plan.candidate_id} direction_sha256={plan.direction_sha256} "
            f"style={plan.style_id} style_fingerprint={plan.style_fingerprint} "
            f"safe_region={plan.safe_region_id}"
        )
    return _check("direction", True, " ".join(lines))


def _viewer_quality(inputs: TechnicalInputs) -> QACheck:
    """Fail obvious viewer-facing contract defects independently of file health."""
    problems: list[str] = []
    for plan in inputs.plans:
        duration_us = max((window.output_end_us for window in plan.windows), default=inputs.duration_us)
        if plan.style_id != "legacy-v1":
            if not plan.direction_id or not plan.direction_sha256:
                problems.append(f"candidate={plan.candidate_id} direction_missing")
            if not plan.captions:
                problems.append(f"candidate={plan.candidate_id} caption_coverage_missing")
            for cue in plan.captions:
                cue_duration = cue.interval.output_end_us - cue.interval.output_start_us
                if cue_duration < 100_000:
                    problems.append(f"candidate={plan.candidate_id} caption_too_short:{cue.event_id}")
                if not cue.words:
                    problems.append(f"candidate={plan.candidate_id} caption_words_missing:{cue.event_id}")
                cue_tokens = _viewer_tokens(cue.text)
                word_tokens = _viewer_tokens(" ".join(word.text for word in cue.words))
                if cue_tokens != word_tokens:
                    problems.append(f"candidate={plan.candidate_id} caption_text_mismatch:{cue.event_id}")
        if plan.time_map is not None:
            ranges = [(segment.source_start_us, segment.source_end_us) for segment in plan.time_map.segments]
            if len(set(ranges)) != len(ranges):
                problems.append(f"candidate={plan.candidate_id} repeated_source_range")
        windows = sorted(plan.windows, key=lambda item: item.output_start_us)
        if windows:
            cursor = 0
            for window in windows:
                if window.output_start_us != cursor or window.output_end_us > duration_us:
                    problems.append(f"candidate={plan.candidate_id} framing_gap_or_overrun")
                    break
                if window.strategy_id.strategy_id != plan.reframing_strategy:
                    problems.append(f"candidate={plan.candidate_id} framing_strategy_mismatch")
                    break
                cursor = window.output_end_us
            if cursor != duration_us:
                problems.append(f"candidate={plan.candidate_id} framing_does_not_cover_duration")
        elif plan.style_id != "legacy-v1":
            problems.append(f"candidate={plan.candidate_id} framing_evidence_missing")
        caption_words = [word.word_id for cue in plan.captions for word in cue.words]
        if len(caption_words) != len(set(caption_words)):
            problems.append(f"candidate={plan.candidate_id} duplicate_caption_word")
        for graphic in plan.motion_graphics:
            if graphic.template == "business_spotlight":
                lowered = graphic.display_text.casefold()
                numeric = any(character.isdigit() for character in lowered)
                measure = any(token in lowered for token in ("$", "%", "million", "billion", "percent"))
                if not numeric or not measure:
                    problems.append(f"candidate={plan.candidate_id} unsupported_quantitative_graphic")
        if plan.reframing_strategy == "center_crop" and plan.source_native_text:
            problems.append(f"candidate={plan.candidate_id} native_text_crop_unreviewed")
    if problems:
        return _check("viewer-quality-contract", False, "; ".join(problems))
    return _check(
        "viewer-quality-contract",
        True,
        "caption word ids are unique; no repeated source ranges or unsupported quantitative graphic; "
        "human visual review remains required",
    )


def _viewer_tokens(text: str) -> list[str]:
    """Compare caption text without treating punctuation/whitespace as words."""
    return re.findall(r"[\w\u00c0-\u024f\u3040-\u30ff\u3400-\u9fff]+", text.casefold(), re.UNICODE)


def _assets(inputs: TechnicalInputs) -> QACheck:
    problems: list[str] = []
    for plan in inputs.plans:
        for binding in plan.assets:
            try:
                entry, record, path = require_asset(
                    inputs.database,
                    inputs.workspace,
                    project_id=plan.project_id,
                    asset_id=binding.asset_id,
                    expected_kind=binding.kind,
                    work_root=inputs.root,
                )
                if sha256_file(path) != binding.sha256 or entry.file_sha256 != binding.sha256:
                    problems.append(f"asset {binding.asset_id} hash changed")
                elif record.status.value != binding.license_status:
                    problems.append(f"asset {binding.asset_id} rights changed")
            except (MediaError, OSError) as exc:
                text = str(exc).replace(str(inputs.root), "work")
                if str(inputs.root) in text or "://" in text:
                    text = f"asset {binding.asset_id} failed a local path check"
                problems.append(text[:180])
    if problems:
        return _check("asset-rights", False, "; ".join(problems))
    return _check("asset-rights", True, "referenced assets match their rights records and hashes")


def _check(name: str, ok: bool, evidence: str) -> QACheck:
    cleaned = evidence.replace("\\", " ")
    if "://" in cleaned:
        cleaned = f"{name} failed; remote evidence omitted"
    return QACheck(
        name=name,
        status=QAStatus.PASS if ok else QAStatus.FAIL,
        evidence=cleaned[:400],
    )
