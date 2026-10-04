"""Technical QA for the current advanced Hero artifact. Evidence omits filesystem paths."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import confine_work_path, require_asset
from clipforge.hero.constants import DURATION_TOLERANCE_US, OUTPUT_HEIGHT, OUTPUT_WIDTH
from clipforge.hero.probe import probe_hero
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.advanced import AdvancedHeroDraftSetDocument, AdvancedHeroPlanDocument
from clipforge.schemas.jobs import QACheck, QAStatus
from clipforge.storage import Database


@dataclass(frozen=True, slots=True)
class TechnicalInputs:
    database: Database
    workspace: SourceWorkspace
    root: Path
    document: AdvancedHeroDraftSetDocument
    artifact_id: str
    manifest_sha256: str
    plans: tuple[AdvancedHeroPlanDocument, ...]
    source_sha256: str
    hero_artifact_id: str
    hero_manifest_sha256: str
    hero_alignment_sha256: dict[str, str]
    hero_plan_sha256: dict[str, str]
    visual_sha256: str
    duration_us: int


def technical_checks(inputs: TechnicalInputs) -> list[QACheck]:
    """Return one evidence-backed check per technical fact. Paths stay out of the text."""
    document = inputs.document
    checks = [
        _check(
            "artifact-kind",
            True,
            f"artifact {inputs.artifact_id} kind advanced_hero_draft_set_json set {document.advanced_set_id}",
        ),
        _provenance(inputs),
        _source_binding(inputs),
        _hero_binding(inputs),
        _manifest(inputs),
        _media(inputs),
        _probe(inputs),
        _intervals(inputs),
        _producers(inputs),
        _remote(inputs),
        _reframing(inputs),
        _assets(inputs),
    ]
    return checks


def _provenance(inputs: TechnicalInputs) -> QACheck:
    provenance = inputs.document.provenance
    ok = inputs.document.source_asset_id in provenance.source_asset_ids and bool(provenance.tool)
    return _check(
        "provenance",
        ok,
        f"artifact {inputs.artifact_id} provenance tool {provenance.tool}",
    )


def _source_binding(inputs: TechnicalInputs) -> QACheck:
    ok = inputs.document.source_sha256 == inputs.source_sha256
    return _check(
        "source-binding",
        ok,
        f"source {inputs.document.source_asset_id} sha256 {inputs.source_sha256}",
    )


def _hero_binding(inputs: TechnicalInputs) -> QACheck:
    ok = (
        inputs.document.hero_artifact_id == inputs.hero_artifact_id
        and inputs.document.hero_manifest_sha256 == inputs.hero_manifest_sha256
    )
    return _check(
        "hero-binding",
        ok,
        f"hero artifact {inputs.hero_artifact_id} manifest sha256 {inputs.hero_manifest_sha256}",
    )


def _manifest(inputs: TechnicalInputs) -> QACheck:
    return _check(
        "manifest",
        len(inputs.manifest_sha256) == 64 and bool(inputs.document.drafts),
        f"manifest sha256 {inputs.manifest_sha256} drafts {len(inputs.document.drafts)}",
    )


def _media(inputs: TechnicalInputs) -> QACheck:
    problems: list[str] = []
    for draft in inputs.document.drafts:
        lexical = (
            inputs.workspace.advanced_run_dir(inputs.document.advanced_set_id) / draft.preview_relative_path
        )
        try:
            path = confine_work_path(
                inputs.root,
                lexical.relative_to(inputs.root).as_posix(),
                label="advanced media",
            )
        except (MediaError, ValueError):
            problems.append(f"candidate {draft.candidate_id} media is a symlink or escapes the work root")
            continue
        if not path.is_file():
            problems.append(f"candidate {draft.candidate_id} media is missing")
            continue
        if path.stat().st_size == 0:
            problems.append(f"candidate {draft.candidate_id} media is zero bytes")
            continue
        if sha256_file(path) != draft.preview_sha256 or path.stat().st_size != draft.preview_size_bytes:
            problems.append(f"candidate {draft.candidate_id} media hash does not match the manifest")
    if problems:
        return _check("media-file", False, "; ".join(problems))
    count = len(inputs.document.drafts)
    return _check("media-file", True, f"{count} advanced media files match the manifest hashes")


def _probe(inputs: TechnicalInputs) -> QACheck:
    facts: list[str] = []
    for draft in inputs.document.drafts:
        lexical = (
            inputs.workspace.advanced_run_dir(inputs.document.advanced_set_id) / draft.preview_relative_path
        )
        try:
            path = confine_work_path(
                inputs.root,
                lexical.relative_to(inputs.root).as_posix(),
                label="advanced media",
            )
        except (MediaError, ValueError):
            return _check("media-probe", False, f"candidate {draft.candidate_id} media is not a regular file")
        if not path.is_file() or path.stat().st_size == 0:
            return _check("media-probe", False, f"candidate {draft.candidate_id} media cannot be probed")
        try:
            probed = probe_hero(path, expected_duration_us=draft.output_duration_us)
        except MediaError as exc:
            text = str(exc).replace(str(inputs.root), "work")
            return _check("media-probe", False, f"candidate {draft.candidate_id} {text}")
        facts.append(
            f"candidate {draft.candidate_id} h264 {probed.pixel_format} aac "
            f"{OUTPUT_WIDTH}x{OUTPUT_HEIGHT} 30/1 duration_error_us {probed.duration_error_us} "
            f"tolerance_us {DURATION_TOLERANCE_US}"
        )
    return _check("media-probe", True, "; ".join(facts))


def _intervals(inputs: TechnicalInputs) -> QACheck:
    problems: list[str] = []
    for plan in inputs.plans:
        events = [("broll", item.interval.output_start_us, item.interval.output_end_us) for item in plan.broll]
        events.extend(("sfx", item.interval.output_start_us, item.interval.output_end_us) for item in plan.sfx)
        events.extend(
            ("typography", item.interval.output_start_us, item.interval.output_end_us)
            for item in plan.typography
        )
        events.extend(
            ("diagram", item.interval.output_start_us, item.interval.output_end_us) for item in plan.diagrams
        )
        for label, start, end in events:
            if start < 0 or end <= start or end > inputs.duration_us:
                problems.append(
                    f"candidate {plan.candidate_id} {label} interval {start}-{end} "
                    f"is outside duration {inputs.duration_us}"
                )
        broll_spans = [(item.interval.output_start_us, item.interval.output_end_us) for item in plan.broll]
        _overlap(plan.candidate_id, "broll", broll_spans, problems)
        _overlap(
            plan.candidate_id,
            "typography",
            [(item.interval.output_start_us, item.interval.output_end_us) for item in plan.typography],
            problems,
        )
    if problems:
        return _check("intervals", False, "; ".join(problems))
    return _check("intervals", True, f"intervals stay inside the {inputs.duration_us} us time map")


def _overlap(candidate_id: str, label: str, spans: list[tuple[int, int]], problems: list[str]) -> None:
    ordered = sorted(spans)
    previous = -1
    for start, end in ordered:
        if start < previous:
            problems.append(f"candidate {candidate_id} {label} intervals overlap")
            return
        previous = end


def _producers(inputs: TechnicalInputs) -> QACheck:
    problems: list[str] = []
    for plan in inputs.plans:
        if plan.source_sha256 != inputs.source_sha256:
            problems.append(f"candidate {plan.candidate_id} source hash is stale")
        if plan.hero_artifact_id != inputs.hero_artifact_id:
            problems.append(f"candidate {plan.candidate_id} hero artifact is stale")
        if plan.hero_manifest_sha256 != inputs.hero_manifest_sha256:
            problems.append(f"candidate {plan.candidate_id} hero manifest is stale")
        if plan.visual_analysis_sha256 != inputs.visual_sha256:
            problems.append(f"candidate {plan.candidate_id} visual analysis is stale")
        alignment = inputs.hero_alignment_sha256.get(plan.candidate_id)
        hero_plan = inputs.hero_plan_sha256.get(plan.candidate_id)
        if alignment is None or plan.alignment_sha256 != alignment:
            problems.append(f"candidate {plan.candidate_id} alignment is stale")
        if hero_plan is None or plan.hero_plan_sha256 != hero_plan:
            problems.append(f"candidate {plan.candidate_id} hero plan is stale")
    if problems:
        return _check("producer-hashes", False, "; ".join(problems))
    return _check(
        "producer-hashes",
        True,
        "source, hero, alignment, plan, and visual hashes match the current producers",
    )


def _remote(inputs: TechnicalInputs) -> QACheck:
    for plan in inputs.plans:
        raw = json.dumps(plan.model_dump(mode="json"))
        if "http://" in raw or "https://" in raw:
            return _check("remote-media", False, f"candidate {plan.candidate_id} plan contains a remote URL")
    return _check("remote-media", True, "advanced plans contain no remote media URL")


def _reframing(inputs: TechnicalInputs) -> QACheck:
    strategy = inputs.document.reframing_strategy
    if strategy != "contain":
        return _check("reframing", False, f"reframing strategy {strategy} is not supported")
    return _check("reframing", True, "reframing strategy contain")


def _assets(inputs: TechnicalInputs) -> QACheck:
    problems: list[str] = []
    for plan in inputs.plans:
        for binding in plan.assets:
            try:
                entry, record, path = require_asset(
                    inputs.database,
                    inputs.workspace,
                    project_id=plan.project_id,
                    asset_id=binding.asset_id,
                    expected_kind=binding.kind,
                    work_root=inputs.root,
                )
                if sha256_file(path) != binding.sha256 or entry.file_sha256 != binding.sha256:
                    problems.append(f"asset {binding.asset_id} hash changed")
                elif record.status.value != binding.license_status:
                    problems.append(f"asset {binding.asset_id} rights changed")
            except (MediaError, OSError) as exc:
                text = str(exc).replace(str(inputs.root), "work")
                if str(inputs.root) in text or "://" in text:
                    text = f"asset {binding.asset_id} failed a local path check"
                problems.append(text[:180])
    if problems:
        return _check("asset-rights", False, "; ".join(problems))
    return _check("asset-rights", True, "referenced assets match their rights records and hashes")


def _check(name: str, ok: bool, evidence: str) -> QACheck:
    cleaned = evidence.replace("\\", " ")
    if "://" in cleaned:
        cleaned = f"{name} failed; remote evidence omitted"
    return QACheck(
        name=name,
        status=QAStatus.PASS if ok else QAStatus.FAIL,
        evidence=cleaned[:400],
    )
