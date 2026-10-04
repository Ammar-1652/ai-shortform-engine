"""Deterministic policy checks. JSON cannot name an importer or a shell command."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from clipforge.errors import MediaError, StorageError
from clipforge.hero.advanced_assets import require_asset
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.advanced import AdvancedHeroPlanDocument
from clipforge.schemas.governance import (
    AssetLicenseRecord,
    ComplianceResult,
    ComplianceStatus,
    RightsStatus,
)
from clipforge.storage import Database

_CLEARED = {RightsStatus.OWNED, RightsStatus.LICENSED, RightsStatus.CAMPAIGN_PROVIDED}


@dataclass(frozen=True, slots=True)
class PolicyContext:
    database: Database
    project_id: str
    source_asset_id: str
    source_license: AssetLicenseRecord | None
    plans: tuple[AdvancedHeroPlanDocument, ...]
    work_root: Path
    workspace: SourceWorkspace | None


Evaluator = Callable[[PolicyContext], ComplianceResult]


def evaluate_policy(rule_id: str, context: PolicyContext) -> ComplianceResult:
    """Run one known policy. An unknown id is insufficient evidence, never a pass."""
    evaluator = _EVALUATORS.get(rule_id)
    if evaluator is None:
        return _result(
            rule_id,
            ComplianceStatus.INSUFFICIENT_EVIDENCE,
            f"policy {rule_id} has no deterministic evaluator",
            context.source_asset_id,
        )
    return evaluator(context)


def evaluate_source_rights(context: PolicyContext) -> ComplianceResult:
    record = context.source_license
    source = context.source_asset_id
    if record is None:
        return _result(
            "policy-source-rights",
            ComplianceStatus.INSUFFICIENT_EVIDENCE,
            f"source {source} has no rights record",
            source,
        )
    if record.asset_id != source:
        return _result(
            "policy-source-rights",
            ComplianceStatus.FAIL,
            f"source {source} rights record names another asset",
            source,
        )
    if record.status is RightsStatus.UNKNOWN:
        return _result(
            "policy-source-rights",
            ComplianceStatus.FAIL,
            f"source {source} rights status is unknown",
            source,
        )
    if record.status is RightsStatus.PROHIBITED:
        return _result(
            "policy-source-rights",
            ComplianceStatus.FAIL,
            f"source {source} rights status is prohibited",
            source,
        )
    if record.status not in _CLEARED:
        return _result(
            "policy-source-rights",
            ComplianceStatus.FAIL,
            f"source {source} rights status is {record.status.value}",
            source,
        )
    if record.evidence_uri is None or not record.evidence_uri.strip():
        return _result(
            "policy-source-rights",
            ComplianceStatus.INSUFFICIENT_EVIDENCE,
            f"source {source} rights evidence is missing",
            source,
        )
    return _result(
        "policy-source-rights",
        ComplianceStatus.PASS,
        f"source {source} rights status is {record.status.value}; evidence recorded",
        source,
    )


def evaluate_asset_rights(context: PolicyContext) -> ComplianceResult:
    assets = [binding for plan in context.plans for binding in plan.assets]
    if not assets:
        return _result(
            "policy-asset-rights",
            ComplianceStatus.PASS,
            "advanced plan references no non-source assets",
            context.source_asset_id,
        )
    if context.workspace is None:
        return _result(
            "policy-asset-rights",
            ComplianceStatus.INSUFFICIENT_EVIDENCE,
            "advanced workspace is missing",
            context.source_asset_id,
        )
    problems: list[str] = []
    for plan in context.plans:
        for binding in plan.assets:
            try:
                entry, record, path = require_asset(
                    context.database,
                    context.workspace,
                    project_id=context.project_id,
                    asset_id=binding.asset_id,
                    expected_kind=binding.kind,
                    work_root=context.work_root,
                )
                if entry.file_sha256 != binding.sha256 or sha256_file(path) != binding.sha256:
                    problems.append(f"asset {binding.asset_id} hash changed after planning")
                elif record.status.value != binding.license_status:
                    problems.append(f"asset {binding.asset_id} rights changed after planning")
            except (MediaError, StorageError, OSError) as exc:
                problems.append(_public(str(exc), context.work_root, binding.asset_id))
    if problems:
        return _result(
            "policy-asset-rights",
            ComplianceStatus.FAIL,
            "; ".join(problems),
            context.source_asset_id,
        )
    names = ", ".join(sorted({item.asset_id for item in assets}))
    return _result(
        "policy-asset-rights",
        ComplianceStatus.PASS,
        f"referenced assets passed rights and hash checks: {names}",
        context.source_asset_id,
    )


def _public(text: str, root: Path, asset_id: str) -> str:
    lowered = text.lower()
    if "symlink" in lowered:
        return f"asset {asset_id} is a symlink"
    if "remote" in lowered:
        return f"asset {asset_id} uses a remote URL"
    if "rights" in lowered:
        return f"asset {asset_id} rights are not cleared"
    if "hash" in lowered:
        return f"asset {asset_id} hash does not match"
    if "missing" in lowered or "not in the local catalog" in text:
        return f"asset {asset_id} is missing or not catalogued"
    if str(root) in text or "://" in text or "\\" in text:
        return f"asset {asset_id} failed a local path check"
    return f"asset {asset_id} failed a rights check"


def _result(rule_id: str, status: ComplianceStatus, evidence: str, source_asset_id: str) -> ComplianceResult:
    del source_asset_id
    return ComplianceResult(
        result_id=str(uuid.uuid4()),
        rule_id=rule_id,
        status=status,
        evidence=evidence,
    )


_EVALUATORS: dict[str, Evaluator] = {
    "policy-source-rights": evaluate_source_rights,
    "policy-asset-rights": evaluate_asset_rights,
}
