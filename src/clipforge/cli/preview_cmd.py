"""Rough preview commands. They accept a source id, not a media path.

Captions stay provisional. The picture uses contain framing. This does not publish.
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
    "Build rough review previews from the current candidate set. "
    "Captions stay provisional. Edit scores do not change the picture."
)

preview_app = typer.Typer(no_args_is_help=True, help=_HELP)


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@preview_app.command("doctor")
def preview_doctor_command(
    work_dir: Annotated[
        Path | None,
        typer.Option("--work-dir", help="Work root used for the disk report."),
    ] = None,
) -> None:
    """Report preview recipe, browser, and tools. Does not launch a browser or render."""
    from clipforge.preview.doctor import doctor_status, format_doctor, preview_doctor

    lines = preview_doctor(resolve_work_dir(work_dir))
    typer.echo(format_doctor(lines))
    if doctor_status(lines) == "FAIL":
        raise typer.Exit(1)


@preview_app.command("render")
def preview_render(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id. Not a filesystem path.")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Ignore a valid preview cache and build again."),
    ] = False,
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Render rough previews for every selected candidate. Does not publish."""
    from clipforge.preview.service import render_previews

    try:
        result = render_previews(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
            force=force,
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"job_id: {result.job_id}")
    typer.echo(f"preview_set_id: {result.preview_set_id}")
    typer.echo(f"source_asset_id: {result.source_asset_id}")
    typer.echo(f"mining_id: {result.mining_id}")
    typer.echo(f"candidate_count: {result.candidate_count}")
    typer.echo(f"rendered_count: {result.rendered_count}")
    typer.echo(f"manifest_path: {result.manifest_path}")
    typer.echo(f"manifest_sha256: {result.manifest_sha256}")
    typer.echo(f"cache: {'hit' if result.cache_hit else 'miss'}")
    typer.echo(f"runtime_seconds: {result.runtime_seconds:.3f}")


@preview_app.command("list")
def preview_list(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """List the current rough previews. Does not render."""
    from clipforge.preview.show import format_preview_list, load_preview_document

    try:
        document = load_preview_document(
            Database(resolve_db_path(db)),
            source_asset_id,
            resolve_work_dir(work_dir),
        )
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(format_preview_list(document))


@preview_app.command("show")
def preview_show(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    candidate_id: Annotated[str, typer.Argument(help="Candidate id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Show one stored rough preview. Word timing remains provisional. Does not render."""
    from clipforge.preview.show import format_preview, load_preview_document

    try:
        document = load_preview_document(
            Database(resolve_db_path(db)),
            source_asset_id,
            resolve_work_dir(work_dir),
        )
        typer.echo(format_preview(document, candidate_id))
    except ClipforgeError as exc:
        _fail(exc)


@preview_app.command("verify")
def preview_verify(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Check the stored rough preview set. Read-only. Does not render or repair."""
    from clipforge.preview.verify import verify_preview

    report = verify_preview(
        database=Database(resolve_db_path(db)),
        source_asset_id=source_asset_id,
        work_root=resolve_work_dir(work_dir),
    )
    for line in report.lines:
        typer.echo(f"{line.status} {line.name}: {line.detail}")
    if report.status == "FAIL":
        raise typer.Exit(1)
