"""Local operator selection. Execution stays in the existing campaign runner."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from clipforge.campaign.antoine import (
    CAMPAIGN_ID,
    GUIDE_NAME,
    POLICY_ID,
    antoine_policy,
    inventory_sources,
    policy_sha256,
)
from clipforge.campaign.production import (
    NarrationProbe,
    bind_campaign_source,
    list_campaign_runs,
    resume_campaign,
    run_campaign,
    show_campaign_run,
    verify_campaign_run,
)
from clipforge.campaign.providers import CampaignError
from clipforge.language.registry import LanguageCapabilityEntry, capability_for
from clipforge.schemas.assets import AssetDownloadRequest
from clipforge.schemas.campaign_operator import (
    CampaignImportSnapshot,
    CampaignSelectionDocument,
    CampaignSourceChoice,
    SelectionStatus,
)
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import Database

_ZERO = "0" * 64
_TOOL = "clipforge-operator"
_TOOL_VERSION = "0.1.0"


def doctor_text() -> str:
    """Read-only operator readiness. Live Whop discovery is not required."""
    english = capability_for("en-US")
    voice = english.narration_model or "unavailable"
    return "\n".join(
        [
            "PASS operator: local selection",
            "PASS whop_live: not_configured",
            "PASS envato: discovery_only",
            "PASS external_publishing: deferred",
            f"PASS voicestudio: {english.language} {english.narration_evidence} {voice}",
            f"PASS alignment: {english.language} {english.alignment_evidence} {english.alignment}",
            "PASS language_ar: alignment_not_claimed",
            "PASS language_ja: alignment_not_claimed",
            "PASS language_zh_cn: unsupported_language",
            "PASS narration: optional_english",
            "PASS board: loopback only",
            "PASS whop_session: not_supplied",
        ]
    )


def catalogue_fingerprint(campaign_id: str = CAMPAIGN_ID) -> str:
    if campaign_id != CAMPAIGN_ID:
        raise CampaignError("campaign is not in the local catalogue", code="missing_campaign")
    body = [
        {
            "download_status": item.download_status,
            "rights_state": item.rights_state,
            "source_id": item.source_id,
        }
        for item in sorted(inventory_sources(), key=lambda row: row.source_id)
    ]
    return _digest({"campaign_id": campaign_id, "sources": body})


def list_sources_text(campaign_id: str = CAMPAIGN_ID) -> str:
    if campaign_id != CAMPAIGN_ID:
        raise CampaignError("campaign is not in the local catalogue", code="missing_campaign")
    lines = []
    for item in sorted(inventory_sources(), key=lambda row: row.source_id):
        lines.append(f"{item.source_id} {item.rights_state} {item.download_status}")
    return "\n".join(lines)


def show_text(campaign_id: str) -> str:
    """Read-only campaign summary. This does not open a database."""
    payload = board_campaign(campaign_id)
    lines = [
        f"campaign {payload['campaign_id']}",
        f"policy {payload['policy_id']} {payload['policy_fingerprint']}",
        f"language {payload['language']}",
        f"narration {payload['narration']}",
        f"publishing {payload['publishing']}",
        f"whop_live {payload['whop_live']}",
        f"envato {payload['envato']}",
        list_sources_text(campaign_id),
    ]
    return "\n".join(lines)


def select_sources(
    work_root: Path,
    *,
    campaign_id: str,
    source_ids: list[str],
    project_id: str,
    operator_id: str,
    language: str = "en-US",
    narration_enabled: bool = False,
    expected_sidecar_sha256: str | None = None,
    database: Database | None = None,
) -> CampaignSelectionDocument:
    """Validate and append one selection. An identical current selection is returned as-is."""
    root = work_root.resolve()
    capability = _require_language(language)
    if narration_enabled and capability.narration_evidence != "verified_live":
        code = capability.narration_reason if capability.narration_reason != "none" else "unsupported_language"
        raise CampaignError("narration locale is not verified", code=code)
    if len(source_ids) != len(set(source_ids)):
        raise CampaignError("duplicate campaign source id", code="duplicate_source")
    catalogue = {item.source_id: item for item in inventory_sources()}
    if campaign_id != CAMPAIGN_ID:
        raise CampaignError("campaign is not in the local catalogue", code="missing_campaign")
    chosen = []
    for source_id in sorted(source_ids):
        item = catalogue.get(source_id)
        if item is None:
            raise CampaignError("campaign source is not in the catalogue", code="missing_source")
        if item.download_status == "not_selected_for_round_18":
            raise CampaignError("unselected source cannot enter a campaign run", code="not_selected")
        chosen.append(item)
    if not chosen:
        raise CampaignError("campaign selection has no sources", code="missing_source")
    choices: list[CampaignSourceChoice] = []
    projects: set[str] = set()
    status: SelectionStatus = "ready"
    reason = "ready"
    for item in chosen:
        if str(item.rights_state) != "allowed":
            choices.append(
                CampaignSourceChoice(
                    source_id=item.source_id,
                    source_sha256=_manifest_sha(database, item.source_id),
                    rights_state=str(item.rights_state),
                )
            )
            status, reason = "blocked", "rights_not_allowed"
            continue
        if database is None:
            raise CampaignError("campaign database is required to bind a source", code="missing_source")
        bound = bind_campaign_source(database, item.source_id)
        if bound.binding is None:
            choices.append(
                CampaignSourceChoice(
                    source_id=item.source_id,
                    source_sha256=bound.expected_sha256,
                    rights_state="allowed",
                )
            )
            status, reason = "blocked", bound.reason or "missing_source"
            continue
        if bound.binding.project_id != project_id:
            raise CampaignError("campaign sources belong to different projects", code="mixed_project")
        projects.add(bound.binding.project_id)
        choices.append(
            CampaignSourceChoice(
                source_id=item.source_id,
                source_sha256=bound.binding.source_sha256,
                rights_state="allowed",
            )
        )
    if len(projects) > 1:
        raise CampaignError("campaign sources belong to different projects", code="mixed_project")
    now = datetime.now(UTC)
    evidence = _digest(
        {
            "campaign_id": campaign_id,
            "catalogue": catalogue_fingerprint(campaign_id),
            "language": capability.language,
            "narration_enabled": narration_enabled,
            "operator_id": operator_id,
            "policy": policy_sha256(),
            "project_id": project_id,
            "reason": reason,
            "sources": [item.model_dump(mode="json") for item in choices],
            "status": status,
        }
    )
    current = _latest(root, campaign_id)
    if (
        current is not None
        and current.evidence_fingerprint == evidence
        and current.status == status
        and current.project_id == project_id
    ):
        return current
    _reject_stale_page(root, campaign_id, expected_sidecar_sha256)
    asset_ids = [item.source_id for item in choices]
    document = CampaignSelectionDocument(
        selection_id=str(uuid4()),
        campaign_id=campaign_id,
        project_id=project_id,
        source_ids=[item.source_id for item in choices],
        sources=choices,
        language=capability.language,
        narration_enabled=narration_enabled,
        narration_policy="optional_english" if narration_enabled else "disabled",
        operator_id=operator_id,
        created_at=now,
        catalogue_fingerprint=catalogue_fingerprint(campaign_id),
        policy_fingerprint=policy_sha256(),
        evidence_fingerprint=evidence,
        status=status,
        reason_code=reason,
        provenance=ArtifactProvenance(
            created_at=now,
            created_by=operator_id,
            tool=_TOOL,
            tool_version=_TOOL_VERSION,
            source_asset_ids=asset_ids,
            inputs_sha256=evidence,
        ),
    )
    _write_new(root, document)
    return document


def verify_selection(work_root: Path, selection_id: str, *, database: Database | None = None) -> str:
    """Re-check a selection. This command does not write."""
    document = _read(work_root.resolve(), selection_id)
    _revalidate(document, database)
    return f"PASS campaign selection {document.selection_id}"


def run_selection(
    database: Database,
    work_root: Path,
    selection_id: str,
    *,
    created_by: str,
    narration_probe: NarrationProbe | None = None,
) -> str:
    """Execute one validated selection through the existing production runner."""
    root = work_root.resolve()
    document = _read(root, selection_id)
    _revalidate(document, database)
    if document.status != "ready":
        raise CampaignError("campaign selection is not ready", code=document.reason_code)
    _require_acquisition_or_binding(root, database, document)
    produced = run_campaign(
        database,
        root,
        campaign_id=document.campaign_id,
        source_ids=list(document.source_ids),
        language=document.language,
        narration_enabled=document.narration_enabled,
        created_by=created_by,
        narration_probe=narration_probe,
    )
    from clipforge.campaign.acquisition import write_operator_binding

    write_operator_binding(
        root,
        campaign_run_id=produced.campaign_run_id,
        campaign_id=produced.campaign_id,
        selection=document,
        selection_sha256=_file_sha(root, document.selection_id),
        produced_sources=[item.model_dump(mode="json") for item in produced.sources],
        language=produced.language,
        narration_enabled=produced.narration_enabled,
    )
    return produced.campaign_run_id


def resume_run(database: Database, work_root: Path, campaign_run_id: str, *, created_by: str) -> str:
    document = resume_campaign(database, work_root, campaign_run_id, created_by=created_by)
    return document.campaign_run_id


def status_text(work_root: Path, campaign_run_id: str) -> str:
    return show_campaign_run(work_root, campaign_run_id)


def verify_run(database: Database, work_root: Path, campaign_run_id: str) -> str:
    return verify_campaign_run(database, work_root, campaign_run_id)


def import_snapshot(
    work_root: Path,
    payload: bytes,
    *,
    database: Database | None = None,
    project_id: str,
    expected_sidecar_sha256: str | None = None,
) -> CampaignSelectionDocument:
    """Validate an operator-supplied snapshot and select those sources. No account is contacted."""
    snapshot = _parse_import(payload)
    if snapshot.selection_state != "selected":
        raise CampaignError("withheld snapshot sources are not selected", code="not_selected")
    return select_sources(
        work_root,
        campaign_id=snapshot.campaign_id,
        source_ids=list(snapshot.source_ids),
        project_id=project_id,
        operator_id=snapshot.operator_id,
        language=snapshot.language,
        narration_enabled=snapshot.narration_enabled,
        expected_sidecar_sha256=expected_sidecar_sha256,
        database=database,
    )


def board_campaigns() -> dict[str, object]:
    return {
        "campaigns": [CAMPAIGN_ID],
        "publishing": "deferred",
        "whop_live": "not_configured",
        "envato": "discovery_only",
    }


def board_campaign(
    campaign_id: str,
    work_root: Path | None = None,
    database: Database | None = None,
) -> dict[str, object]:
    if campaign_id != CAMPAIGN_ID:
        raise CampaignError("campaign is not in the local catalogue", code="missing_campaign")
    policy = antoine_policy()
    english = capability_for(policy.default_language)
    payload: dict[str, object] = {
        "campaign_id": campaign_id,
        "title": "Antoine Sallis Clipping",
        "guide_name": GUIDE_NAME,
        "policy_id": POLICY_ID,
        "policy_fingerprint": policy.policy_sha256,
        "language": english.language,
        "alignment": english.alignment_evidence,
        "narration": english.narration_evidence,
        "voicestudio": english.narration_model or "unavailable",
        "publishing": "deferred",
        "whop_live": "not_configured",
        "envato": "discovery_only",
        "policy_rules": [
            {
                "rule_id": rule.rule_id,
                "name": rule.name,
                "outcome": rule.outcome,
                "description": rule.description,
            }
            for rule in policy.rules
        ],
        "sources": board_sources(campaign_id, database)["sources"],
        "envato_records": _envato_records(work_root, campaign_id),
    }
    _reject_public_leak(payload)
    return payload


def board_sources(campaign_id: str, database: Database | None = None) -> dict[str, object]:
    if campaign_id != CAMPAIGN_ID:
        raise CampaignError("campaign is not in the local catalogue", code="missing_campaign")
    capability = capability_for("en-US")
    rows = []
    for item in sorted(inventory_sources(), key=lambda row: row.source_id):
        facts = _media_facts(database, item.source_id)
        rows.append(
            {
                "source_id": item.source_id,
                "display_name": item.display_name,
                "rights_state": item.rights_state,
                "download_status": item.download_status,
                "selected": item.download_status != "not_selected_for_round_18",
                "catalogue_size_bytes": item.size_bytes,
                "language": capability.language,
                "narration": capability.narration_evidence,
                "alignment": capability.alignment_evidence,
                "duration_us": facts["duration_us"],
                "size_bytes": facts["size_bytes"],
                "source_sha256": facts["media_sha256"],
                "verification": facts["verification"],
                "reason_code": facts["reason_code"],
                "notes": "",
            }
        )
    payload: dict[str, object] = {"campaign_id": campaign_id, "sources": rows, "publishing": "deferred"}
    _reject_public_leak(payload)
    return payload


def board_run(work_root: Path, campaign_run_id: str) -> dict[str, object]:
    document = json.loads(show_campaign_run(work_root, campaign_run_id))
    sources = [_source_view(source) for source in document["sources"]]
    payload: dict[str, object] = {
        "campaign_run_id": document["campaign_run_id"],
        "campaign_id": document["campaign_id"],
        "status": document["status"],
        "reason_code": document["reason_code"],
        "fingerprint": document["fingerprint"],
        "language": document["language"],
        "publishing": document.get("publishing", "deferred"),
        "readiness": _readiness(str(document["status"]), sources),
        "sources": sources,
    }
    _reject_public_leak(payload)
    return payload


def board_source(work_root: Path, campaign_run_id: str, source_id: str) -> dict[str, object]:
    payload = board_run(work_root, campaign_run_id)
    sources = payload["sources"]
    if not isinstance(sources, list):
        raise CampaignError("campaign run sources are missing", code="invalid_document")
    for source in sources:
        if isinstance(source, dict) and source.get("source_id") == source_id:
            detail = {
                "campaign_run_id": payload["campaign_run_id"],
                "campaign_id": payload["campaign_id"],
                "fingerprint": payload["fingerprint"],
                "publishing": payload["publishing"],
                "readiness": payload["readiness"],
                **source,
            }
            _reject_public_leak(detail)
            return detail
    raise CampaignError("campaign source is not in this run", code="missing_source")


def board_runs(work_root: Path, campaign_id: str) -> dict[str, object]:
    if campaign_id != CAMPAIGN_ID:
        raise CampaignError("campaign is not in the local catalogue", code="missing_campaign")
    rows = []
    for run_id in list_campaign_runs(work_root):
        try:
            payload = json.loads(show_campaign_run(work_root, run_id))
        except CampaignError:
            continue
        if payload.get("campaign_id") == campaign_id:
            rows.append(
                {
                    "campaign_run_id": run_id,
                    "status": payload.get("status"),
                    "reason_code": payload.get("reason_code"),
                    "fingerprint": payload.get("fingerprint"),
                }
            )
    return {"campaign_id": campaign_id, "runs": rows, "publishing": "deferred"}


def _source_view(source: dict[str, object]) -> dict[str, object]:
    delivery = source.get("delivery_id")
    candidates = source.get("candidates")
    first = candidates[0] if isinstance(candidates, list) and candidates else {}
    if not isinstance(first, dict):
        first = {}
    candidate_id = first.get("candidate_id")
    review_path = None if not isinstance(candidate_id, str) else f"review/candidates/{candidate_id}"
    hero_path = None if not isinstance(candidate_id, str) else f"hero-review/candidates/{candidate_id}"
    stages = source.get("stages")
    stage_rows = []
    if isinstance(stages, list):
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            stage_rows.append(
                {
                    "stage": stage.get("stage"),
                    "status": stage.get("status"),
                    "cache_hit": stage.get("cache_hit"),
                    "reason_code": stage.get("reason_code"),
                }
            )
    return {
        "source_id": source.get("source_id"),
        "status": source.get("status"),
        "reason_code": source.get("reason_code"),
        "cache_status": source.get("cache_status"),
        "source_sha256": source.get("source_sha256"),
        "rights_state": source.get("rights_state"),
        "delivery_relative": None if not delivery else f"deliveries/{delivery}/manifest.json",
        "qa_set_id": source.get("qa_set_id"),
        "qa_status": first.get("qa_status"),
        "review_decision": first.get("review_decision"),
        "hero_review_id": first.get("hero_review_id"),
        "candidate_review_path": review_path,
        "hero_review_path": hero_path,
        "stages": stage_rows,
    }


def _readiness(status: str, sources: list[dict[str, object]]) -> str:
    if status == "succeeded" and all(item.get("delivery_relative") for item in sources):
        return "locally_deliverable"
    if status == "blocked":
        return "blocked"
    if status == "cancelled":
        return "cancelled"
    if status == "failed":
        return "failed"
    return "partial"


def _require_acquisition_or_binding(
    root: Path, database: Database, document: CampaignSelectionDocument
) -> None:
    """A bound unchanged source may run. Otherwise a verified acquisition is required."""
    from clipforge.campaign.acquisition import latest_successful_result

    for choice in document.sources:
        bound = bind_campaign_source(database, choice.source_id)
        acquired = latest_successful_result(root, choice.source_id, choice.source_sha256)
        if bound.binding is not None and bound.binding.source_sha256 == choice.source_sha256:
            continue
        if acquired is None:
            raise CampaignError("selected source has no verified acquisition", code="acquisition_missing")


def _revalidate(document: CampaignSelectionDocument, database: Database | None) -> None:
    if document.catalogue_fingerprint != catalogue_fingerprint(document.campaign_id):
        raise CampaignError("campaign catalogue changed", code="stale_catalogue")
    if document.policy_fingerprint != policy_sha256():
        raise CampaignError("campaign policy changed", code="stale_policy")
    if document.project_id:
        pass
    capability_for(document.language)
    if document.narration_enabled:
        capability = capability_for(document.language)
        if capability.narration_evidence != "verified_live":
            raise CampaignError("narration locale is not verified", code="unsupported_language")
    if database is None:
        return
    projects: set[str] = set()
    for choice in document.sources:
        if choice.rights_state != "allowed":
            raise CampaignError("campaign source rights are not allowed", code="rights_not_allowed")
        bound = bind_campaign_source(database, choice.source_id)
        if bound.binding is None:
            raise CampaignError(
                "campaign source no longer matches the selection",
                code=bound.reason or "missing_source",
            )
        if bound.binding.project_id != document.project_id:
            raise CampaignError("campaign sources belong to different projects", code="mixed_project")
        if bound.binding.source_sha256 != choice.source_sha256:
            raise CampaignError("campaign source hash changed", code="source_changed")
        projects.add(bound.binding.project_id)
    if len(projects) > 1:
        raise CampaignError("campaign sources belong to different projects", code="mixed_project")


def _reject_stale_page(root: Path, campaign_id: str, expected: str | None) -> None:
    current = _latest(root, campaign_id)
    current_hash = None if current is None else _file_sha(root, current.selection_id)
    if expected is None:
        if current is not None:
            raise CampaignError(
                "The campaign selection changed while this page was open; reload before saving.",
                code="stale_selection",
            )
        return
    if current_hash != expected:
        raise CampaignError(
            "The campaign selection changed while this page was open; reload before saving.",
            code="stale_selection",
        )


def _latest(root: Path, campaign_id: str) -> CampaignSelectionDocument | None:
    base = root / "campaigns" / "selections"
    if not base.is_dir():
        return None
    found: list[CampaignSelectionDocument] = []
    for path in sorted(base.glob("*/selection.json")):
        if path.is_symlink():
            continue
        try:
            document = CampaignSelectionDocument.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, ValueError):
            continue
        if document.campaign_id == campaign_id:
            found.append(document)
    if not found:
        return None
    return max(found, key=lambda item: (item.created_at, item.selection_id))


def _write_new(root: Path, document: CampaignSelectionDocument) -> None:
    from clipforge.media.workspace import mkdir_contained

    directory = root / "campaigns" / "selections" / document.selection_id
    target = directory / "selection.json"
    if target.exists():
        raise CampaignError("campaign selection already exists", code="stale_selection")
    mkdir_contained(root, directory)
    partial = target.with_name("selection.json.partial")
    partial.write_text(document.model_dump_json() + "\n", encoding="utf-8")
    partial.replace(target)


def _read(root: Path, selection_id: str) -> CampaignSelectionDocument:
    if "/" in selection_id or "\\" in selection_id or ".." in selection_id:
        raise CampaignError("selection id is not safe", code="malformed_id")
    path = root / "campaigns" / "selections" / selection_id / "selection.json"
    if path.is_symlink() or not path.is_file():
        raise CampaignError("campaign selection is missing", code="missing_selection")
    try:
        return CampaignSelectionDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise CampaignError("campaign selection was rejected", code="invalid_document") from exc


def _file_sha(root: Path, selection_id: str) -> str:
    path = root / "campaigns" / "selections" / selection_id / "selection.json"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(body: dict[str, object]) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _require_language(language: str) -> LanguageCapabilityEntry:
    try:
        return capability_for(language)
    except ValueError as exc:
        raise CampaignError("language is unsupported", code="unsupported_language") from exc


def _manifest_sha(database: Database | None, source_id: str) -> str:
    if database is None or not database.path.is_file():
        return _ZERO
    with database.connect() as connection:
        row = connection.execute(
            "SELECT content_sha256 FROM source_manifests WHERE original_filename = ?",
            (f"{source_id}.mp4",),
        ).fetchone()
    if row is None:
        return _ZERO
    value = str(row["content_sha256"])
    if len(value) == 64 and all(char in "0123456789abcdef" for char in value):
        return value
    return _ZERO


def _media_facts(database: Database | None, source_id: str) -> dict[str, object]:
    empty: dict[str, object] = {
        "duration_us": None,
        "size_bytes": None,
        "media_sha256": None,
        "verification": "not_configured",
        "reason_code": "not_configured",
    }
    if database is None or not database.path.is_file():
        return empty
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT content_sha256, size_bytes, canonical_duration_us
            FROM source_manifests
            WHERE original_filename = ?
            """,
            (f"{source_id}.mp4",),
        ).fetchone()
    if row is None:
        return {
            "duration_us": None,
            "size_bytes": None,
            "media_sha256": None,
            "verification": "missing_source",
            "reason_code": "missing_source",
        }
    bound = bind_campaign_source(database, source_id)
    verified = bound.binding is not None
    return {
        "duration_us": int(row["canonical_duration_us"]),
        "size_bytes": int(row["size_bytes"]),
        "media_sha256": bound.expected_sha256,
        "verification": "verified" if verified else (bound.reason or "missing_source"),
        "reason_code": "ready" if verified else (bound.reason or "missing_source"),
    }


