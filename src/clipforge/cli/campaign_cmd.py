"""Campaign commands. Acquisition does not publish."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from clipforge.campaign.acquisition import (
    list_acquisitions,
    plan_acquisition,
    resume_acquisition,
    run_acquisition,
    show_acquisition,
    verify_acquisition,
)
from clipforge.campaign.aggregate import (
    list_productions,
    produce,
    production_plan,
    production_report,
    resume_production,
    show_production,
    verify_production,
)
from clipforge.campaign.antoine import CAMPAIGN_ID
from clipforge.campaign.board import open_campaign_board
from clipforge.campaign.operator import (
    doctor_text as operator_doctor_text,
)
from clipforge.campaign.operator import (
    import_snapshot,
    list_sources_text,
    resume_run,
    run_selection,
    select_sources,
    status_text,
    verify_selection,
)
from clipforge.campaign.operator import (
    show_text as operator_show_text,
)
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
from clipforge.campaign.whop import (
    import_whop_snapshot,
    list_whop_imports,
    parse_whop_bytes,
    show_whop_campaign,
    verify_whop_import,
    whop_doctor,
)
from clipforge.campaign.whop_auth import doctor_text as whop_auth_doctor
from clipforge.campaign.whop_auth import login as whop_auth_login
from clipforge.campaign.whop_auth import logout as whop_auth_logout
from clipforge.campaign.whop_auth import refresh as whop_auth_refresh
from clipforge.campaign.whop_auth import refresh_tools as whop_tools_refresh
from clipforge.campaign.whop_auth import status_text as whop_auth_status
from clipforge.campaign.whop_auth import verify_tools as whop_tools_verify
from clipforge.campaign.whop_live import discover_live, discover_whop, select_whop_campaign, whop_capabilities
from clipforge.campaign.whop_tools import show_verified_tool_map as whop_tools_show
from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.schemas.whop_discovery import WhopLiveDiscoveryRequest
from clipforge.storage import Database

campaign_app = typer.Typer(no_args_is_help=True, help="Campaign policy, inventory, and production runs.")
operator_app = typer.Typer(no_args_is_help=True, help="Local operator selection and board.")
acquire_app = typer.Typer(no_args_is_help=True, help="Acquire selected sources into the work root.")
whop_app = typer.Typer(
    no_args_is_help=True,
    help="Import a local Whop snapshot or discover through an enabled connector.",
)
campaign_app.add_typer(operator_app, name="operator")
operator_app.add_typer(acquire_app, name="acquire")
operator_app.add_typer(whop_app, name="whop")
auth_app = typer.Typer(
    no_args_is_help=True,
    help="Operator Whop sign-in. Clipforge does not store credentials.",
)
whop_app.add_typer(auth_app, name="auth")
tools_app = typer.Typer(
    no_args_is_help=True,
    help="Verified Whop tool map. Credentials are not stored.",
)
whop_app.add_typer(tools_app, name="tools")


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


@auth_app.command("doctor")
def whop_auth_doctor_command() -> None:
    """Report the Whop sign-in helper. This does not open a browser."""
    typer.echo(whop_auth_doctor())


@auth_app.command("status")
def whop_auth_status_command() -> None:
    """Read saved sign-in metadata. This does not open a browser."""
    typer.echo(whop_auth_status())


@auth_app.command("login")
def whop_auth_login_command() -> None:
    """Prepare the dedicated profile. Password entry stays with the operator."""
    try:
        typer.echo(whop_auth_login())
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)


@auth_app.command("refresh")
def whop_auth_refresh_command() -> None:
    """Check the connector again. The dedicated profile stays in place."""
    try:
        typer.echo(whop_auth_refresh())
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)


@auth_app.command("logout")
def whop_auth_logout_command() -> None:
    """Remove the dedicated profile after confirmation."""
    confirmed = typer.confirm("Remove the dedicated Whop profile?")
    try:
        typer.echo(whop_auth_logout(confirmed=confirmed))
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)


@tools_app.command("verify")
def whop_tools_verify_command() -> None:
    """Re-read the local tool map. This does not open a socket."""
    try:
        typer.echo(whop_tools_verify())
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)


@tools_app.command("refresh")
def whop_tools_refresh_command() -> None:
    """Record official read-only tools after the connector is ready."""
    try:
        typer.echo(whop_tools_refresh())
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)


@tools_app.command("show")
def whop_tools_show_command() -> None:
    """Show verified tool names and hashes. The path is omitted."""
    try:
        typer.echo(whop_tools_show())
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)


@whop_app.command("doctor")
def whop_doctor_command() -> None:
    """Report Whop intake. Live account access stays unconfigured."""
    typer.echo(whop_doctor())


@whop_app.command("capabilities")
def whop_capabilities_command() -> None:
    """Show the connector boundary. This command does not write."""
    typer.echo(whop_capabilities().model_dump_json())


@whop_app.command("discover")
def whop_discover_command(
    project_id: Annotated[str | None, typer.Option("--project")] = None,
    operator_id: Annotated[str, typer.Option("--operator")] = "operator-1",
    request_path: Annotated[Path | None, typer.Option("--request")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    live: Annotated[bool, typer.Option("--live")] = False,
    connector: Annotated[
        str | None,
        typer.Option(
            "--connector",
            help="public, authenticated, or official-grok. authenticated is a loopback test double.",
        ),
    ] = None,
) -> None:
    """Report discovery. --live reads an enabled connector and stores no credentials."""
    if not live:
        try:
            payload = discover_whop()
        except (ClipforgeError, OSError, ValueError) as exc:
            _fail(exc)
        typer.echo(json.dumps(payload, sort_keys=True))
        return
    if project_id is None:
        _fail(CampaignError("whop project is required", code="missing_project"))
    request = None
    if request_path is not None:
        try:
            request = WhopLiveDiscoveryRequest.model_validate_json(request_path.read_text(encoding="utf-8"))
        except (ClipforgeError, OSError, ValueError) as exc:
            _fail(exc)
    try:
        attempt = discover_live(
            resolve_work_dir(work_dir),
            project_id=project_id,
            operator_id=operator_id,
            request=request,
            connector=connector,
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(attempt.discovery_id)
    typer.echo(f"evidence_origin: {attempt.evidence_origin}")
    typer.echo(f"live_claim: {attempt.live_claim}")
    typer.echo(f"whop_live: {attempt.live_status}")


@whop_app.command("select")
def whop_select_command(
    campaign_id: str,
    import_id: Annotated[str, typer.Option("--import")],
    project_id: Annotated[str, typer.Option("--project")],
    source_id: Annotated[list[str], typer.Option("--source")],
    operator_id: Annotated[str, typer.Option("--operator")] = "operator-1",
    language: Annotated[str, typer.Option("--language")] = "en-US",
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Select allowed sources from one import. This does not contact Whop."""
    try:
        evidence = select_whop_campaign(
            resolve_work_dir(work_dir),
            campaign_id=campaign_id,
            import_id=import_id,
            project_id=project_id,
            source_ids=source_id,
            operator_id=operator_id,
            language=language,
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(evidence.evidence_id)


@whop_app.command("import")
def whop_import_command(
    path: Annotated[Path, typer.Option("--file")],
    project_id: Annotated[str, typer.Option("--project")],
    force: Annotated[bool, typer.Option("--force")] = False,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Import a sanitized snapshot. Credentials are not stored and live transport is not claimed."""
    try:
        raw = path.read_bytes()
        snapshot = parse_whop_bytes(raw)
        attempt = import_whop_snapshot(
            resolve_work_dir(work_dir),
            raw,
            project_id=project_id,
            force=force,
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(attempt.import_id)
    typer.echo(f"whop_live: {attempt.whop_live}")
    typer.echo(f"intake_label: {snapshot.intake_label}")
    typer.echo(f"credentials_stored: {snapshot.credentials_stored}")
    typer.echo(f"live_transport: {snapshot.live_transport}")
    typer.echo(f"status: {attempt.status}")


@whop_app.command("list")
def whop_list_command(
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """List snapshot imports. This command does not write."""
    try:
        rows = list_whop_imports(resolve_work_dir(work_dir))
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(json.dumps([item.import_id for item in rows]))


@whop_app.command("show")
def whop_show_command(
    campaign_id: str,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show one imported campaign. This command does not write."""
    try:
        payload = show_whop_campaign(resolve_work_dir(work_dir), campaign_id)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(json.dumps(payload, sort_keys=True))


@whop_app.command("verify")
def whop_verify_command(
    import_id: str,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Re-check one import. This command does not write."""
    try:
        attempt = verify_whop_import(resolve_work_dir(work_dir), import_id)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(attempt.import_id)
    typer.echo(f"status: {attempt.status}")
    typer.echo(attempt.snapshot_sha256)


@operator_app.command("doctor")
def operator_doctor() -> None:
    """Read operator readiness. This command does not write."""
    typer.echo(operator_doctor_text())


@operator_app.command("list")
def operator_list() -> None:
    """List catalogue campaigns. This command does not write."""
    typer.echo(CAMPAIGN_ID)


@operator_app.command("show")
def operator_show(campaign_id: str) -> None:
    """Show one catalogue campaign. This command does not write."""
    try:
        typer.echo(operator_show_text(campaign_id))
    except ClipforgeError as exc:
        _fail(exc)


@operator_app.command("sources")
def operator_sources(campaign_id: str) -> None:
    """List catalogue sources. This command does not write."""
    try:
        typer.echo(list_sources_text(campaign_id))
    except ClipforgeError as exc:
        _fail(exc)


@operator_app.command("select")
def operator_select(
    campaign_id: str,
    source: Annotated[list[str], typer.Option("--source")],
    project_id: Annotated[str, typer.Option("--project")],
    operator_id: Annotated[str, typer.Option("--operator")],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    language: Annotated[str, typer.Option("--language")] = "en-US",
    narration: Annotated[bool, typer.Option("--narration/--no-narration")] = False,
    expect: Annotated[str | None, typer.Option("--expect")] = None,
) -> None:
    """Append one source selection. An identical selection is returned unchanged."""
    try:
        document = select_sources(
            resolve_work_dir(work_dir),
            campaign_id=campaign_id,
            source_ids=source,
            project_id=project_id,
            operator_id=operator_id,
            language=language,
            narration_enabled=narration,
            expected_sidecar_sha256=expect,
            database=Database(resolve_db_path(db)),
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(document.selection_id)
    typer.echo(document.status)


@operator_app.command("verify")
def operator_verify(
    selection_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Re-check one selection. This command does not write."""
    try:
        typer.echo(
            verify_selection(
                resolve_work_dir(work_dir),
                selection_id,
                database=Database(resolve_db_path(db)),
            )
        )
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@operator_app.command("run")
def operator_run(
    selection_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Run one selection through the existing campaign runner."""
    try:
        typer.echo(
            run_selection(
                Database(resolve_db_path(db)),
                resolve_work_dir(work_dir),
                selection_id,
                created_by="operator",
            )
        )
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@operator_app.command("resume")
def operator_resume(
    campaign_run_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Resume one production run. Only incomplete sources are retried."""
    try:
        typer.echo(
            resume_run(
                Database(resolve_db_path(db)),
                resolve_work_dir(work_dir),
                campaign_run_id,
                created_by="operator",
            )
        )
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@operator_app.command("status")
def operator_status(
    campaign_run_id: str,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show one production run. This command does not write."""
    try:
        typer.echo(status_text(resolve_work_dir(work_dir), campaign_run_id))
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@operator_app.command("import")
def operator_import(
    path: Annotated[Path, typer.Option("--file")],
    project_id: Annotated[str, typer.Option("--project")],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Import a local campaign snapshot. This does not contact an account."""
    try:
        document = import_snapshot(
            resolve_work_dir(work_dir),
            path.read_bytes(),
            database=Database(resolve_db_path(db)),
            project_id=project_id,
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(document.selection_id)


@acquire_app.command("plan")
def acquire_plan(
    selection_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Describe one acquisition. This command does not write."""
    try:
        typer.echo(plan_acquisition(Database(resolve_db_path(db)), resolve_work_dir(work_dir), selection_id))
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@acquire_app.command("run")
def acquire_run(
    selection_id: str,
    operator_id: Annotated[str, typer.Option("--operator")] = "operator",
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    expect: Annotated[str | None, typer.Option("--expect")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Acquire the sources in one selection. An unchanged attempt is reused."""
    try:
        document = run_acquisition(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            selection_id,
            operator_id=operator_id,
            force=force,
            expected_selection_sha256=expect,
        )
    except (ClipforgeError, OSError) as exc:
        _fail(exc)
    typer.echo(document.acquisition_id)
    typer.echo(document.status)


@acquire_app.command("list")
def acquire_list(
    campaign_id: str,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """List acquisition attempts. This command does not write."""
    try:
        for acquisition_id in list_acquisitions(resolve_work_dir(work_dir), campaign_id):
            typer.echo(acquisition_id)
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@acquire_app.command("show")
def acquire_show(
    acquisition_id: str,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show one acquisition attempt. This command does not write."""
    try:
        typer.echo(show_acquisition(resolve_work_dir(work_dir), acquisition_id))
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@acquire_app.command("verify")
def acquire_verify(
    acquisition_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Re-check one acquisition. This command does not write."""
    try:
        typer.echo(
            verify_acquisition(Database(resolve_db_path(db)), resolve_work_dir(work_dir), acquisition_id)
        )
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@acquire_app.command("resume")
def acquire_resume(
    acquisition_id: str,
    operator_id: Annotated[str, typer.Option("--operator")] = "operator",
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    expect: Annotated[str | None, typer.Option("--expect")] = None,
) -> None:
    """Retry incomplete sources. A verified source stays in place."""
    try:
        document = resume_acquisition(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            acquisition_id,
            operator_id=operator_id,
            expected_selection_sha256=expect,
        )
    except (ClipforgeError, OSError) as exc:
        _fail(exc)
    typer.echo(document.acquisition_id)
    typer.echo(document.status)


@operator_app.command("produce")
def operator_produce(
    selection_id: str,
    operator_id: Annotated[str, typer.Option("--operator")] = "operator",
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    expect: Annotated[str | None, typer.Option("--expect")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Produce one selection through the existing campaign runner."""
    try:
        document = produce(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            selection_id,
            operator_id=operator_id,
            force=force,
            expected_selection_sha256=expect,
        )
    except (ClipforgeError, OSError) as exc:
        _fail(exc)
    typer.echo(document.run_id)
    typer.echo(document.status)


@operator_app.command("production-plan")
def operator_production_plan(
    selection_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Describe a production. This command does not write."""
    try:
        typer.echo(production_plan(Database(resolve_db_path(db)), resolve_work_dir(work_dir), selection_id))
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@operator_app.command("production-show")
def operator_production_show(
    run_id: str,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show one production aggregate. This command does not write."""
    try:
        typer.echo(show_production(resolve_work_dir(work_dir), run_id))
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@operator_app.command("production-list")
def operator_production_list(
    campaign_id: str,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """List production aggregates. This command does not write."""
    try:
        for run_id in list_productions(resolve_work_dir(work_dir), campaign_id):
            typer.echo(run_id)
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@operator_app.command("production-verify")
def operator_production_verify(
    run_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Re-check one production aggregate. This command does not write."""
    try:
        typer.echo(verify_production(Database(resolve_db_path(db)), resolve_work_dir(work_dir), run_id))
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@operator_app.command("production-resume")
def operator_production_resume(
    run_id: str,
    operator_id: Annotated[str, typer.Option("--operator")] = "operator",
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    expect: Annotated[str | None, typer.Option("--expect")] = None,
) -> None:
    """Resume one production. Only incomplete pipeline sources are retried."""
    try:
        document = resume_production(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            run_id,
            operator_id=operator_id,
            expected_selection_sha256=expect,
        )
    except (ClipforgeError, OSError) as exc:
        _fail(exc)
    typer.echo(document.run_id)
    typer.echo(document.status)


@operator_app.command("production-report")
def operator_production_report(
    run_id: str,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Summarize one production. This command does not write."""
    try:
        typer.echo(production_report(resolve_work_dir(work_dir), run_id))
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@operator_app.command("serve")
def operator_serve(
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8772,
) -> None:
    """Serve the loopback campaign board. This server has no write route."""
    try:
        database_path = resolve_db_path(db)
        database = Database(database_path) if database_path.is_file() else None
        server = open_campaign_board(
            work_root=resolve_work_dir(work_dir),
            host=host,
            port=port,
            database=database,
        )
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(f"campaign_board: http://127.0.0.1:{server.server_address[1]}/")
    server.serve_forever()


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
