"""Deterministic editorial direction lint before Advanced Hero planning."""

from __future__ import annotations

from collections.abc import Sequence

from clipforge.errors import MediaError
from clipforge.hero.direction_service import validate_source_evidence
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
    return DirectionLintReport(
        direction_id=document.direction_id,
        direction_sha256=direction_sha256,
        status="fail" if any(item.severity == "error" for item in findings) else "pass",
        findings=findings,
    )
