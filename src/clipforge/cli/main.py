"""clipforge command line. Round 3 adds first-pass transcription of prepared ASR audio."""

from __future__ import annotations

import getpass
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge import __version__
from clipforge.cli.candidate_cmd import candidate_app
from clipforge.cli.hero_cmd import hero_app
from clipforge.cli.media_cmd import media_app
from clipforge.cli.preview_cmd import preview_app
from clipforge.cli.review_cmd import review_app
from clipforge.cli.source import source_app
from clipforge.cli.storage_cmd import storage_app
from clipforge.cli.transcript_cmd import transcript_app
from clipforge.cli.vision_cmd import vision_app
from clipforge.doctor import exit_code, format_report, run_checks
from clipforge.errors import ClipforgeError
from clipforge.paths import find_repo_root, resolve_db_path
from clipforge.schemas import Project, assert_schemas_current, export_schemas
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import Database, insert_project, list_projects

app = typer.Typer(
    name="clipforge",
    no_args_is_help=True,
    help="Local-first short-form production engine.",
)
project_app = typer.Typer(no_args_is_help=True, help="Create and list projects.")
db_app = typer.Typer(no_args_is_help=True, help="Initialize and inspect the SQLite database.")
schema_app = typer.Typer(no_args_is_help=True, help="Export or check JSON Schema contracts.")
app.add_typer(project_app, name="project")
app.add_typer(db_app, name="db")
app.add_typer(schema_app, name="schema")
app.add_typer(source_app, name="source")
app.add_typer(media_app, name="media")
app.add_typer(storage_app, name="storage")
app.add_typer(transcript_app, name="transcript")
app.add_typer(vision_app, name="vision")
app.add_typer(candidate_app, name="candidate")
app.add_typer(preview_app, name="preview")
app.add_typer(review_app, name="review")
app.add_typer(hero_app, name="hero")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Print the version."),
    ] = False,
) -> None:
    """Local-first short-form production engine."""


@app.command()
def doctor(
    work_dir: Annotated[
        Path | None,
        typer.Option("--work-dir", help="Directory to probe for writes. Defaults to WORK_ROOT or var/work."),
    ] = None,
) -> None:
    """Check Python, media tools, Node, git, the work directory, SQLite, and GPU clues."""
    checks = run_checks(work_dir)
    typer.echo(format_report(checks))
    code = exit_code(checks)
    if code != 0:
        raise typer.Exit(code)


@project_app.command("create")
def project_create(
    name: Annotated[str, typer.Argument(help="Project name.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    profile_id: Annotated[
        str | None,
        typer.Option("--profile-id", help="Optional campaign profile id. Not loaded from disk yet."),
    ] = None,
) -> None:
    """Create a project row. Prints the new project id."""
    path = resolve_db_path(db)
    now = datetime.now(UTC)
    try:
        created_by = getpass.getuser()
    except OSError as exc:
        _fail(ClipforgeError(f"could not determine the OS user for provenance: {exc}"))
    try:
        project = Project(
            project_id=str(uuid.uuid4()),
            name=name,
            created_at=now,
            profile_id=profile_id,
            provenance=ArtifactProvenance(
                created_at=now,
                created_by=created_by,
                tool="clipforge",
                tool_version=__version__,
            ),
        )
        database = Database(path)
        with database.transaction() as connection:
            insert_project(connection, project)
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(project.project_id)


@project_app.command("list")
def project_list(
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
) -> None:
    """List projects as id, name, and created-at, one per line."""
    path = resolve_db_path(db)
    try:
        database = Database(path)
        with database.connect() as connection:
            projects = list_projects(connection)
    except ClipforgeError as exc:
        _fail(exc)
    if not projects:
        typer.echo("No projects.")
        return
    for project in projects:
        created = project.created_at.isoformat()
        typer.echo(f"{project.project_id}\t{project.name}\t{created}")


@db_app.command("init")
def db_init(
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
) -> None:
    """Create the database file and apply migrations. Safe to repeat."""
    path = resolve_db_path(db)
    try:
        database = Database(path)
        version = database.initialize()
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(f"Initialized {path} at schema version {version}.")


@db_app.command("status")
def db_status(
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
) -> None:
    """Show schema version and row counts. Fails when the file is missing or too new."""
    path = resolve_db_path(db)
    try:
        status = Database(path).status()
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(f"path: {status.path}")
    typer.echo(f"schema_version: {status.schema_version}")
    typer.echo("migrations: " + ", ".join(status.migrations))
    for table, count in status.counts.items():
        typer.echo(f"{table}: {count}")


@schema_app.command("export")
def schema_export(
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Directory for JSON Schema files. Defaults to schemas/generated."),
    ] = None,
) -> None:
    """Write JSON Schema files for the canonical contracts."""
    try:
        directory = out if out is not None else find_repo_root() / "schemas" / "generated"
        written = export_schemas(directory)
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(f"Exported {len(written)} files to {directory}.")


@schema_app.command("check")
def schema_check(
    directory: Annotated[
        Path | None,
        typer.Option("--dir", help="Directory to compare. Defaults to schemas/generated."),
    ] = None,
) -> None:
    """Fail when committed schemas do not match the Pydantic models."""
    try:
        target = directory if directory is not None else find_repo_root() / "schemas" / "generated"
        assert_schemas_current(target)
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(f"Schemas match {target}.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)
