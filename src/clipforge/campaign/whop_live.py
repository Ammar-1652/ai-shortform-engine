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
    audit_whop_import,
    parse_whop_bytes,
    plan_whop_import,
    verify_whop_import,
    whop_lock,
)
from clipforge.campaign.whop_filter import filter_campaigns, request_fingerprint, source_block_reason
from clipforge.campaign.whop_mcp import (
    PUBLIC_MCP_URL,
    configured_connector,
    configured_connector_url,
    configured_url,
    live_smoke_enabled,
    official_endpoint,
    reject_untrusted_document,
    session_handle,
)
from clipforge.campaign.whop_provider import OfficialGrokProvider, build_live_provider
from clipforge.campaign.whop_tools import tool_map_sha256
from clipforge.media.workspace import mkdir_contained
from clipforge.schemas.whop import WhopCampaignSnapshot, WhopImportAttempt
from clipforge.schemas.whop_discovery import (
    DiscoveryMode,
    LiveStatus,
    WhopCampaignCatalogue,
    WhopDiscoveryAttempt,
    WhopFilterDecision,
    WhopLiveDiscoveryRequest,
    WhopProviderCapability,
    WhopSelectionEvidence,
)

EvidenceOrigin = Literal["test_double", "public_connector", "authenticated_connector"]

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
    evidence_origin = "test_double"
    mode = "live_connector"
    tool_name: str | None = None

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or _sample_public()
        self.calls = 0

    def discover(self) -> dict[str, Any]:
        self.calls += 1
        return dict(self.payload)


class FakeBrowserExportProvider:
    """Operator export bytes. Cookies and profiles are not accepted."""

    provider_id = "browser_export"
    provider_version = "1"
    live_status = "not_configured"
    evidence_origin = "test_double"
    mode = "browser_export"
    tool_name: str | None = None

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def discover(self) -> dict[str, Any]:
        self.calls += 1
        return dict(self.payload)


class UnavailableWhopProvider:
    """A configured connector that cannot be reached."""

    provider_id = "whop"
    provider_version = "official"
    live_status = "provider_unavailable"
    evidence_origin = "test_double"
    mode = "live_connector"
    tool_name: str | None = None

    def discover(self) -> dict[str, Any]:
        raise CampaignError("whop provider is unavailable", code="provider_unavailable")


class MalformedWhopProvider:
    """A provider body that must be rejected before a sidecar is written."""

    provider_id = "fake_whop"
    provider_version = "1"
    live_status = "public_discovery"
    evidence_origin = "test_double"
    mode = "live_connector"
    tool_name: str | None = None

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def discover(self) -> dict[str, Any]:
        return self.payload


