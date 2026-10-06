"""Whop snapshot intake. Credentials stay outside Clipforge."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from clipforge.campaign.policy_fingerprint import current_policy_fingerprint
from clipforge.campaign.providers import CampaignError, WhopSnapshotConnector
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import mkdir_contained
from clipforge.schemas.whop import (
    WhopCampaignRecord,
    WhopCampaignSnapshot,
    WhopImportAttempt,
)

_ROOT = ("campaigns", "whop")


class FakeWhopSnapshotConnector:
    """Test double. It does not open a socket or store a cookie."""

    def __init__(self, payload: bytes | None = None) -> None:
        self.payload = payload
        self.calls = 0

    def read_snapshot(self) -> bytes | None:
        self.calls += 1
        return self.payload


def whop_doctor(connector: WhopSnapshotConnector | FakeWhopSnapshotConnector | None = None) -> str:
    """Report connector configuration. This does not open a socket or a browser."""
    del connector
    from clipforge.campaign.whop_mcp import (
        configured_connector,
        configured_connector_url,
        configured_url,
        live_smoke_enabled,
        official_endpoint,
        session_handle,
    )

    live = "not_configured"
    public = "not_configured"
    authenticated = "not_configured"
    session = "not opened"
    if live_smoke_enabled():
        kind = configured_connector()
        if kind == "public" and official_endpoint(configured_url()):
            public = "available"
        elif (
            kind == "authenticated" and session_handle() is not None and configured_connector_url() is not None
        ):
            authenticated = "available"
            session = "handle_only"
        else:
            live = "provider_unavailable"
            public = "unavailable"
            authenticated = "unavailable"
    lines = [
        f"whop_live: {live}",
        "live_smoke: not_executed",
        f"public_provider: {public}",
        f"authenticated_connector: {authenticated}",
        f"session: {session}",
        "auth_required: not_requested",
        "credentials: not stored",
        "cookies: not stored",
        "mutating: disabled",
        "publishing: deferred",
        "endpoint: mcp.whop.com",
        "docs_endpoint: docs.whop.com",
    ]
    return "\n".join(lines)


def import_whop_snapshot(
    work_root: Path,
    payload: bytes,
    *,
    project_id: str,
    force: bool = False,
    promotion_hook: Callable[[str], None] | None = None,
) -> WhopImportAttempt:
    """Validate, then append one sidecar. An invalid payload writes nothing."""
    root = work_root.resolve()
    attempt, raw, write = plan_whop_import(root, payload, project_id=project_id, force=force)
    if write:
        _publish(root, attempt, raw, promotion_hook)
    return attempt


def plan_whop_import(
    work_root: Path,
    payload: bytes,
    *,
    project_id: str,
    force: bool = False,
    provider_id: str = "snapshot",
    provider_version: str = "0",
) -> tuple[WhopImportAttempt, bytes, bool]:
    """Validate a snapshot and report whether a new sidecar must be written."""
    snapshot = parse_whop_bytes(payload)
    raw = _canonical(snapshot)
    digest = hashlib.sha256(raw).hexdigest()
    policy = _policy_fingerprint([item.campaign_id for item in snapshot.campaigns])
    root = work_root.resolve()
    if not force:
        cached = _cached(
            root,
            project_id=project_id,
            digest=digest,
            policy=policy,
            provider_id=provider_id,
            provider_version=provider_version,
            intake_label=snapshot.intake_label,
            operator_id=snapshot.operator_id,
        )
        if cached is not None:
            return cached, raw, False
    now = datetime.now(UTC)
    selectable, status, reason = _selectable(snapshot)
    attempt = WhopImportAttempt(
        import_id=_import_id(
            project_id=project_id,
            digest=digest,
            policy=policy,
            provider_id=provider_id,
            provider_version=provider_version,
            intake_label=snapshot.intake_label,
            operator_id=snapshot.operator_id,
            force=force,
        ),
        project_id=project_id,
        snapshot_sha256=digest,
        policy_fingerprint=policy,
        operator_id=snapshot.operator_id,
        provider_id=provider_id,
        provider_version=provider_version,
        intake_label=snapshot.intake_label,
        campaigns=list(snapshot.campaigns),
        selectable_source_ids=selectable,
        status=status,  # type: ignore[arg-type]
        reason_code=reason,
        created_at=now,
    )
    return attempt, raw, True


def import_from_connector(
    work_root: Path,
    connector: WhopSnapshotConnector | FakeWhopSnapshotConnector,
    *,
    project_id: str,
    force: bool = False,
) -> WhopImportAttempt:
    """Import connector bytes. A missing payload stays not configured."""
    payload = connector.read_snapshot()
    if payload is None:
        raise CampaignError("whop live is not configured", code="not_configured")
    return import_whop_snapshot(work_root, payload, project_id=project_id, force=force)


def list_whop_imports(work_root: Path) -> list[WhopImportAttempt]:
    root = work_root.resolve()
    base = root.joinpath(*_ROOT)
    if base.is_symlink() or not base.is_dir():
        return []
    found: list[WhopImportAttempt] = []
    for child in sorted(base.iterdir()):
        if child.is_symlink() or not child.is_dir():
            continue
        manifest = child / "manifest.json"
        if manifest.is_symlink() or not manifest.is_file():
            continue
        found.append(_load_manifest(manifest))
    return found


def show_whop_campaign(work_root: Path, campaign_id: str) -> dict[str, object]:
    attempt = _latest(work_root.resolve(), campaign_id)
    if attempt is None:
        raise CampaignError("whop campaign is not imported", code="missing_campaign")
    return board_whop_campaign(work_root, campaign_id)


def verify_whop_import(work_root: Path, import_id: str) -> WhopImportAttempt:
    """Re-read the sidecar. This does not write."""
    root = work_root.resolve()
    attempt = _load(root, import_id)
    path = root.joinpath(*_ROOT, import_id, "snapshot.json")
    if path.is_symlink() or not path.is_file():
        raise CampaignError("whop snapshot is missing", code="stale_snapshot")
    if sha256_file(path) != attempt.snapshot_sha256:
        raise CampaignError("whop snapshot changed", code="stale_snapshot")
    current = _policy_fingerprint([item.campaign_id for item in attempt.campaigns])
    if current != attempt.policy_fingerprint:
        raise CampaignError("whop policy changed", code="stale_policy")
    for campaign in attempt.campaigns:
        latest = _latest(root, campaign.campaign_id, project_id=attempt.project_id)
        if latest is None or latest.import_id != attempt.import_id:
            raise CampaignError("a newer whop import is current", code="stale_snapshot")
    return attempt


def select_imported_sources(work_root: Path, import_id: str, source_ids: list[str]) -> list[str]:
    """Bind a selection to the current import. Allowed sources need no second confirmation."""
    attempt = verify_whop_import(work_root, import_id)
    for source_id in source_ids:
        if source_id in attempt.selectable_source_ids:
            continue
        code = "policy_blocked" if _policy_blocks(attempt, source_id) else "rights_not_allowed"
        raise CampaignError("whop source is not selectable", code=code)
    return list(source_ids)


def board_whop_campaign(work_root: Path, campaign_id: str) -> dict[str, object]:
    attempt = _latest(work_root.resolve(), campaign_id)
    if attempt is None:
        payload: dict[str, object] = {
            "campaign_id": campaign_id,
            "whop_live": "not_configured",
            "publishing": "deferred",
            "status": "missing",
            "snapshot_fingerprint": None,
            "policy_fingerprint": None,
            "policy_state": "missing",
            "sources": [],
            "credentials": "not stored",
        }
        _reject_public(payload)
        return payload
    campaign = next(item for item in attempt.campaigns if item.campaign_id == campaign_id)
    sources: list[dict[str, object]] = []
    for source in campaign.sources:
        sources.append(
            {
                "source_id": source.source_id,
                "display_name": source.display_name,
                "rights_state": source.rights_state,
                "policy_state": source.policy_state,
                "selected": source.selected,
                "selectable": source.source_id in attempt.selectable_source_ids,
                "availability": source.availability,
            }
        )
    payload = {
        "campaign_id": campaign_id,
        "import_id": attempt.import_id,
        "whop_live": "not_configured",
        "publishing": "deferred",
        "status": attempt.status,
        "reason_code": attempt.reason_code,
        "snapshot_fingerprint": attempt.snapshot_sha256,
        "policy_fingerprint": attempt.policy_fingerprint,
        "policy_state": campaign.policy_state,
        "category": campaign.category,
        "campaign_status": campaign.status,
        "source_count": len(campaign.sources),
        "operator_id": attempt.operator_id,
        "sources": sources,
        "credentials": "not stored",
    }
    _reject_public(payload)
    return payload


def board_whop_import(work_root: Path, import_id: str) -> dict[str, object]:
    attempt = _load(work_root.resolve(), import_id)
    payload: dict[str, object] = {
        "import_id": attempt.import_id,
        "project_id": attempt.project_id,
        "whop_live": "not_configured",
        "publishing": "deferred",
        "status": attempt.status,
        "reason_code": attempt.reason_code,
        "snapshot_fingerprint": attempt.snapshot_sha256,
        "policy_fingerprint": attempt.policy_fingerprint,
        "selectable_source_ids": list(attempt.selectable_source_ids),
        "campaigns": [item.campaign_id for item in attempt.campaigns],
        "credentials": "not stored",
    }
    _reject_public(payload)
    return payload


def parse_whop_bytes(payload: bytes) -> WhopCampaignSnapshot:
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise CampaignError("whop snapshot was rejected", code="invalid_document") from exc
    if not text.strip():
        raise CampaignError("whop snapshot was rejected", code="invalid_document")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    try:
        if isinstance(parsed, dict):
            return WhopCampaignSnapshot.model_validate(parsed)
        return _parse_jsonl(text)
    except (ValidationError, CampaignError) as exc:
        if isinstance(exc, CampaignError):
            raise
        raise CampaignError("whop snapshot was rejected", code="invalid_document") from exc


def _parse_jsonl(text: str) -> WhopCampaignSnapshot:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    objects: list[Any] = []
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CampaignError("whop snapshot was rejected", code="invalid_document") from exc
        if not isinstance(item, dict):
            raise CampaignError("whop snapshot was rejected", code="invalid_document")
        objects.append(item)
    if not objects or "campaigns" not in objects[0]:
        raise CampaignError("whop snapshot was rejected", code="invalid_document")
    snapshot = WhopCampaignSnapshot.model_validate(objects[0])
    extra: list[WhopCampaignRecord] = []
    for item in objects[1:]:
        extra.append(WhopCampaignRecord.model_validate(item))
    if not extra:
        return snapshot
    merged = snapshot.model_dump(mode="json")
    merged["campaigns"] = [*merged["campaigns"], *[item.model_dump(mode="json") for item in extra]]
    return WhopCampaignSnapshot.model_validate(merged)


def _canonical(snapshot: WhopCampaignSnapshot) -> bytes:
    payload = snapshot.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _policy_fingerprint(campaign_ids: list[str]) -> str:
    parts = [
        f"{campaign_id}:{current_policy_fingerprint(campaign_id)}" for campaign_id in sorted(set(campaign_ids))
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _selectable(snapshot: WhopCampaignSnapshot) -> tuple[list[str], str, str]:
    chosen: list[str] = []
    saw_policy = False
    saw_rights = False
    for campaign in snapshot.campaigns:
        campaign_allowed = campaign.policy_state == "allowed"
        for source in campaign.sources:
            rights_allowed = source.rights_state == "allowed"
            policy_allowed = campaign_allowed and source.policy_state == "allowed"
            if source.selected and rights_allowed and policy_allowed:
                chosen.append(source.source_id)
                continue
            if source.selected and not policy_allowed:
                saw_policy = True
            elif source.selected and not rights_allowed:
                saw_rights = True
    if not snapshot.campaigns:
        return [], "blocked", "no_matching_campaigns"
    unique = sorted(set(chosen))
    if unique:
        return unique, "ready", "ready"
    if saw_policy:
        return [], "blocked", "policy_blocked"
    if saw_rights:
        return [], "blocked", "rights_not_allowed"
    return [], "blocked", "policy_blocked"


def _policy_blocks(attempt: WhopImportAttempt, source_id: str) -> bool:
    for campaign in attempt.campaigns:
        for source in campaign.sources:
            if source.source_id != source_id:
                continue
            if campaign.policy_state != "allowed" or source.policy_state != "allowed":
                return True
    return False


def _import_id(
    *,
    project_id: str,
    digest: str,
    policy: str,
    provider_id: str,
    provider_version: str,
    intake_label: str,
    operator_id: str,
    force: bool,
) -> str:
    raw = json.dumps(
        {
            "project_id": project_id,
            "snapshot_sha256": digest,
            "policy_fingerprint": policy,
            "provider_id": provider_id,
            "provider_version": provider_version,
            "intake_label": intake_label,
            "operator_id": operator_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    mixed = hashlib.sha256(raw).hexdigest()
    if force:
        return f"whop-{mixed[:12]}-{uuid4().hex[:8]}"
    return f"whop-{mixed[:20]}"


def _cached(
    root: Path,
    *,
    project_id: str,
    digest: str,
    policy: str,
    provider_id: str,
    provider_version: str,
    intake_label: str,
    operator_id: str,
) -> WhopImportAttempt | None:
    for attempt in list_whop_imports(root):
        if (
            attempt.project_id == project_id
            and attempt.snapshot_sha256 == digest
            and attempt.policy_fingerprint == policy
            and attempt.provider_id == provider_id
            and attempt.provider_version == provider_version
            and attempt.intake_label == intake_label
            and attempt.operator_id == operator_id
        ):
            return attempt
    return None


def _publish(
    root: Path,
    attempt: WhopImportAttempt,
    snapshot: bytes,
    hook: Callable[[str], None] | None,
) -> None:
    directory = root.joinpath(*_ROOT, attempt.import_id)
    mkdir_contained(root, directory)
    snapshot_partial = directory / "snapshot.json.partial"
    manifest_partial = directory / "manifest.json.partial"
    snapshot_final = directory / "snapshot.json"
    manifest_final = directory / "manifest.json"
    try:
        snapshot_partial.write_bytes(snapshot)
        manifest_partial.write_text(attempt.model_dump_json() + "\n", encoding="utf-8")
        if hook is not None:
            hook("final_rename")
        os.replace(snapshot_partial, snapshot_final)
        os.replace(manifest_partial, manifest_final)
    except Exception:
        for path in (snapshot_partial, manifest_partial, snapshot_final, manifest_final):
            if path.is_symlink():
                continue
            if path.is_file():
                path.unlink()
        raise


def _latest(root: Path, campaign_id: str, *, project_id: str | None = None) -> WhopImportAttempt | None:
    matches = [
        item
        for item in list_whop_imports(root)
        if any(campaign.campaign_id == campaign_id for campaign in item.campaigns)
        and (project_id is None or item.project_id == project_id)
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: (item.created_at, item.import_id))


def _load(root: Path, import_id: str) -> WhopImportAttempt:
    path = root.joinpath(*_ROOT, import_id, "manifest.json")
    if path.is_symlink() or not path.is_file():
        raise CampaignError("whop import is missing", code="missing_import")
    return _load_manifest(path)


def _load_manifest(path: Path) -> WhopImportAttempt:
    try:
        return WhopImportAttempt.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise CampaignError("whop import could not be read", code="invalid_document") from exc


def _reject_public(payload: dict[str, object]) -> None:
    text = json.dumps(payload).lower()
    if any(token in text for token in ("/home/", "/tmp/", "/users/", "file:", "bearer ", "token=", "cookie=")):
        raise CampaignError("whop board payload is not public", code="invalid_document")
