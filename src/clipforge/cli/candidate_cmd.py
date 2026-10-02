"""Candidate commands. They accept a source id, not a transcript or video path.

Mining reads the current transcript and the current visual analysis. Scores are
editorial heuristics. Edit opportunity is separate. There is no virality
probability and this does not publish.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.storage import Database

_LIMITS = (
    "Uses the current transcript and visual evidence. Scores are editorial heuristics. "
    "Edit opportunity is separate. No virality probability."
)

candidate_app = typer.Typer(no_args_is_help=True, help=_LIMITS)


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@candidate_app.command("doctor")
def candidate_doctor_command(
    work_dir: Annotated[
        Path | None,
        typer.Option("--work-dir", help="Work root used for the disk report."),
    ] = None,
) -> None:
    """Report the candidate recipe, profile, and disk. Does not load a model or mine."""
    from clipforge.candidates.doctor import candidate_doctor, doctor_status, format_doctor

    lines = candidate_doctor(resolve_work_dir(work_dir))
    typer.echo(format_doctor(lines))
    if doctor_status(lines) == "FAIL":
        raise typer.Exit(1)


@candidate_app.command(
    "mine",
    help=(
        "Mine from the current transcript and visual evidence. Scores are heuristics. "
        "Edit opportunity is separate. No virality probability. Does not publish."
    ),
)
def candidate_mine(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id. Not a filesystem path.")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Ignore a valid candidate cache and mine again."),
    ] = False,
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Mine candidates from the current transcript and visual analysis.

    Does not run transcription or visual analysis. Scores are editorial
    heuristics. Edit opportunity is separate. No virality probability. No
    publishing.
    """
    from clipforge.candidates.service import mine_source

    try:
        result = mine_source(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
            force=force,
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"job_id: {result.job_id}")
    typer.echo(f"mining_id: {result.mining_id}")
    typer.echo(f"source_asset_id: {result.source_asset_id}")
    typer.echo(f"transcript_id: {result.transcript_id}")
    typer.echo(f"transcript_sha256: {result.transcript_sha256[:12]}")
    typer.echo(f"visual_analysis_id: {result.visual_analysis_id}")
    typer.echo(f"visual_analysis_sha256: {result.visual_analysis_sha256[:12]}")
    typer.echo(f"raw_hypotheses: {result.raw_hypothesis_count}")
    typer.echo(f"hard_filtered: {result.hard_filtered_count}")
    typer.echo(f"duplicates_removed: {result.duplicate_count}")
    typer.echo(f"eligible_distinct: {result.eligible_distinct_count}")
    typer.echo(f"selected: {result.selected_count}")
    typer.echo(f"below_soft_target: {'yes' if result.below_soft_target else 'no'}")
    typer.echo(f"artifact_path: {result.candidate_path}")
    typer.echo(f"artifact_sha256: {result.candidate_sha256}")
    typer.echo(f"cache: {'hit' if result.cache_hit else 'miss'}")
    typer.echo(f"runtime_seconds: {result.runtime_seconds:.3f}")


@candidate_app.command("list")
def candidate_list(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """List selected candidates in editorial rank order. Does not print a virality probability."""
    from clipforge.candidates.show import format_candidate_list, load_candidate_document

    try:
        document = load_candidate_document(
            Database(resolve_db_path(db)),
            source_asset_id,
            resolve_work_dir(work_dir),
        )
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(format_candidate_list(document))


@candidate_app.command("show")
def candidate_show(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    candidate_id: Annotated[str, typer.Argument(help="Candidate id from candidate list.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Show one stored candidate. Word timing remains provisional.

    Does not load video, decode audio, or load a model.
    """
    from clipforge.candidates.show import format_candidate, load_candidate_document

    try:
        document = load_candidate_document(
            Database(resolve_db_path(db)),
            source_asset_id,
            resolve_work_dir(work_dir),
        )
        typer.echo(format_candidate(document, candidate_id))
    except ClipforgeError as exc:
        _fail(exc)


@candidate_app.command("verify")
def candidate_verify(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Check the stored candidate set. Read-only. Does not repair, score, or load a model."""
    from clipforge.candidates.verify import verify_candidate

    report = verify_candidate(
        database=Database(resolve_db_path(db)),
        source_asset_id=source_asset_id,
        work_root=resolve_work_dir(work_dir),
    )
    for line in report.lines:
        typer.echo(f"{line.status} {line.name}: {line.detail}")
    if report.status == "FAIL":
        raise typer.Exit(1)
