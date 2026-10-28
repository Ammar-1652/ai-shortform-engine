"""Shared deterministic checks for treatment-aware direction documents.

This module only evaluates declarative records. Provider acquisition, rendering,
and review remain owned by their existing boundaries.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from clipforge.errors import MediaError
from clipforge.schemas.direction import DirectionDocument, DirectionLintFinding, DirectionOption
from clipforge.schemas.editorial_preset import TreatmentPolicy


def evaluate_treatment_policy(
    option: DirectionOption,
    policy: TreatmentPolicy,
) -> list[DirectionLintFinding]:
    """Return stable policy findings shared by CLI, planning, and QA."""
    findings: list[DirectionLintFinding] = treatment_event_ownership(option)
    beats = {item.beat_id: item for item in option.beats}
    used_broll = [item for item in option.treatment_decisions if item.broll.state == "use"]
    if policy.broll.mode == "blocked" and used_broll:
        findings.append(_error("preset_broll_blocked", "B-roll is selected while the preset blocks B-roll"))
    if len(used_broll) < policy.broll.min_meaningful_beats:
        findings.append(
            _error(
                "preset_broll_minimum_missing",
                "B-roll use does not meet the selected preset meaningful-beat minimum",
            )
        )
    allowed_roles = set(policy.broll.roles)
    for decision in used_broll:
        if decision.broll.role not in allowed_roles:
            findings.append(
                _error("preset_broll_role_invalid", f"B-roll role is not allowed on beat {decision.beat_id}")
            )
        evidence = decision.visual_evidence
        if (
            evidence is None
            or evidence.relevance_status != "related"
            or evidence.relevance_score is None
            or evidence.relevance_score < policy.broll.relevance_threshold
        ):
            findings.append(
                _error("broll_relevance_unproven", f"B-roll relevance is unproven on beat {decision.beat_id}")
            )
        if evidence is not None and evidence.collision_status == "blocked":
            findings.append(
                _error("treatment_collision_blocked", f"visual collision blocks beat {decision.beat_id}")
            )

    consecutive = 0
    for decision in option.treatment_decisions:
        if decision.broll.state == "use":
            consecutive += 1
            if consecutive > policy.broll.max_consecutive_beats:
                findings.append(
                    _error("preset_broll_consecutive_limit", "B-roll exceeds the consecutive-beat limit")
                )
                break
        else:
            consecutive = 0

    if len(option.camera_motion) > policy.camera.max_events:
        findings.append(_error("preset_camera_density_high", "camera events exceed the selected preset policy"))
    if policy.camera.mode == "blocked" and option.camera_motion:
        findings.append(
            _error("preset_camera_blocked", "camera events are selected while the preset blocks camera motion")
        )
    if len(option.camera_motion) < policy.camera.min_events and not all(
        item.camera.state in {"omit_with_reason", "blocked_by_policy"} for item in option.treatment_decisions
    ):
        findings.append(
            _error("preset_camera_minimum_missing", "camera events do not meet the selected preset minimum")
        )
    for event in option.camera_motion:
        if abs(event.scale_end_permille - event.scale_start_permille) / 1000 > policy.camera.max_scale_delta:
            findings.append(
                _error("preset_camera_scale_exceeded", f"camera scale exceeds policy: {event.motion_id}")
            )
        if event.travel_px > policy.camera.max_subject_drift_px:
            findings.append(
                _error("preset_camera_drift_exceeded", f"camera drift exceeds policy: {event.motion_id}")
            )

    if len(option.transitions) > policy.transitions.max_per_30s:
        findings.append(
            _error("preset_transition_density_high", "transition events exceed the selected preset policy")
        )
    if policy.transitions.mode == "blocked" and option.transitions:
        findings.append(
            _error("preset_transitions_blocked", "transitions are selected while the preset blocks transitions")
        )
    for transition in option.transitions:
        if transition.interval.output_start_us == 0:
            findings.append(
                _error(
                    "transition_at_program_start",
                    f"transition starts at program start: {transition.transition_id}",
                )
            )
        if policy.transitions.forbid_on_word_boundary:
            if transition.cut_boundary_us is None:
                findings.append(
                    _error(
                        "transition_boundary_missing",
                        f"transition has no canonical cut boundary: {transition.transition_id}",
                    )
                )
            elif transition.cut_boundary_us != transition.interval.output_start_us:
                findings.append(
                    _error(
                        "transition_boundary_mismatch",
                        f"transition boundary does not match its output interval: {transition.transition_id}",
                    )
                )

    audio = [item for item in option.asset_placements if item.kind == "audio"]
    if len(audio) > policy.sfx.max_cues_per_30s:
        findings.append(_error("preset_sfx_density_high", "SFX placements exceed the selected preset policy"))
    if policy.sfx.mode == "blocked" and audio:
        findings.append(_error("preset_sfx_blocked", "SFX is selected while the preset blocks SFX"))
    for placement in audio:
        if placement.gain_db is not None and placement.gain_db > policy.sfx.max_gain_db:
            findings.append(
                _error("preset_sfx_gain_exceeded", f"SFX gain exceeds policy: {placement.placement_id}")
            )

    requests = {
        request.request_id: request
        for decision in option.treatment_decisions
        for request in decision.asset_requests
    }
    for placement in option.asset_placements:
        request = requests.get(placement.request_id or "")
        if request is None or request.status != "acquired" or placement.asset_status != "acquired":
            findings.append(
                _error(
                    "asset_request_not_acquired", f"asset placement is not acquired: {placement.placement_id}"
                )
            )
            continue
        if (
            request.registered_asset_id != placement.asset_id
            or request.provider_response_sha256 != placement.provider_response_sha256
            or request.selection_id != placement.selection_id
            or request.acquisition_id != placement.acquisition_id
            or request.license_evidence_sha256 != placement.license_evidence_sha256
            or request.registered_asset_sha256 != placement.registered_asset_sha256
        ):
            findings.append(
                _error(
                    "asset_request_binding_stale",
                    f"asset placement provenance is stale: {placement.placement_id}",
                )
            )

    for decision in option.treatment_decisions:
        if policy.sfx.forbid_on_continuous_dialogue and decision.sfx.state == "use":
            beat = beats.get(decision.beat_id)
            if beat is not None and beat.kind == "body":
                findings.append(
                    _error(
                        "preset_sfx_continuous_dialogue", f"SFX is not allowed on body beat {decision.beat_id}"
                    )
                )
        if decision.sfx.state == "use":
            if decision.sfx.duck_db < policy.sfx.speech_duck_db:
                findings.append(
                    _error(
                        "preset_sfx_duck_insufficient",
                        f"SFX ducking is below policy on beat {decision.beat_id}",
                    )
                )
            overlap_us = sum(
                item.interval.output_end_us - item.interval.output_start_us
                for item in audio
                if item.placement_id in decision.sfx.event_ids
            )
            if overlap_us > decision.sfx.max_overlap_us:
                findings.append(
                    _error(
                        "preset_sfx_overlap_exceeded",
                        f"SFX overlap exceeds its declared maximum on beat {decision.beat_id}",
                    )
                )
        if decision.motion_graphics.state == "use" and policy.motion_graphics == "disabled":
            findings.append(
                _error(
                    "preset_motion_graphics_blocked", f"motion graphics are disabled on beat {decision.beat_id}"
                )
            )
    if policy.motion_graphics == "disabled" and option.motion_graphics:
        findings.append(
            _error(
                "preset_motion_graphics_event_blocked",
                "motion-graphics events exist while the policy disables them",
            )
        )
    return _unique(findings)


def treatment_event_ownership(option: DirectionOption) -> list[DirectionLintFinding]:
    """Every planned event has exactly one use decision, including duplicates."""
    events = {
        "camera": [item.motion_id for item in option.camera_motion],
        "transition": [item.transition_id for item in option.transitions],
        "broll": [item.placement_id for item in option.asset_placements if item.kind == "graphic"],
        "sfx": [item.placement_id for item in option.asset_placements if item.kind == "audio"],
        "motion_graphics": [item.graphic_id for item in option.motion_graphics],
    }
    findings = []
    for layer_name, ids in events.items():
        owners = Counter(
            event_id
            for decision in option.treatment_decisions
            if (layer := getattr(decision, layer_name)).state == "use"
            for event_id in layer.event_ids
        )
        if any(count != 1 for count in Counter(ids).values()) or owners != Counter(ids):
            findings.append(
                _error(
                    f"{layer_name}_event_ownership_invalid",
                    f"Every {layer_name} event must have exactly one use decision and render once",
                )
            )
    return findings


def require_treatment_policy(document: DirectionDocument) -> list[DirectionLintFinding]:
    """Shared fail-closed policy gate; legacy recipes keep recorded behavior."""
    if document.direction_recipe_version not in {"direction-v3", "direction-v4"}:
        return []
    from clipforge.editorial.presets import PresetCatalog
    from clipforge.hero.treatment import treatment_fingerprint

    option = next(item for item in document.options if item.option_id == document.selected_option_id)
    digest = treatment_fingerprint(option)
    if digest != document.treatment_fingerprint or any(
        item.dependency_fingerprint != digest for item in option.treatment_decisions
    ):
        raise MediaError("treatment decision fingerprint is stale")
    if any(
        getattr(decision, layer).state == "needs_review"
        for decision in option.treatment_decisions
        for layer in ("camera", "transition", "broll", "sfx", "motion_graphics")
    ):
        raise MediaError("treatment asset or operator decision is unresolved")
    policy = PresetCatalog.load().find(document.preset_id or "clean_explainer").treatment_policy
    findings = evaluate_treatment_policy(option, policy)
    errors = [item for item in findings if item.severity == "error"]
    if errors:
        raise MediaError("treatment policy failed: " + "; ".join(item.code for item in errors))
    return findings


def _error(code: str, message: str) -> DirectionLintFinding:
    return DirectionLintFinding(severity="error", code=code, message=message)


def _unique(findings: Iterable[DirectionLintFinding]) -> list[DirectionLintFinding]:
    seen: set[tuple[str, str]] = set()
    result: list[DirectionLintFinding] = []
    for finding in findings:
        key = (finding.code, finding.message)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result
