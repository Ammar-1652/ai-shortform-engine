"""Local outcome commands. list, show, verify, compare, and doctor do not write."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.analytics.compare import DIMENSIONS, ComparisonFilter
from clipforge.analytics.importers import list_import_profiles, load_import_profile
from clipforge.analytics.labels import list_label_history, set_labels, verify_labels
from clipforge.analytics.server import open_analytics_server, verify_dashboard
from clipforge.analytics.service import (
    AnalyticsError,
    compare_project,
    doctor_text,
    format_project_comparison,
    import_observations,
    list_imports,
    list_outcomes,
    load_observation,
    record_outcome,
    show_import,
    show_outcome,
    verify_import,
    verify_outcome,
)
from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.schemas.analytics import EditorialLabelAssignment, ManualLabels
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
    measurement_window: str | None,
    duration_bucket: str | None,
    hook_type: str | None,
    topic_tag: str | None,
    cta: str | None,
    format_tag: str | None,
    audience_tag: str | None,
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
            measurement_window=measurement_window,
            duration_bucket=duration_bucket,
            hook_type=hook_type,
            topic_tag=topic_tag,
            cta=cta,
            format_tag=format_tag,
            audience_tag=audience_tag,
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


import_app = typer.Typer(invoke_without_command=True, help="Import a local JSON, JSONL, or CSV file.")
analytics_app.add_typer(import_app, name="import")


@import_app.callback(context_settings={"allow_extra_args": True})
def analytics_import(
    ctx: typer.Context,
    profile: Annotated[str, typer.Option("--profile")] = "clipforge-observation-v1",
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Import a local file in one transaction."""
    if ctx.invoked_subcommand is not None:
        return
    if len(ctx.args) != 1:
        _fail(AnalyticsError("import needs one file"))
    try:
        stored = import_observations(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            Path(ctx.args[0]),
            profile_id=profile,
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
    measurement_window: Annotated[str | None, typer.Option("--measurement-window")] = None,
    duration_bucket: Annotated[str | None, typer.Option("--duration-bucket")] = None,
    hook_type: Annotated[str | None, typer.Option("--hook-type")] = None,
    topic_tag: Annotated[str | None, typer.Option("--topic-tag")] = None,
    cta: Annotated[str | None, typer.Option("--cta")] = None,
    format_tag: Annotated[str | None, typer.Option("--format-tag")] = None,
    audience_tag: Annotated[str | None, typer.Option("--audience-tag")] = None,
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
        measurement_window=measurement_window,
        duration_bucket=duration_bucket,
        hook_type=hook_type,
        topic_tag=topic_tag,
        cta=cta,
        format_tag=format_tag,
        audience_tag=audience_tag,
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
    measurement_window: Annotated[str | None, typer.Option("--measurement-window")] = None,
    duration_bucket: Annotated[str | None, typer.Option("--duration-bucket")] = None,
    hook_type: Annotated[str | None, typer.Option("--hook-type")] = None,
    topic_tag: Annotated[str | None, typer.Option("--topic-tag")] = None,
    cta: Annotated[str | None, typer.Option("--cta")] = None,
    format_tag: Annotated[str | None, typer.Option("--format-tag")] = None,
    audience_tag: Annotated[str | None, typer.Option("--audience-tag")] = None,
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
        measurement_window=measurement_window,
        duration_bucket=duration_bucket,
        hook_type=hook_type,
        topic_tag=topic_tag,
        cta=cta,
        format_tag=format_tag,
        audience_tag=audience_tag,
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


@import_app.command("validate")
def analytics_import_validate(
    path: Annotated[Path, typer.Argument()],
    profile: Annotated[str, typer.Option("--profile")] = "clipforge-observation-v1",
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Check a local file without writing."""
    try:
        stored = import_observations(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            path,
            profile_id=profile,
            validate_only=True,
        )
    except (ClipforgeError, ValidationError, OSError) as exc:
        _fail(exc)
    typer.echo(f"valid: {len(stored)}")


@import_app.command("list")
def analytics_import_list(
    project_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """List accepted imports. Does not write."""
    try:
        rows = list_imports(Database(resolve_db_path(db)), project_id)
    except ClipforgeError as exc:
        _fail(exc)
    if not rows:
        typer.echo("No imports are stored.")
        return
    for import_id, profile_id, count in rows:
        typer.echo(f"{import_id}\t{profile_id}\t{count}")


@import_app.command("show")
def analytics_import_show(
    import_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """Show one import. Does not write."""
    try:
        typer.echo(show_import(Database(resolve_db_path(db)), import_id))
    except ClipforgeError as exc:
        _fail(exc)


@import_app.command("verify")
def analytics_import_verify(
    import_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """Check one import. Does not write."""
    try:
        typer.echo(verify_import(Database(resolve_db_path(db)), import_id))
    except ClipforgeError as exc:
        _fail(exc)


import_profile_app = typer.Typer(no_args_is_help=True, help="Show local import profiles.")
analytics_app.add_typer(import_profile_app, name="import-profile")


@import_profile_app.command("list")
def analytics_import_profile_list() -> None:
    """List parser profiles. Does not write."""
    try:
        profiles = list_import_profiles()
    except ClipforgeError as exc:
        _fail(exc)
    for profile in profiles:
        typer.echo(f"{profile.profile_id}\t{profile.kind}")


@import_profile_app.command("show")
def analytics_import_profile_show(profile_id: Annotated[str, typer.Argument()]) -> None:
    """Show one parser profile. Does not write."""
    try:
        profile = load_import_profile(profile_id)
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(profile.model_dump_json())


labels_app = typer.Typer(no_args_is_help=True, help="Append and read manual labels.")
analytics_app.add_typer(labels_app, name="labels")


def _blank(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return value


@labels_app.command("list")
def analytics_labels_list(
    project_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """List effective labels. Does not write."""
    try:
        database = Database(resolve_db_path(db))
        with database.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT artifact_id FROM editorial_label_sets
                WHERE project_id = ?
                ORDER BY artifact_id
                """,
                (project_id,),
            ).fetchall()
        if not rows:
            typer.echo("No labels are stored.")
            return
        for row in rows:
            artifact_id = str(row["artifact_id"])
            history = list_label_history(database, project_id, artifact_id)
            effective = history.entries[-1]
            typer.echo(f"{artifact_id}\t{effective.label_set_id}\t{effective.labels.hook_type}")
    except ClipforgeError as exc:
        _fail(exc)


def _project_for_artifact(database: Database, artifact_id: str) -> str:
    from clipforge.storage import get_artifact

    with database.connect() as connection:
        return get_artifact(connection, artifact_id).project_id


@labels_app.command("show")
def analytics_labels_show(
    artifact_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """Show the effective label set. Does not write."""
    try:
        database = Database(resolve_db_path(db))
        history = list_label_history(database, _project_for_artifact(database, artifact_id), artifact_id)
    except ClipforgeError as exc:
        _fail(exc)
    if not history.entries:
        _fail(AnalyticsError("no labels are stored for this artifact"))
    typer.echo(history.entries[-1].model_dump_json())


@labels_app.command("history")
def analytics_labels_history(
    artifact_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """Show label history from oldest to newest. Does not write."""
    try:
        database = Database(resolve_db_path(db))
        history = list_label_history(database, _project_for_artifact(database, artifact_id), artifact_id)
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(history.model_dump_json())


@labels_app.command("verify")
def analytics_labels_verify(
    project_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """Check label history. Does not write."""
    try:
        typer.echo(verify_labels(Database(resolve_db_path(db)), project_id))
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)


@labels_app.command("set")
def analytics_labels_set(
    project_id: Annotated[str, typer.Argument()],
    artifact_id: Annotated[str, typer.Argument()],
    reviewer_id: Annotated[str, typer.Option("--reviewer-id")],
    source_asset_id: Annotated[str | None, typer.Option("--source-asset-id")] = None,
    outcome_id: Annotated[str | None, typer.Option("--outcome-id")] = None,
    snapshot_id: Annotated[str | None, typer.Option("--snapshot-id")] = None,
    expected_label_set_id: Annotated[str | None, typer.Option("--expected-label-set-id")] = None,
    expected_artifact_sha256: Annotated[str | None, typer.Option("--expected-artifact-sha256")] = None,
    hook_type: Annotated[str, typer.Option("--hook-type")] = "unknown",
    topic_tag: Annotated[list[str] | None, typer.Option("--topic-tag")] = None,
    cta: Annotated[str, typer.Option("--cta")] = "unknown",
    format_tag: Annotated[str, typer.Option("--format-tag")] = "unknown",
    audience_tag: Annotated[str, typer.Option("--audience-tag")] = "unknown",
    platform: Annotated[str | None, typer.Option("--platform")] = None,
    campaign_id: Annotated[str | None, typer.Option("--campaign-id")] = None,
    geography: Annotated[str | None, typer.Option("--geography")] = None,
    notes: Annotated[str, typer.Option("--notes")] = "",
    confidence: Annotated[str | None, typer.Option("--confidence")] = None,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Append one label set."""
    try:
        database = Database(resolve_db_path(db))
        source_id = source_asset_id
        if source_id is None:
            from clipforge.storage import get_artifact

            with database.connect() as connection:
                source_id = get_artifact(connection, artifact_id).source_asset_id
        if source_id is None:
            raise AnalyticsError("artifact has no source")
        assignment = EditorialLabelAssignment(
            project_id=project_id,
            source_asset_id=source_id,
            artifact_id=artifact_id,
            outcome_id=_blank(outcome_id),
            snapshot_id=_blank(snapshot_id),
            expected_label_set_id=_blank(expected_label_set_id),
            expected_artifact_sha256=_blank(expected_artifact_sha256),
            labels=ManualLabels(
                hook_type=hook_type,
                topic_tags=topic_tag or [],
                cta=cta,
                format_tag=format_tag,
                audience_tag=audience_tag,
            ),
            platform=_blank(platform),
            campaign_id=_blank(campaign_id),
            geography=_blank(geography),
            reviewer_id=reviewer_id,
            notes=notes,
            confidence=_blank(confidence),
        )
        label_set = set_labels(database, resolve_work_dir(work_dir), assignment)
    except (ClipforgeError, ValidationError, OSError) as exc:
        _fail(exc)
    typer.echo(f"label_set_id: {label_set.label_set_id}")


dashboard_app = typer.Typer(invoke_without_command=True, help="Serve the loopback analytics page.")
analytics_app.add_typer(dashboard_app, name="dashboard")


@dashboard_app.callback(context_settings={"allow_extra_args": True})
def analytics_dashboard(
    ctx: typer.Context,
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8766,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Serve the analytics page on loopback."""
    if ctx.invoked_subcommand is not None:
        return
    if len(ctx.args) != 1:
        _fail(AnalyticsError("dashboard needs one project id"))
    try:
        server = open_analytics_server(
            database=Database(resolve_db_path(db)),
            project_id=ctx.args[0],
            work_root=resolve_work_dir(work_dir),
            host=host,
            port=port,
        )
    except (ClipforgeError, OSError) as exc:
        _fail(exc)
    bound_port = int(server.server_address[1])
    typer.echo(f"analytics_url: http://127.0.0.1:{bound_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


@dashboard_app.command("verify")
def analytics_dashboard_verify(
    project_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """Check the analytics page bundle. Does not write."""
    try:
        typer.echo(verify_dashboard(Database(resolve_db_path(db)), project_id))
    except (ClipforgeError, OSError) as exc:
        _fail(exc)
