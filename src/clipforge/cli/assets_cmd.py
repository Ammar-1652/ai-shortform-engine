"""Asset discovery commands. Search does not download bytes."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, NoReturn
from uuid import UUID

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
from clipforge.assets.local import LocalAssetKind, register_local_asset
from clipforge.assets.mcp_client import AssetError
from clipforge.assets.portal_bridge import EnvatoPortalBridge, extract_media_archive
from clipforge.assets.provider import (
    DryRunAssetDiscoveryProvider,
    EnvatoMcpDiscoveryProvider,
    FakeAssetDiscoveryProvider,
)
from clipforge.assets.service import acquire_local, doctor_text, search_assets, verify_asset, write_requests
from clipforge.campaign.policy_fingerprint import campaign_blocks_outside_media
from clipforge.cli.envato_auth_cmd import envato_auth_app
from clipforge.errors import ClipforgeError
from clipforge.media.workspace import mkdir_contained
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.schemas.assets import AssetSearchHit
from clipforge.storage import Database

assets_app = typer.Typer(no_args_is_help=True, help="Discover and register external assets.")
envato_app = typer.Typer(
    no_args_is_help=True, help="Query Envato and fetch explicitly selected licensed items."
)
assets_app.add_typer(envato_app, name="envato")
envato_app.add_typer(envato_auth_app, name="auth")


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


_PORTAL_ITEM_TYPES = {
    "audio": "music",
    "video": "video",
    "image": "photo",
    "graphic": "graphics",
    "font": "fonts",
}

_PORTAL_ITEM_TYPE_ALIASES = {
    "audio": {"music", "sound-effects"},
    "font": {"fonts", "font"},
    "video": {"video"},
    "image": {"photo"},
    "graphic": {"graphics"},
}


def _portal_item_type(media_kind: str) -> str:
    try:
        return _PORTAL_ITEM_TYPES[media_kind]
    except KeyError as exc:
        raise AssetError(
            f"portal download is not supported for media kind {media_kind!r}",
            code="unsupported_media",
        ) from exc


def _canonical_portal_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise AssetError(
            "portal item UUID is required and must be a UUID", code="portal_protocol_error"
        ) from exc
    return str(parsed)


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
        if provider == "envato":
            advertised_version = getattr(getattr(chosen, "client", None), "server_version", None)
            if isinstance(advertised_version, str) and advertised_version.strip():
                version = advertised_version.strip()
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


@envato_app.command("fetch")
def envato_fetch(
    request_id: Annotated[str, typer.Option("--request")],
    project_id: Annotated[str, typer.Option("--project")],
    portal_item_uuid: Annotated[
        str | None,
        typer.Option(
            "--portal-item-uuid", help="Optional UUID assertion; the MCP item page is resolved automatically."
        ),
    ] = None,
    license_name: Annotated[
        str | None, typer.Option("--license-name", help="Project name recorded on the Envato certificate.")
    ] = None,
    source_asset_id: Annotated[str | None, typer.Option("--source")] = None,
    content_tags: Annotated[list[str] | None, typer.Option("--tag")] = None,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Authenticate through the saved portal login, fetch, license, and register one MCP result.

    The MCP supplies catalogue metadata; portal page resolution binds that
    metadata to the item downloaded from the operator's subscription bridge.
    Signed URLs and cookies never appear in command output or artifacts.
    """
    root = resolve_work_dir(work_dir).resolve()
    try:
        requests = [item for item in list_envato_requests(root) if item.request_id == request_id]
        if len(requests) != 1:
            raise AssetError("envato request was not found", code="stale_request")
        request = requests[0]
        if request.provider != "envato_mcp":
            raise AssetError("portal fetch requires an Envato MCP request", code="invalid_document")
        if campaign_blocks_outside_media(request.campaign_id):
            raise AssetError("outside media is prohibited by campaign policy", code="policy_blocked")
        requested_uuid = _canonical_portal_uuid(portal_item_uuid) if portal_item_uuid else None
        if request.media_kind not in _PORTAL_ITEM_TYPES:
            raise AssetError(
                "request media kind has no portal item-type mapping",
                code="unsupported_media",
            )
        project_name = license_name or f"clipforge-{request.request_id[:24]}"
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{1,100}", project_name):
            raise AssetError("license name contains unsupported characters", code="invalid_document")
        session_root = root.joinpath("campaigns", "envato-requests", request.request_id, "portal")
        incoming_root = root.joinpath("incoming", "envato-portal", request.request_id)
        mkdir_contained(root, session_root)
        mkdir_contained(root, incoming_root)
        archive = session_root / "download.zip"
        media_staging = incoming_root / "media"
        license_staging = incoming_root / "license.pdf"
        bridge = EnvatoPortalBridge()
        bridge.authenticate()
        if request.item_page_url is None:
            raise AssetError("MCP request has no item page URL to bind", code="missing_item_identity")
        identity = bridge.resolve_item(request.item_page_url)
        expected_type = _portal_item_type(request.media_kind)
        if requested_uuid is not None and identity.item_uuid != requested_uuid:
            raise AssetError("portal UUID does not match the MCP item page", code="portal_item_mismatch")
        allowed_types = _PORTAL_ITEM_TYPE_ALIASES.get(request.media_kind, {expected_type})
        if identity.item_type not in allowed_types:
            raise AssetError("portal item type does not match the MCP request", code="portal_item_mismatch")
        if request.item_id is not None and request.item_id not in {identity.item_id, identity.item_uuid}:
            raise AssetError("portal item identity does not match MCP metadata", code="portal_item_mismatch")
        item_uuid = identity.item_uuid
        downloaded = bridge.fetch_item(
            item_uuid=item_uuid,
            item_type=identity.item_type,
            project_name=project_name,
            media_path=archive,
            license_path=license_staging,
        )
        media_path, media_bytes, media_hash = extract_media_archive(
            downloaded.media_path,
            media_staging,
            media_kind=request.media_kind,
            max_bytes=request.max_bytes,
        )
        relative_media = media_path.resolve().relative_to(root).as_posix()
        relative_license = license_staging.resolve().relative_to(root).as_posix()
        registration = register_envato_asset(
            root,
            Database(resolve_db_path(db)),
            request.request_id,
            relative_file=relative_media,
            project_id=project_id,
            license_relative=relative_license,
            rights="allowed",
            source_asset_id=source_asset_id,
            expect_size=media_bytes,
            content_tags=content_tags,
            download_status="portal_download_verified",
            portal_item_uuid=item_uuid,
            portal_license_id=downloaded.license.license_id,
        )
    except (AssetError, ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(f"request_id: {request.request_id}")
    typer.echo(f"portal_item_uuid: {item_uuid}")
    typer.echo(f"media: {relative_media}")
    typer.echo(f"media_bytes: {media_bytes}")
    typer.echo(f"media_sha256: {media_hash}")
    typer.echo(f"license: {relative_license}")
    typer.echo(f"license_sha256: {downloaded.license_sha256}")
    typer.echo(f"asset_id: {registration.asset_id}")
    typer.echo(f"acquisition_status: {registration.acquisition_status}")
    typer.echo(f"download_status: {registration.download_status}")


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
    content_tags: Annotated[list[str] | None, typer.Option("--tag")] = None,
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
            content_tags=content_tags,
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


@assets_app.command("register-local")
def assets_register_local(
    project_id: Annotated[str, typer.Option("--project")],
    source_asset_ids: Annotated[
        list[str], typer.Option("--source-asset-id", help="Source catalog to receive the asset; repeatable.")
    ],
    relative_file: Annotated[str, typer.Option("--file", help="Path relative to the work root.")],
    license_relative: Annotated[
        str, typer.Option("--license-file", help="Rights evidence path relative to the work root.")
    ],
    kind: Annotated[LocalAssetKind, typer.Option("--kind", help="graphic or audio.")],
    confirm_rights: Annotated[bool, typer.Option("--confirm-rights")] = False,
    content_tags: Annotated[list[str] | None, typer.Option("--tag")] = None,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Register campaign-provided local material in Advanced Hero catalogs.

    This command never searches or downloads. It records a hash, campaign
    rights evidence, and a source-bound catalog entry for each selected source.
    """
    if not source_asset_ids:
        _fail(ClipforgeError("at least one --source-asset-id is required"))
    try:
        registrations = [
            register_local_asset(
                database=Database(resolve_db_path(db)),
                work_root=resolve_work_dir(work_dir),
                project_id=project_id,
                source_asset_id=source_asset_id,
                relative_file=relative_file,
                license_relative=license_relative,
                kind=kind,
                confirm_rights=confirm_rights,
                content_tags=content_tags,
            )
            for source_asset_id in source_asset_ids
        ]
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(
        json.dumps(
            [
                {
                    "asset_id": item.asset_id,
                    "license_record_id": item.license_record_id,
                    "source_asset_id": item.source_asset_id,
                    "relative_path": item.relative_path,
                    "sha256": item.sha256,
                    "kind": item.kind,
                    "cache_status": item.cache_status,
                }
                for item in registrations
            ],
            sort_keys=True,
        )
    )


@assets_app.command("verify-local")
def assets_verify_local(
    source_asset_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Rehash local campaign assets and evidence via the production asset gate."""
    from clipforge.hero.advanced_assets import load_catalog, require_asset
    from clipforge.media.workspace import SourceWorkspace, advanced_read_lock
    from clipforge.storage import get_source_asset

    try:
        database = Database(resolve_db_path(db))
        root = resolve_work_dir(work_dir).resolve()
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
        workspace = SourceWorkspace(root, source.project_id, source_asset_id)
        with advanced_read_lock(workspace):
            entries = [
                entry
                for entry in load_catalog(workspace)
                if entry.reference.provenance.tool == "clipforge.assets.local"
            ]
            if not entries:
                raise ClipforgeError("no registered local campaign assets for this source")
            for entry in entries:
                require_asset(
                    database,
                    workspace,
                    project_id=source.project_id,
                    asset_id=entry.reference.asset_id,
                    expected_kind=entry.reference.kind.value,
                    work_root=root,
                )
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(f"verified_local_assets: {len(entries)}")
    typer.echo("scope: bytes, rights and evidence only; not campaign compliance or editorial approval")


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
