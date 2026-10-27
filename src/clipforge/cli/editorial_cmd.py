"""CLI for the local editorial knowledge and direction layer."""

from __future__ import annotations

import getpass
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn, cast

import typer
from pydantic import ValidationError

from clipforge.editorial.knowledge import (
    KnowledgeError,
    KnowledgeLibrary,
    admit_record_to_library,
    build_decision_trace,
    canonical_digest,
    default_library_path,
    load_context,
    resolve_conflict_in_library,
    write_context,
    write_decision_trace,
    write_feedback,
    write_knowledge_proposal,
)
from clipforge.editorial.motion_catalog import MotionCatalog, MotionCatalogError, default_motion_catalog_path
from clipforge.editorial.reference_analysis import (
    ReferenceAnalysisError,
    analyze_reference_file,
    load_reference_analysis,
    propose_style_card,
)
from clipforge.errors import ClipforgeError, MediaError
from clipforge.hero.direction_service import revise_direction_with_treatment_bindings
from clipforge.hero.treatment import summarize_treatment, treatment_fingerprint
from clipforge.hero.treatment_assets import (
    bind_acquired_request,
    bind_placement_to_request,
    observe_registered_visual_asset,
    persist_treatment_binding,
    select_treatment_request,
    verify_registered_treatment_asset,
)
from clipforge.hero.treatment_policy import evaluate_treatment_policy
from clipforge.schemas.direction import DirectionDocument
from clipforge.schemas.editorial_knowledge import (
    ContextFact,
    EditorialFeedback,
    EditorialGuidanceCard,
    EditorialStyleCard,
    KnowledgeEvaluationCase,
    KnowledgeSource,
    NarrativePattern,
    ReferenceObservation,
)
from clipforge.schemas.provenance import ArtifactProvenance

editorial_app = typer.Typer(no_args_is_help=True, help="Plan and inspect source-grounded editorial direction.")
knowledge_app = typer.Typer(no_args_is_help=True, help="Inspect the versioned editorial knowledge library.")
editorial_app.add_typer(knowledge_app, name="knowledge")
motion_app = typer.Typer(no_args_is_help=True, help="Inspect approved local Remotion motion recipes.")
editorial_app.add_typer(motion_app, name="motion")
reference_app = typer.Typer(no_args_is_help=True, help="Analyze authorized local reference media.")
editorial_app.add_typer(reference_app, name="reference")
direction_app = typer.Typer(
    no_args_is_help=True, help="Compare source-grounded direction options without rendering."
)
editorial_app.add_typer(direction_app, name="direction")
treatment_app = typer.Typer(
    no_args_is_help=True, help="Inspect and validate per-beat B-roll, SFX, camera, and transition treatment."
)
editorial_app.add_typer(treatment_app, name="treatment")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


def _load(config: Path | None) -> KnowledgeLibrary:
    return KnowledgeLibrary.load(config.resolve() if config is not None else default_library_path())


