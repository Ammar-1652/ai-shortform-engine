"""Readiness commands. list, show, verify, readiness, and doctor do not approve."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.benchmark.service import (
    doctor_text,
    list_runs,
    readiness_report,
    run_benchmark,
    show_run,
    verify_run,
)
from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.storage import Database

benchmark_app = typer.Typer(no_args_is_help=True, help="Record local readiness evidence.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@benchmark_app.command("doctor")
def benchmark_doctor() -> None:
    """Report the benchmark rules. This does not read a database."""
    typer.echo(doctor_text())


@benchmark_app.command("run")
def benchmark_run(
    source_id: Annotated[str, typer.Argument()],
    fixture_kind: Annotated[str, typer.Option("--fixture-kind")] = "deterministic_synthetic",
    candidate_id: Annotated[str | None, typer.Option("--candidate-id")] = None,
    voice_provider: Annotated[str, typer.Option("--voice-provider")] = "none",
    force: Annotated[bool, typer.Option("--force")] = False,
    execute: Annotated[bool, typer.Option("--execute")] = False,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Record one readiness pass. Missing approvals are blocked, not invented."""
    try:
        document = run_benchmark(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            source_id,
            fixture_kind=fixture_kind,
            candidate_id=candidate_id,
            voice_provider=voice_provider,
            force=force,
            execute=execute,
        )
    except (ClipforgeError, ValidationError, OSError) as exc:
        _fail(exc)
    typer.echo(f"benchmark_run_id: {document.benchmark_run_id}")
    typer.echo(f"readiness: {document.readiness}")


@benchmark_app.command("list")
def benchmark_list(
    project_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """List readiness records. Does not write."""
    try:
        rows = list_runs(Database(resolve_db_path(db)), project_id)
    except ClipforgeError as exc:
        _fail(exc)
    if not rows:
        typer.echo("No benchmark runs are stored.")
        return
    for item in rows:
        typer.echo(item)


@benchmark_app.command("show")
def benchmark_show(
    benchmark_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show one readiness record. Does not write."""
    try:
        typer.echo(show_run(Database(resolve_db_path(db)), resolve_work_dir(work_dir), benchmark_id))
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)


@benchmark_app.command("verify")
def benchmark_verify(
    benchmark_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Check one readiness record. Does not write."""
    try:
        typer.echo(verify_run(Database(resolve_db_path(db)), resolve_work_dir(work_dir), benchmark_id))
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)


@benchmark_app.command("readiness")
def benchmark_readiness(
    benchmark_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Explain what is still manual. Does not write."""
    try:
        report = readiness_report(Database(resolve_db_path(db)), resolve_work_dir(work_dir), benchmark_id)
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(report.model_dump_json())
