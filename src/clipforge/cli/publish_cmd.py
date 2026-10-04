"""Local delivery commands. External platform publishing is not implemented."""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.publish.errors import EXTERNAL_PUBLISHING, PublishError
from clipforge.publish.service import (
    doctor_ok,
    doctor_text,
    export_delivery,
    list_deliveries,
    plan_delivery,
    recover_delivery,
    resume_delivery,
    show_delivery,
    verify_delivery,
)
from clipforge.storage import Database

publish_app = typer.Typer(no_args_is_help=True, help="Export a verified local delivery package.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


def _actor() -> str:
    try:
        return getpass.getuser()
    except OSError as exc:
        _fail(ClipforgeError(f"could not determine the OS user for provenance: {exc}"))


def _destination(value: str) -> str:
    if value != "local":
        _fail(PublishError(EXTERNAL_PUBLISHING, category="unsupported_destination"))
    return value


@publish_app.command("doctor")
def publish_doctor() -> None:
    """Report the local exporter, filesystem policy, and ffprobe."""
    typer.echo(doctor_text())
    if not doctor_ok():
        raise typer.Exit(1)


@publish_app.command("plan")
def publish_plan(
    source_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    destination: Annotated[str, typer.Option("--destination")] = "local",
    narration_artifact: Annotated[str | None, typer.Option("--narration-artifact")] = None,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Run the read-only delivery preflight and print the plan."""
    _destination(destination)
    try:
        typer.echo(
            plan_delivery(
                Database(resolve_db_path(db)),
                resolve_work_dir(work_dir),
                source_id,
                candidate_id,
                destination=destination,
                include_narration=narration_artifact is not None,
                narration_artifact_id=narration_artifact,
            )
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)


@publish_app.command("export")
def publish_export(
    source_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    destination: Annotated[str, typer.Option("--destination")] = "local",
    narration_artifact: Annotated[str | None, typer.Option("--narration-artifact")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Copy the verified Advanced Hero into a local delivery package."""
    _destination(destination)
    try:
        result = export_delivery(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            source_id,
            candidate_id,
            destination=destination,
            include_narration=narration_artifact is not None,
            narration_artifact_id=narration_artifact,
            force=force,
            created_by=_actor(),
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"status: {result.status}")
    typer.echo(f"delivery_id: {result.delivery_id}")
    typer.echo(f"manifest_sha256: {result.manifest_sha256}")
    typer.echo(f"video_sha256: {result.video_sha256}")
    typer.echo(f"video_size: {result.video_size}")
    typer.echo(f"package: {result.relative_package}")
    if result.job_id is not None:
        typer.echo(f"job_id: {result.job_id}")
    if result.status not in {"succeeded", "cache_hit"}:
        raise typer.Exit(1)


@publish_app.command("list")
def publish_list(
    source_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """List local delivery packages. This does not write."""
    try:
        typer.echo(list_deliveries(Database(resolve_db_path(db)), resolve_work_dir(work_dir), source_id))
    except ClipforgeError as exc:
        _fail(exc)


@publish_app.command("show")
def publish_show(
    source_id: Annotated[str, typer.Argument()],
    delivery_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Print one delivery manifest. This does not write."""
    try:
        typer.echo(
            show_delivery(Database(resolve_db_path(db)), resolve_work_dir(work_dir), source_id, delivery_id)
        )
    except ClipforgeError as exc:
        _fail(exc)


@publish_app.command("verify")
def publish_verify(
    source_id: Annotated[str, typer.Argument()],
    delivery_id: Annotated[str, typer.Argument()],
    destination: Annotated[str, typer.Option("--destination")] = "local",
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Re-check one local package. This does not write."""
    _destination(destination)
    try:
        typer.echo(
            verify_delivery(
                Database(resolve_db_path(db)),
                resolve_work_dir(work_dir),
                source_id,
                delivery_id,
                destination=destination,
            )
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)


@publish_app.command("recover")
def publish_recover(
    source_id: Annotated[str, typer.Argument()],
    delivery_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Mark a stale running delivery failed without promoting it."""
    try:
        typer.echo(
            recover_delivery(Database(resolve_db_path(db)), resolve_work_dir(work_dir), source_id, delivery_id)
        )
    except ClipforgeError as exc:
        _fail(exc)


@publish_app.command("resume")
def publish_resume(
    source_id: Annotated[str, typer.Argument()],
    delivery_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Start a new attempt when the previous delivery is not a verified success."""
    try:
        result = resume_delivery(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            source_id,
            delivery_id,
            created_by=_actor(),
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"status: {result.status}")
    typer.echo(f"delivery_id: {result.delivery_id}")
    typer.echo(f"manifest_sha256: {result.manifest_sha256}")
    if result.status not in {"succeeded", "cache_hit"}:
        raise typer.Exit(1)
