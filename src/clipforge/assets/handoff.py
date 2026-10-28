"""Manual Envato registration. Item pages are not downloaded media."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from clipforge.assets.filters import SUPPORTED_ENVATO_FIELDS, search_arguments
from clipforge.assets.mcp_client import AssetError
from clipforge.campaign.policy_fingerprint import campaign_blocks_outside_media, current_policy_fingerprint
from clipforge.errors import MediaError, StorageError
from clipforge.media.clock import seconds_text_to_us
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_to_file_uri
from clipforge.media.probe import probe_file, read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.media.workspace import SourceWorkspace, ensure_within, mkdir_contained
from clipforge.schemas.acquisition import ProbeFacts
from clipforge.schemas.assets import AssetSearchHit
from clipforge.schemas.envato_asset import (
    EnvatoAssetCacheRecord,
    EnvatoAssetRegistration,
    EnvatoAssetRequest,
    EnvatoAssetVerification,
)
from clipforge.schemas.governance import AssetLicenseRecord, RightsStatus
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import (
    Database,
    get_asset_license_record,
    get_job,
    insert_asset_license_record,
    insert_job,
    update_job,
)

_ModelT = TypeVar("_ModelT", bound=BaseModel)

_KIND = "envato_asset_registration"
_REQUESTS = ("campaigns", "envato-requests")
_ASSETS = ("campaigns", "envato-assets")
_STOCK_SPEC: dict[str, Any] = {
    "name": "search_stock_video",
    "inputSchema": {
        "properties": {
            "searchTerms": {"type": "string", "minLength": 1, "maxLength": 200},
            "perPage": {"type": "integer", "minimum": 1, "maximum": 20},
            "page": {"type": "integer", "minimum": 1, "maximum": 50},
            "filters": {
                "type": "object",
                "properties": {
                    "orientation": {"type": "string", "enum": ["horizontal", "vertical"]},
                    "resolution": {"type": "string", "enum": ["1080p (Full HD)", "720p (HD)", "4K (UHD)"]},
                    "categories": {"type": "string", "enum": ["Stock Footage", "Motion Graphics"]},
                    "min_media_length": {"type": "integer", "minimum": 0, "maximum": 3600},
                    "max_media_length": {"type": "integer", "minimum": 0, "maximum": 3600},
                },
            },
        },
        "required": ["searchTerms"],
    },
}
_ALLOWED_AUDIO_CODECS = {
    "aac",
    "flac",
    "mp2",
    "mp3",
    "opus",
    "pcm_f32be",
    "pcm_f32le",
    "pcm_s16be",
    "pcm_s16le",
    "pcm_s24be",
    "pcm_s24le",
    "pcm_s32be",
    "pcm_s32le",
    "vorbis",
}


def _filter_is_sent(key: str, deferred: dict[Any, Any], report: dict[Any, Any]) -> bool:
    skipped = {"tool_selection", "local_context_only", "post_filter"}
    return key not in deferred and report.get(key) not in skipped


def split_filters(
    query: str,
    filters: dict[str, str],
    spec: dict[str, Any] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Split filters with the selected tool schema. Unsupported keys stay local."""
    tool = spec if spec is not None else _STOCK_SPEC
    _arguments, report, deferred = search_arguments(tool, query, filters)
    supported = {key: value for key, value in filters.items() if _filter_is_sent(key, deferred, report)}
    return supported, deferred


