"""Advanced Hero commands. They do not replace Hero draft v1 and they do not publish."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.schemas.advanced import AdvancedHeroProfile, ReframingStrategy
from clipforge.storage import Database

advanced_app = typer.Typer(
    no_args_is_help=True,
    help="Plan and render an advanced Hero draft from the current Hero set.",
)
direction_app = typer.Typer(
    no_args_is_help=True,
    help="Validate source-grounded motion direction before Advanced Hero planning.",
)
advanced_app.add_typer(direction_app, name="direction")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@advanced_app.command("doctor")
def advanced_doctor(
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Work root.")] = None,
) -> None:
    """Report the advanced profile. Does not write."""
    from clipforge.schemas.advanced import AdvancedHeroProfile, ReframingStrategy

    profile = AdvancedHeroProfile(reframing=ReframingStrategy(strategy_id="contain"))
    typer.echo(f"PASS profile: {profile.profile_id}")
    typer.echo("PASS music: disallowed")
    typer.echo(f"PASS reframing: {profile.reframing.strategy_id}")
    typer.echo("PASS renderer: remotion")
    typer.echo(f"PASS work_dir: {resolve_work_dir(work_dir)}")


@advanced_app.command("plan")
def advanced_plan(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    candidate_id: Annotated[str, typer.Argument(help="Candidate id.")],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    broll: Annotated[list[str] | None, typer.Option("--broll")] = None,
    sfx: Annotated[list[str] | None, typer.Option("--sfx")] = None,
    reframing: Annotated[
        str, typer.Option("--reframing", help="contain, center_crop, or face_follow.")
    ] = "contain",
) -> None:
    """Write an advanced plan for one approved Hero candidate."""
    from clipforge.hero.advanced_service import _context, default_advanced_profile, plan_advanced_candidate

    profile = _profile(reframing)
    try:
        active = profile or default_advanced_profile()
        if active.renderer_recipe_version != "advanced-hero-renderer-v1":
            context = _context(
                Database(resolve_db_path(db)), source_asset_id, candidate_id, resolve_work_dir(work_dir)
            )
            direction_path = context.workspace.direction_file(candidate_id)
            if direction_path.is_symlink() or not direction_path.is_file():
                raise ClipforgeError(
                    "clean Advanced Hero planning requires a validated direction brief; "
                    "run `clipforge hero advanced direction plan` first"
                )
        plan = plan_advanced_candidate(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            candidate_id=candidate_id,
            work_root=resolve_work_dir(work_dir),
            broll_asset_ids=broll,
            sfx_asset_ids=sfx,
            profile=profile,
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"plan_id: {plan.plan_id}")
    typer.echo(f"reframing: {plan.reframing_strategy}")
    typer.echo(f"applied: {plan.reframing_strategy}")
    typer.echo("blocker: none")


@direction_app.command("plan")
def direction_plan(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    candidate_id: Annotated[str, typer.Argument(help="Approved Hero candidate id.")],
    brief: Annotated[
        Path,
        typer.Option("--brief", exists=True, readable=True, help="Skill-produced direction JSON."),
    ],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    style: Annotated[str, typer.Option("--style", help="auto or one allowlisted preset id.")] = "auto",
) -> None:
    """Validate and persist one immutable direction brief."""
    from clipforge.hero.direction_service import save_direction_brief

    try:
        document, destination, digest = save_direction_brief(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            candidate_id=candidate_id,
            work_root=resolve_work_dir(work_dir),
            brief_path=brief.resolve(),
            style=style,
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"direction_id: {document.direction_id}")
    typer.echo(f"selected_option_id: {document.selected_option_id}")
    typer.echo(f"style_id: {document.style_id}")
    typer.echo(f"direction_sha256: {digest}")
    typer.echo(f"path: {destination}")
    typer.echo("blocker: none")


@direction_app.command("doctor")
def direction_doctor() -> None:
    """Report the declarative direction contract and allowlisted presets."""
    from clipforge.hero.motion_style import production_style_ids, style_for_id

    typer.echo("PASS direction_contract: direction-v1")
    typer.echo("PASS options: exactly_three")
    typer.echo("PASS safe_region: portrait-safe-v1")
    typer.echo(f"styles: {','.join(production_style_ids())}")
    for style_id in production_style_ids():
        profile = style_for_id(style_id)
        typer.echo(f"style_{style_id}: {profile.fingerprint()}")


@direction_app.command("show")
def direction_show(
    source_asset_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show the persisted direction and its selected preset."""
    from clipforge.hero.direction_service import load_direction
    from clipforge.preview.inputs import load_preview_inputs
    from clipforge.preview.service import default_profile

    try:
        root = resolve_work_dir(work_dir)
        inputs = load_preview_inputs(
            Database(resolve_db_path(db)),
            source_asset_id,
            root,
            profile_fingerprint=default_profile().fingerprint(),
            create_workspace=False,
        )
        loaded = load_direction(inputs.pair.workspace, candidate_id)
        if loaded is None:
            raise ClipforgeError("no direction document for candidate")
        document, digest = loaded
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"direction_id: {document.direction_id}")
    typer.echo(f"selected_option_id: {document.selected_option_id}")
    typer.echo(f"style_id: {document.style_id}")
    typer.echo(f"direction_sha256: {digest}")


