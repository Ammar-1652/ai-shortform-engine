"""Human review commands. They accept a source id, not a media path."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.review.service import LOOPBACK_HOST
from clipforge.storage import Database

_HELP = (
    "Record human decisions on the current rough preview set. "
    "Decisions stay on this machine. Scores stay unchanged."
)

review_app = typer.Typer(no_args_is_help=True, help=_HELP)


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@review_app.command("doctor")
def review_doctor_command() -> None:
    """Report the review contract and loopback bind. Does not write a review."""
    from clipforge.review.doctor import doctor_status, format_doctor, review_doctor

    lines = review_doctor()
    typer.echo(format_doctor(lines))
    if doctor_status(lines) == "FAIL":
        raise typer.Exit(1)


@review_app.command("open")
def review_open(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id. Not a filesystem path.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
    host: Annotated[
        str,
        typer.Option("--host", help="Loopback address. Public hosts are refused."),
    ] = LOOPBACK_HOST,
    port: Annotated[int, typer.Option("--port", help="TCP port. 0 asks the OS for a free port.")] = 8765,
) -> None:
    """Serve the local review page for one source. Does not change preview files."""
    from clipforge.review.server import open_review_server

    try:
        server = open_review_server(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
            host=host,
            port=port,
        )
    except (ClipforgeError, ValidationError, OSError) as exc:
        _fail(exc)
    bound_host, bound_port = server.server_address[:2]
    host_text = bound_host.decode("ascii") if isinstance(bound_host, bytes) else str(bound_host)
    typer.echo(f"review_url: http://{host_text}:{bound_port}/")
    typer.echo(f"source_asset_id: {source_asset_id}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()
        typer.echo("review server stopped")


@review_app.command("list")
def review_list(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """List effective decisions and history. Does not write a review."""
    from clipforge.review.service import format_review_list

    try:
        typer.echo(
            format_review_list(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir))
        )
    except ClipforgeError as exc:
        _fail(exc)


@review_app.command("decide")
def review_decide(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    candidate_id: Annotated[str, typer.Argument(help="Candidate id in the current preview set.")],
    decision: Annotated[str, typer.Option("--decision", help="approved, rejected, or changes_requested.")],
    reviewer_id: Annotated[str, typer.Option("--reviewer-id", help="Human reviewer id.")],
    preview_set_id: Annotated[str, typer.Option("--preview-set-id", help="Preview set id shown on the page.")],
    manifest_sha256: Annotated[str, typer.Option("--manifest-sha256", help="Current manifest SHA-256.")],
    artifact_id: Annotated[str, typer.Option("--artifact-id", help="Current rough preview artifact id.")],
    project_id: Annotated[str, typer.Option("--project-id", help="Project id shown on the page.")],
    notes: Annotated[str, typer.Option("--notes", help="Optional note stored as text.")] = "",
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Append one human decision. Does not change the preview files."""
    from clipforge.review.service import DecisionContext, record_decision

    context = DecisionContext(
        source_asset_id=source_asset_id,
        project_id=project_id,
        artifact_id=artifact_id,
        preview_set_id=preview_set_id,
        manifest_sha256=manifest_sha256,
        candidate_id=candidate_id,
    )
    try:
        review = record_decision(
            database=Database(resolve_db_path(db)),
            work_root=resolve_work_dir(work_dir),
            context=context,
            decision=decision,
            reviewer_id=reviewer_id,
            notes=notes,
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"review_id: {review.review_id}")
    typer.echo(f"decision: {review.decision}")
    typer.echo(f"candidate_id: {review.candidate_id}")
    typer.echo(f"artifact_id: {review.artifact_id}")


@review_app.command("verify")
def review_verify(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Check the current preview set and stored reviews. Does not write."""
    from clipforge.review.service import verify_review

    report = verify_review(
        database=Database(resolve_db_path(db)),
        source_asset_id=source_asset_id,
        work_root=resolve_work_dir(work_dir),
    )
    for line in report.lines:
        typer.echo(f"{line.status} {line.name}: {line.detail}")
    if report.status == "FAIL":
        raise typer.Exit(1)
