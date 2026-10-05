"""Asset discovery commands. Search does not download bytes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from clipforge.assets.mcp_client import AssetError
from clipforge.assets.provider import (
    DryRunAssetDiscoveryProvider,
    EnvatoMcpDiscoveryProvider,
    FakeAssetDiscoveryProvider,
)
from clipforge.assets.service import acquire_local, doctor_text, search_assets, verify_asset, write_requests
from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_work_dir
from clipforge.schemas.assets import AssetSearchHit

assets_app = typer.Typer(no_args_is_help=True, help="Discover external assets. Files stay manual.")
envato_app = typer.Typer(no_args_is_help=True, help="Query the Envato MCP catalogue.")
assets_app.add_typer(envato_app, name="envato")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


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
        hits = search_assets(_provider(provider), query=query, filters=filters, campaign_id=campaign_id)
        json_path, md_path = write_requests(
            resolve_work_dir(work_dir),
            hits,
            query=query,
            filters=filters,
            campaign_id=campaign_id,
        )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(f"json: {json_path.name}")
    typer.echo(f"markdown: {md_path.name}")
    typer.echo("download_status: manual_download_required")


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
