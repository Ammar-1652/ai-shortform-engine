"""Technical QA for the current advanced Hero artifact. Evidence omits filesystem paths."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from clipforge.campaign.overlays import (
    overlay_spec_sha256,
    validate_overlay_render_geometry,
    validate_overlay_sample_files,
)
from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import confine_work_path, require_asset
from clipforge.hero.advanced_build import stable_id
from clipforge.hero.advanced_service import _require_usable_audio
from clipforge.hero.caption_evidence import verify_caption_coverage_report
from clipforge.hero.constants import DURATION_TOLERANCE_US, OUTPUT_HEIGHT, OUTPUT_WIDTH
from clipforge.hero.editorial_arc import (
    load_editorial_arc,
    remap_direction_intervals,
    validate_arc_review,
    verify_arc_review_frames,
)
from clipforge.hero.motion_style import style_for_id
from clipforge.hero.probe import probe_hero
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.advanced import (
    AdvancedHeroDraftSetDocument,
    AdvancedHeroPlanDocument,
    AdvancedHeroRenderInput,
)
from clipforge.schemas.arc import EditorialArcReview
from clipforge.schemas.campaign import OverlayExclusionEvidence
from clipforge.schemas.caption_evidence import CaptionAudioCoverageReport
from clipforge.schemas.direction import DirectionDocument
from clipforge.schemas.hero import ForcedAlignmentDocument, HeroPlanDocument
from clipforge.schemas.jobs import QACheck, QAStatus
from clipforge.schemas.qa import ViewerEvidenceBundle
from clipforge.schemas.render_checkpoint import AdvancedRenderAuthorization
from clipforge.schemas.treatment import TreatmentAudioMeasurement, TreatmentEvidenceBundle
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
        _caption_evidence(inputs),
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


def _caption_evidence(inputs: TechnicalInputs) -> QACheck:
    """Require decoded cue-edge evidence for clean production outputs."""
    problems: list[str] = []
    missing: list[str] = []
    incomplete_speech: list[str] = []
    drafts = {draft.candidate_id: draft for draft in inputs.document.drafts}
    for plan in inputs.plans:
        if plan.style_id == "legacy-v1":
            continue
        draft = drafts.get(plan.candidate_id)
        if draft is None or not draft.caption_coverage_relative_path or not draft.caption_coverage_sha256:
            missing.append(f"candidate={plan.candidate_id} caption_coverage_evidence_missing")
            continue
        lexical = (
            inputs.workspace.advanced_run_dir(inputs.document.advanced_set_id)
            / draft.caption_coverage_relative_path
        )
        try:
            path = confine_work_path(
                inputs.root,
                lexical.relative_to(inputs.root).as_posix(),
                label="caption coverage evidence",
            )
            if path.is_symlink() or not path.is_file() or sha256_file(path) != draft.caption_coverage_sha256:
                raise MediaError("caption coverage evidence hash is stale")
            report = CaptionAudioCoverageReport.model_validate_json(path.read_text(encoding="utf-8"))
            # Frame collection cannot certify speech omitted by ASR. R5 must
            # provide a separately validated speech inventory before upgrading.
            if report.speech_coverage_status != "complete":
                incomplete_speech.append(f"candidate={plan.candidate_id} speech_coverage_insufficient")
            render_path = confine_work_path(
                inputs.root,
                (path.parent / "render-input.json").relative_to(inputs.root).as_posix(),
                label="caption render input",
            )
            if sha256_file(render_path) != draft.render_input_sha256:
                raise MediaError("caption evidence render input is stale")
            render_input = AdvancedHeroRenderInput.model_validate_json(render_path.read_text(encoding="utf-8"))
            if (
                render_input.captions != plan.captions
                or render_input.alignment_sha256 != plan.alignment_sha256
                or render_input.time_map_sha256 != plan.time_map_sha256
                or render_input.source_sha256 != inputs.source_sha256
                or render_input.speech_review_sha256 != plan.speech_review_sha256
                or render_input.arabic_corrections_sha256 != plan.arabic_corrections_sha256
                or render_input.caption_alignment_sha256 != plan.caption_alignment_sha256
            ):
                raise MediaError("caption evidence render input differs from the current plan")
            verify_caption_coverage_report(
                root=inputs.root,
                run_dir=inputs.workspace.advanced_run_dir(inputs.document.advanced_set_id),
                output=path.parent / "advanced.mp4",
                report=report,
                render_input=render_input,
                render_input_sha256=draft.render_input_sha256,
                source_asset_id=inputs.document.source_asset_id,
            )
        except (MediaError, OSError, UnicodeError, ValidationError, ValueError):
            problems.append(f"candidate={plan.candidate_id} caption_evidence_invalid_or_stale")
    if problems:
        return _check("caption-audio-evidence", False, "; ".join(problems))
    if missing:
        return QACheck(
            name="caption-audio-evidence",
            status=QAStatus.INSUFFICIENT_EVIDENCE,
            evidence="; ".join(missing)[:400],
        )
    if incomplete_speech:
        return QACheck(
            name="caption-audio-evidence",
            status=QAStatus.INSUFFICIENT_EVIDENCE,
            evidence="; ".join(incomplete_speech)[:400],
        )
    return _check(
        "caption-audio-evidence",
        True,
        "caption frame capture matches the encoded output; speech accuracy still requires review",
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
        if (
            direction.knowledge_context_id != (plan.knowledge_context_id or None)
            or direction.knowledge_release_id != (plan.knowledge_release_id or None)
            or direction.knowledge_context_sha256 != (plan.knowledge_context_sha256 or None)
            or direction.knowledge_decision_trace_id != (plan.knowledge_decision_trace_id or None)
            or direction.knowledge_decision_trace_sha256 != (plan.knowledge_decision_trace_sha256 or None)
        ):
            return _check("direction", False, f"candidate={plan.candidate_id} blocker=knowledge_binding_stale")
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
        if direction.direction_recipe_version in {"direction-v3", "direction-v4"}:
            from clipforge.editorial.presets import PresetCatalog
            from clipforge.hero.treatment_policy import evaluate_treatment_policy

            policy = PresetCatalog.load().find(direction.preset_id or "clean_explainer").treatment_policy
            findings = [
                item for item in evaluate_treatment_policy(selected, policy) if item.severity == "error"
            ]
            if findings:
                return _check(
                    "direction",
                    False,
                    f"candidate={plan.candidate_id} blocker=treatment_policy:{findings[0].code}",
                )
        if plan.treatment_fingerprint:
            if not plan.treatment_evidence_relative_path:
                return _check(
                    "direction", False, f"candidate={plan.candidate_id} blocker=treatment_evidence_path_missing"
                )
            bundle_path = confine_work_path(
                inputs.root, plan.treatment_evidence_relative_path, label="treatment evidence bundle"
            )
            if (
                bundle_path.is_symlink()
                or not bundle_path.is_file()
                or sha256_file(bundle_path) != plan.treatment_evidence_sha256
            ):
                return _check(
                    "direction", False, f"candidate={plan.candidate_id} blocker=treatment_evidence_stale"
                )
            try:
                bundle = TreatmentEvidenceBundle.model_validate_json(bundle_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValidationError, ValueError):
                return _check(
                    "direction", False, f"candidate={plan.candidate_id} blocker=treatment_evidence_invalid"
                )
            if (
                bundle.direction_id != plan.direction_id
                or bundle.direction_sha256 != plan.direction_sha256
                or bundle.treatment_fingerprint != plan.treatment_fingerprint
            ):
                return _check(
                    "direction",
                    False,
                    f"candidate={plan.candidate_id} blocker=treatment_evidence_binding_stale",
                )
        if plan.motion_recipe_ids != selected.motion_recipe_ids:
            return _check(
                "direction", False, f"candidate={plan.candidate_id} blocker=motion_recipe_selection_stale"
            )
        if plan.motion_catalog_sha256 != (direction.motion_catalog_sha256 or ""):
            return _check("direction", False, f"candidate={plan.candidate_id} blocker=motion_catalog_stale")
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
        expected_cameras = [
            {
                "event_id": stable_id("direction-camera", direction.direction_id, item.motion_id),
                "interval": item.interval.model_dump(mode="json"),
                "intent": item.intent,
                "path": item.path,
                "target_x_permille": item.target_x_permille,
                "target_y_permille": item.target_y_permille,
                "scale_start_permille": item.scale_start_permille,
                "scale_end_permille": item.scale_end_permille,
                "travel_px": item.travel_px,
                "intensity": item.intensity,
                "easing": item.easing,
                "source_evidence_ids": item.source_evidence_ids,
                "schema_version": "1.0.0",
            }
            for item in selected.camera_motion
        ]
        actual_cameras = [item.model_dump(mode="json") for item in plan.camera_motion]
        if actual_cameras != expected_cameras:
            return _check("direction", False, f"candidate={plan.candidate_id} blocker=camera_motion_stale")
        if selected.transitions:
            expected_transitions = [
                {
                    "event_id": stable_id("transition", plan.candidate_id, item.transition_id),
                    "interval": item.interval.model_dump(mode="json"),
                    "purpose": "visual_reveal",
                    "style": item.style,
                    "source_evidence_ids": item.source_evidence_ids,
                    "direction_purpose": item.purpose,
                    "sfx_placement_id": item.sfx_placement_id,
                    "schema_version": "1.0.0",
                }
                for item in selected.transitions
            ]
            if [item.model_dump(mode="json") for item in plan.transitions] != expected_transitions:
                return _check("direction", False, f"candidate={plan.candidate_id} blocker=transitions_stale")
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
    missing_evidence: list[str] = []
    drafts = {draft.candidate_id: draft for draft in inputs.document.drafts}
    for plan in inputs.plans:
        duration_us = max((window.output_end_us for window in plan.windows), default=inputs.duration_us)
        if plan.style_id != "legacy-v1":
            draft = drafts.get(plan.candidate_id)
            if draft is None or not draft.viewer_evidence_relative_path or not draft.viewer_evidence_sha256:
                missing_evidence.append(f"candidate={plan.candidate_id} viewer_evidence_missing")
            else:
                try:
                    evidence_path = confine_work_path(
                        inputs.root,
                        (
                            inputs.workspace.advanced_run_dir(inputs.document.advanced_set_id)
                            / draft.viewer_evidence_relative_path
                        )
                        .relative_to(inputs.root)
                        .as_posix(),
                        label="viewer evidence",
                    )
                    if (
                        evidence_path.is_symlink()
                        or not evidence_path.is_file()
                        or sha256_file(evidence_path) != draft.viewer_evidence_sha256
                    ):
                        raise MediaError("viewer evidence hash is stale")
                    bundle = ViewerEvidenceBundle.model_validate_json(evidence_path.read_text(encoding="utf-8"))
                    if (
                        bundle.project_id != inputs.document.project_id
                        or bundle.source_asset_id != inputs.document.source_asset_id
                        or bundle.candidate_id != plan.candidate_id
                        or bundle.artifact_id != inputs.artifact_id
                        or bundle.encoded_media_sha256 != draft.preview_sha256
                        or bundle.render_input_sha256 != draft.render_input_sha256
                        or bundle.duration_us != draft.output_duration_us
                        or bundle.style_fingerprint != plan.style_fingerprint
                        or bundle.treatment_fingerprint != plan.treatment_fingerprint
                        or bundle.treatment_evidence_sha256 != plan.treatment_evidence_sha256
                        or bundle.treatment_evidence_relative_path != plan.treatment_evidence_relative_path
                    ):
                        raise MediaError("viewer evidence is bound to a different artifact")
                    auth_path = evidence_path.parent.parent / "authorization.json"
                    authorization = AdvancedRenderAuthorization.model_validate_json(
                        auth_path.read_text(encoding="utf-8")
                    )
                    if bundle.manifest_sha256 != authorization.batch_sha256:
                        raise MediaError("viewer evidence batch manifest hash is stale")
                    render_input_path = evidence_path.parent.parent / "render-input.json"
                    render_input = AdvancedHeroRenderInput.model_validate_json(
                        render_input_path.read_text(encoding="utf-8")
                    )
                    if (
                        sha256_file(render_input_path) != draft.render_input_sha256
                        or render_input.style_fingerprint != bundle.style_fingerprint
                        or bundle.pilot_sha256 != render_input.pilot_sha256
                        or render_input.treatment_fingerprint != bundle.treatment_fingerprint
                        or render_input.treatment_evidence_sha256 != bundle.treatment_evidence_sha256
                    ):
                        raise MediaError("viewer evidence render input is stale")
                    if plan.treatment_audio_mix is not None and bundle.treatment_audio_mix_status != "measured":
                        raise MediaError("viewer evidence is missing measured treatment audio mix facts")
                    if (
                        plan.treatment_audio_mix is not None
                        and plan.treatment_audio_mix.cue_event_ids
                        and bundle.treatment_audio_intelligibility_status != "pass"
                    ):
                        raise MediaError(
                            "viewer evidence is missing a passing decoded audio intelligibility result"
                        )
                    if plan.treatment_audio_mix is not None:
                        measurement_path = confine_work_path(
                            inputs.root,
                            (evidence_path.parent / bundle.treatment_audio_measurement_relative_path)
                            .relative_to(inputs.root)
                            .as_posix(),
                            label="treatment audio measurement",
                        )
                        if (
                            measurement_path.is_symlink()
                            or not measurement_path.is_file()
                            or sha256_file(measurement_path) != bundle.treatment_audio_measurement_sha256
                        ):
                            raise MediaError("treatment audio measurement is missing or stale")
                        measurement = TreatmentAudioMeasurement.model_validate_json(
                            measurement_path.read_text(encoding="utf-8")
                        )
                        if (
                            measurement.source_asset_id != inputs.document.source_asset_id
                            or measurement.candidate_id != plan.candidate_id
                            or measurement.treatment_evidence_sha256 != plan.treatment_evidence_sha256
                            or measurement.encoded_media_sha256 != draft.preview_sha256
                            or measurement.mix.treatment_fingerprint != plan.treatment_fingerprint
                            or measurement.mix.mix_id != plan.treatment_audio_mix.mix_id
                            or measurement.mix.intelligibility_status != "pass"
                        ):
                            raise MediaError("treatment audio measurement is bound to another render")
                    if (
                        bundle.camera_motion_event_ids
                        != sorted(item.event_id for item in render_input.camera_motion)
                        or bundle.transition_event_ids
                        != sorted(item.event_id for item in render_input.transitions)
                        or bundle.motion_recipe_ids != sorted(render_input.motion_recipe_ids)
                    ):
                        raise MediaError("viewer evidence direction event receipt is stale")
                    if plan.campaign_overlay is not None:
                        if not draft.overlay_exclusion_relative_path or not draft.overlay_exclusion_sha256:
                            raise MediaError("overlay exclusion evidence is missing or stale")
                        exclusion_path = confine_work_path(
                            inputs.root,
                            (evidence_path.parent.parent / "overlay-exclusion.json")
                            .relative_to(inputs.root)
                            .as_posix(),
                            label="overlay exclusion evidence",
                        )
                        if (
                            not exclusion_path.is_file()
                            or exclusion_path.is_symlink()
                            or sha256_file(exclusion_path) != draft.overlay_exclusion_sha256
                            or render_input.overlay_exclusion_sha256 != draft.overlay_exclusion_sha256
                        ):
                            raise MediaError("overlay exclusion evidence is missing or stale")
                        exclusion = OverlayExclusionEvidence.model_validate_json(
                            exclusion_path.read_text(encoding="utf-8")
                        )
                        validate_overlay_sample_files(inputs.root, exclusion)
                        validate_overlay_render_geometry(exclusion, render_input)
                        if (
                            exclusion.source_asset_id != inputs.document.source_asset_id
                            or exclusion.candidate_id != plan.candidate_id
                            or exclusion.source_sha256 != plan.source_sha256
                            or exclusion.time_map_sha256 != plan.time_map_sha256
                            or exclusion.overlay_spec_sha256 != overlay_spec_sha256(plan.campaign_overlay)
                            or exclusion.transform_sha256
                            != (render_input.trajectory_sha256 or plan.reframing_config_sha256)
                        ):
                            raise MediaError("overlay exclusion evidence is bound to another transform")
                    if plan.editorial_arc_review_sha256:
                        arc_review_path = confine_work_path(
                            inputs.root,
                            (evidence_path.parent.parent / "editorial-arc-review.json")
                            .relative_to(inputs.root)
                            .as_posix(),
                            label="editorial arc review",
                        )
                        if (
                            not arc_review_path.is_file()
                            or arc_review_path.is_symlink()
                            or sha256_file(arc_review_path) != plan.editorial_arc_review_sha256
                        ):
                            raise MediaError("editorial arc review is missing or stale")
                        arc_review = EditorialArcReview.model_validate_json(
                            arc_review_path.read_text(encoding="utf-8")
                        )
                        arc, _arc_digest = load_editorial_arc(
                            inputs.workspace.advanced_arc_file(plan.candidate_id)
                        )
                        validate_arc_review(arc_review, arc)
                        verify_arc_review_frames(inputs.root, arc_review)
                        if (
                            arc_review.decision != "accepted"
                            or arc_review.source_asset_id != inputs.document.source_asset_id
                            or arc_review.candidate_id != plan.candidate_id
                            or arc_review.source_sha256 != plan.source_sha256
                            or arc_review.arc_sha256 != plan.editorial_arc_sha256
                        ):
                            raise MediaError("editorial arc review is bound to another arc")
                    expected_font = hashlib.sha256(
                        json.dumps(
                            sorted(render_input.motion_style.font_sha256)
                            if render_input.motion_style is not None
                            else [],
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                    if bundle.font_dependency_sha256 != expected_font:
                        raise MediaError("viewer evidence font dependency is stale")
                    run_dir = inputs.workspace.advanced_run_dir(inputs.document.advanced_set_id)
                    for evidence_file in [
                        *bundle.decoded_frames,
                        *bundle.contact_sheets,
                        *bundle.platform_crop_previews,
                    ]:
                        evidence_file_path = confine_work_path(
                            inputs.root,
                            (run_dir / evidence_file.relative_path).relative_to(inputs.root).as_posix(),
                            label="viewer evidence file",
                        )
                        if (
                            evidence_file_path.is_symlink()
                            or not evidence_file_path.is_file()
                            or sha256_file(evidence_file_path) != evidence_file.sha256
                        ):
                            raise MediaError("viewer evidence decoded file is stale")
                except (MediaError, OSError, UnicodeError, ValidationError, ValueError):
                    problems.append(f"candidate={plan.candidate_id} viewer_evidence_invalid_or_stale")
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
            alignment_path = (
                inputs.workspace.advanced_alignment_file(plan.candidate_id)
                if plan.editorial_arc_id
                else inputs.workspace.hero_alignment_file(plan.candidate_id)
            )
            if plan.caption_alignment_sha256 and draft is not None:
                alignment_path = confine_work_path(
                    inputs.root,
                    (
                        inputs.workspace.advanced_run_dir(inputs.document.advanced_set_id)
                        / "candidates"
                        / plan.candidate_id
                        / "caption-alignment.json"
                    )
                    .relative_to(inputs.root)
                    .as_posix(),
                    label="reviewed caption alignment",
                )
                if not alignment_path.is_file() or sha256_file(alignment_path) != plan.caption_alignment_sha256:
                    problems.append(f"candidate={plan.candidate_id} reviewed_caption_alignment_stale")
            if alignment_path.is_symlink() or not alignment_path.is_file():
                problems.append(f"candidate={plan.candidate_id} caption_alignment_missing")
            else:
                try:
                    alignment = ForcedAlignmentDocument.model_validate_json(
                        alignment_path.read_text(encoding="utf-8")
                    )
                    problems.extend(_caption_alignment_problems(plan, alignment))
                except (OSError, UnicodeError, ValidationError, ValueError):
                    problems.append(f"candidate={plan.candidate_id} caption_alignment_invalid")
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
    if missing_evidence:
        return QACheck(
            name="viewer-quality-contract",
            status=QAStatus.INSUFFICIENT_EVIDENCE,
            evidence="; ".join(missing_evidence)[:400],
        )
    return _check(
        "viewer-quality-contract",
        True,
        "caption word ids are unique; no repeated source ranges or unsupported quantitative graphic; "
        "human visual review remains required",
    )


def _caption_alignment_problems(
    plan: AdvancedHeroPlanDocument,
    alignment: ForcedAlignmentDocument,
) -> list[str]:
    """Compare persisted caption words with the alignment used for this plan."""
    expected = list(alignment.words)
    rendered = [word for cue in plan.captions for word in cue.words]
    expected_ids = [word.word_id for word in expected]
    rendered_ids = [word.word_id for word in rendered]
    problems: list[str] = []
    if rendered_ids != expected_ids:
        problems.append(f"candidate={plan.candidate_id} caption_alignment_word_coverage")
        return problems
    by_id = {word.word_id: word for word in expected}
    for word in rendered:
        source = by_id[word.word_id]
        if word.text.strip() != source.text.strip() or word.verification_status != source.verification_status:
            problems.append(f"candidate={plan.candidate_id} caption_alignment_text:{word.word_id}")
        if (
            word.output_start_us != source.output_start_us
            or word.output_end_us != source.output_end_us
            or word.output_start_frame != source.output_start_frame
            or word.output_end_frame_exclusive != source.output_end_frame_exclusive
        ):
            problems.append(f"candidate={plan.candidate_id} caption_alignment_timing:{word.word_id}")
    return problems


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