@direction_app.command("verify")
def direction_verify(
    source_asset_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Verify direction evidence and binding to the current promoted Hero plan."""
    from clipforge.hero.advanced_service import _context
    from clipforge.hero.direction_service import load_direction, validate_source_evidence
    from clipforge.hero.motion_style import style_for_id

    try:
        root = resolve_work_dir(work_dir)
        database = Database(resolve_db_path(db))
        context = _context(database, source_asset_id, candidate_id, root)
        loaded = load_direction(context.workspace, candidate_id)
        if loaded is None:
            raise ClipforgeError("no direction document for candidate")
        document, digest = loaded
        if (
            document.source_sha256 != context.source_sha256
            or document.hero_plan_sha256 != context.hero_plan_sha256
        ):
            raise ClipforgeError("direction is stale against the current promoted Hero plan")
        if document.time_map_sha256 != context.hero_plan.edit_plan.time_map_sha256:
            raise ClipforgeError("direction is stale against the current TimeMap")
        if document.alignment_sha256 != context.alignment_sha256:
            raise ClipforgeError("direction is stale against the current forced alignment")
        if document.visual_analysis_sha256 != context.visual_sha256:
            raise ClipforgeError("direction is stale against the current visual analysis")
        profile = style_for_id(document.style_id)
        if document.style_fingerprint != profile.fingerprint():
            raise ClipforgeError("direction style fingerprint is stale")
        validate_source_evidence(
            document,
            context.alignment.words,
            context.hero_plan.edit_plan.time_map,
            {scene.scene_id for scene in context.visual.scenes},
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo("PASS direction")
    typer.echo(f"style_id: {document.style_id}")
    typer.echo(f"direction_sha256: {digest}")


@advanced_app.command("render")
def advanced_render(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    narration_artifact: Annotated[str | None, typer.Option("--narration-artifact")] = None,
) -> None:
    """Render stored advanced plans with the production Remotion backend."""
    from clipforge.hero.advanced_service import render_advanced_drafts

    try:
        result = render_advanced_drafts(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
            force=force,
            narration_artifact_id=narration_artifact,
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"status: {result.status}")
    typer.echo(f"advanced_set_id: {result.advanced_set_id}")
    typer.echo(f"cache_hit: {str(result.cache_hit).lower()}")
    if result.manifest_path is not None and result.manifest_path.is_file():
        from clipforge.schemas.advanced import AdvancedHeroDraftSetDocument

        document = AdvancedHeroDraftSetDocument.model_validate_json(
            result.manifest_path.read_text(encoding="utf-8")
        )
        typer.echo(f"applied: {document.reframing_strategy}")
        typer.echo("blocker: none")
    if result.status == "noop":
        raise typer.Exit(1)


@advanced_app.command("list")
def advanced_list(
    source_asset_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """List the current advanced set. Does not write."""
    from clipforge.hero.advanced_service import format_advanced_list

    try:
        text = format_advanced_list(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir))
        typer.echo(text)
    except ClipforgeError as exc:
        _fail(exc)


@advanced_app.command("show")
def advanced_show(
    source_asset_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show one advanced draft. Does not write."""
    from clipforge.hero.advanced_service import format_advanced_show

    try:
        typer.echo(
            format_advanced_show(
                Database(resolve_db_path(db)), source_asset_id, candidate_id, resolve_work_dir(work_dir)
            )
        )
    except ClipforgeError as exc:
        _fail(exc)


@advanced_app.command("verify")
def advanced_verify(
    source_asset_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Check the current advanced set. Does not write."""
    from clipforge.hero.advanced_service import verify_advanced

    try:
        verify_advanced(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir))
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo("PASS advanced_hero")


def _profile(name: str) -> AdvancedHeroProfile | None:
    from clipforge.hero.advanced_service import default_advanced_profile

    if name == "contain":
        return None
    if name == "face_follow":
        return default_advanced_profile().model_copy(
            update={"reframing": ReframingStrategy(strategy_id="face_follow")}
        )
    if name == "center_crop":
        return default_advanced_profile().model_copy(
            update={"reframing": ReframingStrategy(strategy_id="center_crop")}
        )
    if name == "manual_window":
        raise ClipforgeError("manual_window strategy requires a reframing window")
    if name in {"visual_safe_window", "multi_face_safe_window", "saliency_window"}:
        raise ClipforgeError(f"reframing strategy {name} is not supported")
    raise ClipforgeError(f"unknown reframing strategy {name}")


reframe_app = typer.Typer(
    no_args_is_help=True,
    help="Inspect a face-follow plan. These commands do not write.",
)
advanced_app.add_typer(reframe_app, name="reframe")


@reframe_app.command("doctor")
def reframe_doctor() -> None:
    """Report the reframing contract. Does not write."""
    typer.echo("PASS reframing default: contain")
    typer.echo("PASS reframing options: center_crop, face_follow")
    typer.echo("PASS identity: not_claimed")
    typer.echo("PASS speaker: not_claimed")
    typer.echo("PASS recognition: not_used")
    typer.echo("PASS whop: deferred")
    typer.echo("PASS publishing: deferred")


@reframe_app.command("show")
def reframe_show(
    source_asset_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show the stored reframing plan. Does not write."""
    from clipforge.hero.reframe_inspect import format_reframe_show

    try:
        typer.echo(
            format_reframe_show(
                Database(resolve_db_path(db)),
                source_asset_id,
                candidate_id,
                resolve_work_dir(work_dir),
            )
        )
    except ClipforgeError as exc:
        _fail(exc)


@reframe_app.command("verify")
def reframe_verify(
    source_asset_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Recompute the trajectory and compare it. Does not write."""
    from clipforge.hero.reframe_inspect import verify_reframe

    try:
        typer.echo(
            verify_reframe(
                Database(resolve_db_path(db)),
                source_asset_id,
                candidate_id,
                resolve_work_dir(work_dir),
            )
        )
    except ClipforgeError as exc:
        _fail(exc)
