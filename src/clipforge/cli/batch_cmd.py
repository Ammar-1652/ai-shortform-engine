"""Batch commands. list, show, and verify do not write."""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.batch.service import list_batch, resume_batch, run_batch, show_batch, verify_batch
from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.storage import Database

batch_app = typer.Typer(no_args_is_help=True, help="Run several sources in one database.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


def _actor() -> str:
    try:
        return getpass.getuser()
    except OSError as exc:
        _fail(ClipforgeError(f"could not determine the OS user: {exc}"))


@batch_app.command("doctor")
def batch_doctor() -> None:
    """Report the batch rules. This does not download anything."""
    typer.echo("PASS concurrency: 1")
    typer.echo("PASS database: one sqlite file")
    typer.echo("PASS resume: failed blocked and cancelled children only")


@batch_app.command("run")
def batch_run(
    source_asset_ids: Annotated[list[str], typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    created_by: Annotated[str | None, typer.Option("--created-by")] = None,
    concurrency: Annotated[int, typer.Option("--concurrency")] = 1,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Prepare each source in order."""
    try:
        document = run_batch(
            database=Database(resolve_db_path(db)),
            source_asset_ids=source_asset_ids,
            work_root=resolve_work_dir(work_dir),
            created_by=created_by or _actor(),
            concurrency=concurrency,
            force=force,
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"batch_id: {document.batch_id}")
    typer.echo(f"status: {document.status}")
    if document.status != "succeeded":
        raise typer.Exit(1)


@batch_app.command("list")
def batch_list(
    batch_id: Annotated[str, typer.Argument()],
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Summarize a batch. Does not write."""
    try:
        typer.echo(list_batch(resolve_work_dir(work_dir), batch_id))
    except ClipforgeError as exc:
        _fail(exc)


@batch_app.command("show")
def batch_show(
    batch_id: Annotated[str, typer.Argument()],
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show a batch. Does not write."""
    try:
        typer.echo(show_batch(resolve_work_dir(work_dir), batch_id))
    except ClipforgeError as exc:
        _fail(exc)


@batch_app.command("verify")
def batch_verify(
    batch_id: Annotated[str, typer.Argument()],
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Check a batch manifest. Does not write."""
    try:
        verify_batch(resolve_work_dir(work_dir), batch_id)
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo("PASS batch")


@batch_app.command("resume")
def batch_resume(
    batch_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    created_by: Annotated[str | None, typer.Option("--created-by")] = None,
) -> None:
    """Rerun only failed, blocked, or cancelled children."""
    try:
        document = resume_batch(
            Database(resolve_db_path(db)),
            batch_id,
            resolve_work_dir(work_dir),
            created_by=created_by or _actor(),
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"batch_id: {document.batch_id}")
    typer.echo(f"status: {document.status}")
    if document.status != "succeeded":
        raise typer.Exit(1)
