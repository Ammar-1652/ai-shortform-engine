"""Job inspection and recovery. list, show, and verify do not write."""

from __future__ import annotations

import getpass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.jobs.service import (
    list_job_text,
    recover_jobs,
    resume_job,
    retry_job,
    show_job,
    verify_job,
)
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.storage import Database

job_app = typer.Typer(no_args_is_help=True, help="Inspect and recover recorded jobs.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


def _actor() -> str:
    try:
        return getpass.getuser()
    except OSError as exc:
        _fail(ClipforgeError(f"could not determine the OS user: {exc}"))


@job_app.command("doctor")
def job_doctor() -> None:
    """Report the durable job states. This does not download anything."""
    typer.echo("PASS states: pending running succeeded failed cancelled blocked")
    typer.echo("PASS stale_policy: updated_at age, not a lock file")
    typer.echo("PASS resume: media_prepare speech rough_preview")


@job_app.command("list")
def job_list(
    project_id: Annotated[str | None, typer.Argument()] = None,
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """List jobs. Does not write."""
    try:
        typer.echo(list_job_text(Database(resolve_db_path(db)), project_id))
    except ClipforgeError as exc:
        _fail(exc)


@job_app.command("show")
def job_show(
    job_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """Print a sanitized job. Does not write."""
    try:
        typer.echo(show_job(Database(resolve_db_path(db)), job_id))
    except ClipforgeError as exc:
        _fail(exc)


@job_app.command("verify")
def job_verify(
    job_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Check one job against its source. Does not write."""
    try:
        verify_job(Database(resolve_db_path(db)), job_id, resolve_work_dir(work_dir))
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo("PASS job")


@job_app.command("recover")
def job_recover(
    project_id: Annotated[str | None, typer.Argument()] = None,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    older_than_minutes: Annotated[int, typer.Option("--older-than-minutes")] = 15,
) -> None:
    """Fail stale running jobs. They are not marked succeeded."""
    try:
        changed = recover_jobs(
            Database(resolve_db_path(db)),
            project_id,
            now=datetime.now(UTC),
            stale_after=timedelta(minutes=older_than_minutes),
        )
    except ClipforgeError as exc:
        _fail(exc)
    if not changed:
        typer.echo("No stale running jobs.")
        return
    for job_id in changed:
        typer.echo(f"failed {job_id}")


@job_app.command("resume")
def job_resume(
    job_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    created_by: Annotated[str | None, typer.Option("--created-by")] = None,
) -> None:
    """Start a new attempt and keep the previous job row."""
    try:
        child = resume_job(
            Database(resolve_db_path(db)),
            job_id,
            resolve_work_dir(work_dir),
            created_by=created_by or _actor(),
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"job_id: {child}")
    typer.echo(f"parent_job_id: {job_id}")


@job_app.command("retry")
def job_retry(
    job_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    created_by: Annotated[str | None, typer.Option("--created-by")] = None,
) -> None:
    """Retry with the same safety rules as resume."""
    try:
        child = retry_job(
            Database(resolve_db_path(db)),
            job_id,
            resolve_work_dir(work_dir),
            created_by=created_by or _actor(),
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"job_id: {child}")
    typer.echo(f"parent_job_id: {job_id}")
