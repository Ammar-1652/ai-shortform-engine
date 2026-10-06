"""Optional Whop discovery. Credentials stay outside Clipforge, and Whop is not modified."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import ValidationError

from clipforge.campaign.providers import CampaignError
from clipforge.campaign.whop import (
    _canonical,
    _policy_fingerprint,
    import_whop_snapshot,
    parse_whop_bytes,
    verify_whop_import,
)
from clipforge.campaign.whop_filter import filter_campaigns
from clipforge.campaign.whop_mcp import configured_connector, live_smoke_enabled, redact
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import mkdir_contained
from clipforge.schemas.whop import WhopCampaignSnapshot
from clipforge.schemas.whop_discovery import (
    DiscoveryMode,
    LiveStatus,
    WhopCampaignCatalogue,
    WhopDiscoveryAttempt,
    WhopLiveDiscoveryRequest,
    WhopProviderCapability,
    WhopSelectionEvidence,
)

_ROOT = ("campaigns", "whop-discoveries")
_SELECTION_ROOT = ("campaigns", "whop-selections")
_RELOAD = "The campaign selection changed while this page was open; reload before saving."
_DEFAULT_PROHIBITED = ("gambling",)


class _Provider(Protocol):
    """A read-only campaign source. Implementations must not accept secrets."""

    provider_id: str
    provider_version: str
    live_status: str
    mode: str

    def discover(self) -> dict[str, Any]:
        """Return normalized campaign metadata."""


class FakeWhopProvider:
    """Public catalogue rows for tests. This does not open a socket."""

    provider_id = "fake_whop"
    provider_version = "1"
    live_status = "public_discovery"
    mode = "live_connector"

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or _sample_public()
        self.calls = 0

    def discover(self) -> dict[str, Any]:
        self.calls += 1
        cleaned = redact(self.payload)
        if not isinstance(cleaned, dict):
            return {}
        return cleaned


class FakeBrowserExportProvider:
    """Operator export bytes. Cookies and profiles are not accepted."""

    provider_id = "browser_export"
    provider_version = "1"
    live_status = "authenticated_discovery"
    mode = "browser_export"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def discover(self) -> dict[str, Any]:
        self.calls += 1
        cleaned = redact(self.payload)
        if not isinstance(cleaned, dict):
            raise CampaignError("whop export was rejected", code="invalid_document")
        return cleaned


class UnavailableWhopProvider:
    """A configured connector that cannot be reached."""

    provider_id = "whop"
    provider_version = "official"
    live_status = "provider_unavailable"
    mode = "live_connector"

    def discover(self) -> dict[str, Any]:
        raise CampaignError("whop provider is unavailable", code="provider_unavailable")


class MalformedWhopProvider:
    """A provider body that must be rejected before a sidecar is written."""

    provider_id = "fake_whop"
    provider_version = "1"
    live_status = "public_discovery"
    mode = "live_connector"

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def discover(self) -> dict[str, Any]:
        return self.payload


def whop_capabilities() -> WhopProviderCapability:
    """Report the connector without opening a session."""
    status: LiveStatus
    mode: DiscoveryMode
    if not live_smoke_enabled():
        status = "not_configured"
        mode = "not_configured"
    elif not configured_connector():
        status = "provider_unavailable"
        mode = "not_configured"
    else:
        status = "provider_unavailable"
        mode = "live_connector"
    return WhopProviderCapability(
        provider_id="whop",
        provider_version="official",
        mode=mode,
        live_status=status,
        public_fields=["title", "campaign_url", "status", "category", "payout_text"],
        account_fields=["membership"],
    )


def discover_whop(provider: _Provider | None = None) -> dict[str, object]:
    """Read provider metadata. This function does not write a sidecar."""
    if provider is None:
        return {
            "whop_live": "not_configured" if not live_smoke_enabled() else "provider_unavailable",
            "publishing": "deferred",
            "credentials": "not stored",
            "mutating_operations": "disabled",
            "campaigns": [],
        }
    try:
        payload = provider.discover()
    except CampaignError as exc:
        live = exc.code if exc.code in {"not_configured", "provider_unavailable"} else "provider_unavailable"
        return {
            "whop_live": live,
            "publishing": "deferred",
            "credentials": "not stored",
            "mutating_operations": "disabled",
            "campaigns": [],
        }
    if not isinstance(payload, dict):
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    snapshot = normalize_whop_payload(payload, operator_id=str(payload.get("operator_id") or "operator-1"))
    return {
        "whop_live": str(getattr(provider, "live_status", "public_discovery")),
        "publishing": "deferred",
        "credentials": "not stored",
        "mutating_operations": "disabled",
        "campaigns": [item.campaign_id for item in snapshot.campaigns],
        "missing_fields": _missing_fields(snapshot),
    }


def import_discovered(
    work_root: Path,
    provider: _Provider,
    *,
    project_id: str,
    operator_id: str = "operator-1",
    request: WhopLiveDiscoveryRequest | None = None,
    force: bool = False,
    promotion_hook: Callable[[str], None] | None = None,
) -> WhopDiscoveryAttempt:
    """Normalize a provider result and append one discovery. Invalid input writes nothing."""
    payload = provider.discover()
    if not isinstance(payload, dict):
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    cleaned = redact(payload)
    if not isinstance(cleaned, dict):
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    snapshot = normalize_whop_payload(cleaned, operator_id=operator_id)
    return _store_discovery(
        work_root,
        snapshot,
        project_id=project_id,
        provider_id=str(getattr(provider, "provider_id", "whop")),
        provider_version=str(getattr(provider, "provider_version", "1")),
        live_status=str(getattr(provider, "live_status", "public_discovery")),
        mode=str(getattr(provider, "mode", "live_connector")),
        request=request,
        force=force,
        promotion_hook=promotion_hook,
    )


def normalize_whop_payload(payload: dict[str, Any], *, operator_id: str) -> WhopCampaignSnapshot:
    """Map a provider body onto the snapshot schema. Unknown keys and secrets fail first."""
    allowed = {"operator_id", "exported_at", "campaigns", "public_fields", "schema_version"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    if "schema_version" in payload and "campaigns" in payload and "operator_id" in payload:
        try:
            return parse_whop_bytes(json.dumps(payload).encode("utf-8"))
        except CampaignError:
            raise
    campaigns = payload.get("campaigns")
    if not isinstance(campaigns, list) or not campaigns:
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    exported = payload.get("exported_at") or datetime.now(UTC).isoformat()
    document = {
        "schema_version": "1.0.0",
        "operator_id": payload.get("operator_id") or operator_id,
        "exported_at": exported,
        "campaigns": [_campaign(item) for item in campaigns],
    }
    try:
        return WhopCampaignSnapshot.model_validate(document)
    except ValidationError as exc:
        raise CampaignError("whop provider response was rejected", code="invalid_document") from exc


def list_discoveries(work_root: Path) -> list[WhopDiscoveryAttempt]:
    root = work_root.resolve()
    base = root.joinpath(*_ROOT)
    if base.is_symlink() or not base.is_dir():
        return []
    found: list[WhopDiscoveryAttempt] = []
    for child in sorted(base.iterdir()):
        path = child / "manifest.json"
        if child.is_symlink() or path.is_symlink() or not path.is_file():
            continue
        try:
            found.append(WhopDiscoveryAttempt.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, ValidationError):
            continue
    return found


def verify_discovery(work_root: Path, discovery_id: str) -> WhopDiscoveryAttempt:
    """Re-read one discovery. This does not write."""
    root = work_root.resolve()
    attempt = _load_discovery(root, discovery_id)
    path = root.joinpath(*_ROOT, discovery_id, "response.json")
    if path.is_symlink() or not path.is_file():
        raise CampaignError("whop discovery is missing", code="stale_discovery")
    if sha256_file(path) != attempt.response_sha256:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    if attempt.status == "cancelled":
        raise CampaignError("whop discovery was cancelled", code="cancelled")
    return attempt


def cancel_discovery(work_root: Path, discovery_id: str) -> WhopDiscoveryAttempt:
    """Mark one discovery cancelled and remove a partial file."""
    root = work_root.resolve()
    attempt = _load_discovery(root, discovery_id)
    for partial in root.joinpath(*_ROOT, discovery_id).glob("*.partial"):
        if partial.is_file() and not partial.is_symlink():
            partial.unlink()
    cancelled = attempt.model_copy(update={"status": "cancelled", "reason_code": "cancelled"})
    path = root.joinpath(*_ROOT, discovery_id, "manifest.json")
    path.write_text(cancelled.model_dump_json() + "\n", encoding="utf-8")
    return cancelled


def select_whop_campaign(
    work_root: Path,
    *,
    campaign_id: str,
    import_id: str,
    project_id: str,
    source_ids: list[str],
    operator_id: str,
    language: str = "en-US",
    narration_request: str = "not_requested",
    expected_catalogue: str | None = None,
    expected_policy: str | None = None,
    expected_source_hashes: dict[str, str] | None = None,
) -> WhopSelectionEvidence:
    """Record an allowed selection. A stale import asks the operator to reload."""
    try:
        attempt = verify_whop_import(work_root, import_id)
    except CampaignError as exc:
        if exc.code in {"stale_snapshot", "stale_policy"}:
            raise CampaignError(_RELOAD, code=exc.code) from exc
        raise
    if expected_catalogue is not None and expected_catalogue != attempt.snapshot_sha256:
        raise CampaignError(_RELOAD, code="stale_selection")
    if expected_policy is not None and expected_policy != attempt.policy_fingerprint:
        raise CampaignError(_RELOAD, code="stale_policy")
    campaign = next((item for item in attempt.campaigns if item.campaign_id == campaign_id), None)
    if campaign is None:
        raise CampaignError("whop campaign is not imported", code="missing_campaign")
    chosen = sorted(source_ids)
    hashes: list[str] = []
    for source_id in chosen:
        source = next((item for item in campaign.sources if item.source_id == source_id), None)
        if source is None:
            raise CampaignError("whop source is missing", code="missing_source")
        if source_id not in attempt.selectable_source_ids:
            code = "policy_blocked" if source.policy_state != "allowed" else "rights_not_allowed"
            raise CampaignError("whop source is not selectable", code=code)
        current = source.content_sha256 or _metadata_hash(source.model_dump(mode="json"))
        supplied = None if expected_source_hashes is None else expected_source_hashes.get(source_id)
        if supplied is not None and supplied != current:
            raise CampaignError(_RELOAD, code="source_changed")
        hashes.append(current)
    now = datetime.now(UTC)
    body = {
        "campaign_id": campaign_id,
        "catalogue": attempt.snapshot_sha256,
        "import_id": import_id,
        "language": language,
        "narration_request": narration_request,
        "operator_id": operator_id,
        "policy": attempt.policy_fingerprint,
        "project_id": project_id,
        "source_hashes": hashes,
        "source_ids": chosen,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    fingerprint = hashlib.sha256(encoded).hexdigest()
    evidence = WhopSelectionEvidence(
        evidence_id="sel-" + fingerprint[:20],
        campaign_id=campaign_id,
        import_id=import_id,
        project_id=project_id,
        catalogue_fingerprint=attempt.snapshot_sha256,
        policy_fingerprint=attempt.policy_fingerprint,
        source_ids=chosen,
        source_hashes=hashes,
        language=language,
        narration_request=_narration(narration_request),
        operator_id=operator_id,
        evidence_fingerprint=fingerprint,
        created_at=now,
    )
    root = work_root.resolve()
    path = root.joinpath(*_SELECTION_ROOT, evidence.evidence_id, "evidence.json")
    if path.is_file() and not path.is_symlink():
        return WhopSelectionEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    mkdir_contained(root, path.parent)
    path.write_text(evidence.model_dump_json() + "\n", encoding="utf-8")
    return evidence


def board_capabilities() -> dict[str, object]:
    payload = whop_capabilities().model_dump(mode="json")
    _reject_public(payload)
    return payload


def board_discoveries(work_root: Path) -> dict[str, object]:
    rows = [
        {
            "discovery_id": item.discovery_id,
            "live_status": item.live_status,
            "status": item.status,
            "provider_id": item.provider_id,
            "provider_version": item.provider_version,
            "catalogue_fingerprint": item.catalogue_fingerprint,
            "policy_fingerprint": item.policy_fingerprint,
        }
        for item in list_discoveries(work_root)
    ]
    payload: dict[str, object] = {
        "discoveries": rows,
        "publishing": "deferred",
        "credentials": "not_stored",
    }
    _reject_public(payload)
    return payload


def board_discovery(work_root: Path, discovery_id: str) -> dict[str, object]:
    item = _load_discovery(work_root.resolve(), discovery_id)
    payload: dict[str, object] = {
        "discovery_id": item.discovery_id,
        "live_status": item.live_status,
        "provider_id": item.provider_id,
        "provider_version": item.provider_version,
        "status": item.status,
        "catalogue_fingerprint": item.catalogue_fingerprint,
        "policy_fingerprint": item.policy_fingerprint,
        "decisions": [decision.model_dump(mode="json") for decision in item.decisions],
        "credentials": "not_stored",
        "publishing": "deferred",
    }
    _reject_public(payload)
    return payload


def board_filter_results(work_root: Path, campaign_id: str) -> dict[str, object]:
    from clipforge.campaign.whop import show_whop_campaign

    campaign = show_whop_campaign(work_root, campaign_id)
    decisions = []
    for item in list_discoveries(work_root):
        for decision in item.decisions:
            if decision.campaign_id == campaign_id:
                decisions.append(decision.model_dump(mode="json"))
    payload: dict[str, object] = {
        "campaign_id": campaign_id,
        "whop_live": campaign.get("whop_live", "not_configured"),
        "decisions": decisions,
        "selection_fingerprint": _selection_fingerprint(work_root, campaign_id),
        "publishing": "deferred",
        "credentials": "not_stored",
    }
    _reject_public(payload)
    return payload


def _store_discovery(
    work_root: Path,
    snapshot: WhopCampaignSnapshot,
    *,
    project_id: str,
    provider_id: str,
    provider_version: str,
    live_status: str,
    mode: str,
    request: WhopLiveDiscoveryRequest | None,
    force: bool,
    promotion_hook: Callable[[str], None] | None,
) -> WhopDiscoveryAttempt:
    now = datetime.now(UTC)
    active_request = request or WhopLiveDiscoveryRequest(
        request_id="req-default",
        provider_id=provider_id,
        provider_version=provider_version,
        prohibited_categories=list(_DEFAULT_PROHIBITED),
        require_policy="allowed",
        require_rights="allowed",
        created_at=snapshot.exported_at,
    )
    decisions = filter_campaigns(snapshot, active_request, now=now)
    response = _canonical(snapshot)
    response_sha = hashlib.sha256(response).hexdigest()
    request_sha = _request_sha(active_request)
    catalogue = response_sha
    policy = _policy_fingerprint([item.campaign_id for item in snapshot.campaigns])
    identity = _identity(
        provider_id=provider_id,
        provider_version=provider_version,
        request_sha256=request_sha,
        policy_fingerprint=policy,
        catalogue_fingerprint=catalogue,
        response_sha256=response_sha,
    )
    live = _as_live_status(live_status)
    discovery_mode = _as_mode(mode)
    try:
        catalogue_record = WhopCampaignCatalogue(
            catalogue_id="cat-" + catalogue[:20],
            provider_id=provider_id,
            provider_version=provider_version,
            live_status=live,
            campaigns=list(snapshot.campaigns),
            catalogue_fingerprint=catalogue,
            missing_fields=_missing_fields(snapshot),
        )
    except ValidationError as exc:
        raise CampaignError("whop catalogue was rejected", code="invalid_document") from exc
    if catalogue_record.catalogue_fingerprint != catalogue:
        raise CampaignError("whop catalogue fingerprint changed", code="invalid_document")
    root = work_root.resolve()
    if not force:
        cached = _cache_hit(root, identity, response_sha)
        if cached is not None:
            return cached
    included = any(item.included for item in decisions)
    attempt_import = import_whop_snapshot(root, response, project_id=project_id, force=force)
    base_id = "disc-" + identity[:20]
    discovery_id = base_id
    if force or _discovery_cancelled(root, base_id):
        discovery_id = f"disc-{identity[:12]}-{uuid4().hex[:8]}"
    attempt = WhopDiscoveryAttempt(
        discovery_id=discovery_id,
        project_id=project_id,
        mode=discovery_mode,
        provider_id=provider_id,
        provider_version=provider_version,
        live_status=live,
        request_sha256=request_sha,
        response_sha256=response_sha,
        catalogue_fingerprint=catalogue,
        policy_fingerprint=policy,
        identity_sha256=identity,
        import_id=attempt_import.import_id,
        campaign_ids=[item.campaign_id for item in snapshot.campaigns],
        decisions=decisions,
        status="ready" if included else "blocked",
        reason_code="ready" if included else "policy_blocked",
        created_at=now,
    )
    _publish(root, attempt, response, promotion_hook)
    return attempt


def _campaign(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    allowed = {
        "schema_version",
        "campaign_id",
        "title",
        "policy_state",
        "sources",
        "campaign_url",
        "status",
        "category",
        "payout_text",
        "language",
    }
    if set(item) - allowed:
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    sources = item.get("sources")
    if not isinstance(sources, list):
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    return {
        "schema_version": "1.0.0",
        "campaign_id": item.get("campaign_id"),
        "title": item.get("title"),
        "policy_state": item.get("policy_state") or "unknown",
        "campaign_url": item.get("campaign_url"),
        "status": item.get("status") or "unknown",
        "category": item.get("category"),
        "payout_text": item.get("payout_text"),
        "language": item.get("language"),
        "sources": [_source(source) for source in sources],
    }


def _source(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    allowed = {
        "schema_version",
        "source_id",
        "display_name",
        "rights_state",
        "policy_state",
        "selected",
        "source_url",
        "content_sha256",
        "size_bytes",
        "duration_us",
        "media_format",
        "availability",
    }
    if set(item) - allowed:
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    return {
        "schema_version": "1.0.0",
        "source_id": item.get("source_id"),
        "display_name": item.get("display_name"),
        "rights_state": item.get("rights_state") or "unknown",
        "policy_state": item.get("policy_state") or "unknown",
        "selected": bool(item.get("selected", False)),
        "source_url": item.get("source_url"),
        "content_sha256": item.get("content_sha256"),
        "size_bytes": item.get("size_bytes"),
        "duration_us": item.get("duration_us"),
        "media_format": item.get("media_format"),
        "availability": item.get("availability") or "unknown",
    }


def _missing_fields(snapshot: WhopCampaignSnapshot) -> list[str]:
    missing: list[str] = []
    for campaign in snapshot.campaigns:
        if campaign.campaign_url is None:
            missing.append("campaign_url")
        if campaign.category is None:
            missing.append("category")
        for source in campaign.sources:
            if source.content_sha256 is None:
                missing.append("content_sha256")
            if source.duration_us is None:
                missing.append("duration_us")
    return sorted(set(missing))


def _request_sha(request: WhopLiveDiscoveryRequest) -> str:
    """Hash the filter. The request id and timestamp are not filter facts."""
    payload = request.model_dump(mode="json")
    payload.pop("created_at", None)
    payload.pop("request_id", None)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _identity(**parts: str) -> str:
    raw = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _metadata_hash(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cache_hit(root: Path, identity: str, response_sha: str) -> WhopDiscoveryAttempt | None:
    for item in list_discoveries(root):
        if item.identity_sha256 != identity or item.status == "cancelled":
            continue
        path = root.joinpath(*_ROOT, item.discovery_id, "response.json")
        if path.is_symlink() or not path.is_file() or sha256_file(path) != response_sha:
            raise CampaignError("whop discovery changed", code="stale_discovery")
        if item.response_sha256 != response_sha:
            raise CampaignError("whop discovery changed", code="stale_discovery")
        return item.model_copy(update={"cache_status": "hit"})
    return None


def _publish(
    root: Path,
    attempt: WhopDiscoveryAttempt,
    response: bytes,
    hook: Callable[[str], None] | None,
) -> None:
    directory = root.joinpath(*_ROOT, attempt.discovery_id)
    mkdir_contained(root, directory)
    response_partial = directory / "response.json.partial"
    manifest_partial = directory / "manifest.json.partial"
    response_final = directory / "response.json"
    manifest_final = directory / "manifest.json"
    previous_response = _existing_bytes(response_final)
    previous_manifest = _existing_bytes(manifest_final)
    try:
        response_partial.write_bytes(response)
        manifest_partial.write_text(attempt.model_dump_json() + "\n", encoding="utf-8")
        if hook is not None:
            hook("staging_write")
        if hook is not None:
            hook("final_rename")
        os.replace(response_partial, response_final)
        os.replace(manifest_partial, manifest_final)
    except Exception:
        for path in (response_partial, manifest_partial):
            if path.is_file() and not path.is_symlink():
                path.unlink()
        if previous_response is None and response_final.is_file() and not response_final.is_symlink():
            response_final.unlink()
        elif previous_response is not None:
            response_final.write_bytes(previous_response)
        if previous_manifest is None and manifest_final.is_file() and not manifest_final.is_symlink():
            manifest_final.unlink()
        elif previous_manifest is not None:
            manifest_final.write_bytes(previous_manifest)
        raise


def _load_discovery(root: Path, discovery_id: str) -> WhopDiscoveryAttempt:
    path = root.joinpath(*_ROOT, discovery_id, "manifest.json")
    if path.is_symlink() or not path.is_file():
        raise CampaignError("whop discovery is missing", code="missing_discovery")
    try:
        return WhopDiscoveryAttempt.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise CampaignError("whop discovery could not be read", code="invalid_document") from exc


def _reject_public(payload: dict[str, object]) -> None:
    text = json.dumps(payload).lower()
    tokens = ("/home/", "/tmp/", "/users/", "file:", "bearer ", "token=", "cookie=", "password=", "api_key")
    if any(token in text for token in tokens):
        raise CampaignError("whop board payload is not public", code="invalid_document")


def _as_live_status(value: str) -> LiveStatus:
    if value == "public_discovery":
        return "public_discovery"
    if value == "authenticated_discovery":
        return "authenticated_discovery"
    if value == "not_configured":
        return "not_configured"
    if value == "provider_unavailable":
        return "provider_unavailable"
    raise CampaignError("whop live status is unknown", code="invalid_document")


def _as_mode(value: str) -> DiscoveryMode:
    if value == "snapshot":
        return "snapshot"
    if value == "browser_export":
        return "browser_export"
    if value == "live_connector":
        return "live_connector"
    if value == "not_configured":
        return "not_configured"
    raise CampaignError("whop mode is unknown", code="invalid_document")


def _narration(value: str) -> Literal["not_requested", "requested"]:
    if value == "requested":
        return "requested"
    if value == "not_requested":
        return "not_requested"
    raise CampaignError("whop narration request is unknown", code="invalid_document")


def _existing_bytes(path: Path) -> bytes | None:
    if path.is_file() and not path.is_symlink():
        return path.read_bytes()
    return None


def _selection_fingerprint(work_root: Path, campaign_id: str) -> str | None:
    root = work_root.resolve()
    base = root.joinpath(*_SELECTION_ROOT)
    if base.is_symlink() or not base.is_dir():
        return None
    found: str | None = None
    latest = ""
    for child in sorted(base.iterdir()):
        path = child / "evidence.json"
        if child.is_symlink() or path.is_symlink() or not path.is_file():
            continue
        try:
            evidence = WhopSelectionEvidence.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError):
            continue
        if evidence.campaign_id != campaign_id:
            continue
        stamp = evidence.created_at.isoformat()
        if stamp >= latest:
            latest = stamp
            found = evidence.evidence_fingerprint
    return found


def _discovery_cancelled(root: Path, discovery_id: str) -> bool:
    path = root.joinpath(*_ROOT, discovery_id, "manifest.json")
    if path.is_symlink() or not path.is_file():
        return False
    try:
        attempt = WhopDiscoveryAttempt.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError):
        return False
    return attempt.status == "cancelled"


def _sample_public() -> dict[str, Any]:
    return {
        "operator_id": "operator-1",
        "exported_at": "2026-10-06T12:00:00Z",
        "campaigns": [
            {
                "campaign_id": "camp-city",
                "title": "City rewards",
                "campaign_url": "https://whop.com/city-rewards",
                "status": "active",
                "category": "clipping",
                "policy_state": "allowed",
                "payout_text": "public cpm",
                "language": "en-US",
                "sources": [
                    {
                        "source_id": "src-city",
                        "display_name": "City clip",
                        "rights_state": "allowed",
                        "policy_state": "allowed",
                        "selected": True,
                        "source_url": "https://whop.com/city-rewards/src-city",
                        "availability": "available",
                        "content_sha256": "a" * 64,
                        "size_bytes": 1200,
                        "duration_us": 1_000_000,
                        "media_format": "mp4",
                    }
                ],
            }
        ],
    }
