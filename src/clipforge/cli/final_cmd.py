"""Final review commands. They do not publish and they do not approve automatically."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.review.service import LOOPBACK_HOST
from clipforge.storage import Database

final_app = typer.Typer(no_args_is_help=True, help="Final human approval before local delivery.")
review_app = typer.Typer(no_args_is_help=True, help="Read and record the final review for one candidate.")
final_app.add_typer(review_app, name="review")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@review_app.command("doctor")
def final_doctor_command() -> None:
    """Report the final-review gate. This does not write."""
    typer.echo("editorial_operator: codex_operator")
    typer.echo("deterministic_enforcer: system_enforcer")
    typer.echo("final_review: human_reviewer")
    typer.echo("final_playback_required: true")
    typer.echo("hero_approval_authorizes_delivery: no")
    typer.echo("qa_authorizes_delivery: no")
    typer.echo("whop: deferred")
    typer.echo("external_publishing: deferred")
    from clipforge.storage.migrations import CURRENT_SCHEMA_VERSION

    typer.echo(f"sqlite_schema: {CURRENT_SCHEMA_VERSION}")


@review_app.command("open")
def final_open_command(
    source_asset_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    host: Annotated[str, typer.Option("--host")] = LOOPBACK_HOST,
    port: Annotated[int, typer.Option("--port")] = 8765,
) -> None:
    """Serve the loopback final review page."""
    from clipforge.review.server import open_final_review_server

    try:
        server = open_final_review_server(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            candidate_id=candidate_id,
            work_root=resolve_work_dir(work_dir),
            host=host,
            port=port,
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    bound_host, bound_port = server.server_address[:2]
    host_text = bound_host.decode("ascii") if isinstance(bound_host, bytes) else str(bound_host)
    typer.echo(f"final_review_url: http://{host_text}:{bound_port}/final-review")
    typer.echo(f"candidate_id: {candidate_id}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()


@review_app.command("list")
def final_list_command(
    source_asset_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """List final decisions. This does not write."""
    from clipforge.review.final_gate import human_notes
    from clipforge.storage import get_source_asset, list_reviews

    database = Database(resolve_db_path(db))
    try:
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
            reviews = list_reviews(connection, source.project_id)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    rows = [item for item in reviews if item.subject_kind == "final"]
    if not rows:
        typer.echo("final_reviews: none")
        typer.echo("whop: deferred")
        return
    for item in rows:
        typer.echo(f"{item.review_id} {item.candidate_id} {item.decision} {human_notes(item.notes)}")


@review_app.command("show")
def final_show_command(
    source_asset_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show one final review card. This does not write."""
    _show(source_asset_id, candidate_id, db, work_dir, listed=False)


@review_app.command("verify")
def final_verify_command(
    source_asset_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Re-check the effective final decision. This does not write."""
    _show(source_asset_id, candidate_id, db, work_dir, listed=False, require_approved=True)


@review_app.command("decide")
def final_decide_command(
    source_asset_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    decision: Annotated[str, typer.Option("--decision")],
    reviewer_id: Annotated[str, typer.Option("--reviewer")],
    notes: Annotated[str, typer.Option("--notes")] = "",
    watch_record: Annotated[Path | None, typer.Option("--watch-record")] = None,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Append one human final decision for the current Advanced Hero evidence."""
    from clipforge.review.final_gate import capture_final_decision
    from clipforge.schemas.qa import HumanPlaybackReview

    try:
        playback = None
        if watch_record is not None:
            if watch_record.is_symlink() or not watch_record.is_file():
                raise ClipforgeError("human playback file is missing or a symlink")
            playback = HumanPlaybackReview.model_validate_json(watch_record.read_text(encoding="utf-8"))
        review = capture_final_decision(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            source_asset_id,
            candidate_id,
            decision=decision,
            reviewer_id=reviewer_id,
            notes=notes,
            playback=playback,
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(review.review_id)
    typer.echo(f"decision: {review.decision}")
    typer.echo("automated: false")


@review_app.command("watch-target")
def final_watch_target_command(
    source_asset_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Print exact playback bindings as JSON, without recording any watch or approval."""
    from clipforge.publish.preflight import preflight_delivery
    from clipforge.review.final_gate import evidence_for_facts
    from clipforge.review.playback import playback_target
    from clipforge.transcription.io import dump_json

    try:
        facts = preflight_delivery(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            source_asset_id,
            candidate_id,
            probe=False,
            require_final=False,
        )
        evidence = {**evidence_for_facts(facts), "video_sha256": facts.video_sha256}
        typer.echo(dump_json(playback_target(evidence)), nl=False)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)


def _show(
    source_asset_id: str,
    candidate_id: str,
    db: Path | None,
    work_dir: Path | None,
    *,
    listed: bool,
    require_approved: bool = False,
) -> None:
    from clipforge.review.final_gate import final_board

    chosen = candidate_id or "cand-1"
    if listed and not candidate_id:
        chosen = candidate_id
    try:
        if not chosen:
            raise ClipforgeError("candidate id is required")
        card = final_board(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            source_asset_id,
            chosen,
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(f"candidate_id: {card.get('candidate_id', chosen)}")
    typer.echo(f"effective_decision: {card.get('effective_decision', 'missing')}")
    blockers = card.get("blockers")
    names = blockers if isinstance(blockers, list) else []
    typer.echo("blockers: " + ",".join(str(item) for item in names))
    typer.echo("whop: deferred")
    typer.echo("external_publishing: deferred")
    if require_approved and card.get("effective_decision") != "approved":
        raise typer.Exit(1)