def whop_capabilities() -> WhopProviderCapability:
    """Report the connector without opening a session."""
    status: LiveStatus = "not_configured"
    mode: DiscoveryMode = "not_configured"
    public_provider: Literal["not_configured", "available", "unavailable"] = "not_configured"
    authenticated: Literal["not_configured", "available", "unavailable"] = "not_configured"
    if live_smoke_enabled():
        kind = configured_connector()
        if kind == "public" and official_endpoint(configured_url()):
            public_provider = "available"
            mode = "live_connector"
        elif (
            kind == "authenticated" and session_handle() is not None and configured_connector_url() is not None
        ):
            authenticated = "available"
            mode = "browser_export"
        elif kind == "official-grok" and official_endpoint(configured_url()):
            authenticated = "available"
            mode = "live_connector"
        else:
            status = "provider_unavailable"
            public_provider = "unavailable"
            authenticated = "unavailable"
    return WhopProviderCapability(
        provider_id="whop",
        provider_version="official",
        mode=mode,
        live_status=status,
        public_fields=["title", "campaign_url", "status", "category", "payout_text"],
        account_fields=["membership"],
        public_provider=public_provider,
        authenticated_connector=authenticated,
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
        if exc.code not in {"not_configured", "provider_unavailable"}:
            raise
        return {
            "whop_live": exc.code,
            "publishing": "deferred",
            "credentials": "not stored",
            "mutating_operations": "disabled",
            "campaigns": [],
            "written": False,
        }
    if not isinstance(payload, dict):
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    reject_untrusted_document(payload)
    snapshot = normalize_whop_payload(payload, operator_id=str(payload.get("operator_id") or "operator-1"))
    return {
        "whop_live": _as_live_status(str(getattr(provider, "live_status", ""))),
        "publishing": "deferred",
        "credentials": "not stored",
        "mutating_operations": "disabled",
        "campaigns": [item.campaign_id for item in snapshot.campaigns],
        "missing_fields": _missing_fields(snapshot),
        "evidence_origin": str(getattr(provider, "evidence_origin", "test_double")),
        "live_claim": "not_claimed",
        "written": False,
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
    binder = getattr(provider, "bind_request", None)
    if callable(binder) and request is not None:
        binder(request)
    payload = provider.discover()
    if not isinstance(payload, dict):
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    reject_untrusted_document(payload)
    if "campaigns" not in payload or payload.get("campaigns") is None:
        raise CampaignError("whop provider response was empty", code="empty_discovery")
    snapshot = normalize_whop_payload(payload, operator_id=operator_id)
    tool_name = getattr(provider, "tool_name", None)
    evidence_origin = _as_origin(str(getattr(provider, "evidence_origin", "")))
    live_claim = _accepted_claim(provider, evidence_origin)
    return _store_discovery(
        work_root,
        snapshot,
        project_id=project_id,
        provider_id=str(getattr(provider, "provider_id", "whop")),
        provider_version=str(getattr(provider, "provider_version", "1")),
        live_status=_as_live_status(str(getattr(provider, "live_status", ""))),
        evidence_origin=evidence_origin,
        mode=str(getattr(provider, "mode", "live_connector")),
        tool_name=tool_name if isinstance(tool_name, str) else None,
        operator_id=operator_id,
        request=request,
        force=force,
        promotion_hook=promotion_hook,
        map_sha=_accepted_map_sha(provider),
        live_claim=live_claim,
    )


def discover_live(
    work_root: Path,
    *,
    project_id: str,
    operator_id: str,
    request: WhopLiveDiscoveryRequest | None = None,
    connector: str | None = None,
) -> WhopDiscoveryAttempt:
    """Run the enabled connector. A blocked or empty result is an error after validation."""
    provider = build_live_provider(connector)
    attempt = import_discovered(
        work_root,
        provider,
        project_id=project_id,
        operator_id=operator_id,
        request=request,
    )
    if attempt.live_claim == "claimed" and attempt.evidence_origin != "authenticated_connector":
        raise CampaignError("whop live claim is not allowed", code="forged_status")
    if attempt.live_claim not in {"not_claimed", "claimed"}:
        raise CampaignError("whop live claim is not allowed", code="forged_status")
    if attempt.reason_code == "no_matching_campaigns":
        raise CampaignError("whop discovery matched nothing", code="no_matching_campaigns")
    if attempt.status != "ready":
        raise CampaignError("whop discovery was blocked", code=attempt.reason_code)
    return attempt


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
    if not isinstance(campaigns, list):
        raise CampaignError("whop provider response was malformed", code="invalid_document")
    exported = payload.get("exported_at") or datetime.now(UTC).isoformat()
    document = {
        "schema_version": "1.0.0",
        "operator_id": operator_id,
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
    _revalidate(root, attempt, allow_cancelled=False)
    return attempt


def resume_discovery(work_root: Path, discovery_id: str) -> WhopDiscoveryAttempt:
    """Write a new discovery from a cancelled response. This does not contact Whop."""
    root = work_root.resolve()
    attempt = _load_discovery(root, discovery_id)
    if attempt.status != "cancelled":
        raise CampaignError("whop discovery is not cancelled", code="not_cancelled")
    _revalidate(root, attempt, allow_cancelled=True)
    directory = root.joinpath(*_ROOT, discovery_id)
    response = (directory / "response.json").read_bytes()
    request_bytes = (directory / "request.json").read_bytes()
    snapshot = parse_whop_bytes(response)
    fresh = filter_campaigns(snapshot, attempt.discovery_request) if snapshot.campaigns else []
    if [(item.included, item.included_source_ids, item.reason_code) for item in fresh] != [
        (item.included, item.included_source_ids, item.reason_code) for item in attempt.decisions
    ]:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    included = any(item.included for item in fresh)
    reason = "no_matching_campaigns" if not snapshot.campaigns else ("ready" if included else "policy_blocked")
    new_id = f"disc-{attempt.identity_sha256[:12]}-{uuid4().hex[:8]}"
    resumed = attempt.model_copy(
        update={
            "discovery_id": new_id,
            "decisions": fresh,
            "status": "ready" if included else "blocked",
            "reason_code": reason,
            "cache_status": "miss",
            "created_at": datetime.now(UTC),
        }
    )
    if attempt.import_id is None:
        raise CampaignError("whop import is missing", code="missing_import")
    imported = audit_whop_import(root, attempt.import_id)
    import_dir = root.joinpath("campaigns", "whop", attempt.import_id)
    before = (directory / "manifest.json").read_bytes()
    with whop_lock(root):
        _promote_pair(
            root,
            imported,
            (import_dir / "snapshot.json").read_bytes(),
            False,
            resumed,
            response,
            request_bytes,
            None,
        )
    if (directory / "manifest.json").read_bytes() != before:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    return resumed


def cancel_discovery(work_root: Path, discovery_id: str) -> WhopDiscoveryAttempt:
    """Mark one discovery cancelled and remove a partial file."""
    root = work_root.resolve()
    attempt = _load_discovery(root, discovery_id)
    for partial in root.joinpath(*_ROOT, discovery_id).glob("*.partial"):
        if partial.is_file() and not partial.is_symlink():
            partial.unlink()
    cancelled = attempt.model_copy(update={"status": "cancelled", "reason_code": "cancelled"})
    path = root.joinpath(*_ROOT, discovery_id, "manifest.json")
    with whop_lock(root):
        _replace_bytes(path, (cancelled.model_dump_json() + "\n").encode("utf-8"))
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
    discovery_id: str | None = None,
    expected_catalogue: str | None = None,
    expected_policy: str | None = None,
    expected_source_hashes: dict[str, str] | None = None,
) -> WhopSelectionEvidence:
    """Record an allowed selection. The stored discovery request is enforced again."""
    root = work_root.resolve()
    try:
        discovery = _discovery_for_selection(root, import_id, project_id, discovery_id)
        attempt = verify_whop_import(root, import_id)
    except CampaignError as exc:
        if exc.code in {"stale_snapshot", "stale_policy", "stale_discovery", "stale_selection"}:
            raise CampaignError(_RELOAD, code=exc.code) from exc
        raise
    if attempt.project_id != project_id or discovery.project_id != project_id:
        raise CampaignError("whop discovery belongs to another project", code="project_mismatch")
    if discovery.import_id != import_id:
        raise CampaignError("whop discovery belongs to another project", code="project_mismatch")
    if expected_catalogue is not None and expected_catalogue != attempt.snapshot_sha256:
        raise CampaignError(_RELOAD, code="stale_selection")
    if expected_policy is not None and expected_policy != attempt.policy_fingerprint:
        raise CampaignError(_RELOAD, code="stale_policy")
    if discovery.policy_fingerprint != attempt.policy_fingerprint:
        raise CampaignError(_RELOAD, code="stale_policy")
    if discovery.response_sha256 != attempt.snapshot_sha256:
        raise CampaignError(_RELOAD, code="stale_snapshot")
    response_path = root.joinpath(*_ROOT, discovery.discovery_id, "response.json")
    snapshot = parse_whop_bytes(response_path.read_bytes())
    campaign = next((item for item in snapshot.campaigns if item.campaign_id == campaign_id), None)
    if campaign is None:
        raise CampaignError("whop campaign is not imported", code="missing_campaign")
    fresh = filter_campaigns(snapshot, discovery.discovery_request)
    decision = next((item for item in fresh if item.campaign_id == campaign_id), None)
    stored = next((item for item in discovery.decisions if item.campaign_id == campaign_id), None)
    if stored is None or decision is None or decision.model_dump(mode="json") != stored.model_dump(mode="json"):
        raise CampaignError(_RELOAD, code="stale_selection")
    if decision.filter_fingerprint != discovery.filter_fingerprint:
        raise CampaignError(_RELOAD, code="stale_selection")
    if not decision.included:
        raise CampaignError("whop campaign is excluded", code=decision.reason_code)
    if discovery.operator_id != operator_id:
        raise CampaignError("whop discovery belongs to another operator", code="operator_mismatch")
    if discovery.status != "ready":
        raise CampaignError("whop discovery is blocked", code=discovery.reason_code)
    if attempt.status != "ready":
        raise CampaignError("whop import is blocked", code=attempt.reason_code)
    chosen = sorted(source_ids)
    hashes: list[str | None] = []
    for source_id in chosen:
        source = next((item for item in campaign.sources if item.source_id == source_id), None)
        if source is None:
            raise CampaignError("whop source is missing", code="missing_source")
        blocked = source_block_reason(source, discovery.discovery_request)
        declared = source.declared_content_sha256 or source.content_sha256
        if blocked is not None or source_id not in decision.included_source_ids:
            raise CampaignError("whop source is excluded", code=blocked or "policy_blocked")
        supplied = None if expected_source_hashes is None else expected_source_hashes.get(source_id)
        if declared is not None and supplied is not None and supplied != declared:
            raise CampaignError(_RELOAD, code="source_changed")
        hashes.append(declared)
    now = datetime.now(UTC)
    body = {
        "campaign_id": campaign_id,
        "catalogue": attempt.snapshot_sha256,
        "discovery_id": discovery.discovery_id,
        "filter": discovery.filter_fingerprint,
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
        discovery_id=discovery.discovery_id,
        project_id=project_id,
        catalogue_fingerprint=attempt.snapshot_sha256,
        policy_fingerprint=attempt.policy_fingerprint,
        filter_fingerprint=discovery.filter_fingerprint,
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
            "evidence_origin": item.evidence_origin,
            "live_claim": item.live_claim,
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
        "evidence_origin": item.evidence_origin,
        "live_claim": item.live_claim,
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
    live_status: LiveStatus,
    evidence_origin: EvidenceOrigin,
    mode: str,
    tool_name: str | None,
    operator_id: str,
    request: WhopLiveDiscoveryRequest | None,
    force: bool,
    promotion_hook: Callable[[str], None] | None,
    map_sha: str | None = None,
    live_claim: Literal["not_claimed", "claimed"] = "not_claimed",
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
    decisions = filter_campaigns(snapshot, active_request, now=now) if snapshot.campaigns else []
    if map_sha is None:
        map_sha = tool_map_sha256()
    response = _canonical(snapshot)
    response_sha = hashlib.sha256(response).hexdigest()
    request_sha = request_fingerprint(active_request)
    catalogue = response_sha
    policy = _policy_fingerprint([item.campaign_id for item in snapshot.campaigns])
    discovery_mode = _as_mode(mode)
    declarations = _declaration_sha(snapshot)
    if active_request.require_acquisition_reference:
        acquisition_policy = "require_reference"
    else:
        acquisition_policy = "optional_reference"
    identity = _identity(
        project_id=project_id,
        operator_id=operator_id,
        provider_id=provider_id,
        provider_version=provider_version,
        provider_mode=discovery_mode,
        tool_name=tool_name or "",
        request_sha256=request_sha,
        policy_fingerprint=policy,
        catalogue_fingerprint=catalogue,
        response_sha256=response_sha,
        source_declarations=declarations,
        acquisition_policy=acquisition_policy,
        tool_map_sha256=map_sha,
        evidence_origin=evidence_origin,
        live_claim=live_claim,
    )
    live = live_status
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
        cached = _cache_hit(root, identity, response_sha, project_id)
        if cached is not None:
            return cached
    if not snapshot.campaigns:
        included = False
        reason = "no_matching_campaigns"
    else:
        included = any(item.included for item in decisions)
        reason = "ready" if included else "policy_blocked"
    attempt_import, snapshot_bytes, write_import = plan_whop_import(
        root,
        response,
        project_id=project_id,
        force=force,
        provider_id=provider_id,
        provider_version=provider_version,
    )
    if hashlib.sha256(snapshot_bytes).hexdigest() != attempt_import.snapshot_sha256:
        raise CampaignError("whop snapshot hash changed", code="invalid_document")
    base_id = "disc-" + identity[:20]
    discovery_id = base_id
    if force or _discovery_cancelled(root, base_id):
        discovery_id = f"disc-{identity[:12]}-{uuid4().hex[:8]}"
    attempt = WhopDiscoveryAttempt(
        discovery_id=discovery_id,
        project_id=project_id,
        operator_id=operator_id,
        mode=discovery_mode,
        provider_id=provider_id,
        provider_version=provider_version,
        live_status=live,
        evidence_origin=evidence_origin,
        request_sha256=request_sha,
        filter_fingerprint=request_sha,
        response_sha256=response_sha,
        catalogue_fingerprint=catalogue,
        policy_fingerprint=policy,
        identity_sha256=identity,
        tool_map_sha256=map_sha,
        live_claim=live_claim,
        discovery_request=active_request,
        tool_name=tool_name,
        import_id=attempt_import.import_id,
        campaign_ids=[item.campaign_id for item in snapshot.campaigns],
        decisions=decisions,
        status="ready" if included else "blocked",
        reason_code=reason,
        created_at=now,
    )
    request_bytes = (active_request.model_dump_json() + "\n").encode("utf-8")
    with whop_lock(root):
        _promote_pair(
            root,
            attempt_import,
            snapshot_bytes,
            write_import,
            attempt,
            response,
            request_bytes,
            promotion_hook,
        )
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
        "campaign_type",
        "business_id",
        "platforms",
        "reward_rate_text",
        "currency",
        "budget_text",
        "minimum_payout_text",
        "maximum_payout_text",
        "flat_fee_text",
        "footage_references",
        "requirements_text",
        "prohibited_text",
        "required_messaging",
        "required_duration_text",
        "required_format",
        "policy_evidence",
        "provider_updated_at",
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
        "campaign_type": item.get("campaign_type"),
        "business_id": item.get("business_id"),
        "platforms": item.get("platforms") or [],
        "reward_rate_text": item.get("reward_rate_text"),
        "currency": item.get("currency"),
        "budget_text": item.get("budget_text"),
        "minimum_payout_text": item.get("minimum_payout_text"),
        "maximum_payout_text": item.get("maximum_payout_text"),
        "flat_fee_text": item.get("flat_fee_text"),
        "footage_references": item.get("footage_references") or [],
        "requirements_text": item.get("requirements_text"),
        "prohibited_text": item.get("prohibited_text"),
        "required_messaging": item.get("required_messaging"),
        "required_duration_text": item.get("required_duration_text"),
        "required_format": item.get("required_format"),
        "policy_evidence": item.get("policy_evidence"),
        "provider_updated_at": item.get("provider_updated_at"),
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
        "media_download_url",
        "declared_content_sha256",
        "acquired_file_sha256",
        "acquired_file_size",
        "acquired_ffprobe_fingerprint",
        "acquisition_reference",
        "acquisition_status",
        "direct_download",
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
        "media_download_url": item.get("media_download_url"),
        "declared_content_sha256": item.get("declared_content_sha256"),
        "acquired_file_sha256": item.get("acquired_file_sha256"),
        "acquired_file_size": item.get("acquired_file_size"),
        "acquired_ffprobe_fingerprint": item.get("acquired_ffprobe_fingerprint"),
        "acquisition_reference": item.get("acquisition_reference"),
        "acquisition_status": item.get("acquisition_status") or "unknown",
        "direct_download": item.get("direct_download") or "unknown",
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
    return request_fingerprint(request)


def _declaration_sha(snapshot: WhopCampaignSnapshot) -> str:
    """Hash declared source facts. A page URL is not a file hash."""
    rows = [
        {
            "campaign_id": campaign.campaign_id,
            "source_id": source.source_id,
            "declared_content_sha256": source.declared_content_sha256,
            "acquisition_reference": source.acquisition_reference,
            "acquisition_status": source.acquisition_status,
            "direct_download": source.direct_download,
        }
        for campaign in snapshot.campaigns
        for source in campaign.sources
    ]
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _accepted_claim(provider: _Provider, evidence_origin: str) -> Literal["not_claimed", "claimed"]:
    """Allow a live claim only after the official endpoint call completed."""
    claim = getattr(provider, "live_claim", "not_claimed")
    if claim == "not_claimed":
        return "not_claimed"
    official = (
        isinstance(provider, OfficialGrokProvider)
        and claim == "claimed"
        and getattr(provider, "official_call_completed", False) is True
        and evidence_origin == "authenticated_connector"
        and getattr(provider, "live_status", "") == "authenticated_discovery"
        and getattr(provider, "url", "") == PUBLIC_MCP_URL
        and getattr(provider, "opener", "missing") is None
        and getattr(provider, "allow_loopback", False) is False
        and getattr(provider, "allow_fixture", False) is False
    )
    if official:
        return "claimed"
    raise CampaignError("whop live claim is not allowed", code="forged_status")


def _accepted_map_sha(provider: _Provider) -> str:
    """Use the packaged hash, or the current operator map when the provider names it."""
    packaged = tool_map_sha256()
    supplied = getattr(provider, "tool_map_sha256", None)
    if not isinstance(supplied, str):
        return packaged
    if len(supplied) != 64 or set(supplied) - set("0123456789abcdef"):
        raise CampaignError("whop tool map could not be read", code="invalid_document")
    if supplied == packaged:
        return supplied
    from clipforge.campaign.whop_tools import load_verified_tool_map

    try:
        rows, current = load_verified_tool_map()
    except CampaignError as exc:
        raise CampaignError("whop tool map could not be read", code="invalid_document") from exc
    if rows and supplied == current:
        return supplied
    raise CampaignError("whop discovery changed", code="stale_discovery")


def _map_sha_still_valid(digest: str) -> bool:
    if digest == tool_map_sha256():
        return True
    from clipforge.campaign.whop_tools import load_verified_tool_map

    try:
        rows, current = load_verified_tool_map()
    except CampaignError:
        return False
    return bool(rows) and current == digest


def _identity(**parts: str) -> str:
    raw = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cache_hit(
    root: Path,
    identity: str,
    response_sha: str,
    project_id: str,
) -> WhopDiscoveryAttempt | None:
    discovery_id = "disc-" + identity[:20]
    directory = root.joinpath(*_ROOT, discovery_id)
    manifest = directory / "manifest.json"
    if not manifest.exists():
        return None
    if manifest.is_symlink() or not manifest.is_file():
        raise CampaignError("whop discovery changed", code="stale_discovery")
    try:
        item = WhopDiscoveryAttempt.model_validate_json(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise CampaignError("whop discovery changed", code="stale_discovery") from exc
    if item.status == "cancelled" and item.identity_sha256 == identity and item.project_id == project_id:
        return None
    if item.project_id != project_id or item.identity_sha256 != identity:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    if item.response_sha256 != response_sha:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    _revalidate(root, item, allow_cancelled=False)
    return item.model_copy(update={"cache_status": "hit"})


def _revalidate(root: Path, attempt: WhopDiscoveryAttempt, *, allow_cancelled: bool) -> None:
    directory = root.joinpath(*_ROOT, attempt.discovery_id)
    manifest = directory / "manifest.json"
    response_path = directory / "response.json"
    request_path = directory / "request.json"
    for path in (manifest, response_path, request_path):
        if path.is_symlink() or not path.is_file():
            raise CampaignError("whop discovery changed", code="stale_discovery")
    try:
        loaded = WhopDiscoveryAttempt.model_validate_json(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise CampaignError("whop discovery changed", code="stale_discovery") from exc
    if loaded.model_dump(mode="json") != attempt.model_dump(mode="json"):
        raise CampaignError("whop discovery changed", code="stale_discovery")
    if manifest.read_text(encoding="utf-8") != loaded.model_dump_json() + "\n":
        raise CampaignError("whop discovery changed", code="stale_discovery")
    response = response_path.read_bytes()
    request_bytes = request_path.read_bytes()
    if hashlib.sha256(response).hexdigest() != attempt.response_sha256:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    try:
        stored_request = WhopLiveDiscoveryRequest.model_validate_json(request_bytes.decode("utf-8"))
        snapshot = parse_whop_bytes(response)
    except (UnicodeError, ValidationError) as exc:
        raise CampaignError("whop discovery changed", code="stale_discovery") from exc
    if request_fingerprint(stored_request) != attempt.filter_fingerprint:
        raise CampaignError("whop discovery request changed", code="stale_discovery")
    if hashlib.sha256(response).hexdigest() != attempt.catalogue_fingerprint:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    if _policy_fingerprint(list(attempt.campaign_ids)) != attempt.policy_fingerprint:
        raise CampaignError("whop policy changed", code="stale_policy")
    if not _map_sha_still_valid(attempt.tool_map_sha256):
        raise CampaignError("whop discovery changed", code="stale_discovery")
    recomputed = _identity(
        project_id=attempt.project_id,
        operator_id=attempt.operator_id,
        provider_id=attempt.provider_id,
        provider_version=attempt.provider_version,
        provider_mode=attempt.mode,
        tool_name=attempt.tool_name or "",
        request_sha256=attempt.request_sha256,
        policy_fingerprint=attempt.policy_fingerprint,
        catalogue_fingerprint=attempt.catalogue_fingerprint,
        response_sha256=attempt.response_sha256,
        source_declarations=_declaration_sha(snapshot),
        acquisition_policy=_acquisition_policy(attempt.discovery_request),
        tool_map_sha256=attempt.tool_map_sha256,
        evidence_origin=attempt.evidence_origin,
        live_claim=attempt.live_claim,
    )
    if recomputed != attempt.identity_sha256:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    prefix = "disc-" + recomputed[:20]
    resumed_prefix = "disc-" + recomputed[:12] + "-"
    if attempt.discovery_id != prefix and not attempt.discovery_id.startswith(resumed_prefix):
        raise CampaignError("whop discovery changed", code="stale_discovery")
    if attempt.evidence_origin not in {"test_double", "public_connector", "authenticated_connector"}:
        raise CampaignError("whop provider status was forged", code="forged_status")
    authenticated = attempt.live_status == "authenticated_discovery"
    if authenticated and attempt.evidence_origin != "authenticated_connector":
        raise CampaignError("whop provider status was forged", code="forged_status")
    fresh = filter_campaigns(snapshot, stored_request) if snapshot.campaigns else []
    if [item.model_dump(mode="json") for item in attempt.decisions] != [
        item.model_dump(mode="json") for item in fresh
    ]:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    if list(attempt.campaign_ids) != [item.campaign_id for item in snapshot.campaigns]:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    if attempt.status != "cancelled":
        expected_status, expected_reason = _discovery_outcome(snapshot, fresh)
        if attempt.status != expected_status or attempt.reason_code != expected_reason:
            raise CampaignError("whop discovery changed", code="stale_discovery")
    if attempt.import_id is None:
        raise CampaignError("whop import is missing", code="missing_import")
    imported = audit_whop_import(root, attempt.import_id)
    if imported.import_id != attempt.import_id or imported.project_id != attempt.project_id:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    if imported.snapshot_sha256 != attempt.response_sha256:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    if imported.policy_fingerprint != attempt.policy_fingerprint:
        raise CampaignError("whop policy changed", code="stale_policy")
    if imported.provider_id != attempt.provider_id or imported.provider_version != attempt.provider_version:
        raise CampaignError("whop discovery changed", code="stale_discovery")
    if attempt.status == "ready" and imported.status != "ready":
        raise CampaignError("whop import is blocked", code="stale_import")
    if not allow_cancelled and attempt.status == "cancelled":
        raise CampaignError("whop discovery was cancelled", code="cancelled")


def _discovery_outcome(
    snapshot: WhopCampaignSnapshot,
    decisions: list[WhopFilterDecision],
) -> tuple[str, str]:
    if not snapshot.campaigns:
        return "blocked", "no_matching_campaigns"
    if any(item.included for item in decisions):
        return "ready", "ready"
    return "blocked", "policy_blocked"


def _replace_bytes(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise CampaignError("whop destination is a symlink", code="symlink_rejected")
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(data)
    os.replace(partial, path)


def _acquisition_policy(request: WhopLiveDiscoveryRequest) -> str:
    if request.require_acquisition_reference:
        return "require_reference"
    return "optional_reference"


def _discovery_for_selection(
    root: Path,
    import_id: str,
    project_id: str,
    discovery_id: str | None,
) -> WhopDiscoveryAttempt:
    if discovery_id is not None:
        item = _load_discovery(root, discovery_id)
    else:
        matches = [
            item
            for item in list_discoveries(root)
            if item.import_id == import_id and item.status != "cancelled"
        ]
        owned = [item for item in matches if item.project_id == project_id]
        if not owned:
            if matches:
                raise CampaignError("whop discovery belongs to another project", code="project_mismatch")
            raise CampaignError("whop discovery is missing", code="missing_discovery")
        item = max(owned, key=lambda row: (row.created_at, row.discovery_id))
    if item.project_id != project_id or item.import_id != import_id:
        raise CampaignError("whop discovery belongs to another project", code="project_mismatch")
    return verify_discovery(root, item.discovery_id)


def _promote_pair(
    root: Path,
    imported: WhopImportAttempt,
    snapshot: bytes,
    write_import: bool,
    attempt: WhopDiscoveryAttempt,
    response: bytes,
    request_bytes: bytes,
    hook: Callable[[str], None] | None,
) -> None:
    """Stage the import and the discovery, then promote both. A failure removes this attempt."""
    if hashlib.sha256(response).hexdigest() != attempt.response_sha256:
        raise CampaignError("whop discovery hash changed", code="invalid_document")
    if hashlib.sha256(snapshot).hexdigest() != imported.snapshot_sha256:
        raise CampaignError("whop snapshot hash changed", code="invalid_document")
    import_dir = root.joinpath("campaigns", "whop", imported.import_id)
    disc_dir = root.joinpath(*_ROOT, attempt.discovery_id)
    partials: list[Path] = []
    new_dirs: list[Path] = []

    def fire(name: str) -> None:
        if hook is not None:
            hook(name)

    def stage(directory: Path, name: str, data: bytes, hook_name: str) -> Path:
        fire(hook_name)
        _reject_symlink(directory)
        if not directory.exists():
            mkdir_contained(root, directory)
            new_dirs.append(directory)
        partial = directory / f"{name}.partial"
        partial.write_bytes(data)
        partials.append(partial)
        return partial

    restores: list[tuple[Path, bytes | None]] = []

    def promote(partial: Path, final: Path, hook_name: str) -> None:
        fire(hook_name)
        _reject_symlink(final)
        previous = final.read_bytes() if final.is_file() and not final.is_symlink() else None
        os.replace(partial, final)
        restores.append((final, previous))

    try:
        fire("staging_write")
        import_snapshot = import_dir / "snapshot.json.partial"
        import_manifest = import_dir / "manifest.json.partial"
        if write_import:
            import_snapshot = stage(import_dir, "snapshot.json", snapshot, "stage_import")
            import_manifest = stage(
                import_dir,
                "manifest.json",
                (imported.model_dump_json() + "\n").encode("utf-8"),
                "stage_import_manifest",
            )
        response_partial = stage(disc_dir, "response.json", response, "stage_discovery_response")
        request_partial = stage(disc_dir, "request.json", request_bytes, "stage_discovery_request")
        manifest_partial = stage(
            disc_dir,
            "manifest.json",
            (attempt.model_dump_json() + "\n").encode("utf-8"),
            "stage_discovery_manifest",
        )
        fire("final_rename")
        if write_import:
            promote(import_snapshot, import_dir / "snapshot.json", "promote_import")
            promote(import_manifest, import_dir / "manifest.json", "promote_import_manifest")
        promote(response_partial, disc_dir / "response.json", "promote_discovery_response")
        promote(request_partial, disc_dir / "request.json", "promote_discovery_request")
        promote(manifest_partial, disc_dir / "manifest.json", "promote_discovery_manifest")
        fire("promoted")
    except Exception as exc:
        _rollback(partials, restores, new_dirs)
        if isinstance(exc, CampaignError):
            raise
        raise CampaignError("whop discovery promotion failed", code="promotion_failed") from exc


def _rollback(
    partials: list[Path],
    restores: list[tuple[Path, bytes | None]],
    new_dirs: list[Path],
) -> None:
    for path in partials:
        if path.is_file() and not path.is_symlink():
            path.unlink()
    for path, previous in reversed(restores):
        if path.is_symlink():
            continue
        if previous is None:
            if path.is_file():
                path.unlink()
        else:
            path.write_bytes(previous)
    for directory in reversed(new_dirs):
        if directory.is_symlink() or not directory.is_dir():
            continue
        if not any(directory.iterdir()):
            directory.rmdir()


def _reject_symlink(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise CampaignError("whop destination is a symlink", code="symlink_rejected")
        if current.parent == current:
            return
        current = current.parent


def _load_discovery(root: Path, discovery_id: str) -> WhopDiscoveryAttempt:
    path = root.joinpath(*_ROOT, discovery_id, "manifest.json")
    if path.is_symlink() or not path.is_file():
        raise CampaignError("whop discovery is missing", code="missing_discovery")
    try:
        return WhopDiscoveryAttempt.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise CampaignError("whop discovery changed", code="stale_discovery") from exc


def _reject_public(payload: dict[str, object]) -> None:
    text = json.dumps(payload).lower()
    tokens = ("/home/", "/tmp/", "/users/", "file:", "bearer ", "token=", "cookie=", "password=", "api_key")
    if any(token in text for token in tokens):
        raise CampaignError("whop board payload is not public", code="invalid_document")


def _as_origin(value: str) -> EvidenceOrigin:
    if value == "test_double":
        return "test_double"
    if value == "public_connector":
        return "public_connector"
    if value == "authenticated_connector":
        return "authenticated_connector"
    raise CampaignError("whop provider status was forged", code="forged_status")


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
