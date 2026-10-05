"""Persist campaign inventory. Acquisition is explicit and local."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from clipforge.campaign.antoine import (
    CAMPAIGN_ID,
    EVALUATOR_VERSION,
    POLICY_ID,
    antoine_policy,
    file_by_id,
    inventory_sources,
    policy_sha256,
    selected_files,
)
from clipforge.campaign.policy import evaluate_mode, footage_priority
from clipforge.campaign.providers import (
    CampaignError,
    CampaignSourceProvider,
    DryRunSourceProvider,
)
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import ensure_within
from clipforge.schemas.campaign import (
    OperatorAction,
    PolicyDecision,
    SourceAcquisition,
    SourceInventoryManifest,
    SourceRightsEvidence,
)

_ROOT_NAME = "campaigns"


def doctor_text() -> str:
    native = evaluate_mode("clipforge_native_editor")
    blocked = evaluate_mode("external_black_box_ai_tool")
    return "\n".join(
        [
            f"PASS campaign: {CAMPAIGN_ID}",
            f"PASS native_editor: {native.decision}",
            f"PASS external_black_box: {blocked.decision}",
            f"PASS footage_priority: {footage_priority()}",
            "PASS external_publishing: deferred",
            "PASS credentials: not stored",
        ]
    )


def list_text() -> str:
    return CAMPAIGN_ID


def show_text() -> str:
    policy = antoine_policy()
    return json.dumps(
        {
            "campaign_id": CAMPAIGN_ID,
            "policy_id": policy.policy_id,
            "policy_sha256": policy.policy_sha256,
            "default_language": policy.default_language,
            "external_publishing": "deferred",
        },
        sort_keys=True,
    )


def policy_text() -> str:
    return antoine_policy().model_dump_json()


def inventory_text() -> str:
    return json.dumps(
        [item.model_dump(mode="json") for item in inventory_sources()],
        sort_keys=True,
    )


def acquire_plan_text(provider: CampaignSourceProvider | None = None) -> str:
    active = provider or DryRunSourceProvider()
    rows = []
    for item in active.plan():
        rows.append(
            {
                "source_id": item.source_id,
                "drive_id": item.drive_id,
                "display_name": item.display_name,
                "size_bytes": item.size_bytes,
                "download_status": item.download_status,
            }
        )
    return json.dumps(rows, sort_keys=True)


def ingest_campaign(
    work_root: Path,
    provider: CampaignSourceProvider,
    *,
    operator_confirmed: bool = False,
    created_by: str = "campaign",
) -> SourceInventoryManifest:
    """Acquire selected sources. Unselected files are recorded and not fetched."""
    root = work_root.resolve()
    if root.is_symlink():
        raise CampaignError("campaign work root is a symlink", code="symlink")
    now = datetime.now(UTC)
    acquisitions: list[SourceAcquisition] = []
    for item in inventory_sources():
        catalogue = file_by_id(item.source_id)
        if catalogue is None or not catalogue.selected:
            acquisitions.append(
                SourceAcquisition(
                    acquisition_id=f"acq-{item.source_id}",
                    campaign_id=CAMPAIGN_ID,
                    source_id=item.source_id,
                    provider="google_drive",
                    download_status="not_selected_for_round_18",
                    error_code="not_selected_for_round_18",
                )
            )
            continue
        relative = f"{_ROOT_NAME}/{CAMPAIGN_ID}/sources/{item.source_id}.mp4"
        destination = root / relative
        _confine(root, destination)
        try:
            status = provider.acquire(item.source_id, destination)
        except CampaignError as exc:
            acquisitions.append(_acquisition(item.source_id, "rejected", error_code=exc.code))
            continue
        digest = None
        size = None
        acquired_at = None
        local_path = None
        if status == "acquired":
            if destination.is_symlink() or not destination.is_file():
                raise CampaignError("acquired source is missing", code="missing_source")
            digest = sha256_file(destination)
            size = destination.stat().st_size
            acquired_at = now
            local_path = relative
        acquisitions.append(
            _acquisition(
                item.source_id,
                status,
                local_path=local_path,
                digest=digest,
                size=size,
                acquired_at=acquired_at,
                confirmed=operator_confirmed and status == "acquired",
                error_code="none" if status != "provider_unavailable" else "provider_unavailable",
            )
        )
    rights = [
        SourceRightsEvidence(
            evidence_id=f"evidence-guide-{item.source_id}",
            campaign_id=CAMPAIGN_ID,
            source_id=item.source_id,
            evidence_kind="campaign_guide",
            statement="The campaign guide authorizes supplied Antoine Sallis footage.",
            recorded_by=created_by,
        )
        for item in selected_files()
    ]
    if operator_confirmed:
        rights.extend(
            SourceRightsEvidence(
                evidence_id=f"evidence-operator-{item.source_id}",
                campaign_id=CAMPAIGN_ID,
                source_id=item.source_id,
                evidence_kind="operator_authorization",
                statement="The operator confirmed this selected source for round 18.",
                recorded_by=created_by,
            )
            for item in selected_files()
        )
    decisions = _decisions(now, confirmed=operator_confirmed)
    sources = inventory_sources()
    if operator_confirmed:
        sources = [
            item.model_copy(update={"rights_state": "allowed"})
            if item.source_id in {row.source_id for row in selected_files()}
            else item
            for item in sources
        ]
    document = SourceInventoryManifest(
        manifest_id="inventory-antoine-sallis",
        campaign_id=CAMPAIGN_ID,
        policy_sha256=policy_sha256(),
        sources=sources,
        acquisitions=acquisitions,
        rights=rights,
        decisions=decisions,
        created_at=now,
    )
    _write_manifest(root, document)
    _write_action(
        root,
        OperatorAction(
            action_id=hashlib.sha256(document.model_dump_json().encode("utf-8")).hexdigest()[:32],
            campaign_id=CAMPAIGN_ID,
            action="ingest",
            result="recorded",
            error_code="none",
            selected_source_ids=[item.source_id for item in selected_files()],
            created_at=now,
        ),
    )
    return document


def verify_campaign(work_root: Path) -> str:
    """Re-hash acquired files. This command does not download or publish."""
    root = work_root.resolve()
    document = _read_manifest(root)
    for item in document.acquisitions:
        if item.download_status != "acquired" or item.local_relative_path is None or item.sha256 is None:
            continue
        path = root / item.local_relative_path
        _confine(root, path)
        if path.is_symlink() or not path.is_file():
            raise CampaignError("acquired source is missing", code="missing_source")
        if sha256_file(path) != item.sha256:
            raise CampaignError("source hash changed", code="source_mutated")
    source_states = {item.source_id: item.rights_state for item in document.sources}
    for acquisition in document.acquisitions:
        if acquisition.download_status == "acquired" and source_states.get(acquisition.source_id) != "allowed":
            raise CampaignError("source rights are not allowed", code="rights_unverified")
    unselected = [
        item.download_status
        for item in document.acquisitions
        if item.download_status == "not_selected_for_round_18"
    ]
    if len(unselected) != 3:
        raise CampaignError("unselected sources were not preserved", code="inventory_mismatch")
    return "PASS campaign inventory"


def _acquisition(
    source_id: str,
    status: str,
    *,
    local_path: str | None = None,
    digest: str | None = None,
    size: int | None = None,
    acquired_at: datetime | None = None,
    confirmed: bool = False,
    error_code: str = "none",
) -> SourceAcquisition:
    return SourceAcquisition(
        acquisition_id=f"acq-{source_id}",
        campaign_id=CAMPAIGN_ID,
        source_id=source_id,
        provider="google_drive",
        download_status=status,  # type: ignore[arg-type]
        local_relative_path=local_path,
        sha256=digest,
        size_bytes=size,
        acquired_at=acquired_at,
        operator_confirmation=confirmed,
        error_code=error_code,
    )


def _decisions(now: datetime, *, confirmed: bool) -> list[PolicyDecision]:
    native = evaluate_mode("clipforge_native_editor")
    blocked = evaluate_mode("external_black_box_ai_tool")
    voice = evaluate_mode("voice_narration_provider", operator_confirmed=confirmed)
    rows = (
        ("decision-native", native),
        ("decision-black-box", blocked),
        ("decision-voice", voice),
    )
    return [
        PolicyDecision(
            decision_id=decision_id,
            campaign_id=CAMPAIGN_ID,
            policy_id=POLICY_ID,
            policy_sha256=policy_sha256(),
            rule_id=item.rule_id,
            decision=item.decision,
            implementation_mode=item.mode,
            evidence_ids=["evidence-guide-src-before-famous"],
            evaluator_version=EVALUATOR_VERSION,
            human_confirmation="confirmed" if confirmed and item.decision == "allowed" else "not_required",
            created_at=now,
        )
        for decision_id, item in rows
    ]


def _write_manifest(root: Path, document: SourceInventoryManifest) -> None:
    path = root / _ROOT_NAME / CAMPAIGN_ID / "inventory.json"
    _confine(root, path)
    if path.is_symlink() or path.parent.is_symlink():
        raise CampaignError("inventory path is a symlink", code="symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document.model_dump_json() + "\n", encoding="utf-8")


def _write_action(root: Path, action: OperatorAction) -> None:
    path = root / _ROOT_NAME / CAMPAIGN_ID / "actions" / f"{action.action_id}.json"
    _confine(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(action.model_dump_json() + "\n", encoding="utf-8")


def _read_manifest(root: Path) -> SourceInventoryManifest:
    path = root / _ROOT_NAME / CAMPAIGN_ID / "inventory.json"
    _confine(root, path)
    if path.is_symlink() or not path.is_file():
        raise CampaignError("campaign inventory is missing", code="missing_inventory")
    try:
        return SourceInventoryManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise CampaignError("campaign inventory could not be read", code="missing_inventory") from exc


def _confine(root: Path, path: Path) -> None:
    if "\\" in path.as_posix():
        raise CampaignError("acquisition path contains a backslash", code="unsafe_path")
    ensure_within(root, path)