def _envato_records(work_root: Path | None, campaign_id: str) -> list[dict[str, object]]:
    if work_root is None:
        return []
    path = work_root.resolve() / "assets" / campaign_id / "asset_download_requests.json"
    if path.is_symlink() or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [{"provider": "envato_mcp", "renderable": False, "reason_code": "invalid_document"}]
    requests = payload.get("requests") if isinstance(payload, dict) else None
    if not isinstance(requests, list):
        return [{"provider": "envato_mcp", "renderable": False, "reason_code": "invalid_document"}]
    rows: list[dict[str, object]] = []
    for item in requests:
        try:
            request = AssetDownloadRequest.model_validate(item)
        except ValidationError:
            rows.append({"provider": "envato_mcp", "renderable": False, "reason_code": "invalid_document"})
            continue
        hit = request.hit
        blocked = hit.campaign_policy_decision == "blocked"
        locally_verified = (
            hit.local_path is not None
            and hit.sha256 is not None
            and hit.download_status == "acquired"
            and bool(hit.license_evidence)
            and bool(hit.item_id)
            and not blocked
        )
        rows.append(
            {
                "provider": hit.provider,
                "provider_version": "not_recorded",
                "search_tool": hit.provider,
                "query": request.query,
                "filters": request.filters,
                "item_url": hit.item_url,
                "item_id": hit.item_id,
                "duration_seconds": hit.duration_seconds,
                "direct_download_url": hit.direct_download_url,
                "rights_status": hit.commercial_use,
                "license_evidence_status": "present" if hit.license_evidence else "missing",
                "download_status": hit.download_status,
                "policy": hit.campaign_policy_decision,
                "renderable": locally_verified,
                "reason_code": "locally_verified" if locally_verified else "discovery_only",
            }
        )
    return rows


