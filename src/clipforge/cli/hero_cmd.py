"""Hero draft commands. They accept a source id, not a media path.

Approval stays human. This does not publish.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.storage import Database

_HELP = (
    "Build Hero drafts from candidates approved on the current rough preview. "
    "Forced alignment stays on the selected clip."
)

hero_app = typer.Typer(no_args_is_help=True, help=_HELP)


def _register_review() -> None:
    from clipforge.cli.hero_advanced_cmd import advanced_app
    from clipforge.cli.hero_review_cmd import hero_review_app

    hero_app.add_typer(hero_review_app, name="review")
    hero_app.add_typer(advanced_app, name="advanced")


_register_review()


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@hero_app.command("doctor")
def hero_doctor_command(
    work_dir: Annotated[
        Path | None,
        typer.Option("--work-dir", help="Work root used for the disk report."),
    ] = None,
) -> None:
    """Report alignment tools and the Hero profile. Does not align or launch a browser."""
    from clipforge.hero.doctor import doctor_status, format_doctor, hero_doctor

    lines = hero_doctor(resolve_work_dir(work_dir))
    typer.echo(format_doctor(lines))
    if doctor_status(lines) == "FAIL":
        raise typer.Exit(1)


@hero_app.command("align")
def hero_align(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id. Not a filesystem path.")],
    candidate_id: Annotated[str, typer.Argument(help="Approved candidate id.")],
    allow_model_download: Annotated[
        bool,
        typer.Option("--allow-model-download", help="Permit fetching a missing alignment model."),
    ] = False,
    language: Annotated[
        str | None,
        typer.Option("--language", help="Requested locale. It must match the transcript language."),
    ] = None,
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Align one approved candidate clip. Does not align the rest of the source."""
    from clipforge.hero.service import align_hero_candidate

    try:
        document = align_hero_candidate(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            candidate_id=candidate_id,
            work_root=resolve_work_dir(work_dir),
            allow_model_download=allow_model_download,
            language=language,
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"alignment_id: {document.alignment_id}")
    typer.echo(f"candidate_id: {document.candidate_id}")
    typer.echo(f"model_name: {document.model_name}")
    typer.echo(f"whisperx_version: {document.whisperx_version}")
    typer.echo(f"locale: {document.locale}")
    typer.echo(f"alignment_status: {document.alignment_status}")
    typer.echo(f"word_count: {len(document.words)}")
    typer.echo("alignment_quality: forced")


@hero_app.command("plan")
def hero_plan(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id. Not a filesystem path.")],
    candidate_id: Annotated[str, typer.Argument(help="Approved candidate id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Write a Hero edit plan from stored forced alignment. Provisional timing is refused."""
    from clipforge.hero.plan import digest_plan
    from clipforge.hero.service import plan_hero_candidate

    try:
        document = plan_hero_candidate(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            candidate_id=candidate_id,
            work_root=resolve_work_dir(work_dir),
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"plan_id: {document.plan_id}")
    typer.echo(f"candidate_id: {document.edit_plan.candidate_id}")
    typer.echo("stage: hero")
    typer.echo(f"plan_sha256: {digest_plan(document)}")
    typer.echo(f"caption_count: {len(document.edit_plan.captions)}")
    typer.echo(f"motion_count: {len(document.edit_plan.motion_events)}")


@hero_app.command("render")
def hero_render(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id. Not a filesystem path.")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Ignore a valid Hero cache and build a new draft set."),
    ] = False,
    allow_model_download: Annotated[
        bool,
        typer.Option("--allow-model-download", help="Permit fetching a missing alignment model."),
    ] = False,
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Draft approved candidates in rank order. Does not publish."""
    from clipforge.hero.service import render_hero_drafts

    try:
        result = render_hero_drafts(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
            force=force,
            allow_model_download=allow_model_download,
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"status: {result.status}")
    typer.echo(f"job_id: {result.job_id or ''}")
    typer.echo(f"hero_set_id: {result.hero_set_id or ''}")
    typer.echo(f"source_asset_id: {result.source_asset_id}")
    typer.echo(f"rendered_count: {result.rendered_count}")
    typer.echo(f"manifest_path: {result.manifest_path or ''}")
    typer.echo(f"manifest_sha256: {result.manifest_sha256 or ''}")
    typer.echo(f"cache: {'hit' if result.cache_hit else 'miss'}")
    typer.echo(f"runtime_seconds: {result.runtime_seconds:.3f}")
    for candidate_id, reason in result.excluded:
        typer.echo(f"excluded: {candidate_id} {reason}")


@hero_app.command("list")
def hero_list(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """List the current Hero drafts. Does not align."""
    from clipforge.hero.show import format_hero_list, load_current_hero

    try:
        current = load_current_hero(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir))
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(format_hero_list(current))


@hero_app.command("show")
def hero_show(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    candidate_id: Annotated[str, typer.Argument(help="Candidate id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Show one stored Hero draft. Does not align."""
    from clipforge.hero.show import format_hero_show, load_current_hero

    try:
        current = load_current_hero(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir))
        typer.echo(format_hero_show(current, candidate_id))
    except ClipforgeError as exc:
        _fail(exc)


@hero_app.command("verify")
def hero_verify(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Check the stored Hero draft set. Read-only. Does not align or repair."""
    from clipforge.hero.verify import verify_hero

    report = verify_hero(
        database=Database(resolve_db_path(db)),
        source_asset_id=source_asset_id,
        work_root=resolve_work_dir(work_dir),
    )
    for line in report.lines:
        typer.echo(f"{line.status} {line.name}: {line.detail}")
    if report.status == "FAIL":
        raise typer.Exit(1)
