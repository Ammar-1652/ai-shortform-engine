"""Advanced Hero commands. They do not replace Hero draft v1 and they do not publish."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import TypeAdapter, ValidationError

from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.schemas.advanced import AdvancedHeroProfile, ReframingStrategy, ReframingWindow
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
        str,
        typer.Option("--reframing", help="auto, contain, center_crop, face_follow, or manual_window."),
    ] = "contain",
    focus_x: Annotated[
        int | None, typer.Option("--focus-x", min=0, help="Manual crop focus x in visual pixels.")
    ] = None,
    focus_y: Annotated[
        int | None, typer.Option("--focus-y", min=0, help="Manual crop focus y in visual pixels.")
    ] = None,
    manual_windows_file: Annotated[
        Path | None,
        typer.Option(
            "--manual-windows-file",
            help="JSON array of reviewed ReframingWindow records for a moving subject.",
        ),
    ] = None,
    editorial_arc_file: Annotated[
        Path | None,
        typer.Option(
            "--editorial-arc-file",
            help="Source-grounded hook/body/punch arc JSON with an ordered TimeMap.",
        ),
    ] = None,
    draft_only: Annotated[
        bool,
        typer.Option(
            "--draft-only",
            help="Build an unapproved review draft; delivery remains blocked until Hero approval.",
        ),
    ] = False,
) -> None:
    """Write an advanced plan for one approved Hero candidate."""
    from clipforge.hero.advanced_service import (
        _context,
        choose_auto_reframing_strategy,
        default_advanced_profile,
        plan_advanced_candidate,
    )
    from clipforge.hero.editorial_arc import load_editorial_arc

    try:
        database = Database(resolve_db_path(db))
        root = resolve_work_dir(work_dir)
        context = None
        editorial_arc = None
        editorial_arc_sha256 = ""
        if editorial_arc_file is not None:
            context = _context(
                database,
                source_asset_id,
                candidate_id,
                root,
                require_hero_approval=not draft_only,
            )
            editorial_arc, editorial_arc_sha256 = load_editorial_arc(editorial_arc_file.resolve())
        if reframing == "auto":
            context = context or _context(
                database,
                source_asset_id,
                candidate_id,
                root,
                require_hero_approval=not draft_only,
            )
            selected_strategy = choose_auto_reframing_strategy(
                database=database,
                context=context,
                candidate_id=candidate_id,
                review_only=draft_only,
                actor="clipforge",
            )
            selected_reframing = TypeAdapter(ReframingStrategy).validate_python(
                {"strategy_id": selected_strategy}
            )
            active = default_advanced_profile().model_copy(update={"reframing": selected_reframing})
        else:
            profile = _profile(reframing)
            active = profile or default_advanced_profile()
        if reframing == "manual_window":
            if manual_windows_file is not None and (focus_x is not None or focus_y is not None):
                raise ClipforgeError("choose --manual-windows-file or --focus-x/--focus-y, not both")
            context = _context(
                database,
                source_asset_id,
                candidate_id,
                root,
                require_hero_approval=not draft_only,
            )
            visual_width = context.visual.proxy_width
            visual_height = context.visual.proxy_height
            if manual_windows_file is not None:
                if manual_windows_file.is_symlink() or not manual_windows_file.is_file():
                    raise ClipforgeError("manual window file must be a regular, non-symlink JSON file")
                try:
                    payload = json.loads(manual_windows_file.read_text(encoding="utf-8"))
                    windows = TypeAdapter(list[ReframingWindow]).validate_python(payload)
                except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
                    raise ClipforgeError(f"invalid manual window file: {exc}") from exc
                if not windows:
                    raise ClipforgeError("manual window file must contain at least one reviewed window")
                active = default_advanced_profile().model_copy(
                    update={
                        "reframing": ReframingStrategy(strategy_id="manual_window"),
                        "manual_windows": windows,
                    }
                )
            else:
                if focus_x is None or focus_y is None:
                    raise ClipforgeError("manual_window requires --focus-x/--focus-y or --manual-windows-file")
                crop_width, crop_height = _portrait_crop_size(visual_width, visual_height)
                if focus_x >= visual_width or focus_y >= visual_height:
                    raise ClipforgeError("manual crop focus must fall inside the visual frame")
                crop_x = min(max(0, focus_x - crop_width // 2), visual_width - crop_width)
                crop_y = min(max(0, focus_y - crop_height // 2), visual_height - crop_height)
                end_us = context.hero_plan.edit_plan.time_map.to_time_map().total_output_duration()
                manual = ReframingWindow(
                    window_id=f"manual-{candidate_id}",
                    strategy_id=ReframingStrategy(strategy_id="manual_window"),
                    output_start_us=0,
                    output_end_us=end_us,
                    source_x=crop_x,
                    source_y=crop_y,
                    source_width=crop_width,
                    source_height=crop_height,
                    frame_width=visual_width,
                    frame_height=visual_height,
                )
                active = default_advanced_profile().model_copy(
                    update={
                        "reframing": ReframingStrategy(strategy_id="manual_window"),
                        "manual_window": manual,
                    }
                )
        if active.renderer_recipe_version != "advanced-hero-renderer-v1":
            context = context or _context(
                database,
                source_asset_id,
                candidate_id,
                root,
                require_hero_approval=not draft_only,
            )
            direction_path = (
                context.workspace.advanced_review_direction_file(candidate_id)
                if draft_only
                else context.workspace.direction_file(candidate_id)
            )
            if direction_path.is_symlink() or not direction_path.is_file():
                raise ClipforgeError(
                    "clean Advanced Hero planning requires a validated direction brief; "
                    "run `clipforge hero advanced direction plan` first"
                )
        plan = plan_advanced_candidate(
            database=database,
            source_asset_id=source_asset_id,
            candidate_id=candidate_id,
            work_root=root,
            broll_asset_ids=broll,
            sfx_asset_ids=sfx,
            profile=active,
            editorial_arc=editorial_arc,
            editorial_arc_sha256=editorial_arc_sha256,
            allow_unapproved=draft_only,
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"plan_id: {plan.plan_id}")
    typer.echo(f"reframing: {plan.reframing_strategy}")
    typer.echo(f"applied: {plan.reframing_strategy}")
    if plan.editorial_arc_id:
        typer.echo(f"editorial_arc_id: {plan.editorial_arc_id}")
        typer.echo(f"editorial_arc_sha256: {plan.editorial_arc_sha256}")
    typer.echo("blocker: none")


def _portrait_crop_size(frame_width: int, frame_height: int) -> tuple[int, int]:
    """Largest integer multiple of 9:16 that fits inside the source frame."""
    scale = min(frame_width // 9, frame_height // 16)
    if scale < 1:
        raise ClipforgeError("source frame is too small for a portrait crop")
    return 9 * scale, 16 * scale


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
    draft_only: Annotated[
        bool,
        typer.Option(
            "--draft-only",
            help="Persist a direction for an unapproved review draft; production delivery remains blocked.",
        ),
    ] = False,
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
            allow_unapproved=draft_only,
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
    draft_only: Annotated[
        bool,
        typer.Option(
            "--draft-only",
            help="Verify a direction bound to an unapproved review draft.",
        ),
    ] = False,
) -> None:
    """Verify direction evidence and binding to the current promoted Hero plan."""
    from clipforge.hero.advanced_service import _context
    from clipforge.hero.direction_service import load_direction, validate_source_evidence
    from clipforge.hero.motion_style import style_for_id

    try:
        root = resolve_work_dir(work_dir)
        database = Database(resolve_db_path(db))
        context = _context(
            database,
            source_asset_id,
            candidate_id,
            root,
            require_hero_approval=not draft_only,
        )
        loaded = load_direction(context.workspace, candidate_id, review_only=draft_only)
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
    resume: Annotated[
        str | None,
        typer.Option("--resume", help="Resume a failed Advanced run by its advanced_set_id."),
    ] = None,
    draft_only: Annotated[
        bool,
        typer.Option(
            "--draft-only",
            help="Render an unapproved Advanced draft for joint review; never eligible for delivery.",
        ),
    ] = False,
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
            draft_only=draft_only,
            resume_advanced_set_id=resume,
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
    draft_only: Annotated[
        bool,
        typer.Option(
            "--draft-only",
            help="Verify the isolated review-only Advanced draft namespace.",
        ),
    ] = False,
) -> None:
    """Check the current advanced set. Does not write."""
    from clipforge.hero.advanced_service import verify_advanced

    try:
        verify_advanced(
            Database(resolve_db_path(db)),
            source_asset_id,
            resolve_work_dir(work_dir),
            review_only=draft_only,
        )
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
        return default_advanced_profile()
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
