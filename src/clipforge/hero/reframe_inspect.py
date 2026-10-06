"""Read-only reframing inspection. These functions do not write rows or files."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError, StorageError
from clipforge.hero.reframe import ReframeError, assert_unlinked, build_face_follow, facts_line
from clipforge.hero.show import load_current_hero
from clipforge.preview.inputs import load_preview_inputs
from clipforge.preview.service import default_profile
from clipforge.schemas.advanced import AdvancedHeroPlanDocument
from clipforge.schemas.reframe import ReframePlanDocument
from clipforge.storage import Database
from clipforge.storage.repository import get_job


def format_reframe_show(
    database: Database,
    source_asset_id: str,
    candidate_id: str,
    work_root: Path,
) -> str:
    """Print the stored strategy. A missing plan is a blocker, not a contain claim."""
    root = work_root.resolve()
    plan, document, blocker = _load(database, source_asset_id, candidate_id, root)
    if plan is None:
        return "\n".join(
            [
                f"candidate_id: {candidate_id}",
                "requested: contain",
                "applied: contain",
                "blocker: visual_analysis_missing",
            ]
        )
    if plan.reframing_strategy != "face_follow" or document is None:
        return "\n".join(
            [
                f"candidate_id: {candidate_id}",
                "requested: contain",
                "applied: contain",
                "trajectory: none",
                f"blocker: {blocker or 'none'}",
            ]
        )
    return "\n".join(
        [
            f"candidate_id: {candidate_id}",
            facts_line(document, blocker=blocker),
        ]
    )


def verify_reframe(
    database: Database,
    source_asset_id: str,
    candidate_id: str,
    work_root: Path,
) -> str:
    """Recompute the trajectory from the stored visual analysis. This does not write."""
    root = work_root.resolve()
    plan, document, blocker = _load(database, source_asset_id, candidate_id, root)
    if blocker:
        raise MediaError(blocker)
    if plan is None or plan.reframing_strategy == "contain":
        return "PASS reframing applied=contain blocker=none"
    if document is None or document.trajectory is None:
        raise MediaError("visual_analysis_missing")
    rebuilt = _recompute(database, source_asset_id, candidate_id, root, plan)
    if rebuilt.trajectory_sha256 != document.trajectory_sha256:
        raise MediaError("visual_analysis_stale")
    if rebuilt.trajectory is None or rebuilt.trajectory.digest() != document.trajectory.digest():
        raise MediaError("visual_analysis_stale")
    return f"PASS reframing applied=face_follow trajectory={document.trajectory_sha256}"


def _load(
    database: Database,
    source_asset_id: str,
    candidate_id: str,
    root: Path,
) -> tuple[AdvancedHeroPlanDocument | None, ReframePlanDocument | None, str]:
    inputs = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=default_profile().fingerprint(),
        create_workspace=False,
    )
    workspace = inputs.pair.workspace
    _reject_visual(inputs.pair.visual_path, root)
    plan_path = workspace.advanced_plan_file(candidate_id)
    if plan_path.is_symlink():
        return None, None, "unsafe_path"
    if not plan_path.is_file():
        return None, None, "visual_analysis_missing"
    try:
        plan = AdvancedHeroPlanDocument.model_validate_json(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise MediaError("advanced plan could not be read") from exc
    if plan.reframing_strategy != "face_follow":
        return plan, None, ""
    side = workspace.reframe_plan_file(candidate_id)
    if side.is_symlink():
        return plan, None, "unsafe_path"
    if not side.is_file():
        return plan, None, "visual_analysis_missing"
    try:
        assert_unlinked(side, root)
        document = ReframePlanDocument.model_validate_json(side.read_text(encoding="utf-8"))
    except ReframeError as exc:
        return plan, None, exc.code
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise MediaError("reframe plan could not be read") from exc
    if document.visual_analysis_sha256 != inputs.pair.visual_sha256:
        return plan, document, "visual_analysis_stale"
    if document.source_sha256 != inputs.pair.manifest.content_sha256:
        return plan, document, "visual_analysis_stale"
    return plan, document, ""


def _recompute(
    database: Database,
    source_asset_id: str,
    candidate_id: str,
    root: Path,
    plan: AdvancedHeroPlanDocument,
) -> ReframePlanDocument:
    hero = load_current_hero(database, source_asset_id, root)
    inputs = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=default_profile().fingerprint(),
        create_workspace=False,
    )
    draft = next((item for item in hero.document.drafts if item.candidate_id == candidate_id), None)
    if draft is None:
        raise MediaError("visual_analysis_missing")
    alignment_path = hero.manifest_path.parent / "candidates" / candidate_id / "alignment.json"
    if alignment_path.is_symlink() or not alignment_path.is_file():
        raise MediaError("visual_analysis_missing")
    from clipforge.schemas.hero import ForcedAlignmentDocument

    try:
        alignment = ForcedAlignmentDocument.model_validate_json(alignment_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise MediaError("visual_analysis_missing") from exc
    job_id = inputs.pair.visual.provenance.job_id or ""
    succeeded = False
    if job_id:
        try:
            with database.connect() as connection:
                succeeded = get_job(connection, job_id).status.value == "succeeded"
        except StorageError:
            succeeded = False
    duration = plan.windows[-1].output_end_us if plan.windows else 1
    try:
        return build_face_follow(
            samples=list(inputs.pair.visual.face_detection_samples),
            source_width=inputs.pair.visual.proxy_width,
            source_height=inputs.pair.visual.proxy_height,
            duration_us=duration,
            source_sha256=inputs.pair.manifest.content_sha256,
            analysis_source_sha256=inputs.pair.visual.source_sha256,
            analysis_present=bool(inputs.pair.visual.face_detection_samples),
            producer_succeeded=succeeded,
            visual_analysis_id=inputs.pair.visual.analysis_id,
            visual_analysis_sha256=inputs.pair.visual_sha256,
            producer_job_id=job_id,
            words=list(alignment.words),
            plan_id=plan.plan_id,
            source_asset_id=plan.source_asset_id,
            created_by="clipforge",
            tool_version="verify",
        )
    except ReframeError as exc:
        raise MediaError(exc.code) from exc


def _reject_visual(path: Path, root: Path) -> None:
    try:
        assert_unlinked(path, root)
    except ReframeError as exc:
        raise MediaError(exc.code) from exc
    if not path.is_file():
        raise MediaError("visual_analysis_missing")
