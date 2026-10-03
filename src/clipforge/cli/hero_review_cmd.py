"""Hero review commands. They read the current Hero draft and append decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.review.service import LOOPBACK_HOST
from clipforge.storage import Database

hero_review_app = typer.Typer(no_args_is_help=True, help="Review the current Hero draft set on this machine.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@hero_review_app.command("doctor")
def hero_review_doctor(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Report whether the current Hero draft can be reviewed. Does not write."""
    from clipforge.review.doctor import DoctorLine, doctor_status, format_doctor, review_doctor
    from clipforge.review.hero_board import hero_review_board, integrity_category

    lines = review_doctor()
    try:
        board = hero_review_board(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir))
    except ClipforgeError as exc:
        lines.append(DoctorLine("FAIL", integrity_category(str(exc)), str(exc)))
    else:
        status = str(board.get("status"))
        count = board.get("draft_count")
        lines.append(DoctorLine("PASS", "hero_review", f"{status} drafts {count}"))
    typer.echo(format_doctor(lines))
    if doctor_status(lines) == "FAIL":
        raise typer.Exit(1)


@hero_review_app.command("open")
def hero_review_open(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id. Not a filesystem path.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
    host: Annotated[
        str,
        typer.Option("--host", help="Loopback address. Other hosts are refused."),
    ] = LOOPBACK_HOST,
    port: Annotated[int, typer.Option("--port", help="TCP port. 0 asks the OS for a free port.")] = 8765,
) -> None:
    """Serve the local Hero review page. Does not change Hero files."""
    from clipforge.review.server import open_hero_review_server

    try:
        server = open_hero_review_server(
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
    typer.echo(f"hero_review_url: http://{host_text}:{bound_port}/")
    typer.echo(f"source_asset_id: {source_asset_id}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()
        typer.echo("hero review server stopped")


@hero_review_app.command("list")
def hero_review_list(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """List Hero decisions. Does not write a review."""
    from clipforge.review.hero_board import format_hero_review_list, hero_review_board

    try:
        board = hero_review_board(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir))
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(format_hero_review_list(board))


@hero_review_app.command("show")
def hero_review_show(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    candidate_id: Annotated[str, typer.Argument(help="Candidate id in the current Hero manifest.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Show one Hero draft and its review history. Does not write."""
    from clipforge.review.hero_board import format_hero_review_show, hero_review_board

    try:
        board = hero_review_board(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir))
        typer.echo(format_hero_review_show(board, candidate_id))
    except ClipforgeError as exc:
        _fail(exc)


@hero_review_app.command("decide")
def hero_review_decide(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    candidate_id: Annotated[str, typer.Argument(help="Candidate id in the current Hero manifest.")],
    decision: Annotated[str, typer.Option("--decision", help="approved, rejected, or changes_requested.")],
    reviewer_id: Annotated[str, typer.Option("--reviewer-id", help="Human reviewer id.")],
    hero_set_id: Annotated[str, typer.Option("--hero-set-id", help="Hero set id shown on the page.")],
    manifest_sha256: Annotated[str, typer.Option("--manifest-sha256", help="Current Hero manifest SHA-256.")],
    artifact_id: Annotated[str, typer.Option("--artifact-id", help="Current Hero artifact id.")],
    project_id: Annotated[str, typer.Option("--project-id", help="Project id shown on the page.")],
    source_sha256: Annotated[str, typer.Option("--source-sha256", help="Source SHA-256 shown on the page.")],
    plan_id: Annotated[str, typer.Option("--plan-id", help="Hero plan id shown on the page.")],
    plan_sha256: Annotated[str, typer.Option("--plan-sha256", help="Hero plan SHA-256 shown on the page.")],
    alignment_id: Annotated[str, typer.Option("--alignment-id", help="Alignment id shown on the page.")],
    alignment_sha256: Annotated[
        str,
        typer.Option("--alignment-sha256", help="Alignment SHA-256 shown on the page."),
    ],
    notes: Annotated[str, typer.Option("--notes", help="Optional note stored as text.")] = "",
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Append one Hero decision. Does not change the Hero files."""
    from clipforge.review.service import DecisionContext, record_hero_decision

    context = DecisionContext(
        source_asset_id=source_asset_id,
        project_id=project_id,
        artifact_id=artifact_id,
        preview_set_id=hero_set_id,
        manifest_sha256=manifest_sha256,
        candidate_id=candidate_id,
        subject_kind="hero",
        hero_set_id=hero_set_id,
        source_sha256=source_sha256,
        alignment_id=alignment_id,
        alignment_sha256=alignment_sha256,
        plan_id=plan_id,
        plan_sha256=plan_sha256,
    )
    try:
        review = record_hero_decision(
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


@hero_review_app.command("verify")
def hero_review_verify(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Check the current Hero draft set and stored reviews. Does not write."""
    from clipforge.review.hero_board import hero_review_board, integrity_category

    try:
        board = hero_review_board(Database(resolve_db_path(db)), source_asset_id, resolve_work_dir(work_dir))
    except ClipforgeError as exc:
        typer.echo(f"FAIL {integrity_category(str(exc))}: {exc}")
        raise typer.Exit(1) from exc
    typer.echo(f"PASS hero_review: {board.get('status')} drafts {board.get('draft_count')}")
