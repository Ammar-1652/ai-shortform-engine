"""Campaign commands. Acquisition does not publish."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from clipforge.campaign.antoine import CAMPAIGN_ID
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
from clipforge.paths import resolve_work_dir

campaign_app = typer.Typer(no_args_is_help=True, help="Campaign policy, inventory, and acquisition.")


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
def campaign_list() -> None:
    """List known campaigns."""
    typer.echo(list_text())


@campaign_app.command("show")
def campaign_show(campaign_id: str) -> None:
    """Show one campaign policy binding."""
    if campaign_id != CAMPAIGN_ID:
        _fail(CampaignError("campaign is not in the local catalogue", code="missing_campaign"))
    typer.echo(show_text())


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
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Re-hash acquired sources. This command does not download."""
    if campaign_id != CAMPAIGN_ID:
        _fail(CampaignError("campaign is not in the local catalogue", code="missing_campaign"))
    try:
        typer.echo(verify_campaign(resolve_work_dir(work_dir)))
    except (ClipforgeError, OSError) as exc:
        _fail(exc)