@editorial_app.command("doctor")
def editorial_doctor(
    config: Annotated[Path | None, typer.Option("--config", help="Knowledge library JSON path.")] = None,
) -> None:
    """Validate the local editorial knowledge release without writing."""
    try:
        library = _load(config)
        release = library.active_release()
    except (ClipforgeError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo("PASS editorial_knowledge")
    typer.echo(f"path: {library.path}")
    typer.echo(f"active_release: {release.release_id}")
    typer.echo(f"sources: {len(library.document.sources)}")
    typer.echo(f"guidance_cards: {len(library.document.guidance_cards)}")
    typer.echo(f"narrative_patterns: {len(library.document.narrative_patterns)}")
    typer.echo(f"style_cards: {len(library.document.style_cards)}")
    typer.echo(f"evaluation_cases: {len(library.document.evaluations)}")
    typer.echo("network: not_required")


@editorial_app.command("verify")
def editorial_verify(
    config: Annotated[Path | None, typer.Option("--config", help="Knowledge library JSON path.")] = None,
) -> None:
    """Verify knowledge records, references, and the active release."""
    try:
        library = _load(config)
        release = library.active_release()
    except (ClipforgeError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"PASS editorial_knowledge release={release.release_id}")


@knowledge_app.command("verify")
def knowledge_verify(
    config: Annotated[Path | None, typer.Option("--config", help="Knowledge library JSON path.")] = None,
) -> None:
    """Verify the knowledge library from its nested namespace."""
    editorial_verify(config=config)


@editorial_app.command("presets")
def editorial_presets(
    config: Annotated[Path | None, typer.Option("--config", help="Knowledge library JSON path.")] = None,
) -> None:
    """List narrative presets and active coordinated style cards."""
    from clipforge.editorial.presets import PresetCatalog, PresetCatalogError

    try:
        preset_catalog = PresetCatalog.load()
    except (ClipforgeError, PresetCatalogError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    for preset in preset_catalog.document.presets:
        typer.echo(
            json.dumps(
                {
                    "type": "narrative_preset",
                    "preset_id": preset.preset_id,
                    "narrative_structure": preset.narrative_structure,
                    "motion_recipe_ids": preset.motion_recipe_ids,
                    "caption_mode": preset.caption_mode,
                    "preset_sha256": preset.preset_sha256,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    try:
        library = _load(config)
    except (ClipforgeError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    for style in library.document.style_cards:
        if style.state == "active":
            typer.echo(
                json.dumps(
                    {
                        "style_card_id": style.style_card_id,
                        "name": style.name,
                        "confidence": style.confidence,
                        "caption_style_id": style.caption_style_id,
                        "narrative_pattern_ids": style.narrative_pattern_ids,
                        "motion_recipe_ids": style.motion_recipe_ids,
                        "limitations": style.limitations,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )


def _load_motion(config: Path | None) -> MotionCatalog:
    return MotionCatalog.load(config.resolve() if config is not None else default_motion_catalog_path())


@direction_app.command("compare")
def direction_compare(
    brief: Annotated[Path, typer.Argument(exists=True, readable=True, help="Validated direction JSON brief.")],
) -> None:
    """Compare three declarative options without changing or rendering them."""
    from clipforge.hero.direction_service import _editorial_score

    path = brief.absolute()
    if path.is_symlink() or not path.is_file():
        typer.echo("direction brief must be a regular file", err=True)
        raise typer.Exit(1)
    try:
        document = DirectionDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        typer.echo(f"invalid direction brief: {exc}", err=True)
        raise typer.Exit(1) from exc
    for rank, option in enumerate(
        sorted(document.options, key=lambda item: (-_editorial_score(item), item.option_id)),
        start=1,
    ):
        typer.echo(
            json.dumps(
                {
                    "rank": rank,
                    "option_id": option.option_id,
                    "style_id": option.style_id,
                    "submitted_score": option.selection_score,
                    "deterministic_score": round(_editorial_score(option), 6),
                    "hook_body_punch": [beat.kind for beat in option.beats],
                    "camera_motion": len(option.camera_motion),
                    "transitions": len(option.transitions),
                    "treatment_decisions": len(option.treatment_decisions),
                    "treatment_fingerprint": document.treatment_fingerprint,
                    "motion_graphics": len(option.motion_graphics),
                    "asset_placements": len(option.asset_placements),
                    "selection_reason": option.selection_reason,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )


def _load_treatment_direction(path: Path) -> DirectionDocument:
    if path.is_symlink() or not path.is_file():
        raise MediaError("treatment direction must be a regular file")
    try:
        return DirectionDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise MediaError(f"invalid treatment direction: {exc}") from exc


@treatment_app.command("doctor")
def treatment_doctor() -> None:
    """Verify typed treatment policies and report the current graphics flag."""
    from clipforge.editorial.presets import PresetCatalog, PresetCatalogError

    try:
        catalog = PresetCatalog.load()
    except (ClipforgeError, PresetCatalogError, ValidationError) as exc:
        _fail(exc)
    for preset in catalog.document.presets:
        policy = preset.treatment_policy
        typer.echo(
            json.dumps(
                {
                    "preset_id": preset.preset_id,
                    "beat_coverage": policy.beat_coverage,
                    "broll": policy.broll.mode,
                    "camera": policy.camera.mode,
                    "transitions": policy.transitions.mode,
                    "sfx": policy.sfx.mode,
                    "motion_graphics": policy.motion_graphics,
                },
                sort_keys=True,
            )
        )


@treatment_app.command("plan")
def treatment_plan(
    direction: Annotated[
        Path, typer.Argument(exists=True, readable=True, help="Treatment-aware direction JSON.")
    ],
) -> None:
    """Show the deterministic treatment plan and pending provider requests."""
    try:
        document = _load_treatment_direction(direction.absolute())
        selected = next(item for item in document.options if item.option_id == document.selected_option_id)
        summary = summarize_treatment(selected)
    except (ClipforgeError, ValidationError, ValueError) as exc:
        _fail(exc)
    typer.echo(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
    for decision in selected.treatment_decisions:
        for request in decision.asset_requests:
            typer.echo(
                json.dumps(
                    {"type": "asset_request", **request.model_dump(mode="json")},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )


@treatment_app.command("show")
def treatment_show(
    direction: Annotated[
        Path, typer.Argument(exists=True, readable=True, help="Treatment-aware direction JSON.")
    ],
) -> None:
    """Print all selected per-beat treatment decisions without writing files."""
    try:
        document = _load_treatment_direction(direction.absolute())
        selected = next(item for item in document.options if item.option_id == document.selected_option_id)
    except (ClipforgeError, ValidationError, ValueError) as exc:
        _fail(exc)
    for decision in selected.treatment_decisions:
        typer.echo(json.dumps(decision.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))


@treatment_app.command("lint")
def treatment_lint(
    direction: Annotated[
        Path, typer.Argument(exists=True, readable=True, help="Treatment-aware direction JSON.")
    ],
) -> None:
    """Validate treatment coverage and dependency fingerprints without rendering."""
    try:
        document = _load_treatment_direction(direction.absolute())
        selected = next(item for item in document.options if item.option_id == document.selected_option_id)
        findings: list[dict[str, str]] = []
        if document.direction_recipe_version not in {"direction-v3", "direction-v4"}:
            findings.append(
                {"severity": "error", "code": "legacy_direction", "message": "direction-v3 is required"}
            )
        if len(selected.treatment_decisions) != len(selected.beats):
            findings.append(
                {"severity": "error", "code": "coverage_missing", "message": "every beat needs a decision"}
            )
        expected = treatment_fingerprint(selected)
        if document.treatment_fingerprint != expected:
            findings.append(
                {"severity": "error", "code": "fingerprint_stale", "message": "treatment fingerprint is stale"}
            )
        for decision in selected.treatment_decisions:
            if decision.dependency_fingerprint != document.treatment_fingerprint:
                findings.append({"severity": "error", "code": "decision_stale", "message": decision.beat_id})
            for layer in (
                decision.broll,
                decision.camera,
                decision.transition,
                decision.sfx,
                decision.motion_graphics,
            ):
                if layer.state == "needs_review":
                    findings.append(
                        {
                            "severity": "error",
                            "code": "needs_review",
                            "message": f"{decision.beat_id}:{layer.layer}",
                        }
                    )
        from clipforge.editorial.presets import PresetCatalog

        if document.direction_recipe_version in {"direction-v3", "direction-v4"}:
            preset_id = document.preset_id or "clean_explainer"
            policy = PresetCatalog.load().find(preset_id).treatment_policy
            findings.extend(
                item.model_dump(mode="json") for item in evaluate_treatment_policy(selected, policy)
            )
    except (ClipforgeError, ValidationError, ValueError) as exc:
        _fail(exc)
    typer.echo(json.dumps({"status": "fail" if findings else "pass", "findings": findings}, sort_keys=True))
    if findings:
        raise typer.Exit(1)


@treatment_app.command("bind-asset")
def treatment_bind_asset(
    request: Annotated[Path, typer.Argument(exists=True, readable=True, help="Treatment asset request JSON.")],
    placement: Annotated[Path, typer.Argument(exists=True, readable=True, help="Draft placement JSON.")],
    provider_response_sha256: Annotated[str, typer.Option("--provider-response-sha256")],
    selection_id: Annotated[str, typer.Option("--selection-id")],
    acquisition_id: Annotated[str, typer.Option("--acquisition-id")],
    license_evidence_sha256: Annotated[str, typer.Option("--license-evidence-sha256")],
    registered_asset_id: Annotated[str, typer.Option("--registered-asset-id")],
    registered_asset_sha256: Annotated[str, typer.Option("--registered-asset-sha256")],
    provider: Annotated[Literal["envato", "openverse", "local"], typer.Option("--provider")],
    project_id: Annotated[str, typer.Option("--project-id")],
    source_asset_id: Annotated[str, typer.Option("--source-asset-id")],
    media_kind: Annotated[Literal["graphic", "audio"], typer.Option("--media-kind")],
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    observation: Annotated[Path | None, typer.Option("--observation", exists=True, readable=True)] = None,
) -> None:
    """Bind verified provider/acquisition evidence to one treatment placement."""
    from clipforge.paths import resolve_db_path, resolve_work_dir
    from clipforge.schemas.direction import DirectionAssetPlacement
    from clipforge.schemas.treatment import TreatmentAssetRequest
    from clipforge.storage import Database

    try:
        request_doc = TreatmentAssetRequest.model_validate_json(request.read_text(encoding="utf-8"))
        placement_doc = DirectionAssetPlacement.model_validate_json(placement.read_text(encoding="utf-8"))
        selected = (
            select_treatment_request(
                request_doc,
                provider_response_sha256=provider_response_sha256,
                selection_id=selection_id,
            )
            if request_doc.status == "pending"
            else request_doc
        )
        if (
            selected.provider_response_sha256 != provider_response_sha256
            or selected.selection_id != selection_id
        ):
            raise MediaError("treatment selection evidence does not match the request")
        verification = verify_registered_treatment_asset(
            work_root=resolve_work_dir(work_dir),
            database=Database(resolve_db_path(db)),
            project_id=project_id,
            source_asset_id=source_asset_id,
            provider=provider,
            provider_response_sha256=provider_response_sha256,
            selection_id=selection_id,
            acquisition_id=acquisition_id,
            license_evidence_sha256=license_evidence_sha256,
            registered_asset_id=registered_asset_id,
            registered_asset_sha256=registered_asset_sha256,
            media_kind=media_kind,
        )
        acquired = bind_acquired_request(selected, verification=verification)
        bound = bind_placement_to_request(placement_doc, acquired)
        binding_path = persist_treatment_binding(
            work_root=resolve_work_dir(work_dir),
            request=acquired,
            placement=bound,
            verification=verification,
            source_asset_id=source_asset_id,
            observation_path=observation,
        )
    except (ClipforgeError, ValidationError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(
        json.dumps(
            {
                "request": acquired.model_dump(mode="json"),
                "placement": bound.model_dump(mode="json"),
                "binding_relative_path": binding_path.relative_to(resolve_work_dir(work_dir)).as_posix(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


@treatment_app.command("observe-asset")
def treatment_observe_asset(
    asset_id: Annotated[str, typer.Option("--asset-id")],
    project_id: Annotated[str, typer.Option("--project-id")],
    source_asset_id: Annotated[str, typer.Option("--source-asset-id")],
    output_start_us: Annotated[int, typer.Option("--output-start-us")],
    output_end_us: Annotated[int, typer.Option("--output-end-us")],
    source_evidence_id: Annotated[list[str], typer.Option("--source-evidence-id")],
    observed_label: Annotated[list[str], typer.Option("--observed-label")],
    relevance_score: Annotated[float, typer.Option("--relevance-score")],
    relevance_threshold: Annotated[float, typer.Option("--relevance-threshold")],
    reviewed_by: Annotated[str, typer.Option("--reviewed-by")],
    review_note: Annotated[str, typer.Option("--review-note")],
    source_in_us: Annotated[int, typer.Option("--source-in-us")] = 0,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """Decode and persist reviewed visual evidence for one registered asset."""
    from clipforge.paths import resolve_db_path, resolve_work_dir
    from clipforge.schemas.editorial import OutputInterval
    from clipforge.storage import Database

    try:
        path, observation = observe_registered_visual_asset(
            database=Database(resolve_db_path(db)),
            work_root=resolve_work_dir(work_dir),
            project_id=project_id,
            source_asset_id=source_asset_id,
            asset_id=asset_id,
            output_interval=OutputInterval(output_start_us=output_start_us, output_end_us=output_end_us),
            source_in_us=source_in_us,
            source_evidence_ids=source_evidence_id,
            observed_labels=observed_label,
            relevance_score=relevance_score,
            relevance_threshold=relevance_threshold,
            reviewed_by=reviewed_by,
            review_note=review_note,
        )
    except (ClipforgeError, ValidationError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(
        json.dumps(
            {
                "observation_id": observation.observation_id,
                "observation_relative_path": path.relative_to(resolve_work_dir(work_dir)).as_posix(),
                "media_sha256": observation.media_sha256,
                "relevance_score": observation.relevance_score,
            },
            sort_keys=True,
        )
    )


@treatment_app.command("revise-direction")
def treatment_revise_direction(
    candidate_id: Annotated[str, typer.Option("--candidate-id")],
    source_asset_id: Annotated[str, typer.Option("--source-asset-id")],
    binding: Annotated[
        list[Path], typer.Option("--binding", exists=True, readable=True, help="Verified binding sidecar.")
    ],
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    allow_unapproved: Annotated[bool, typer.Option("--allow-unapproved")] = False,
) -> None:
    """Publish a new immutable direction revision from verified bindings."""
    from clipforge.paths import resolve_db_path, resolve_work_dir
    from clipforge.storage import Database

    try:
        root = resolve_work_dir(work_dir).resolve()
        document, destination, digest = revise_direction_with_treatment_bindings(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            candidate_id=candidate_id,
            work_root=root,
            binding_paths=[path.absolute() for path in binding],
            allow_unapproved=allow_unapproved,
        )
    except (ClipforgeError, ValidationError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(
        json.dumps(
            {
                "direction_id": document.direction_id,
                "direction_recipe_version": document.direction_recipe_version,
                "direction_relative_path": destination.relative_to(root).as_posix(),
                "direction_sha256": digest,
            },
            sort_keys=True,
        )
    )


@motion_app.command("doctor")
def motion_doctor(
    config: Annotated[Path | None, typer.Option("--config", help="Motion catalog JSON path.")] = None,
) -> None:
    """Validate local motion references and Remotion component routes."""
    try:
        catalog = _load_motion(config)
    except (ClipforgeError, MotionCatalogError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo("PASS motion_catalog")
    typer.echo(f"path: {catalog.path}")
    typer.echo(f"references: {len(catalog.document.references)}")
    typer.echo(f"approved_recipes: {len(catalog.approved())}")
    typer.echo("network: not_required")


@motion_app.command("verify")
def motion_verify(
    config: Annotated[Path | None, typer.Option("--config", help="Motion catalog JSON path.")] = None,
) -> None:
    """Verify recipe provenance, component routes, and hashes."""
    try:
        catalog = _load_motion(config)
    except (ClipforgeError, MotionCatalogError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"PASS motion_catalog recipes={len(catalog.document.recipes)}")


@motion_app.command("list")
def motion_list(
    approved_only: Annotated[bool, typer.Option("--approved-only")] = False,
    config: Annotated[Path | None, typer.Option("--config", help="Motion catalog JSON path.")] = None,
) -> None:
    """List local motion recipes without rendering or writing."""
    try:
        catalog = _load_motion(config)
    except (ClipforgeError, MotionCatalogError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    recipes = catalog.approved() if approved_only else catalog.document.recipes
    for recipe in recipes:
        typer.echo(
            json.dumps(
                {
                    "recipe_id": recipe.recipe_id,
                    "state": recipe.state,
                    "component_id": recipe.component_id,
                    "fallback_component_id": recipe.fallback_component_id,
                    "purposes": [purpose.value for purpose in recipe.purposes],
                    "readability_risk": recipe.readability_risk,
                },
                sort_keys=True,
            )
        )


@motion_app.command("show")
def motion_show(
    recipe_id: Annotated[str, typer.Argument()],
    config: Annotated[Path | None, typer.Option("--config", help="Motion catalog JSON path.")] = None,
) -> None:
    """Show one validated local motion recipe."""
    try:
        recipe = _load_motion(config).find(recipe_id)
    except (ClipforgeError, MotionCatalogError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(recipe.model_dump_json(indent=2))


@editorial_app.command("analyze-reference")
def analyze_reference(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    permission: Annotated[
        str,
        typer.Option("--permission", help="analysis_allowed or reuse_allowed."),
    ] = "analysis_allowed",
    permission_evidence: Annotated[
        str,
        typer.Option("--permission-evidence"),
    ] = "operator authorized local reference",
    source_id: Annotated[str | None, typer.Option("--source-id")] = None,
) -> None:
    """Probe an authorized local reference and record measured facts plus unknowns."""
    try:
        if permission not in {"analysis_allowed", "reuse_allowed"}:
            raise ClipforgeError("permission must be analysis_allowed or reuse_allowed")
        document = analyze_reference_file(
            source,
            work_root=work_dir,
            permission=cast(Literal["analysis_allowed", "reuse_allowed"], permission),
            permission_evidence=permission_evidence,
            source_id=source_id,
        )
    except (ClipforgeError, ReferenceAnalysisError, ValidationError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"analysis_id: {document.analysis_id}")
    typer.echo(f"source_id: {document.source_id}")
    typer.echo(f"media_sha256: {document.media_sha256}")
    typer.echo(f"unknowns: {','.join(document.unknowns)}")


@reference_app.command("show")
def reference_show(
    analysis_file: Annotated[Path, typer.Argument(exists=True, readable=True)],
) -> None:
    """Show one verified reference analysis document."""
    try:
        document = load_reference_analysis(analysis_file.absolute())
    except (ClipforgeError, ReferenceAnalysisError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(document.model_dump_json(indent=2))


@reference_app.command("verify")
def reference_verify(
    analysis_file: Annotated[Path, typer.Argument(exists=True, readable=True)],
) -> None:
    """Verify one reference analysis without changing it."""
    try:
        document = load_reference_analysis(analysis_file.absolute())
    except (ClipforgeError, ReferenceAnalysisError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"PASS reference_analysis analysis_id={document.analysis_id}")


@reference_app.command("propose-style-card")
def reference_propose_style_card(
    analysis_file: Annotated[Path, typer.Argument(exists=True, readable=True)],
    style_card_id: Annotated[str, typer.Option("--style-card-id")],
    name: Annotated[str, typer.Option("--name")],
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Create a proposed style card from measured reference evidence."""
    try:
        analysis = load_reference_analysis(analysis_file.absolute())
        card, path = propose_style_card(
            analysis,
            style_card_id=style_card_id,
            name=name,
            work_root=work_dir,
        )
    except (ClipforgeError, ReferenceAnalysisError, ValidationError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"style_card_id: {card.style_card_id}")
    typer.echo(f"state: {card.state}")
    typer.echo(f"content_sha256: {card.content_sha256}")
    typer.echo(f"path: {path}")


@knowledge_app.command("list")
def knowledge_list(
    record_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            help="source, observation, evaluation, guidance, pattern, style, conflict, or release.",
        ),
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help="Knowledge library JSON path.")] = None,
) -> None:
    """List knowledge records as JSON lines without writing."""
    try:
        library = _load(config)
    except (ClipforgeError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    groups: dict[str, list[Any]] = {
        "source": library.document.sources,
        "observation": library.document.observations,
        "evaluation": library.document.evaluations,
        "guidance": library.document.guidance_cards,
        "pattern": library.document.narrative_patterns,
        "style": library.document.style_cards,
        "conflict": library.document.conflicts,
        "release": library.document.releases,
    }
    if record_type is not None and record_type not in groups:
        typer.echo(f"unknown knowledge type: {record_type}", err=True)
        raise typer.Exit(1)
    selected = groups.items() if record_type is None else [(record_type, groups[record_type])]
    for kind, records in selected:
        for record in records:
            payload = record.model_dump(mode="json")
            identifier = next(
                value for key, value in payload.items() if key.endswith("_id") and key != "schema_version"
            )
            typer.echo(
                json.dumps(
                    {"type": kind, "id": identifier, "state": payload.get("state")},
                    sort_keys=True,
                )
            )


@knowledge_app.command("show")
def knowledge_show(
    record_id: Annotated[str, typer.Argument(help="Knowledge record id.")],
    config: Annotated[Path | None, typer.Option("--config", help="Knowledge library JSON path.")] = None,
) -> None:
    """Show one validated knowledge record."""
    try:
        record = _load(config).find(record_id)
    except (ClipforgeError, ValidationError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(record.model_dump_json(indent=2))


@knowledge_app.command("intake")
def knowledge_intake(
    record_file: Annotated[Path, typer.Argument(exists=True, readable=True)],
    record_type: Annotated[
        str,
        typer.Option(
            "--type",
            help="source, observation, evaluation, guidance, pattern, or style.",
        ),
    ],
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Validate and persist an unadmitted knowledge record proposal."""
    types: dict[str, type[Any]] = {
        "source": KnowledgeSource,
        "observation": ReferenceObservation,
        "evaluation": KnowledgeEvaluationCase,
        "guidance": EditorialGuidanceCard,
        "pattern": NarrativePattern,
        "style": EditorialStyleCard,
    }
    model_type = types.get(record_type)
    if model_type is None:
        _fail(ClipforgeError(f"unsupported knowledge proposal type: {record_type}"))
    try:
        record = model_type.model_validate_json(record_file.absolute().read_text(encoding="utf-8"))
        destination = write_knowledge_proposal(record, record_type=record_type, work_root=work_dir)
    except (ClipforgeError, OSError, UnicodeError, ValidationError, ValueError) as exc:
        _fail(exc)
    typer.echo(f"proposal: {destination}")
    typer.echo("state: proposed")


@knowledge_app.command("admit")
def knowledge_admit(
    record_file: Annotated[Path, typer.Argument(exists=True, readable=True)],
    record_type: Annotated[str, typer.Option("--type")],
    release_id: Annotated[str, typer.Option("--release-id")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Append an evaluated record and create a new active knowledge release."""
    try:
        release = admit_record_to_library(
            config=config.absolute() if config is not None else default_library_path(),
            record_type=record_type,
            record_path=record_file,
            release_id=release_id,
        )
    except (ClipforgeError, OSError, UnicodeError, ValidationError, ValueError) as exc:
        _fail(exc)
    typer.echo(f"release_id: {release.release_id}")
    typer.echo(f"manifest_sha256: {release.manifest_sha256}")
    typer.echo("state: active")


@knowledge_app.command("evaluate")
def knowledge_evaluate(
    record_file: Annotated[Path, typer.Argument(exists=True, readable=True)],
    record_type: Annotated[str, typer.Option("--type")],
    evaluation_id: Annotated[list[str], typer.Option("--evaluation-id")],
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Attach evaluation cases and produce an evaluated proposal sidecar."""
    types: dict[str, type[Any]] = {
        "guidance": EditorialGuidanceCard,
        "pattern": NarrativePattern,
        "style": EditorialStyleCard,
    }
    model_type = types.get(record_type)
    if model_type is None:
        _fail(ClipforgeError("evaluation accepts guidance, pattern, or style records"))
    if not evaluation_id:
        _fail(ClipforgeError("at least one --evaluation-id is required"))
    try:
        record = model_type.model_validate_json(record_file.absolute().read_text(encoding="utf-8"))
        payload = record.model_dump(mode="json")
        payload["state"] = "evaluated"
        payload["evaluation_ids"] = sorted(set(evaluation_id))
        payload["content_sha256"] = "0" * 64
        evaluated = model_type.model_validate(payload)
        evaluated = evaluated.model_copy(
            update={"content_sha256": canonical_digest(evaluated, exclude="content_sha256")}
        )
        destination = write_knowledge_proposal(
            evaluated,
            record_type=record_type,
            work_root=work_dir,
            filename_prefix="evaluated",
        )
    except (ClipforgeError, OSError, UnicodeError, ValidationError, ValueError) as exc:
        _fail(exc)
    typer.echo(f"proposal: {destination}")
    typer.echo("state: evaluated")


@knowledge_app.command("conflicts")
def knowledge_conflicts(
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """List unresolved and resolved knowledge conflicts without writing."""
    try:
        library = _load(config)
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    for conflict in library.document.conflicts:
        typer.echo(
            json.dumps(
                {
                    "conflict_id": conflict.conflict_id,
                    "record_ids": conflict.record_ids,
                    "status": conflict.status,
                    "winning_record_id": conflict.winning_record_id,
                },
                sort_keys=True,
            )
        )


@knowledge_app.command("resolve")
def knowledge_resolve(
    conflict_id: Annotated[str, typer.Option("--conflict-id")],
    winning_record_id: Annotated[str, typer.Option("--winning-record-id")],
    resolution_note: Annotated[str, typer.Option("--resolution-note")],
    release_id: Annotated[str, typer.Option("--release-id")],
    config: Annotated[Path | None, typer.Option("--config")] = None,
) -> None:
    """Resolve a conflict and publish a new active knowledge release."""
    try:
        release = resolve_conflict_in_library(
            config=config.absolute() if config is not None else default_library_path(),
            conflict_id=conflict_id,
            winning_record_id=winning_record_id,
            resolution_note=resolution_note,
            resolved_by="codex_operator",
            release_id=release_id,
        )
    except (ClipforgeError, OSError, UnicodeError, ValidationError, ValueError) as exc:
        _fail(exc)
    typer.echo(f"release_id: {release.release_id}")
    typer.echo(f"manifest_sha256: {release.manifest_sha256}")
    typer.echo("state: active")


@knowledge_app.command("context")
def knowledge_context(
    project_id: Annotated[str, typer.Option("--project-id")],
    source_asset_id: Annotated[str, typer.Option("--source-asset-id")],
    candidate_id: Annotated[str, typer.Option("--candidate-id")],
    source_sha256: Annotated[str, typer.Option("--source-sha256")],
    language: Annotated[str, typer.Option("--language")],
    platform: Annotated[str, typer.Option("--platform")],
    fact: Annotated[list[str] | None, typer.Option("--fact", help="Verified fact text; repeatable.")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Retrieval tag; repeatable.")] = None,
    campaign_id: Annotated[str | None, typer.Option("--campaign-id")] = None,
    profile_id: Annotated[str | None, typer.Option("--profile-id")] = None,
    transcript_sha256: Annotated[str | None, typer.Option("--transcript-sha256")] = None,
    alignment_sha256: Annotated[str | None, typer.Option("--alignment-sha256")] = None,
    visual_analysis_sha256: Annotated[str | None, typer.Option("--visual-analysis-sha256")] = None,
    release_id: Annotated[str | None, typer.Option("--release-id")] = None,
    unknown: Annotated[
        list[str] | None,
        typer.Option("--unknown", help="Known missing evidence; repeatable."),
    ] = None,
    capability_id: Annotated[
        list[str] | None, typer.Option("--capability-id", help="Available Clipforge capability; repeatable.")
    ] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    config: Annotated[Path | None, typer.Option("--config", help="Knowledge library JSON path.")] = None,
) -> None:
    """Build and persist a hash-bound direction context for Codex."""
    try:
        now = datetime.now(UTC)
        provenance = ArtifactProvenance(
            created_at=now,
            created_by=getpass.getuser(),
            tool="clipforge editorial knowledge",
            tool_version="0.1.0",
            source_asset_ids=[source_asset_id],
        )
        facts = [
            ContextFact(
                fact_id=f"fact-{index}",
                kind="source",
                text=value,
                verified=True,
            )
            for index, value in enumerate(fact or [], start=1)
        ]
        if not facts:
            raise KnowledgeError("at least one --fact is required")
        bundle = _load(config).build_context(
            project_id=project_id,
            source_asset_id=source_asset_id,
            candidate_id=candidate_id,
            source_sha256=source_sha256,
            language=language,
            platform=platform,
            facts=facts,
            tags={value.strip() for value in (tag or []) if value.strip()},
            provenance=provenance,
            campaign_id=campaign_id,
            profile_id=profile_id,
            transcript_sha256=transcript_sha256,
            alignment_sha256=alignment_sha256,
            visual_analysis_sha256=visual_analysis_sha256,
            release_id=release_id,
            unknowns=unknown,
            capability_ids=capability_id,
        )
        path, digest = write_context(bundle, work_root=work_dir)
    except (ClipforgeError, ValidationError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"context_id: {bundle.context_id}")
    typer.echo(f"context_sha256: {bundle.context_sha256}")
    typer.echo(f"file_sha256: {digest}")
    typer.echo(f"path: {path}")


@knowledge_app.command("feedback")
def knowledge_feedback(
    plan_id: Annotated[str, typer.Option("--plan-id")],
    observation: Annotated[str, typer.Option("--observation")],
    kind: Annotated[str, typer.Option("--kind")],
    severity: Annotated[str, typer.Option("--severity")],
    reviewer_role: Annotated[str, typer.Option("--reviewer-role")],
    artifact_id: Annotated[str | None, typer.Option("--artifact-id")] = None,
    scene_id: Annotated[str | None, typer.Option("--scene-id")] = None,
    evidence_path: Annotated[
        list[str] | None, typer.Option("--evidence-path", help="Relative evidence path; repeatable.")
    ] = None,
    proposed_card_id: Annotated[
        list[str] | None, typer.Option("--proposed-card-id", help="Guidance card id; repeatable.")
    ] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Append feedback tied to an exact direction/render artifact."""
    try:
        feedback = EditorialFeedback(
            feedback_id=f"feedback-{uuid.uuid4()}",
            plan_id=plan_id,
            artifact_id=artifact_id,
            scene_id=scene_id,
            reviewer_role=cast(Literal["codex_operator", "human_reviewer"], reviewer_role),
            kind=cast(Literal["defect", "preference", "acceptance", "rejection", "performance"], kind),
            severity=cast(Literal["error", "warning", "info"], severity),
            observation=observation,
            evidence_paths=evidence_path or [],
            proposed_card_ids=proposed_card_id or [],
            created_at=datetime.now(UTC),
        )
        path = write_feedback(feedback, work_root=work_dir)
    except (ClipforgeError, ValidationError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"feedback_id: {feedback.feedback_id}")
    typer.echo(f"path: {path}")


@knowledge_app.command("trace")
def knowledge_trace(
    context_file: Annotated[Path, typer.Argument(exists=True, readable=True)],
    reason: Annotated[list[str], typer.Option("--reason", help="Why the chosen direction fits; repeatable.")],
    selected_guidance: Annotated[list[str] | None, typer.Option("--selected-guidance")] = None,
    selected_pattern: Annotated[list[str] | None, typer.Option("--selected-pattern")] = None,
    selected_style: Annotated[list[str] | None, typer.Option("--selected-style")] = None,
    selected_motion: Annotated[list[str] | None, typer.Option("--selected-motion")] = None,
    source_evidence: Annotated[list[str] | None, typer.Option("--source-evidence")] = None,
    deviation: Annotated[list[str] | None, typer.Option("--deviation")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Record Codex's selected guidance and rejected context alternatives."""
    try:
        context, _ = load_context(context_file.resolve())
        trace = build_decision_trace(
            context,
            reasons=reason,
            selected_guidance_ids=selected_guidance,
            selected_pattern_ids=selected_pattern,
            selected_style_card_ids=selected_style,
            selected_motion_recipe_ids=selected_motion,
            source_evidence_ids=source_evidence,
            deviations=deviation,
        )
        path, digest = write_decision_trace(trace, work_root=work_dir)
    except (ClipforgeError, ValidationError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"trace_id: {trace.trace_id}")
    typer.echo(f"trace_sha256: {digest}")
    typer.echo(f"path: {path}")
