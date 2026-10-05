"""Normalize discovery results and write a manual download request."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from clipforge.assets.mcp_client import AssetError, envato_enabled, envato_url
from clipforge.assets.provider import AssetDiscoveryProvider, DryRunAssetDiscoveryProvider
from clipforge.campaign.antoine import CAMPAIGN_ID
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import ensure_within
from clipforge.schemas.assets import AssetDownloadRequest, AssetSearchHit

_SECRET = ("bearer ", "password=", "token=", "authorization:", "cookie=")


def doctor_text(provider: AssetDiscoveryProvider | None = None) -> str:
    if provider is not None:
        return provider.doctor()
    return "\n".join(
        [
            f"endpoint: {envato_url()}",
            f"enabled: {1 if envato_enabled() else 0}",
            "connection: not_configured" if not envato_enabled() else "connection: not_run",
            "authentication: not stored",
            "direct_download: unsupported",
            "last_smoke: none",
        ]
    )


def render_block_reason(hit: AssetSearchHit) -> str | None:
    """Why a discovery hit must stay out of a render. None means the hit is still not downloaded.

    A blocked, remote, or unlicensed hit never becomes render media. This does not fetch bytes.
    """
    if hit.campaign_policy_decision != "allowed":
        return hit.rejection_reason or "policy_blocked"
    if hit.direct_download_url is not None:
        return "remote_url"
    if hit.download_status == "rejected" or hit.selection_status == "rejected":
        return hit.rejection_reason or "rejected"
    if not hit.license_evidence or not hit.sha256:
        return "missing_license_evidence"
    if hit.local_path is None:
        return "not_local"
    return None


def search_assets(
    provider: AssetDiscoveryProvider,
    *,
    query: str,
    filters: dict[str, str],
    campaign_id: str,
) -> list[AssetSearchHit]:
    rows = provider.search(query, filters)
    now = datetime.now(UTC)
    hits: list[AssetSearchHit] = []
    for row in rows:
        hit = _normalize(row, campaign_id=campaign_id, now=now)
        if hit is not None:
            hits.append(hit)
    return hits


def write_requests(
    work_root: Path,
    hits: list[AssetSearchHit],
    *,
    query: str,
    filters: dict[str, str],
    campaign_id: str,
) -> tuple[Path, Path]:
    root = work_root.resolve()
    now = datetime.now(UTC)
    requests = [
        AssetDownloadRequest(
            request_id=hit.request_id,
            campaign_id=campaign_id,
            query=query,
            filters=filters,
            hit=hit,
            requested_format=hit.format[0] if hit.format else None,
            operator_confirmation_required=True,
        )
        for hit in hits
    ]
    directory = root / "assets" / campaign_id
    if directory.is_symlink():
        raise AssetError("asset request directory is a symlink", code="symlink")
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "asset_download_requests.json"
    md_path = directory / "asset_download_requests.md"
    payload = {
        "query": query,
        "filters": filters,
        "requests": [item.model_dump(mode="json") for item in requests],
        "created_at": now.isoformat(),
    }
    text = json.dumps(payload, sort_keys=True)
    _reject_secrets(text)
    json_path.write_text(text + "\n", encoding="utf-8")
    md_path.write_text(_markdown(query, filters, requests), encoding="utf-8")
    return json_path, md_path


def import_results(path: Path, *, campaign_id: str) -> list[AssetSearchHit]:
    if path.is_symlink():
        raise AssetError("import path is a symlink", code="symlink")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssetError("asset results could not be read", code="malformed_response") from exc
    rows = payload.get("requests") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise AssetError("asset results are missing", code="malformed_response")
    hits: list[AssetSearchHit] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("hit"), dict):
            continue
        hit = AssetSearchHit.model_validate(row["hit"])
        if hit.provider == "fake":
            hits.append(hit)
            continue
        if campaign_id == CAMPAIGN_ID and hit.campaign_policy_decision != "blocked":
            raise AssetError("antoine campaign cannot import an outside asset", code="policy_blocked")
        hits.append(hit)
    return hits


def acquire_local(
    work_root: Path,
    request_path: Path,
    local_path: Path,
    *,
    license_statement: str,
    campaign_id: str,
) -> AssetSearchHit:
    """Bind a file the operator already downloaded. Remote URLs are refused."""
    if campaign_id == CAMPAIGN_ID:
        raise AssetError(
            "outside media is prohibited by campaign policy",
            code="outside_media_prohibited_by_campaign_policy",
        )
    root = work_root.resolve()
    hits = import_results(request_path, campaign_id=campaign_id)
    if not hits:
        raise AssetError("asset request is empty", code="missing_request")
    hit = hits[0]
    if hit.campaign_policy_decision == "blocked":
        raise AssetError("asset is blocked by campaign policy", code="policy_blocked")
    if not license_statement.strip():
        raise AssetError("license evidence is required", code="rights_unverified")
    if local_path.is_symlink() or not local_path.is_file():
        raise AssetError("local asset is missing or a symlink", code="symlink")
    if str(local_path).startswith("http://") or str(local_path).startswith("https://"):
        raise AssetError("remote media cannot be acquired as a render input", code="remote_url")
    ensure_within(root, local_path)
    digest = sha256_file(local_path)
    relative = local_path.resolve().relative_to(root).as_posix()
    payload = hit.model_dump(mode="json")
    payload.update(
        {
            "local_path": relative,
            "sha256": digest,
            "download_status": "acquired",
            "license_evidence": license_statement.strip(),
            "operator_confirmation": True,
            "direct_download_url": None,
        }
    )
    return AssetSearchHit.model_validate(payload)


def verify_asset(work_root: Path, hit: AssetSearchHit) -> str:
    """Re-hash a bound file. This does not search or download."""
    if hit.local_path is None or hit.sha256 is None:
        return "PASS asset manual_download_required"
    root = work_root.resolve()
    path = root / hit.local_path
    if path.is_symlink() or not path.is_file():
        raise AssetError("asset file is missing", code="missing_asset")
    ensure_within(root, path)
    if sha256_file(path) != hit.sha256:
        raise AssetError("asset hash changed", code="stale_asset")
    return "PASS asset"


def _normalize(row: dict[str, object], *, campaign_id: str, now: datetime) -> AssetSearchHit | None:
    item_id = _text(row, "item_id", "id", "itemId")
    title = _text(row, "title", "name")
    item_url = _https(row, "item_url", "url", "itemUrl")
    direct = _https(row, "direct_download_url", "download_url")
    decision: str = "pending"
    reason = None
    selection = "candidate"
    if campaign_id == CAMPAIGN_ID:
        decision = "blocked"
        reason = "outside_media_prohibited_by_campaign_policy"
        selection = "rejected"
    formats = _list(row, "format", "formats")
    software = _list(row, "compatible_software", "compatibleSoftware")
    provider_name = row.get("provider")
    if provider_name not in {"envato_mcp", "fake", "dry_run"}:
        provider_name = "envato_mcp"
    return AssetSearchHit(
        request_id=str(uuid4()),
        provider=provider_name,  # type: ignore[arg-type]
        item_id=item_id,
        title=title,
        item_url=item_url,
        asset_type=_asset_type(row.get("asset_type") or row.get("item_type") or row.get("type")),
        category=_text(row, "category"),
        format=formats,
        compatible_software=software,
        genre=_text(row, "genre"),
        style=_text(row, "style"),
        duration_seconds=_number(row.get("duration_seconds") or row.get("duration")),
        dimensions=_text(row, "dimensions"),
        frame_rate=_text(row, "frame_rate", "frameRate"),
        license_url=_https(row, "license_url", "licenseUrl"),
        license_evidence=_text(row, "license_evidence"),
        commercial_use="unknown",
        campaign_policy_decision=decision,  # type: ignore[arg-type]
        selection_status=selection,  # type: ignore[arg-type]
        rejection_reason=reason,
        download_status="rejected" if selection == "rejected" else "manual_download_required",
        direct_download_url=None if direct is None else direct,
        operator_confirmation=False,
        created_at=now,
    )


def _text(row: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip() and "://" not in value:
            return value.strip()
    return None


def _https(row: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.startswith("https://") and "bearer" not in value.lower():
            return value
    return None


def _list(row: dict[str, object], *keys: str) -> list[str]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, list):
            picked = [
                item.strip() for item in value if isinstance(item, str) and item.strip() and "://" not in item
            ]
            return picked
    return []


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def _asset_type(value: object) -> Literal["video", "audio", "image", "graphic", "template", "unknown"]:
    if not isinstance(value, str):
        return "unknown"
    lowered = value.lower().replace("_", "-")
    if "video" in lowered:
        return "video"
    if "audio" in lowered or "music" in lowered:
        return "audio"
    if lowered in {"image", "photo", "photos"}:
        return "image"
    if "graphic" in lowered:
        return "graphic"
    if "template" in lowered:
        return "template"
    return "unknown"


def _markdown(query: str, filters: dict[str, str], requests: list[AssetDownloadRequest]) -> str:
    lines = [
        "# Asset download requests",
        "",
        f"Query: {query}",
        f"Filters: {json.dumps(filters, sort_keys=True)}",
        "",
        "Envato MCP does not download the file. A person downloads it from the item page.",
        "",
    ]
    if not requests:
        lines.append("No catalog rows were returned.")
        return "\n".join(lines) + "\n"
    for item in requests:
        hit = item.hit
        lines.extend(
            [
                f"## {hit.title or 'untitled'}",
                f"- item id: {hit.item_id or 'not provided'}",
                f"- item page: {hit.item_url or 'not provided'}",
                f"- formats: {', '.join(hit.format) if hit.format else 'not provided'}",
                f"- license: {hit.license_evidence or 'not provided'}",
                f"- campaign decision: {hit.campaign_policy_decision}",
                f"- rejection: {hit.rejection_reason or 'none'}",
                f"- download status: {hit.download_status}",
                "- operator confirmation: required",
                "",
            ]
        )
    text = "\n".join(lines)
    _reject_secrets(text)
    return text


def _reject_secrets(text: str) -> None:
    lowered = text.lower()
    if any(token in lowered for token in _SECRET):
        raise AssetError("refusing to write a secret into an asset request", code="secret")


def dry_provider() -> DryRunAssetDiscoveryProvider:
    return DryRunAssetDiscoveryProvider()
