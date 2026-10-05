"""Asset discovery commands. Search does not download bytes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from clipforge.assets.handoff import (
    cancel_envato_asset,
    create_envato_requests,
    filters_for_provider,
    list_envato_assets,
    list_envato_requests,
    register_envato_asset,
    resume_envato_asset,
    show_envato_asset,
    verify_envato_asset,
)
from clipforge.assets.mcp_client import AssetError
from clipforge.assets.provider import (
    DryRunAssetDiscoveryProvider,
    EnvatoMcpDiscoveryProvider,
    FakeAssetDiscoveryProvider,
)
from clipforge.assets.service import acquire_local, doctor_text, search_assets, verify_asset, write_requests
from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.schemas.assets import AssetSearchHit
from clipforge.storage import Database

assets_app = typer.Typer(no_args_is_help=True, help="Discover external assets. Files stay manual.")
envato_app = typer.Typer(no_args_is_help=True, help="Query the Envato MCP catalogue.")
assets_app.add_typer(envato_app, name="envato")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


def _provider_names(name: str) -> tuple[str, str]:
    if name == "fake":
        return "fake", "fake"
    if name == "dry-run":
        return "dry_run", "dry_run"
    if name == "envato":
        return "envato_mcp", "envato_mcp"
    _fail(ClipforgeError("asset provider must be fake, dry-run, or envato"))


def _provider(
    name: str,
) -> FakeAssetDiscoveryProvider | DryRunAssetDiscoveryProvider | EnvatoMcpDiscoveryProvider:
    if name == "fake":
        return FakeAssetDiscoveryProvider()
    if name == "dry-run":
        return DryRunAssetDiscoveryProvider()
    if name == "envato":
        return EnvatoMcpDiscoveryProvider()
    _fail(ClipforgeError("asset provider must be fake, dry-run, or envato"))


def _filters(
    category: str,
    asset_type: str,
    asset_format: str,
    software: str,
    genre: str,
    style: str,
    duration: str,
    min_duration: int | None,
    max_duration: int | None,
    orientation: str,
    resolution: str,
    intended_use: str,
) -> dict[str, str]:
    pairs = {
        "category": category,
        "asset_type": asset_type,
        "format": asset_format,
        "compatible_software": software,
        "genre": genre,
        "style": style,
        "duration": duration,
        "min_duration": str(min_duration) if min_duration is not None else "",
        "max_duration": str(max_duration) if max_duration is not None else "",
        "orientation": orientation,
        "resolution": resolution,
        "intended_use": intended_use,
    }
    return {key: value for key, value in pairs.items() if value.strip()}


@assets_app.command("doctor")
def assets_doctor(provider: Annotated[str, typer.Option("--provider")] = "envato") -> None:
    """Report the MCP endpoint without exposing secrets."""
    try:
        typer.echo(doctor_text(_provider(provider)))
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@envato_app.command("search")
def envato_search(
    query: Annotated[str, typer.Option("--query")],
    campaign_id: Annotated[str, typer.Option("--campaign")] = "antoine-sallis",
    provider: Annotated[str, typer.Option("--provider")] = "dry-run",
    category: Annotated[str, typer.Option("--category")] = "",
    asset_type: Annotated[str, typer.Option("--asset-type")] = "",
    asset_format: Annotated[str, typer.Option("--format")] = "",
    software: Annotated[str, typer.Option("--software")] = "",
    genre: Annotated[str, typer.Option("--genre")] = "",
    style: Annotated[str, typer.Option("--style")] = "",
    duration: Annotated[str, typer.Option("--duration")] = "",
    min_duration: Annotated[int | None, typer.Option("--min-duration")] = None,
    max_duration: Annotated[int | None, typer.Option("--max-duration")] = None,
    orientation: Annotated[str, typer.Option("--orientation")] = "",
    resolution: Annotated[str, typer.Option("--resolution")] = "",
    intended_use: Annotated[str, typer.Option("--intended-use")] = "",
) -> None:
    """Search a catalogue. Missing metadata stays null."""
    filters = _filters(
        category,
        asset_type,
        asset_format,
        software,
        genre,
        style,
        duration,
        min_duration,
        max_duration,
        orientation,
        resolution,
        intended_use,
    )
    try:
        hits = search_assets(_provider(provider), query=query, filters=filters, campaign_id=campaign_id)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(json.dumps([hit.model_dump(mode="json") for hit in hits], sort_keys=True))


@envato_app.command("request")
def envato_request(
    query: Annotated[str, typer.Option("--query")],
    campaign_id: Annotated[str, typer.Option("--campaign")] = "antoine-sallis",
    provider: Annotated[str, typer.Option("--provider")] = "dry-run",
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    category: Annotated[str, typer.Option("--category")] = "",
    asset_type: Annotated[str, typer.Option("--asset-type")] = "",
    asset_format: Annotated[str, typer.Option("--format")] = "",
    software: Annotated[str, typer.Option("--software")] = "",
    genre: Annotated[str, typer.Option("--genre")] = "",
    style: Annotated[str, typer.Option("--style")] = "",
    duration: Annotated[str, typer.Option("--duration")] = "",
    min_duration: Annotated[int | None, typer.Option("--min-duration")] = None,
    max_duration: Annotated[int | None, typer.Option("--max-duration")] = None,
    orientation: Annotated[str, typer.Option("--orientation")] = "",
    resolution: Annotated[str, typer.Option("--resolution")] = "",
    intended_use: Annotated[str, typer.Option("--intended-use")] = "",
) -> None:
    """Write the manual download request. This does not fetch media."""
    filters = _filters(
        category,
        asset_type,
        asset_format,
        software,
        genre,
        style,
        duration,
        min_duration,
        max_duration,
        orientation,
        resolution,
        intended_use,
    )
    try:
        chosen = _provider(provider)
        hits = search_assets(chosen, query=query, filters=filters, campaign_id=campaign_id)
        root = resolve_work_dir(work_dir)
        supported, deferred = filters_for_provider(chosen, query, filters)
        sent_payload: dict[str, object] = {}
        sent_payload.update(supported)
        json_path, md_path = write_requests(
            root,
            hits,
            query=query,
            filters=filters,
            campaign_id=campaign_id,
            sent_filters=sent_payload,
            deferred_filters=deferred,
        )
        label, version = _provider_names(provider)
        stored = create_envato_requests(
            root,
            query=query,
            filters=filters,
            campaign_id=campaign_id,
            provider=label,
            provider_version=version,
            hits=hits,
            supported_filters=supported,
            deferred_filters=deferred,
            requested_duration=duration or None,
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(f"json: {json_path.name}")
    typer.echo(f"markdown: {md_path.name}")
    typer.echo("download_status: manual_download_required")
    for item in stored:
        typer.echo(f"request_id: {item.request_id}")


@envato_app.command("import-results")
def envato_import(
    path: Annotated[Path, typer.Argument()],
    campaign_id: Annotated[str, typer.Option("--campaign")] = "antoine-sallis",
) -> None:
    """Read a request file. This does not contact Envato."""
    from clipforge.assets.service import import_results

    try:
        hits = import_results(path, campaign_id=campaign_id)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(str(len(hits)))


@assets_app.command("acquire")
def assets_acquire(
    request_path: Annotated[Path, typer.Argument()],
    source: Annotated[Path, typer.Option("--source")],
    campaign_id: Annotated[str, typer.Option("--campaign")],
    license_statement: Annotated[str, typer.Option("--license")],
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Bind a local file to a request. Antoine stock assets are refused."""
    try:
        hit = acquire_local(
            resolve_work_dir(work_dir),
            request_path,
            source,
            license_statement=license_statement,
            campaign_id=campaign_id,
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(hit.model_dump_json())


@assets_app.command("verify")
def assets_verify(
    path: Annotated[Path, typer.Argument()],
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Re-hash a bound asset. This command does not search."""
    try:
        hit = AssetSearchHit.model_validate_json(path.read_text(encoding="utf-8"))
        typer.echo(verify_asset(resolve_work_dir(work_dir), hit))
    except (AssetError, ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)


@envato_app.command("requests")
def envato_requests(
    campaign_id: Annotated[str, typer.Option("--campaign")] = "antoine-sallis",
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """List manual download requests. This command does not write."""
    try:
        rows = list_envato_requests(resolve_work_dir(work_dir), campaign_id)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(json.dumps([item.model_dump(mode="json") for item in rows], sort_keys=True))


@envato_app.command("register")
def envato_register(
    request_id: Annotated[str, typer.Option("--request")],
    relative_file: Annotated[str, typer.Option("--file")],
    project_id: Annotated[str, typer.Option("--project")],
    license_relative: Annotated[str, typer.Option("--license-file")],
    rights: Annotated[str, typer.Option("--rights")] = "allowed",
    source_asset_id: Annotated[str | None, typer.Option("--source")] = None,
    expect_size: Annotated[int | None, typer.Option("--expect-size")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    asset_id: Annotated[str | None, typer.Option("--asset-id")] = None,
    cancel: Annotated[bool, typer.Option("--cancel")] = False,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Register a file the operator already placed under incoming."""
    try:
        registration = register_envato_asset(
            resolve_work_dir(work_dir),
            Database(resolve_db_path(db)),
            request_id,
            relative_file=relative_file,
            project_id=project_id,
            license_relative=license_relative,
            rights=rights,
            source_asset_id=source_asset_id,
            expect_size=expect_size,
            force=force,
            asset_id=asset_id,
            cancel=cancel,
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(registration.asset_id)
    typer.echo(f"acquisition_status: {registration.acquisition_status}")
    typer.echo(f"download_status: {registration.download_status}")


@envato_app.command("show")
def envato_show(
    asset_id: str,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show one registration. This command does not write."""
    try:
        registration = show_envato_asset(resolve_work_dir(work_dir), asset_id)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(registration.model_dump_json())


@envato_app.command("verify")
def envato_verify(
    asset_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Re-check one registration. This command does not write."""
    try:
        result = verify_envato_asset(resolve_work_dir(work_dir), Database(resolve_db_path(db)), asset_id)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(result.model_dump_json())
    if not result.renderable:
        raise typer.Exit(1)


@envato_app.command("list")
def envato_list(
    campaign_id: Annotated[str, typer.Option("--campaign")] = "antoine-sallis",
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """List registrations. This command does not write."""
    try:
        rows = list_envato_assets(resolve_work_dir(work_dir), campaign_id)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(json.dumps([item.asset_id for item in rows], sort_keys=True))


@envato_app.command("cancel")
def envato_cancel(
    asset_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Cancel an unverified registration and remove its partial file."""
    try:
        registration = cancel_envato_asset(resolve_work_dir(work_dir), Database(resolve_db_path(db)), asset_id)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(registration.acquisition_status)


@envato_app.command("resume")
def envato_resume(
    asset_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Continue a cancelled or failed registration."""
    try:
        registration = resume_envato_asset(resolve_work_dir(work_dir), Database(resolve_db_path(db)), asset_id)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(registration.asset_id)
    typer.echo(f"acquisition_status: {registration.acquisition_status}")
