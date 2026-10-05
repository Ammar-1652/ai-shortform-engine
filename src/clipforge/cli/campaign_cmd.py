"""Campaign commands. Acquisition does not publish."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from clipforge.campaign.antoine import CAMPAIGN_ID
from clipforge.campaign.production import (
    list_campaign_runs,
    plan_campaign,
    resume_campaign,
    run_campaign,
    show_campaign_run,
    verify_campaign_run,
)
from clipforge.campaign.providers import (
    CampaignError,
    DryRunSourceProvider,
    FakeSourceProvider,
    GoogleDriveSourceProvider,
)
from clipforge.campaign.service import (
    acquire_plan_text,
    doctor_text,
    ingest_campaign,
    inventory_text,
    list_text,
    policy_text,
    show_text,
    verify_campaign,
)
from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.storage import Database

campaign_app = typer.Typer(no_args_is_help=True, help="Campaign policy, inventory, and production runs.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


def _provider(name: str) -> FakeSourceProvider | DryRunSourceProvider | GoogleDriveSourceProvider:
    if name == "fake":
        return FakeSourceProvider()
    if name == "dry-run":
        return DryRunSourceProvider()
    if name == "google-drive":
        return GoogleDriveSourceProvider()
    _fail(ClipforgeError("campaign provider must be fake, dry-run, or google-drive"))


@campaign_app.command("doctor")
def campaign_doctor() -> None:
    """Report native editing, blocked black-box tools, and deferred publishing."""
    typer.echo(doctor_text())


@campaign_app.command("list")
def campaign_list(
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """List known campaigns. Pass --work-dir to include production run ids."""
    typer.echo(list_text())
    if work_dir is not None:
        for run_id in list_campaign_runs(resolve_work_dir(work_dir)):
            typer.echo(run_id)


@campaign_app.command("plan")
def campaign_plan(
    campaign_id: str,
    language: Annotated[str, typer.Option("--language")] = "en-US",
    narration: Annotated[bool, typer.Option("--narration/--no-narration")] = True,
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
) -> None:
    """Print one campaign plan. This does not insert jobs."""
    try:
        document = plan_campaign(
            campaign_id=campaign_id,
            source_ids=source or None,
            language=language,
            narration_enabled=narration,
        )
    except (ClipforgeError, ValueError) as exc:
        _fail(exc)
    typer.echo(document.model_dump_json())


@campaign_app.command("run")
def campaign_run(
    campaign_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    language: Annotated[str, typer.Option("--language")] = "en-US",
    narration: Annotated[bool, typer.Option("--narration/--no-narration")] = True,
    source: Annotated[list[str] | None, typer.Option("--source")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Execute explicit campaign sources, or reuse a matching succeeded run."""
    try:
        document = run_campaign(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            campaign_id=campaign_id,
            source_ids=source or None,
            language=language,
            narration_enabled=narration,
            force=force,
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(document.campaign_run_id)
    typer.echo(document.status)


@campaign_app.command("show")
def campaign_show(
    campaign_id: str,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show a catalogue campaign or one production run."""
    if campaign_id == CAMPAIGN_ID:
        typer.echo(show_text())
        return
    try:
        typer.echo(show_campaign_run(resolve_work_dir(work_dir), campaign_id))
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@campaign_app.command("inventory")
def campaign_inventory(campaign_id: str) -> None:
    """Show catalogue rows, including files that must not be fetched."""
    if campaign_id != CAMPAIGN_ID:
        _fail(CampaignError("campaign is not in the local catalogue", code="missing_campaign"))
    typer.echo(inventory_text())


@campaign_app.command("policy")
def campaign_policy(campaign_id: str) -> None:
    """Show the hash-bound policy snapshot."""
    if campaign_id != CAMPAIGN_ID:
        _fail(CampaignError("campaign is not in the local catalogue", code="missing_campaign"))
    typer.echo(policy_text())


@campaign_app.command("acquire-plan")
def campaign_acquire_plan(
    campaign_id: str,
    provider: Annotated[str, typer.Option("--provider")] = "dry-run",
) -> None:
    """Print the acquisition plan. This does not download."""
    if campaign_id != CAMPAIGN_ID:
        _fail(CampaignError("campaign is not in the local catalogue", code="missing_campaign"))
    try:
        typer.echo(acquire_plan_text(_provider(provider)))
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@campaign_app.command("ingest")
def campaign_ingest(
    campaign_id: str,
    provider: Annotated[str, typer.Option("--provider")] = "google-drive",
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Acquire only the selected sources. Unselected files are not fetched."""
    if campaign_id != CAMPAIGN_ID:
        _fail(CampaignError("campaign is not in the local catalogue", code="missing_campaign"))
    confirmed = os.environ.get("CLIPFORGE_CAMPAIGN_OPERATOR_CONFIRM", "").strip() == "1"
    try:
        document = ingest_campaign(
            resolve_work_dir(work_dir),
            _provider(provider),
            operator_confirmed=confirmed,
        )
    except (ClipforgeError, OSError) as exc:
        _fail(exc)
    acquired = [item.source_id for item in document.acquisitions if item.download_status == "acquired"]
    unavailable = [
        item.source_id for item in document.acquisitions if item.download_status == "provider_unavailable"
    ]
    typer.echo(f"campaign: {campaign_id}")
    typer.echo(f"acquired: {','.join(acquired) if acquired else 'none'}")
    typer.echo(f"provider_unavailable: {','.join(unavailable) if unavailable else 'none'}")
    typer.echo("external publishing: deferred")


@campaign_app.command("verify")
def campaign_verify(
    campaign_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Re-hash a catalogue inventory or one production run. This command does not download."""
    try:
        if campaign_id == CAMPAIGN_ID:
            typer.echo(verify_campaign(resolve_work_dir(work_dir)))
            return
        typer.echo(
            verify_campaign_run(
                Database(resolve_db_path(db)),
                resolve_work_dir(work_dir),
                campaign_id,
            )
        )
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@campaign_app.command("resume")
def campaign_resume(
    campaign_run_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Retry incomplete campaign sources. A verified source stays cached."""
    try:
        document = resume_campaign(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            campaign_run_id,
        )
    except (ClipforgeError, OSError) as exc:
        _fail(exc)
    typer.echo(document.campaign_run_id)
    typer.echo(document.status)
