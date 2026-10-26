"""Deterministic editorial direction lint before Advanced Hero planning."""

from __future__ import annotations

from collections.abc import Sequence

from clipforge.errors import MediaError
from clipforge.hero.direction_service import validate_source_evidence
from clipforge.hero.treatment import treatment_fingerprint
from clipforge.hero.treatment_policy import evaluate_treatment_policy
from clipforge.schemas.direction import DirectionDocument, DirectionLintFinding, DirectionLintReport
from clipforge.schemas.hero import AlignedWord
from clipforge.schemas.time import TimeMapDocument


def lint_direction(
    document: DirectionDocument,
    *,
    direction_sha256: str,
    words: Sequence[AlignedWord],
    time_map: TimeMapDocument,
    scene_ids: set[str],
) -> DirectionLintReport:
    """Return lint findings without modifying the direction document."""
    findings: list[DirectionLintFinding] = []
    try:
        validate_source_evidence(document, words, time_map, scene_ids)
    except MediaError as exc:
        findings.append(
            DirectionLintFinding(
                severity="error",
                code="source_evidence_invalid",
                message=str(exc),
            )
        )
    selected = next(option for option in document.options if option.option_id == document.selected_option_id)
    if document.direction_recipe_version == "direction-v3":
        if document.treatment_fingerprint is None:
            findings.append(
                DirectionLintFinding(
                    severity="error",
                    code="treatment_fingerprint_missing",
                    message="treatment-aware direction must carry a treatment fingerprint",
                )
            )
        else:
            expected_treatment = treatment_fingerprint(selected)
            if document.treatment_fingerprint != expected_treatment:
                findings.append(
                    DirectionLintFinding(
                        severity="error",
                        code="treatment_fingerprint_stale",
                        message="direction treatment decisions are stale against the selected option",
                    )
                )
        if len(selected.treatment_decisions) != len(selected.beats):
            findings.append(
                DirectionLintFinding(
                    severity="error",
                    code="treatment_coverage_missing",
                    message="every selected hook/body/punch beat needs treatment decisions",
                )
            )
        for decision in selected.treatment_decisions:
            if decision.dependency_fingerprint != document.treatment_fingerprint:
                findings.append(
                    DirectionLintFinding(
                        severity="error",
                        code="treatment_decision_stale",
                        message=f"treatment decision is stale: {decision.beat_id}",
                    )
                )
            for layer in (
                decision.broll,
                decision.camera,
                decision.transition,
                decision.sfx,
                decision.motion_graphics,
            ):
                if layer.state == "needs_review":
                    findings.append(
                        DirectionLintFinding(
                            severity="error",
                            code="treatment_needs_review",
                            message=(
                                f"{layer.layer} treatment needs asset or operator review "
                                f"on beat {decision.beat_id}"
                            ),
                        )
                    )
        if document.direction_recipe_version == "direction-v3":
            try:
                from clipforge.editorial.presets import PresetCatalog, PresetCatalogError

                preset_id = document.preset_id or "clean_explainer"
                policy = PresetCatalog.load().find(preset_id).treatment_policy
                findings.extend(evaluate_treatment_policy(selected, policy))
                selected_layers = [
                    layer
                    for decision in selected.treatment_decisions
                    for layer in (
                        decision.broll,
                        decision.camera,
                        decision.transition,
                        decision.sfx,
                        decision.motion_graphics,
                    )
                ]
                policy_modes = {
                    "broll": policy.broll.mode,
                    "camera": policy.camera.mode,
                    "transition": policy.transitions.mode,
                    "sfx": policy.sfx.mode,
                    "motion_graphics": policy.motion_graphics,
                }
                for layer in selected_layers:
                    if layer.state == "use" and policy_modes[layer.layer] == "blocked":
                        findings.append(
                            DirectionLintFinding(
                                severity="error",
                                code="treatment_policy_conflict",
                                message=f"{layer.layer} is used while the selected preset blocks it",
                            )
                        )
                for decision in selected.treatment_decisions:
                    if decision.broll.state == "use" and decision.visual_evidence is not None:
                        if decision.visual_evidence.relevance_status != "related":
                            findings.append(
                                DirectionLintFinding(
                                    severity="error",
                                    code="broll_relevance_unproven",
                                    message=f"B-roll relevance is not proven on beat {decision.beat_id}",
                                )
                            )
                        if decision.visual_evidence.collision_status == "blocked":
                            findings.append(
                                DirectionLintFinding(
                                    severity="error",
                                    code="treatment_collision_blocked",
                                    message=f"visual collision blocks treatment on beat {decision.beat_id}",
                                )
                            )
                    beat_by_id = {beat.beat_id: beat for beat in selected.beats}
                    if (
                        policy.sfx.forbid_on_continuous_dialogue
                        and decision.sfx.state == "use"
                        and beat_by_id.get(decision.beat_id) is not None
                        and beat_by_id[decision.beat_id].kind == "body"
                    ):
                        findings.append(
                            DirectionLintFinding(
                                severity="error",
                                code="preset_sfx_continuous_dialogue",
                                message=f"SFX is not allowed on continuous dialogue beat {decision.beat_id}",
                            )
                        )
                if len(selected.camera_motion) > policy.camera.max_events:
                    findings.append(
                        DirectionLintFinding(
                            severity="error",
                            code="preset_camera_density_high",
                            message="camera events exceed the selected preset policy",
                        )
                    )
                if len(selected.camera_motion) < policy.camera.min_events:
                    intentional_camera_omission = all(
                        decision.camera.state in {"omit_with_reason", "blocked_by_policy"}
                        for decision in selected.treatment_decisions
                    )
                    if not intentional_camera_omission:
                        findings.append(
                            DirectionLintFinding(
                                severity="error",
                                code="preset_camera_minimum_missing",
                                message="camera events do not meet the selected preset minimum",
                            )
                        )
                for event in selected.camera_motion:
                    scale_delta = abs(event.scale_end_permille - event.scale_start_permille) / 1000
                    if scale_delta > policy.camera.max_scale_delta:
                        findings.append(
                            DirectionLintFinding(
                                severity="error",
                                code="preset_camera_scale_exceeded",
                                message=f"camera event exceeds preset scale delta: {event.motion_id}",
                            )
                        )
                    if event.travel_px > policy.camera.max_subject_drift_px:
                        findings.append(
                            DirectionLintFinding(
                                severity="error",
                                code="preset_camera_drift_exceeded",
                                message=f"camera event exceeds preset subject drift: {event.motion_id}",
                            )
                        )
                if len(selected.transitions) > policy.transitions.max_per_30s:
                    findings.append(
                        DirectionLintFinding(
                            severity="error",
                            code="preset_transition_density_high",
                            message="transition events exceed the selected preset policy",
                        )
                    )
                used_broll = [decision.broll.state == "use" for decision in selected.treatment_decisions]
                consecutive = 0
                for uses_broll in used_broll:
                    consecutive = consecutive + 1 if uses_broll else 0
                    if consecutive > policy.broll.max_consecutive_beats:
                        findings.append(
                            DirectionLintFinding(
                                severity="error",
                                code="preset_broll_consecutive_limit",
                                message="B-roll exceeds the selected preset consecutive-beat limit",
                            )
                        )
                        break
                audio_placements = [item for item in selected.asset_placements if item.kind == "audio"]
                if len(audio_placements) > policy.sfx.max_cues_per_30s:
                    findings.append(
                        DirectionLintFinding(
                            severity="error",
                            code="preset_sfx_density_high",
                            message="SFX placements exceed the selected preset policy",
                        )
                    )
                for placement in audio_placements:
                    if placement.gain_db is not None and placement.gain_db > policy.sfx.max_gain_db:
                        findings.append(
                            DirectionLintFinding(
                                severity="error",
                                code="preset_sfx_gain_exceeded",
                                message=f"SFX placement exceeds preset gain limit: {placement.placement_id}",
                            )
                        )
                request_by_id = {
                    request.request_id: request
                    for decision in selected.treatment_decisions
                    for request in decision.asset_requests
                }
                for placement in selected.asset_placements:
                    if placement.request_id is None:
                        findings.append(
                            DirectionLintFinding(
                                severity="error",
                                code="asset_request_binding_missing",
                                message=(
                                    "asset placement is not bound to a treatment request: "
                                    f"{placement.placement_id}"
                                ),
                            )
                        )
                        continue
                    request = request_by_id.get(placement.request_id)
                    if request is None:
                        findings.append(
                            DirectionLintFinding(
                                severity="error",
                                code="asset_request_unknown",
                                message=(
                                    "asset placement references an unknown treatment request: "
                                    f"{placement.request_id}"
                                ),
                            )
                        )
                    elif request.status != "acquired" or placement.asset_status != "acquired":
                        findings.append(
                            DirectionLintFinding(
                                severity="error",
                                code="asset_request_not_acquired",
                                message=f"asset request is not acquired: {request.request_id}",
                            )
                        )
            except PresetCatalogError as exc:
                findings.append(
                    DirectionLintFinding(
                        severity="error",
                        code="treatment_policy_invalid",
                        message=str(exc),
                    )
                )
    if document.motion_catalog_sha256 is not None or selected.motion_recipe_ids:
        try:
            from clipforge.editorial.motion_catalog import MotionCatalog, MotionCatalogError

            catalog = MotionCatalog.load()
            if document.motion_catalog_sha256 != catalog.fingerprint():
                findings.append(
                    DirectionLintFinding(
                        severity="error",
                        code="motion_catalog_stale",
                        message="direction is bound to a stale motion catalog",
                    )
                )
            for recipe_id in selected.motion_recipe_ids:
                recipe = catalog.find(recipe_id)
                if recipe.state != "approved":
                    findings.append(
                        DirectionLintFinding(
                            severity="error",
                            code="motion_recipe_not_approved",
                            message=f"motion recipe is not approved: {recipe_id}",
                        )
                    )
        except MotionCatalogError as exc:
            findings.append(
                DirectionLintFinding(severity="error", code="motion_catalog_invalid", message=str(exc))
            )
    layer_count = len(selected.motion_graphics) + len(selected.asset_placements)
    if layer_count > 4:
        findings.append(
            DirectionLintFinding(
                severity="error",
                code="effect_density_high",
                message="selected direction has more than four optional graphic or asset layers",
            )
        )
    elif layer_count == 0:
        findings.append(
            DirectionLintFinding(
                severity="info",
                code="optional_layers_omitted",
                message="direction uses captions and source picture without optional assets or graphics",
            )
        )
    if document.direction_recipe_version == "direction-v2" and not (
        selected.motion_graphics or selected.asset_placements or selected.camera_motion or selected.transitions
    ):
        findings.append(
            DirectionLintFinding(
                severity="error",
                code="direction_layers_missing",
                message=(
                    "clean direction requires at least one purposeful camera, graphic, "
                    "asset, or transition layer"
                ),
            )
        )
    if len(selected.camera_motion) > 4:
        findings.append(
            DirectionLintFinding(
                severity="error",
                code="camera_density_high",
                message="selected direction has more than four camera moves",
            )
        )
    if len(selected.transitions) > 3:
        findings.append(
            DirectionLintFinding(
                severity="error",
                code="transition_density_high",
                message="selected direction has more than three transitions",
            )
        )
    if (
        selected.context_line is not None
        and selected.context_line.interval.output_end_us != time_map.to_time_map().total_output_duration()
    ):
        findings.append(
            DirectionLintFinding(
                severity="error",
                code="context_line_not_full_duration",
                message="context line must cover the complete approved output",
            )
        )
    if selected.source_native_text_status == "unavailable":
        findings.append(
            DirectionLintFinding(
                severity="warning",
                code="source_native_text_unreviewed",
                message="source-native text was not reviewed; optional typography may need human inspection",
            )
        )
    unique_findings: list[DirectionLintFinding] = []
    seen_findings: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding.code, finding.message)
        if key not in seen_findings:
            seen_findings.add(key)
            unique_findings.append(finding)
    return DirectionLintReport(
        direction_id=document.direction_id,
        direction_sha256=direction_sha256,
        status="fail" if any(item.severity == "error" for item in unique_findings) else "pass",
        findings=unique_findings,
    )