def filters_for_provider(
    provider: object, query: str, filters: dict[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Use the provider's last search split when it has one. Otherwise stay offline."""
    deferred = getattr(provider, "last_deferred", None)
    report = getattr(provider, "last_report", None)
    if isinstance(deferred, dict) and isinstance(report, dict) and report:
        supported = {key: value for key, value in filters.items() if _filter_is_sent(key, deferred, report)}
        return supported, {str(key): str(value) for key, value in deferred.items()}
    del query
    return _offline_filter_split(filters)


def _offline_filter_split(filters: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Classify filters without a network call when no tool schema was consulted."""
    kind = filters.get("asset_type", "video")
    if kind == "audio":
        tool_name = "search_sound_effects"
    elif kind == "font":
        tool_name = "search_fonts"
    else:
        tool_name = "search_stock_video"
    explicit = SUPPORTED_ENVATO_FIELDS.get(tool_name, {})
    supported: dict[str, str] = {}
    deferred: dict[str, str] = {}
    for key, value in filters.items():
        if key in {"asset_type", "item_type", "intended_use"}:
            continue
        if key in explicit:
            supported[key] = value
        else:
            deferred[key] = value
    return supported, deferred


def create_envato_requests(
    work_root: Path,
    *,
    query: str,
    filters: dict[str, str],
    campaign_id: str,
    provider: str,
    provider_version: str,
    hits: list[AssetSearchHit],
    supported_filters: dict[str, str],
    deferred_filters: dict[str, str],
    requested_duration: str | None = None,
    expected_codec: str | None = None,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_frame_rate: str | None = None,
    max_bytes: int = 200_000_000,
) -> list[EnvatoAssetRequest]:
    """Persist manual download requests. Missing provider fields stay null."""
    root = work_root.resolve()
    now = datetime.now(UTC)
    fingerprint = current_policy_fingerprint(campaign_id)
    rows: list[AssetSearchHit | None] = list(hits) if hits else [None]
    stored: list[EnvatoAssetRequest] = []
    for hit in rows:
        request_id = hit.request_id if hit is not None else f"envreq-{uuid4().hex[:12]}"
        kind = _media_kind(hit, filters)
        request = EnvatoAssetRequest(
            request_id=request_id,
            provider=provider,  # type: ignore[arg-type]
            provider_version=provider_version,
            query=query,
            supported_filters=supported_filters,
            deferred_filters=deferred_filters,
            item_page_url=None if hit is None else hit.item_url,
            item_id=None if hit is None else hit.item_id,
            direct_download_url=None if hit is None else hit.direct_download_url,
            media_kind=kind,  # type: ignore[arg-type]
            intended_use=filters.get("intended_use") or "unspecified",
            campaign_id=campaign_id,
            policy_fingerprint=fingerprint,
            requested_format=filters.get("format"),
            requested_resolution=filters.get("resolution"),
            requested_duration=requested_duration,
            expected_codec=expected_codec,
            expected_width=expected_width,
            expected_height=expected_height,
            expected_frame_rate=expected_frame_rate,
            max_bytes=max_bytes,
            created_at=now,
        )
        path = root.joinpath(*_REQUESTS, request.request_id, "request.json")
        _write_json(root, path, request.model_dump_json())
        stored.append(request)
    return stored


def list_envato_requests(work_root: Path, campaign_id: str | None = None) -> list[EnvatoAssetRequest]:
    return [
        item
        for item in _read_models(work_root, _REQUESTS, "request.json", EnvatoAssetRequest)
        if campaign_id is None or item.campaign_id == campaign_id
    ]


def register_envato_asset(
    work_root: Path,
    database: Database,
    request_id: str,
    *,
    relative_file: str,
    project_id: str,
    license_relative: str,
    rights: str,
    source_asset_id: str | None = None,
    expect_size: int | None = None,
    force: bool = False,
    asset_id: str | None = None,
    cancel: bool = False,
    content_tags: list[str] | None = None,
    download_status: Literal[
        "manual_download_required", "portal_download_verified"
    ] = "manual_download_required",
    portal_item_uuid: str | None = None,
    portal_license_id: str | None = None,
    promotion_hook: Callable[[str], None] | None = None,
) -> EnvatoAssetRegistration:
    """Promote a file the operator already placed under incoming."""
    root = work_root.resolve()
    request = _load_request(root, request_id)
    _assert_request_current(request)
    if campaign_blocks_outside_media(request.campaign_id):
        raise AssetError("outside media is prohibited by campaign policy", code="policy_blocked")
    incoming = _confine(root, relative_file, require_incoming=True)
    evidence = _confine(root, license_relative, require_incoming=False)
    _assert_rights(rights)
    if not evidence.read_bytes().strip():
        raise AssetError("license evidence is missing", code="missing_license_evidence")
    digest = sha256_file(incoming)
    size = incoming.stat().st_size
    if expect_size is not None and size != expect_size:
        raise AssetError("file size does not match", code="size_mismatch")
    if size <= 0 or size > request.max_bytes:
        raise AssetError("file exceeds the campaign byte limit", code="file_size_limit")
    requested_tags = None if content_tags is None else list(_normalize_content_tags(content_tags))
    if not force and asset_id is None and not cancel:
        cached = _cache_hit(root, request, project_id, digest, size, requested_tags, portal_item_uuid)
        if cached is not None:
            return cached.model_copy(update={"cache_status": "hit"})
    chosen = (
        asset_id
        if asset_id is not None and not force
        else _asset_id(digest, force, requested_tags, portal_item_uuid)
    )
    stored_tags = list(requested_tags or [])
    if cancel:
        return _write_cancelled(
            root,
            database,
            request,
            chosen,
            project_id,
            relative_file,
            license_relative,
            rights,
            size,
            digest,
            stored_tags,
        )
    return _promote(
        root,
        database,
        request,
        chosen,
        project_id,
        incoming,
        evidence,
        source_asset_id,
        digest,
        size,
        relative_file,
        promotion_hook,
        stored_tags,
        download_status,
        portal_item_uuid,
        portal_license_id,
    )


def resume_envato_asset(
    work_root: Path,
    database: Database,
    asset_id: str,
    *,
    promotion_hook: Callable[[str], None] | None = None,
) -> EnvatoAssetRegistration:
    """Continue a cancelled or failed registration. A verified asset is not rewritten."""
    root = work_root.resolve()
    current = _load_registration(root, asset_id)
    if current.acquisition_status == "verified":
        return current.model_copy(update={"cache_status": "hit"})
    if current.incoming_relative is None or current.license_evidence is None:
        raise AssetError("envato registration cannot be resumed", code="missing_asset")
    return register_envato_asset(
        root,
        database,
        current.request_id,
        relative_file=current.incoming_relative,
        project_id=current.project_id,
        license_relative=current.license_evidence,
        rights="allowed",
        asset_id=asset_id,
        content_tags=current.content_tags,
        download_status=current.download_status,
        portal_item_uuid=current.portal_item_uuid,
        portal_license_id=current.portal_license_id,
        promotion_hook=promotion_hook,
    )


def cancel_envato_asset(work_root: Path, database: Database, asset_id: str) -> EnvatoAssetRegistration:
    """Mark an unverified registration cancelled and remove its partial file."""
    root = work_root.resolve()
    current = _load_registration(root, asset_id)
    if current.acquisition_status == "verified":
        raise AssetError("a verified envato asset is not cancelled", code="invalid_document")
    _remove_partials(root, asset_id)
    cancelled = current.model_copy(
        update={"acquisition_status": "cancelled", "failure_code": "cancelled", "relative_path": None}
    )
    _write_json(root, _manifest_path(root, asset_id), cancelled.model_dump_json())
    _mark_job(database, current.project_id, current.producer_job_id, JobStatus.CANCELLED, None)
    return cancelled


def show_envato_asset(work_root: Path, asset_id: str) -> EnvatoAssetRegistration:
    return _load_registration(work_root.resolve(), asset_id)


def list_envato_assets(work_root: Path, campaign_id: str | None = None) -> list[EnvatoAssetRegistration]:
    return [
        item
        for item in _read_models(work_root, _ASSETS, "manifest.json", EnvatoAssetRegistration)
        if campaign_id is None or item.campaign_id == campaign_id
    ]


def verify_envato_asset(work_root: Path, database: Database, asset_id: str) -> EnvatoAssetVerification:
    """Re-check one asset. Files and the database stay as they were."""
    root = work_root.resolve()
    try:
        registration = _load_registration(root, asset_id)
    except AssetError as exc:
        return _verification(asset_id, "missing", exc.code, None, False, exc.code)
    try:
        checked = assert_envato_registration(
            root,
            database,
            asset_id,
            project_id=registration.project_id,
            file_sha256=registration.sha256 or "",
        )
    except MediaError as exc:
        reason = _reason_from_message(str(exc))
        return _verification(
            asset_id,
            "failed" if registration.acquisition_status == "failed" else "stale",
            reason,
            registration,
            False,
            reason,
        )
    return _verification(asset_id, "verified", "verified", checked, True, None)


def assert_envato_registration(
    work_root: Path,
    database: Database,
    asset_id: str,
    *,
    project_id: str,
    file_sha256: str,
) -> EnvatoAssetRegistration:
    """Fail closed before an Advanced Hero render job can be inserted."""
    try:
        registration = _load_registration(work_root, asset_id)
    except AssetError as exc:
        raise MediaError(f"advanced asset {asset_id} is not registered") from exc
    incomplete = registration.acquisition_status != "verified" or registration.sha256 is None
    if incomplete or registration.relative_path is None:
        raise MediaError(f"advanced asset {asset_id} is not verified")
    if registration.project_id != project_id:
        raise MediaError(f"advanced asset {asset_id} belongs to another project")
    if registration.rights_status != "allowed":
        raise MediaError(f"advanced asset {asset_id} rights status is {registration.rights_status}")
    if not registration.license_evidence:
        raise MediaError(f"advanced asset {asset_id} license evidence is missing")
    if registration.sha256 != file_sha256:
        raise MediaError(f"advanced asset {asset_id} hash does not match the registration")
    if registration.policy_fingerprint != current_policy_fingerprint(registration.campaign_id):
        raise MediaError(f"advanced asset {asset_id} policy is stale")
    path = _confine(work_root.resolve(), registration.relative_path, require_incoming=False)
    if sha256_file(path) != registration.sha256 or path.stat().st_size != registration.byte_size:
        raise MediaError(f"advanced asset {asset_id} bytes changed after registration")
    evidence = _confine(work_root.resolve(), registration.license_evidence, require_incoming=False)
    if not evidence.read_bytes().strip():
        raise MediaError(f"advanced asset {asset_id} license evidence is missing")
    try:
        request = _load_request(work_root.resolve(), registration.request_id)
    except AssetError as exc:
        raise MediaError(f"advanced asset {asset_id} request is stale") from exc
    policy_differs = request.policy_fingerprint != registration.policy_fingerprint
    url_differs = request.item_page_url != registration.item_page_url
    if policy_differs or url_differs:
        raise MediaError(f"advanced asset {asset_id} request is stale")
    try:
        with database.connect() as connection:
            job = get_job(connection, registration.producer_job_id)
    except StorageError as exc:
        raise MediaError(f"advanced asset {asset_id} producer job is missing") from exc
    if job.status is not JobStatus.SUCCEEDED or job.project_id != project_id:
        raise MediaError(f"advanced asset {asset_id} producer job did not succeed")
    return registration


def envato_campaign_board(
    work_root: Path,
    campaign_id: str,
    database: Database | None,
) -> dict[str, object]:
    requests = list_envato_requests(work_root, campaign_id)
    assets = [_asset_public(work_root, item, database) for item in list_envato_assets(work_root, campaign_id)]
    deferred: dict[str, str] = {}
    for request in requests:
        deferred.update(request.deferred_filters)
    payload: dict[str, object] = {
        "requests": [_request_public(item) for item in requests],
        "deferred_filters": deferred,
        "handoff_assets": assets,
    }
    _reject_public(payload)
    return payload


def envato_asset_board(work_root: Path, asset_id: str, database: Database | None) -> dict[str, object]:
    registration = _load_registration(work_root.resolve(), asset_id)
    payload = _asset_public(work_root, registration, database)
    _reject_public(payload)
    return payload


def campaign_asset_board(work_root: Path, campaign_id: str, database: Database | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "campaign_id": campaign_id,
        "assets": [
            _asset_public(work_root, item, database) for item in list_envato_assets(work_root, campaign_id)
        ],
        "publishing": "deferred",
    }
    _reject_public(payload)
    return payload


def _promote(
    root: Path,
    database: Database,
    request: EnvatoAssetRequest,
    asset_id: str,
    project_id: str,
    incoming: Path,
    evidence: Path,
    source_asset_id: str | None,
    digest: str,
    size: int,
    incoming_relative: str,
    hook: Callable[[str], None] | None,
    content_tags: list[str],
    download_status: Literal["manual_download_required", "portal_download_verified"],
    portal_item_uuid: str | None,
    portal_license_id: str | None,
) -> EnvatoAssetRegistration:
    final = root.joinpath(*_ASSETS, asset_id, "media", incoming.name)
    manifest = _manifest_path(root, asset_id)
    catalog = _catalog_path(root, project_id, source_asset_id)
    previous_media = _read_bytes(final)
    previous_manifest = _read_bytes(manifest)
    previous_catalog = _read_bytes(catalog) if catalog is not None else None
    staging = final.with_name(final.name + ".partial")
    job_id = str(uuid4())
    started = False
    try:
        _copy_file(root, incoming, staging)
        if sha256_file(staging) != digest:
            raise AssetError("staged bytes changed", code="source_changed")
        _insert_running(database, project_id, job_id, asset_id, digest, request)
        started = True
        facts = _inspect(root, staging, request)
        _hook(hook, "staging_write")
        _hook(hook, "database_insert")
        _hook(hook, "final_rename")
        mkdir_contained(root, final.parent)
        os.replace(staging, final)
        evidence_relative = _store_evidence(root, asset_id, evidence)
        relative = final.resolve().relative_to(root).as_posix()
        now = datetime.now(UTC)
        registration = EnvatoAssetRegistration(
            asset_id=asset_id,
            request_id=request.request_id,
            campaign_id=request.campaign_id,
            project_id=project_id,
            item_page_url=request.item_page_url,
            item_id=request.item_id,
            portal_item_uuid=portal_item_uuid,
            portal_license_id=portal_license_id,
            relative_path=relative,
            byte_size=size,
            sha256=digest,
            probe=facts,
            license_evidence=evidence_relative,
            rights_status="allowed",
            provider_version=request.provider_version,
            acquisition_status="verified",
            producer_job_id=job_id,
            policy_fingerprint=request.policy_fingerprint,
            media_kind=request.media_kind,
            content_tags=content_tags,
            direct_download_url=request.direct_download_url,
            download_status=download_status,
            cache_status="miss",
            incoming_relative=incoming_relative,
            created_at=now,
        )
        _write_json(root, manifest, registration.model_dump_json())
        _write_checksum(root, asset_id, digest, relative)
        _insert_license(database, registration, now)
        _finish_job(database, project_id, job_id, asset_id, digest, request, JobStatus.SUCCEEDED, None)
        if source_asset_id is not None and catalog is not None:
            _write_catalog(root, catalog, registration, source_asset_id)
        _write_cache(root, registration, now)
        return registration
    except Exception as exc:
        _remove_file(staging)
        _restore(final, previous_media)
        _restore(manifest, previous_manifest)
        if catalog is not None:
            _restore(catalog, previous_catalog)
        code = exc.code if isinstance(exc, AssetError) else "promotion_failed"
        if started:
            _fail_job(database, project_id, job_id, code)
        if previous_manifest is None:
            evidence_relative = evidence.resolve().relative_to(root).as_posix()
            _write_failure(
                root,
                request,
                asset_id,
                project_id,
                job_id,
                code,
                size,
                digest,
                incoming_relative,
                evidence_relative,
            )
        if isinstance(exc, AssetError):
            raise
        raise AssetError("envato promotion failed", code="promotion_failed") from exc


def _write_cancelled(
    root: Path,
    database: Database,
    request: EnvatoAssetRequest,
    asset_id: str,
    project_id: str,
    incoming_relative: str,
    license_relative: str,
    rights: str,
    size: int,
    digest: str,
    content_tags: list[str],
) -> EnvatoAssetRegistration:
    now = datetime.now(UTC)
    job_id = str(uuid4())
    registration = EnvatoAssetRegistration(
        asset_id=asset_id,
        request_id=request.request_id,
        campaign_id=request.campaign_id,
        project_id=project_id,
        item_page_url=request.item_page_url,
        item_id=request.item_id,
        byte_size=size,
        sha256=digest,
        rights_status=rights,  # type: ignore[arg-type]
        provider_version=request.provider_version,
        acquisition_status="cancelled",
        producer_job_id=job_id,
        policy_fingerprint=request.policy_fingerprint,
        media_kind=request.media_kind,
        content_tags=content_tags,
        direct_download_url=request.direct_download_url,
        failure_code="cancelled",
        incoming_relative=incoming_relative,
        license_evidence=license_relative,
        created_at=now,
    )
    _insert_running(database, project_id, job_id, asset_id, digest, request)
    _mark_job(database, project_id, job_id, JobStatus.CANCELLED, None)
    _write_json(root, _manifest_path(root, asset_id), registration.model_dump_json())
    return registration


def _write_failure(
    root: Path,
    request: EnvatoAssetRequest,
    asset_id: str,
    project_id: str,
    job_id: str,
    code: str,
    size: int,
    digest: str,
    incoming_relative: str,
    license_relative: str,
) -> None:
    now = datetime.now(UTC)
    registration = EnvatoAssetRegistration(
        asset_id=asset_id,
        request_id=request.request_id,
        campaign_id=request.campaign_id,
        project_id=project_id,
        item_page_url=request.item_page_url,
        item_id=request.item_id,
        byte_size=size,
        sha256=digest,
        rights_status="allowed",
        provider_version=request.provider_version,
        acquisition_status="failed",
        producer_job_id=job_id,
        policy_fingerprint=request.policy_fingerprint,
        media_kind=request.media_kind,
        failure_code=code,
        incoming_relative=incoming_relative,
        license_evidence=license_relative,
        created_at=now,
    )
    try:
        _write_json(root, _manifest_path(root, asset_id), registration.model_dump_json())
    except (AssetError, OSError):
        return


def _inspect(root: Path, path: Path, request: EnvatoAssetRequest) -> ProbeFacts:
    _confine(root, path.resolve().relative_to(root).as_posix(), require_incoming=False)
    if request.media_kind == "audio":
        return _inspect_audio_asset(root, path, request)
    if request.media_kind == "font":
        return _inspect_font_asset(root, path, request)
    try:
        _raw, normalized = probe_file(
            path, ProcessRunner(), video_override=None, audio_override=None, log_path=None
        )
    except MediaError as exc:
        raise AssetError("media could not be probed", code="corrupt_media") from exc
    try:
        ProcessRunner().run(
            [resolve_ffmpeg(), "-v", "error", "-i", str(path), "-f", "null", "-"],
            log_path=None,
            check=True,
        )
    except MediaError as exc:
        raise AssetError("media could not be decoded", code="corrupt_media") from exc
    video = normalized.video_streams[0] if normalized.video_streams else None
    audio = normalized.audio_streams[0] if normalized.audio_streams else None
    if request.media_kind in {"video", "graphic", "image"} and video is None:
        raise AssetError("video stream is missing", code="unsupported_media")
    video_codec = None if video is None else video.codec_name
    audio_codec = None if audio is None else audio.codec_name
    if request.media_kind in {"video", "graphic", "image"} and video_codec != "h264":
        raise AssetError("video codec is not allowed", code="unsupported_codec")
    if audio is not None and audio_codec not in _ALLOWED_AUDIO_CODECS:
        raise AssetError("audio codec is not allowed", code="unsupported_codec")
    if request.expected_codec not in {None, video_codec, audio_codec}:
        raise AssetError("codec does not match the request", code="unsupported_codec")
    width = None if video is None else video.width
    height = None if video is None else video.height
    if request.expected_width is not None and width != request.expected_width:
        raise AssetError("dimensions do not match the request", code="unsupported_media")
    if request.expected_height is not None and height != request.expected_height:
        raise AssetError("dimensions do not match the request", code="unsupported_media")
    _expect_resolution(request.requested_resolution, width, height)
    frame_rate = None
    if video is not None and video.avg_frame_rate is not None:
        frame_rate = f"{video.avg_frame_rate.numerator}/{video.avg_frame_rate.denominator}"
    if request.expected_frame_rate is not None and frame_rate != request.expected_frame_rate:
        raise AssetError("frame rate does not match the request", code="unsupported_media")
    duration = normalized.timeline.canonical_duration_us
    _expect_duration(request.requested_duration, duration)
    format_name = None if normalized.format.format_name is None else normalized.format.format_name.split(",")[0]
    try:
        return ProbeFacts(
            duration_us=duration,
            width=width,
            height=height,
            video_codec=video_codec,
            audio_codec=audio_codec,
            frame_rate=frame_rate,
            sample_rate=None if audio is None else audio.sample_rate,
            format_name=format_name,
        )
    except ValidationError as exc:
        raise AssetError("probe facts were rejected", code="corrupt_media") from exc


def _inspect_audio_asset(root: Path, path: Path, request: EnvatoAssetRequest) -> ProbeFacts:
    """Probe a standalone SFX/music file without forcing it through video ingest."""
    try:
        payload = read_ffprobe_json(path, ProcessRunner(), log_path=None)
    except MediaError as exc:
        raise AssetError("media could not be probed", code="corrupt_media") from exc
    streams = payload.get("streams")
    audio_streams = (
        [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"]
        if isinstance(streams, list)
        else []
    )
    if not audio_streams:
        raise AssetError("audio stream is missing", code="unsupported_media")
    audio = audio_streams[0]
    codec = audio.get("codec_name")
    if not isinstance(codec, str) or codec not in _ALLOWED_AUDIO_CODECS:
        raise AssetError("audio codec is not allowed", code="unsupported_codec")
    duration = seconds_text_to_us(audio.get("duration"))
    if duration is None or duration <= 0:
        fmt = payload.get("format")
        duration = seconds_text_to_us(fmt.get("duration")) if isinstance(fmt, dict) else None
    if duration is None or duration <= 0:
        raise AssetError("audio duration is missing", code="corrupt_media")
    try:
        sample_rate = int(audio["sample_rate"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AssetError("audio sample rate is missing", code="corrupt_media") from exc
    if sample_rate <= 0:
        raise AssetError("audio sample rate is invalid", code="corrupt_media")
    if request.expected_codec not in {None, codec}:
        raise AssetError("codec does not match the request", code="unsupported_codec")
    _expect_duration(request.requested_duration, duration)
    fmt = payload.get("format")
    format_name = fmt.get("format_name") if isinstance(fmt, dict) else None
    try:
        return ProbeFacts(
            duration_us=duration,
            width=None,
            height=None,
            video_codec=None,
            audio_codec=codec,
            frame_rate=None,
            sample_rate=sample_rate,
            format_name=format_name.split(",")[0] if isinstance(format_name, str) else None,
        )
    except ValidationError as exc:
        raise AssetError("probe facts were rejected", code="corrupt_media") from exc


def _inspect_font_asset(root: Path, path: Path, request: EnvatoAssetRequest) -> ProbeFacts:
    """Validate a local font with Fontconfig without treating it as media."""
    del root, request
    suffix = path.suffix.casefold()
    if suffix == ".partial":
        suffix = Path(path.stem).suffix.casefold()
    if suffix not in {".ttf", ".otf", ".woff", ".woff2"}:
        raise AssetError("font file extension is not supported", code="unsupported_media")
    if path.stat().st_size <= 0:
        raise AssetError("font file is empty", code="corrupt_media")
    import shutil

    executable = shutil.which("fc-scan")
    if executable is None:
        raise AssetError("fc-scan is required to validate a font", code="unsupported_media")
    try:
        result = ProcessRunner().run(
            [executable, "--format=%{family}", str(path)],
            log_path=None,
            check=True,
            timeout_s=15,
        )
    except MediaError as exc:
        raise AssetError("font could not be validated", code="corrupt_media") from exc
    if not result.stdout.strip():
        raise AssetError("font has no readable family metadata", code="corrupt_media")
    try:
        return ProbeFacts(
            duration_us=0,
            width=None,
            height=None,
            video_codec=None,
            audio_codec=None,
            frame_rate=None,
            sample_rate=None,
            format_name=suffix.removeprefix("."),
        )
    except ValidationError as exc:
        raise AssetError("font probe facts were rejected", code="corrupt_media") from exc


def _expect_resolution(requested: str | None, width: int | None, height: int | None) -> None:
    if requested is None:
        return
    if requested.endswith("p"):
        try:
            pixels = int(requested[:-1])
        except ValueError as exc:
            raise AssetError("resolution is not usable", code="unsupported_media") from exc
        if height != pixels:
            raise AssetError("resolution does not match the request", code="unsupported_media")
        return
    if "x" not in requested:
        raise AssetError("resolution is not usable", code="unsupported_media")
    left, right = requested.split("x", 1)
    try:
        expect_width = int(left)
        expect_height = int(right)
    except ValueError as exc:
        raise AssetError("resolution is not usable", code="unsupported_media") from exc
    if width != expect_width or height != expect_height:
        raise AssetError("resolution does not match the request", code="unsupported_media")


def _expect_duration(requested: str | None, duration_us: int) -> None:
    if requested is None:
        return
    try:
        seconds = float(requested)
    except ValueError as exc:
        raise AssetError("duration is not usable", code="unsupported_media") from exc
    if abs(duration_us - int(seconds * 1_000_000)) > 250_000:
        raise AssetError("duration does not match the request", code="unsupported_media")


def _confine(root: Path, relative: str, *, require_incoming: bool) -> Path:
    if "\\" in relative:
        raise AssetError("backslash path is not permitted", code="backslash")
    lowered = relative.lower()
    if "://" in lowered or lowered.startswith("file:"):
        raise AssetError("remote path is not permitted", code="remote_url")
    if not relative or relative.startswith("/") or "\x00" in relative:
        raise AssetError("path escapes the work root", code="outside_root")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise AssetError("traversal path is not permitted", code="traversal")
    if require_incoming and (len(parts) < 2 or parts[0] != "incoming"):
        raise AssetError("file must already be under incoming", code="outside_root")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise AssetError("path is a symlink", code="symlink")
    if not current.is_file():
        raise AssetError("file is missing", code="missing_asset")
    try:
        ensure_within(root, current.resolve())
    except MediaError as exc:
        raise AssetError("path escapes the work root", code="outside_root") from exc
    return current


def _assert_rights(rights: str) -> None:
    if rights == "allowed":
        return
    if rights == "unknown":
        raise AssetError("rights are unknown", code="rights_not_allowed")
    if rights == "prohibited":
        raise AssetError("rights are prohibited", code="rights_not_allowed")
    raise AssetError("rights are not allowed", code="rights_not_allowed")


def _assert_request_current(request: EnvatoAssetRequest) -> None:
    if request.policy_fingerprint != current_policy_fingerprint(request.campaign_id):
        raise AssetError("envato request policy is stale", code="stale_policy")
    if request.download_status != "manual_download_required":
        raise AssetError("envato request is stale", code="stale_request")


def _cache_hit(
    root: Path,
    request: EnvatoAssetRequest,
    project_id: str,
    digest: str,
    size: int,
    content_tags: list[str] | None,
    portal_item_uuid: str | None,
) -> EnvatoAssetRegistration | None:
    for item in list_envato_assets(root, request.campaign_id):
        if item.acquisition_status != "verified" or item.project_id != project_id:
            continue
        if item.sha256 != digest or item.byte_size != size:
            continue
        if item.item_id != request.item_id or item.item_page_url != request.item_page_url:
            continue
        if item.portal_item_uuid != portal_item_uuid:
            continue
        if item.policy_fingerprint != request.policy_fingerprint or item.relative_path is None:
            continue
        if content_tags is not None and tuple(item.content_tags) != tuple(content_tags):
            continue
        path = root / item.relative_path
        if path.is_symlink() or not path.is_file() or sha256_file(path) != digest:
            continue
        return item
    return None


def _asset_id(
    digest: str,
    force: bool,
    content_tags: list[str] | None,
    portal_item_uuid: str | None,
) -> str:
    if force:
        return f"env-{digest[:12]}-{uuid4().hex[:8]}"
    portal_suffix = ""
    if portal_item_uuid is not None:
        portal_suffix = "-portal-" + hashlib.sha256(portal_item_uuid.encode("utf-8")).hexdigest()[:12]
    if content_tags:
        tag_digest = hashlib.sha256("\x1f".join(content_tags).encode("utf-8")).hexdigest()[:8]
        return f"env-{digest[:20]}{portal_suffix}-tag-{tag_digest}"
    return f"env-{digest[:20]}{portal_suffix}"


def _normalize_content_tags(tags: list[str]) -> tuple[str, ...]:
    return tuple(sorted({" ".join(tag.split()).strip().casefold() for tag in tags if tag.strip()}))


def _media_kind(hit: AssetSearchHit | None, filters: dict[str, str]) -> str:
    if hit is not None and hit.asset_type != "unknown":
        return hit.asset_type
    declared = filters.get("asset_type")
    if declared in {"video", "audio", "image", "graphic", "font"}:
        return declared
    return "unknown"


def _load_request(root: Path, request_id: str) -> EnvatoAssetRequest:
    path = root.joinpath(*_REQUESTS, request_id, "request.json")
    if path.is_symlink() or not path.is_file():
        raise AssetError("envato request is missing", code="stale_request")
    try:
        return EnvatoAssetRequest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise AssetError("envato request could not be read", code="stale_request") from exc


def _load_registration(root: Path, asset_id: str) -> EnvatoAssetRegistration:
    path = _manifest_path(root, asset_id)
    if path.is_symlink() or not path.is_file():
        raise AssetError("envato asset is missing", code="missing_asset")
    try:
        return EnvatoAssetRegistration.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise AssetError("envato asset could not be read", code="invalid_document") from exc


def _manifest_path(root: Path, asset_id: str) -> Path:
    return root.joinpath(*_ASSETS, asset_id, "manifest.json")


def _catalog_path(root: Path, project_id: str, source_asset_id: str | None) -> Path | None:
    if source_asset_id is None:
        return None
    return SourceWorkspace(root, project_id, source_asset_id).advanced_asset_catalog()


def _copy_file(root: Path, source: Path, target: Path) -> None:
    mkdir_contained(root, target.parent)
    try:
        with source.open("rb") as incoming, target.open("xb") as outgoing:
            while True:
                block = incoming.read(1024 * 1024)
                if not block:
                    break
                outgoing.write(block)
    except OSError as exc:
        _remove_file(target)
        raise AssetError("staged copy failed", code="promotion_failed") from exc


def _store_evidence(root: Path, asset_id: str, source: Path) -> str:
    target = root.joinpath(*_ASSETS, asset_id, "license.txt")
    mkdir_contained(root, target.parent)
    partial = target.with_name("license.txt.partial")
    partial.write_bytes(source.read_bytes())
    os.replace(partial, target)
    return target.resolve().relative_to(root).as_posix()


def _write_checksum(root: Path, asset_id: str, digest: str, relative: str) -> None:
    path = root.joinpath(*_ASSETS, asset_id, "checksums.sha256")
    _write_text(root, path, f"{digest}  {relative}\n")


def _write_cache(root: Path, registration: EnvatoAssetRegistration, now: datetime) -> None:
    if registration.sha256 is None:
        return
    record = EnvatoAssetCacheRecord(
        cache_id=f"cache-{registration.asset_id}",
        asset_id=registration.asset_id,
        request_id=registration.request_id,
        content_sha256=registration.sha256,
        byte_size=registration.byte_size,
        policy_fingerprint=registration.policy_fingerprint,
        status="miss",
        created_at=now,
    )
    _write_json(root, root.joinpath(*_ASSETS, registration.asset_id, "cache.json"), record.model_dump_json())


def _write_catalog(
    root: Path, catalog: Path, registration: EnvatoAssetRegistration, source_asset_id: str
) -> None:
    workspace = SourceWorkspace(root, registration.project_id, source_asset_id)
    workspace.ensure()
    existing: dict[str, Any] = {"assets": []}
    if catalog.is_file() and not catalog.is_symlink():
        try:
            loaded = json.loads(catalog.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AssetError("advanced asset catalog could not be read", code="invalid_document") from exc
        if isinstance(loaded, dict):
            existing = loaded
    assets = existing.get("assets")
    if not isinstance(assets, list):
        assets = []
    kept = [
        item
        for item in assets
        if not (isinstance(item, dict) and item.get("asset_id") == registration.asset_id)
    ]
    now = registration.created_at
    provenance = ArtifactProvenance(
        created_at=now,
        created_by="operator",
        tool="clipforge.assets.handoff",
        tool_version="0.1.0",
        source_asset_ids=[source_asset_id],
        job_id=registration.producer_job_id,
    )
    path = root / (registration.relative_path or "")
    kept.append(
        {
            "schema_version": "1.0.0",
            "asset_id": registration.asset_id,
            "project_id": registration.project_id,
            "uri": path_to_file_uri(path),
            "kind": "envato",
            "license_record_id": f"lic-{registration.asset_id}",
            "provenance": provenance.model_dump(mode="json"),
            "content_tags": registration.content_tags,
            "relative_path": registration.relative_path,
            "file_sha256": registration.sha256,
        }
    )
    _write_text(root, catalog, json.dumps({"assets": kept}, sort_keys=True))


def _insert_license(database: Database, registration: EnvatoAssetRegistration, now: datetime) -> None:
    record = AssetLicenseRecord(
        license_record_id=f"lic-{registration.asset_id}",
        asset_id=registration.asset_id,
        status=RightsStatus.LICENSED,
        license_name="envato",
        evidence_uri=registration.license_evidence,
        notes="manual envato registration",
        recorded_at=now,
        recorded_by="operator",
    )
    with database.transaction() as connection:
        try:
            get_asset_license_record(connection, record.license_record_id)
        except StorageError:
            insert_asset_license_record(connection, record)


def _insert_running(
    database: Database,
    project_id: str,
    job_id: str,
    asset_id: str,
    digest: str,
    request: EnvatoAssetRequest,
) -> None:
    now = datetime.now(UTC)
    record = JobRecord(
        job_id=job_id,
        project_id=project_id,
        kind=_KIND,
        status=JobStatus.RUNNING,
        created_at=now,
        updated_at=now,
        payload={
            "asset_id": asset_id,
            "request_id": request.request_id,
            "campaign_id": request.campaign_id,
            "sha256": digest,
            "policy_fingerprint": request.policy_fingerprint,
        },
    )
    with database.transaction() as connection:
        insert_job(connection, record)


def _finish_job(
    database: Database,
    project_id: str,
    job_id: str,
    asset_id: str,
    digest: str,
    request: EnvatoAssetRequest,
    status: JobStatus,
    error_code: str | None,
) -> None:
    now = datetime.now(UTC)
    with database.transaction() as connection:
        current = get_job(connection, job_id)
        update_job(
            connection,
            JobRecord(
                job_id=job_id,
                project_id=project_id,
                kind=_KIND,
                status=status,
                created_at=current.created_at,
                updated_at=now,
                error_message=None if status is not JobStatus.FAILED else (error_code or "failed"),
                payload={
                    "asset_id": asset_id,
                    "request_id": request.request_id,
                    "campaign_id": request.campaign_id,
                    "sha256": digest,
                    "policy_fingerprint": request.policy_fingerprint,
                },
            ),
        )


def _fail_job(database: Database, project_id: str, job_id: str, code: str) -> None:
    try:
        with database.transaction() as connection:
            current = get_job(connection, job_id)
            update_job(
                connection,
                current.model_copy(
                    update={
                        "status": JobStatus.FAILED,
                        "updated_at": datetime.now(UTC),
                        "error_message": code,
                    }
                ),
            )
    except StorageError:
        return
    del project_id


def _mark_job(
    database: Database, project_id: str, job_id: str, status: JobStatus, error_code: str | None
) -> None:
    with database.transaction() as connection:
        current = get_job(connection, job_id)
        update_job(
            connection,
            current.model_copy(
                update={
                    "status": status,
                    "updated_at": datetime.now(UTC),
                    "error_message": error_code if status is JobStatus.FAILED else current.error_message,
                    "project_id": project_id,
                }
            ),
        )


def _write_json(root: Path, path: Path, body: str) -> None:
    _write_text(root, path, body + "\n")


def _write_text(root: Path, path: Path, body: str) -> None:
    mkdir_contained(root, path.parent)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(body, encoding="utf-8")
    os.replace(partial, path)


def _read_models(work_root: Path, parts: tuple[str, ...], name: str, model: type[_ModelT]) -> list[_ModelT]:
    root = work_root.resolve()
    base = root.joinpath(*parts)
    if base.is_symlink() or not base.is_dir():
        return []
    found: list[_ModelT] = []
    for child in sorted(base.iterdir()):
        if child.is_symlink() or not child.is_dir():
            continue
        path = child / name
        if path.is_symlink() or not path.is_file():
            continue
        try:
            found.append(model.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, ValidationError):
            continue
    return found


def _read_bytes(path: Path | None) -> bytes | None:
    if path is None or path.is_symlink() or not path.is_file():
        return None
    return path.read_bytes()


def _restore(path: Path, payload: bytes | None) -> None:
    if payload is None:
        _remove_file(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _remove_file(path: Path) -> None:
    if path.is_symlink() or not path.exists():
        return
    if path.is_file():
        path.unlink()


def _remove_partials(root: Path, asset_id: str) -> None:
    media = root.joinpath(*_ASSETS, asset_id, "media")
    if media.is_symlink() or not media.is_dir():
        return
    for path in media.iterdir():
        if path.name.endswith(".partial") and path.is_file() and not path.is_symlink():
            path.unlink()


def _hook(hook: Callable[[str], None] | None, stage: str) -> None:
    if hook is not None:
        hook(stage)


def _verification(
    asset_id: str,
    status: str,
    reason: str,
    registration: EnvatoAssetRegistration | None,
    renderable: bool,
    failure: str | None,
) -> EnvatoAssetVerification:
    return EnvatoAssetVerification(
        asset_id=asset_id,
        status=status,  # type: ignore[arg-type]
        reason_code=reason,
        sha256=None if registration is None else registration.sha256,
        byte_size=None if registration is None else registration.byte_size,
        probe=None if registration is None else registration.probe,
        rights_status="missing" if registration is None else registration.rights_status,
        renderable=renderable,
        failure_reason=failure,
        relative_path=None if registration is None else registration.relative_path,
    )


def _reason_from_message(message: str) -> str:
    lowered = message.lower()
    if "policy" in lowered:
        return "stale_policy"
    if "request" in lowered:
        return "stale_request"
    if "bytes changed" in lowered or "hash" in lowered:
        return "stale_registration"
    if "rights" in lowered:
        return "rights_not_allowed"
    if "license" in lowered:
        return "missing_license_evidence"
    if "job" in lowered:
        return "job_not_succeeded"
    if "not verified" in lowered or "not registered" in lowered:
        return "stale_registration"
    return "stale_registration"


def _request_public(request: EnvatoAssetRequest) -> dict[str, object]:
    return {
        "request_id": request.request_id,
        "provider": request.provider,
        "provider_version": request.provider_version,
        "query": request.query,
        "supported_filters": request.supported_filters,
        "deferred_filters": request.deferred_filters,
        "item_page_url": request.item_page_url,
        "item_id": request.item_id,
        "direct_download_url": request.direct_download_url,
        "media_kind": request.media_kind,
        "intended_use": request.intended_use,
        "campaign_id": request.campaign_id,
        "policy_fingerprint": request.policy_fingerprint,
        "requested_format": request.requested_format,
        "requested_resolution": request.requested_resolution,
        "requested_duration": request.requested_duration,
        "download_status": request.download_status,
    }


def _asset_public(
    work_root: Path,
    registration: EnvatoAssetRegistration,
    database: Database | None,
) -> dict[str, object]:
    renderable = False
    failure: str | None = registration.failure_code
    digest = registration.sha256
    verified = digest is not None and registration.acquisition_status == "verified"
    if database is not None and verified and digest is not None:
        try:
            assert_envato_registration(
                work_root,
                database,
                registration.asset_id,
                project_id=registration.project_id,
                file_sha256=digest,
            )
            renderable = True
            failure = None
        except MediaError as exc:
            failure = _reason_from_message(str(exc))
    probe: dict[str, object] | None = None
    if registration.probe is not None:
        probe = {
            "duration_us": registration.probe.duration_us,
            "width": registration.probe.width,
            "height": registration.probe.height,
            "video_codec": registration.probe.video_codec,
            "audio_codec": registration.probe.audio_codec,
            "frame_rate": registration.probe.frame_rate,
            "sample_rate": registration.probe.sample_rate,
            "format_name": registration.probe.format_name,
        }
    return {
        "asset_id": registration.asset_id,
        "campaign_id": registration.campaign_id,
        "project_id": registration.project_id,
        "item_page_url": registration.item_page_url,
        "item_id": registration.item_id,
        "portal_item_uuid": registration.portal_item_uuid,
        "portal_license_id": registration.portal_license_id,
        "direct_download_url": registration.direct_download_url,
        "download_status": registration.download_status,
        "relative_path": registration.relative_path,
        "byte_size": registration.byte_size,
        "sha256": registration.sha256,
        "probe": probe,
        "license_evidence": registration.license_evidence,
        "rights_status": registration.rights_status,
        "provider_version": registration.provider_version,
        "acquisition_status": registration.acquisition_status,
        "producer_job_id": registration.producer_job_id,
        "policy_fingerprint": registration.policy_fingerprint,
        "renderable": renderable,
        "failure_reason": failure,
    }


def _reject_public(payload: dict[str, object]) -> None:
    text = json.dumps(payload).lower()
    if any(token in text for token in ("/home/", "/tmp/", "/users/", "file:", "bearer ", "token=", "cookie=")):
        raise AssetError("envato board payload is not public", code="invalid_document")
