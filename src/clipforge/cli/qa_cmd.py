"""QA commands. verify, list, and show only read. gate does not publish."""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.qa.service import gate_qa, list_qa, run_qa, show_qa, verify_qa
from clipforge.storage import Database

qa_app = typer.Typer(no_args_is_help=True, help="Run technical and campaign QA gates.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


def _actor() -> str:
    try:
        return getpass.getuser()
    except OSError as exc:
        _fail(ClipforgeError(f"could not determine the OS user for provenance: {exc}"))


@qa_app.command("doctor")
def qa_doctor() -> None:
    """Report the QA artifact kind and that a run needs an advanced Hero draft."""
    typer.echo("PASS artifact_kind: qa_set_json")
    typer.echo("PASS target: advanced_hero_draft_set_json")
    typer.echo("PASS gate: technical and campaign must both pass")


@qa_app.command("run")
def qa_run(
    source_asset_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Evaluate the current advanced Hero artifact and write a QA set."""
    try:
        result = run_qa(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
            created_by=_actor(),
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"qa_set_id: {result.qa_set_id}")
    typer.echo(f"artifact_id: {result.artifact_id}")
    typer.echo(f"profile_id: {result.profile_id}")
    typer.echo(f"status: {result.status}")
    typer.echo(f"manifest_sha256: {result.manifest_sha256}")
    if result.status != "pass":
        raise typer.Exit(1)


@qa_app.command("list")
def qa_list(
    source_asset_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Summarize the current QA set. Does not write."""
    try:
        typer.echo(list_qa(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir)))
    except ClipforgeError as exc:
        _fail(exc)


@qa_app.command("show")
def qa_show(
    source_asset_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Print sanitized QA evidence. Does not write."""
    try:
        typer.echo(show_qa(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir)))
    except ClipforgeError as exc:
        _fail(exc)


@qa_app.command("verify")
def qa_verify(
    source_asset_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Check the current QA set against live producers. Does not write."""
    try:
        verify_qa(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir))
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo("PASS qa")


@qa_app.command("gate")
def qa_gate_command(
    source_asset_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Succeed only when the current QA set passes both gates."""
    try:
        document = gate_qa(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir))
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"PASS qa gate {document.qa_set_id}")
