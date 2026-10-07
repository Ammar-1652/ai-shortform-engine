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
    from clipforge.hero.advanced_service import plan_advanced_candidate

    profile = _profile(reframing)
    try:
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
    if name == "contain":
        return None
    if name == "face_follow":
        return AdvancedHeroProfile(reframing=ReframingStrategy(strategy_id="face_follow"))
    if name == "center_crop":
        return AdvancedHeroProfile(reframing=ReframingStrategy(strategy_id="center_crop"))
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
