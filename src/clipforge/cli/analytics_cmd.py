"""Local outcome commands. list, show, verify, compare, and doctor do not write."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.analytics.compare import DIMENSIONS, ComparisonFilter
from clipforge.analytics.service import (
    AnalyticsError,
    compare_project,
    doctor_text,
    format_project_comparison,
    import_observations,
    list_outcomes,
    load_observation,
    record_outcome,
    show_outcome,
    verify_outcome,
)
from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.storage import Database

analytics_app = typer.Typer(no_args_is_help=True, help="Record local outcome observations.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


def _filter(
    *,
    platform: str | None,
    campaign_id: str | None,
    geography: str | None,
    profile_id: str | None,
    source_asset_id: str | None,
    observed_from: str | None,
    observed_to: str | None,
    duration_bucket: str | None,
    hook_type: str | None,
    topic_tag: str | None,
    cta: str | None,
    caption_presence: str | None,
    broll_presence: str | None,
    sfx_presence: str | None,
    typography_presence: str | None,
    diagram_presence: str | None,
    reframing_strategy: str | None,
    motion_library_version: str | None,
    rank_band: str | None,
) -> ComparisonFilter:
    try:
        return ComparisonFilter(
            platform=platform,
            campaign_id=campaign_id,
            geography=geography,
            profile_id=profile_id,
            source_asset_id=source_asset_id,
            observed_from=_time(observed_from),
            observed_to=_time(observed_to),
            duration_bucket=duration_bucket,
            hook_type=hook_type,
            topic_tag=topic_tag,
            cta=cta,
            caption_presence=caption_presence,
            broll_presence=broll_presence,
            sfx_presence=sfx_presence,
            typography_presence=typography_presence,
            diagram_presence=diagram_presence,
            reframing_strategy=reframing_strategy,
            motion_library_version=motion_library_version,
            rank_band=rank_band,
        )
    except ValueError as exc:
        _fail(exc)


def _time(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed


@analytics_app.command("doctor")
def analytics_doctor() -> None:
    """Report the analytics rules. This does not read a database."""
    typer.echo(doctor_text())


@analytics_app.command("record")
def analytics_record(
    input_path: Annotated[Path, typer.Option("--input", exists=False)],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Record one local JSON observation."""
    try:
        observation = load_observation(resolve_work_dir(work_dir), input_path)
        outcome = record_outcome(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            observation,
        )
    except (ClipforgeError, ValidationError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(exc)
    typer.echo(f"outcome_id: {outcome.outcome_id}")
    typer.echo(f"snapshot_id: {outcome.snapshot_id}")


@analytics_app.command("import")
def analytics_import(
    path: Annotated[Path, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Import a local JSON or JSONL file in one transaction."""
    try:
        stored = import_observations(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            path,
        )
    except (ClipforgeError, ValidationError, OSError) as exc:
        _fail(exc)
    typer.echo(f"outcomes: {len(stored)}")
    for item in stored:
        typer.echo(item.outcome_id)


@analytics_app.command("list")
def analytics_list(
    project_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    platform: Annotated[str | None, typer.Option("--platform")] = None,
    campaign_id: Annotated[str | None, typer.Option("--campaign-id")] = None,
    geography: Annotated[str | None, typer.Option("--geography")] = None,
    profile_id: Annotated[str | None, typer.Option("--profile-id")] = None,
    source_asset_id: Annotated[str | None, typer.Option("--artifact-source")] = None,
    observed_from: Annotated[str | None, typer.Option("--from")] = None,
    observed_to: Annotated[str | None, typer.Option("--to")] = None,
    duration_bucket: Annotated[str | None, typer.Option("--duration-bucket")] = None,
    hook_type: Annotated[str | None, typer.Option("--hook-type")] = None,
    topic_tag: Annotated[str | None, typer.Option("--topic-tag")] = None,
    cta: Annotated[str | None, typer.Option("--cta")] = None,
    caption_presence: Annotated[str | None, typer.Option("--caption-presence")] = None,
    broll_presence: Annotated[str | None, typer.Option("--broll-presence")] = None,
    sfx_presence: Annotated[str | None, typer.Option("--sfx-presence")] = None,
    typography_presence: Annotated[str | None, typer.Option("--typography-presence")] = None,
    diagram_presence: Annotated[str | None, typer.Option("--diagram-presence")] = None,
    reframing_strategy: Annotated[str | None, typer.Option("--reframing-strategy")] = None,
    motion_library_version: Annotated[str | None, typer.Option("--motion-library-version")] = None,
    rank_band: Annotated[str | None, typer.Option("--rank-band")] = None,
) -> None:
    """List outcomes. Does not write."""
    chosen = _filter(
        platform=platform,
        campaign_id=campaign_id,
        geography=geography,
        profile_id=profile_id,
        source_asset_id=source_asset_id,
        observed_from=observed_from,
        observed_to=observed_to,
        duration_bucket=duration_bucket,
        hook_type=hook_type,
        topic_tag=topic_tag,
        cta=cta,
        caption_presence=caption_presence,
        broll_presence=broll_presence,
        sfx_presence=sfx_presence,
        typography_presence=typography_presence,
        diagram_presence=diagram_presence,
        reframing_strategy=reframing_strategy,
        motion_library_version=motion_library_version,
        rank_band=rank_band,
    )
    try:
        rows = list_outcomes(Database(resolve_db_path(db)), project_id, chosen)
    except ClipforgeError as exc:
        _fail(exc)
    if not rows:
        typer.echo("No outcomes are stored.")
        return
    for item in rows:
        typer.echo(f"{item.outcome_id}\t{item.platform}\t{item.observed_at.isoformat()}\t{item.artifact_id}")


@analytics_app.command("show")
def analytics_show(
    outcome_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """Show one outcome. Does not write."""
    try:
        typer.echo(show_outcome(Database(resolve_db_path(db)), outcome_id))
    except ClipforgeError as exc:
        _fail(exc)


@analytics_app.command("verify")
def analytics_verify(
    outcome_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Check one outcome. Does not write."""
    try:
        typer.echo(verify_outcome(Database(resolve_db_path(db)), resolve_work_dir(work_dir), outcome_id))
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)


@analytics_app.command("compare")
def analytics_compare(
    project_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    by: Annotated[str, typer.Option("--by")] = "platform",
    output_format: Annotated[str, typer.Option("--format")] = "text",
    platform: Annotated[str | None, typer.Option("--platform")] = None,
    campaign_id: Annotated[str | None, typer.Option("--campaign-id")] = None,
    geography: Annotated[str | None, typer.Option("--geography")] = None,
    profile_id: Annotated[str | None, typer.Option("--profile-id")] = None,
    observed_from: Annotated[str | None, typer.Option("--from")] = None,
    observed_to: Annotated[str | None, typer.Option("--to")] = None,
    source_asset_id: Annotated[str | None, typer.Option("--artifact-source")] = None,
    duration_bucket: Annotated[str | None, typer.Option("--duration-bucket")] = None,
    hook_type: Annotated[str | None, typer.Option("--hook-type")] = None,
    topic_tag: Annotated[str | None, typer.Option("--topic-tag")] = None,
    cta: Annotated[str | None, typer.Option("--cta")] = None,
    caption_presence: Annotated[str | None, typer.Option("--caption-presence")] = None,
    broll_presence: Annotated[str | None, typer.Option("--broll-presence")] = None,
    sfx_presence: Annotated[str | None, typer.Option("--sfx-presence")] = None,
    typography_presence: Annotated[str | None, typer.Option("--typography-presence")] = None,
    diagram_presence: Annotated[str | None, typer.Option("--diagram-presence")] = None,
    reframing_strategy: Annotated[str | None, typer.Option("--reframing-strategy")] = None,
    motion_library_version: Annotated[str | None, typer.Option("--motion-library-version")] = None,
    rank_band: Annotated[str | None, typer.Option("--rank-band")] = None,
) -> None:
    """Describe cohorts. Does not write."""
    if by not in DIMENSIONS:
        _fail(AnalyticsError(f"unknown comparison dimension {by}"))
    if output_format not in {"text", "json"}:
        _fail(AnalyticsError("format must be text or json"))
    chosen = _filter(
        platform=platform,
        campaign_id=campaign_id,
        geography=geography,
        profile_id=profile_id,
        source_asset_id=source_asset_id,
        observed_from=observed_from,
        observed_to=observed_to,
        duration_bucket=duration_bucket,
        hook_type=hook_type,
        topic_tag=topic_tag,
        cta=cta,
        caption_presence=caption_presence,
        broll_presence=broll_presence,
        sfx_presence=sfx_presence,
        typography_presence=typography_presence,
        diagram_presence=diagram_presence,
        reframing_strategy=reframing_strategy,
        motion_library_version=motion_library_version,
        rank_band=rank_band,
    )
    try:
        document = compare_project(
            Database(resolve_db_path(db)),
            project_id,
            dimension=by,
            comparison_filter=chosen,
            created_by="cli",
        )
    except (ClipforgeError, ValidationError, ValueError) as exc:
        _fail(exc)
    if output_format == "json":
        typer.echo(document.model_dump_json())
        return
    typer.echo(format_project_comparison(document))
    if document.status == "insufficient_evidence":
        raise typer.Exit(1)