def _parse_import(payload: bytes) -> CampaignImportSnapshot:
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise CampaignError("campaign snapshot was rejected", code="invalid_document") from exc
    if not text.strip():
        raise CampaignError("campaign snapshot was rejected", code="invalid_document")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    try:
        if isinstance(parsed, dict):
            snapshots = [CampaignImportSnapshot.model_validate(parsed)]
        elif isinstance(parsed, list):
            snapshots = [CampaignImportSnapshot.model_validate(item) for item in parsed]
        else:
            snapshots = [
                CampaignImportSnapshot.model_validate_json(line) for line in text.splitlines() if line.strip()
            ]
    except (ValidationError, ValueError) as exc:
        raise CampaignError("campaign snapshot was rejected", code="invalid_document") from exc
    if not snapshots:
        raise CampaignError("campaign snapshot was rejected", code="invalid_document")
    first = snapshots[0]
    for item in snapshots[1:]:
        same = (
            item.campaign_id == first.campaign_id
            and item.operator_id == first.operator_id
            and item.language == first.language
            and item.narration_enabled == first.narration_enabled
            and item.policy_state == first.policy_state
            and item.selection_state == first.selection_state
        )
        if not same:
            raise CampaignError("campaign snapshot rows do not match", code="invalid_document")
    source_ids: list[str] = []
    for item in snapshots:
        source_ids.extend(item.source_ids)
    if len(source_ids) != len(set(source_ids)):
        raise CampaignError("duplicate campaign source id", code="duplicate_source")
    if len(snapshots) == 1 and snapshots[0].source_ids == sorted(source_ids):
        return snapshots[0]
    return snapshots[0].model_copy(update={"source_ids": sorted(source_ids)})


def _reject_public_leak(payload: dict[str, object]) -> None:
    text = json.dumps(payload).lower()
    if any(token in text for token in ("/home/", "/tmp/", "/users/", "file://", "bearer ", "token=")):
        raise CampaignError("campaign board payload contains a path or a secret", code="invalid_document")
