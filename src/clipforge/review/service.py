"""Human review decisions bound to the current rough-preview artifact.

Decisions are append-only. They do not change the candidate set, the preview
files, or any score. A decision for an older preview artifact is history only.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import ClipforgeError, MediaError, StorageError
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.mutation import inspect_mutation
from clipforge.media.workspace import SourceWorkspace, ensure_within
from clipforge.preview.constants import KIND_PREVIEW
from clipforge.preview.inputs import load_preview_inputs
from clipforge.preview.integrity import preview_problems
from clipforge.preview.service import default_profile
from clipforge.schemas.governance import ReviewDecision, require_rights_cleared
from clipforge.schemas.preview import RoughPreviewCacheRecord, RoughPreviewSetDocument
from clipforge.storage import (
    Database,
    find_artifact,
    get_asset_license_record,
    get_job,
    get_source_asset,
    get_source_manifest,
    insert_review,
    list_reviews,
)

STALE_MESSAGE = "the preview set changed while this review page was open; reload before saving"
HERO_STALE_MESSAGE = "The Hero set changed while this review page was open; reload before saving."
NOTES_MAX = 4000
DECISIONS = frozenset({"approved", "rejected", "changes_requested"})
LOOPBACK_HOST = "127.0.0.1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_REQUEST_KEYS = frozenset(
    {
        "source_asset_id",
        "project_id",
        "artifact_id",
        "preview_set_id",
        "manifest_sha256",
        "candidate_id",
        "decision",
        "reviewer_id",
        "notes",
        "automated",
        "subject_kind",
        "hero_set_id",
        "source_sha256",
        "alignment_id",
        "alignment_sha256",
        "plan_id",
        "plan_sha256",
        "advanced_set_id",
    }
)


@dataclass(frozen=True, slots=True)
class CurrentPreview:
    inputs_project_id: str
    source_asset_id: str
    artifact_id: str
    document: RoughPreviewSetDocument
    manifest_path: Path
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class DecisionContext:
    source_asset_id: str
    project_id: str
    artifact_id: str
    preview_set_id: str
    manifest_sha256: str
    candidate_id: str
    subject_kind: str = "candidate"
    hero_set_id: str = ""
    source_sha256: str = ""
    alignment_id: str = ""
    alignment_sha256: str = ""
    plan_id: str = ""
    plan_sha256: str = ""
    advanced_set_id: str = ""


@dataclass(frozen=True, slots=True)
class ReviewVerifyLine:
    status: str
    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class ReviewVerifyReport:
    source_asset_id: str
    lines: tuple[ReviewVerifyLine, ...]

    @property
    def status(self) -> str:
        if any(line.status == "FAIL" for line in self.lines):
            return "FAIL"
        return "PASS"


def require_current_preview(database: Database, source_asset_id: str, work_root: Path) -> CurrentPreview:
    """Load one verified preview set. A stale or broken set is not reviewable."""
    root = work_root.resolve()
    try:
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
            manifest = get_source_manifest(connection, source_asset_id)
            license_record = get_asset_license_record(connection, source.license_record_id)
    except StorageError as exc:
        raise MediaError(str(exc)) from exc
    try:
        require_rights_cleared(license_record)
    except ClipforgeError as exc:
        raise MediaError(str(exc)) from exc
    try:
        inspect_mutation(path_from_file_uri(source.uri), manifest)
    except MediaError as exc:
        raise MediaError(str(exc)) from exc
    sidecar = SourceWorkspace(root, source.project_id, source_asset_id).preview_sidecar()
    record = _read_record(sidecar)
    fingerprint = record.profile_fingerprint if record is not None else default_profile().fingerprint()
    inputs = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=fingerprint,
        create_workspace=False,
    )
    if record is None:
        raise MediaError(
            f"no current rough preview set for source {source_asset_id}. "
            f"Run `clipforge preview render {source_asset_id}`."
        )
    with database.connect() as connection:
        row = find_artifact(connection, source.project_id, source_asset_id, KIND_PREVIEW)
        job = None
        if row is not None and row.job_id is not None:
            try:
                job = get_job(connection, row.job_id)
            except StorageError as exc:
                raise MediaError(str(exc)) from exc
    if row is None or row.job_id is None or job is None:
        raise MediaError(
            f"no current rough preview set for source {source_asset_id}. "
            f"Run `clipforge preview render {source_asset_id}`."
        )
    path = path_from_file_uri(row.uri)
    expected = inputs.pair.workspace.preview_run_dir(record.preview_set_id) / "manifest.json"
    ensure_within(root, path)
    if path != expected or path.is_symlink() or not path.is_file():
        raise MediaError("preview artifact is not manifest.json inside this source's preview run")
    try:
        document = RoughPreviewSetDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise MediaError(f"current rough preview set could not be read: {exc}") from exc
    problems = preview_problems(
        document,
        record,
        manifest_path=path,
        work_root=root,
        workspace=inputs.pair.workspace,
        inputs=inputs,
        artifact_job_id=row.job_id,
        artifact_uri=row.uri,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
    )
    if problems:
        raise MediaError("rough preview set is not reviewable: " + "; ".join(problems))
    return CurrentPreview(
        inputs_project_id=source.project_id,
        source_asset_id=source_asset_id,
        artifact_id=row.artifact_id,
        document=document,
        manifest_path=path,
        manifest_sha256=sha256_file(path),
    )


def review_board(database: Database, source_asset_id: str, work_root: Path) -> dict[str, object]:
    """Sanitized review JSON. This does not include filesystem paths."""
    current = require_current_preview(database, source_asset_id, work_root)
    reviews = _reviews(database, current.inputs_project_id)
    cards = [_card(current, item.candidate_id, reviews) for item in current.document.previews]
    return {
        "source_asset_id": current.source_asset_id,
        "project_id": current.inputs_project_id,
        "preview_set_id": current.document.preview_set_id,
        "manifest_sha256": current.manifest_sha256,
        "mining_id": current.document.mining_id,
        "artifact_id": current.artifact_id,
        "integrity": "PASS",
        "candidate_count": len(cards),
        "candidates": cards,
        "stage": "rough",
        "hero": _hero_section(database, source_asset_id, work_root, reviews),
    }


def candidate_card(
    database: Database,
    source_asset_id: str,
    candidate_id: str,
    work_root: Path,
) -> dict[str, object]:
    board = review_board(database, source_asset_id, work_root)
    cards = board["candidates"]
    if not isinstance(cards, list):
        raise MediaError("review board candidates were not a list")
    for card in cards:
        if isinstance(card, dict) and card.get("candidate_id") == candidate_id:
            return card
    raise MediaError(f"unknown candidate {candidate_id}")


def preview_media_path(database: Database, source_asset_id: str, candidate_id: str, work_root: Path) -> Path:
    """Resolve one current preview MP4. The caller must already have rejected traversal."""
    current = require_current_preview(database, source_asset_id, work_root)
    preview = next((item for item in current.document.previews if item.candidate_id == candidate_id), None)
    if preview is None:
        raise MediaError(f"unknown candidate {candidate_id}")
    relative = f"candidates/{candidate_id}/preview.mp4"
    if preview.preview_relative_path != relative:
        raise MediaError("refusing to serve a preview path that is not preview.mp4")
    path = current.manifest_path.parent / relative
    if path.is_symlink():
        raise MediaError("refusing to serve a symlinked preview")
    ensure_within(work_root.resolve(), path)
    if not path.is_file():
        raise MediaError(f"preview file for {candidate_id} is missing")
    return path


def record_decision(
    *,
    database: Database,
    work_root: Path,
    context: DecisionContext,
    decision: str,
    reviewer_id: str,
    notes: str,
) -> ReviewDecision:
    """Insert one review row. Previous rows are left untouched."""
    if decision not in DECISIONS:
        raise MediaError(f"decision must be approved, rejected, or changes_requested, got {decision!r}")
    reviewer = reviewer_id.strip()
    if not reviewer:
        raise MediaError("reviewer_id must not be blank")
    if len(reviewer) > 200:
        raise MediaError("reviewer_id is longer than 200 characters")
    if len(notes) > NOTES_MAX:
        raise MediaError(f"notes are longer than {NOTES_MAX} characters")
    current = require_current_preview(database, context.source_asset_id, work_root)
    _require_fresh(current, context)
    review = ReviewDecision.model_validate(
        {
            "review_id": str(uuid.uuid4()),
            "project_id": current.inputs_project_id,
            "artifact_id": current.artifact_id,
            "candidate_id": context.candidate_id,
            "subject_kind": "candidate",
            "decision": decision,
            "reviewer_id": reviewer,
            "created_at": datetime.now(UTC),
            "notes": notes,
            "automated": False,
        }
    )
    with database.transaction() as connection:
        row = find_artifact(connection, current.inputs_project_id, current.source_asset_id, KIND_PREVIEW)
        if row is None or row.artifact_id != current.artifact_id:
            raise MediaError(STALE_MESSAGE)
        if sha256_file(current.manifest_path) != current.manifest_sha256:
            raise MediaError(STALE_MESSAGE)
        insert_review(connection, review)
    return review


def parse_decision_body(payload: object) -> tuple[DecisionContext, str, str, str]:
    """Reject unknown keys, automated approval, and malformed review bodies."""
    if not isinstance(payload, dict):
        raise MediaError("review body must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_KEYS)
    if unknown:
        raise MediaError("unknown review fields: " + ", ".join(unknown))
    if "automated" in payload and payload["automated"] is not False:
        raise MediaError("automated review decisions are rejected")
    decision = payload.get("decision")
    if not isinstance(decision, str) or decision not in DECISIONS:
        raise MediaError("decision must be approved, rejected, or changes_requested")
    reviewer = payload.get("reviewer_id")
    if not isinstance(reviewer, str):
        raise MediaError("reviewer_id must not be blank")
    notes = payload.get("notes", "")
    if notes is None:
        notes = ""
    if not isinstance(notes, str):
        raise MediaError("notes must be text")
    subject = payload.get("subject_kind", "candidate")
    if subject is None:
        subject = "candidate"
    if not isinstance(subject, str) or subject not in {"candidate", "hero"}:
        raise MediaError("subject_kind must be candidate or hero")
    hero_set_id = payload.get("hero_set_id", "")
    if hero_set_id is None:
        hero_set_id = ""
    if not isinstance(hero_set_id, str):
        raise MediaError("hero_set_id must be text")
    if subject == "hero" and not hero_set_id.strip():
        raise MediaError("hero_set_id must not be blank")
    context = DecisionContext(
        source_asset_id=_required_text(payload, "source_asset_id"),
        project_id=_required_text(payload, "project_id"),
        artifact_id=_required_text(payload, "artifact_id"),
        preview_set_id=_required_text(payload, "preview_set_id"),
        manifest_sha256=_required_text(payload, "manifest_sha256"),
        candidate_id=_required_text(payload, "candidate_id"),
        subject_kind=subject,
        hero_set_id=hero_set_id,
        source_sha256=_optional_text(payload, "source_sha256"),
        alignment_id=_optional_text(payload, "alignment_id"),
        alignment_sha256=_optional_text(payload, "alignment_sha256"),
        plan_id=_optional_text(payload, "plan_id"),
        plan_sha256=_optional_text(payload, "plan_sha256"),
        advanced_set_id=_optional_text(payload, "advanced_set_id"),
    )
    if subject == "hero":
        for key in ("source_sha256", "alignment_id", "alignment_sha256", "plan_id", "plan_sha256"):
            if not str(getattr(context, key)).strip():
                raise MediaError(f"{key} is required")
        _require_hero_identifiers(context)
    return context, decision, reviewer, notes


def record_hero_decision(
    *,
    database: Database,
    work_root: Path,
    context: DecisionContext,
    decision: str,
    reviewer_id: str,
    notes: str,
) -> ReviewDecision:
    """Append one Hero-draft review. It does not publish and it does not replace the rough decision."""
    from clipforge.hero.constants import KIND_HERO
    from clipforge.hero.show import load_current_hero
    from clipforge.review.hero_board import require_current_binding

    if context.subject_kind != "hero":
        raise MediaError("a hero review requires subject_kind hero")
    if decision not in DECISIONS:
        raise MediaError(f"decision must be approved, rejected, or changes_requested, got {decision!r}")
    reviewer = reviewer_id.strip()
    if not reviewer:
        raise MediaError("reviewer_id must not be blank")
    if len(reviewer) > 200:
        raise MediaError("reviewer_id is longer than 200 characters")
    if len(notes) > NOTES_MAX:
        raise MediaError(f"notes are longer than {NOTES_MAX} characters")
    current = load_current_hero(database, context.source_asset_id, work_root)
    require_current_binding(current, context)
    try:
        review = ReviewDecision.model_validate(
            {
                "review_id": str(uuid.uuid4()),
                "project_id": current.project_id,
                "artifact_id": current.artifact_id,
                "candidate_id": context.candidate_id,
                "subject_kind": "hero",
                "decision": decision,
                "reviewer_id": reviewer,
                "created_at": datetime.now(UTC),
                "notes": notes,
                "automated": False,
            }
        )
    except ValidationError as exc:
        raise MediaError(f"review decision is not valid: {exc}") from exc
    with database.transaction() as connection:
        row = find_artifact(connection, current.project_id, current.source_asset_id, KIND_HERO)
        if row is None or row.artifact_id != current.artifact_id:
            raise MediaError(HERO_STALE_MESSAGE)
        if sha256_file(current.manifest_path) != current.manifest_sha256:
            raise MediaError(HERO_STALE_MESSAGE)
        insert_review(connection, review)
    return review


def verify_review(*, database: Database, source_asset_id: str, work_root: Path) -> ReviewVerifyReport:
    """Read the current preview set and stored reviews. This does not write."""
    try:
        current = require_current_preview(database, source_asset_id, work_root)
    except (MediaError, StorageError, ValidationError) as exc:
        return ReviewVerifyReport(source_asset_id, (ReviewVerifyLine("FAIL", "preview", str(exc)),))
    reviews = _reviews(database, current.inputs_project_id)
    lines = [
        ReviewVerifyLine(
            "PASS",
            "preview",
            f"preview set {current.document.preview_set_id} candidates {len(current.document.previews)}",
        ),
        ReviewVerifyLine("PASS", "reviews", f"{len(reviews)} stored review rows"),
    ]
    return ReviewVerifyReport(source_asset_id, tuple(lines))


def format_review_list(database: Database, source_asset_id: str, work_root: Path) -> str:
    board = review_board(database, source_asset_id, work_root)
    lines = [
        f"preview_set_id: {board['preview_set_id']}",
        f"artifact_id: {board['artifact_id']}",
        f"manifest_sha256: {board['manifest_sha256']}",
        "rank\tcandidate_id\tdecision\treviewer\tcreated_at\tcurrent_artifact",
    ]
    history_lines = ["history:"]
    cards = board["candidates"]
    if not isinstance(cards, list) or not cards:
        lines.append("No candidates were selected in the current candidate set.")
        return "\n".join(lines)
    for card in cards:
        if not isinstance(card, dict):
            continue
        current_decision = card.get("current_decision")
        if isinstance(current_decision, dict):
            lines.append(
                f"{card['rank']}\t{card['candidate_id']}\t{current_decision['decision']}\t"
                f"{current_decision['reviewer_id']}\t{current_decision['created_at']}\tyes"
            )
        else:
            lines.append(f"{card['rank']}\t{card['candidate_id']}\tnone\t\t\tno")
        history = card.get("history")
        if isinstance(history, list):
            for item in history:
                if not isinstance(item, dict):
                    continue
                flag = "current" if item.get("current_artifact") is True else "older_artifact"
                history_lines.append(
                    f"{card['candidate_id']}\t{item.get('decision')}\t{item.get('reviewer_id')}\t"
                    f"{item.get('created_at')}\t{flag}"
                )
    return "\n".join(lines + history_lines)


def decision_json(review: ReviewDecision) -> dict[str, object]:
    return {
        "review_id": review.review_id,
        "candidate_id": review.candidate_id,
        "artifact_id": review.artifact_id,
        "decision": review.decision,
        "reviewer_id": review.reviewer_id,
        "created_at": review.created_at.isoformat(),
        "notes": review.notes,
        "automated": False,
    }


def _card(current: CurrentPreview, candidate_id: str, reviews: list[ReviewDecision]) -> dict[str, object]:
    preview = next(item for item in current.document.previews if item.candidate_id == candidate_id)
    history = [
        _history_item(review, current.artifact_id)
        for review in reviews
        if review.subject_kind == "candidate" and review.candidate_id == candidate_id
    ]
    effective = effective_review(reviews, current.artifact_id, candidate_id)
    return {
        "rank": preview.rank,
        "candidate_id": preview.candidate_id,
        "source_start_us": preview.source_start_us,
        "source_end_us": preview.source_end_us,
        "output_duration_us": preview.output_duration_us,
        "output_frame_count": preview.output_frame_count,
        "caption_count": preview.caption_count,
        "timing_quality": preview.timing_quality,
        "width": preview.width,
        "height": preview.height,
        "fps_numerator": preview.output_fps_numerator,
        "fps_denominator": preview.output_fps_denominator,
        "video_codec": preview.detected_video_codec,
        "audio_codec": preview.detected_audio_codec,
        "pixel_format": preview.detected_pixel_format,
        "duration_error_us": preview.duration_error_us,
        "preview_url": f"/media/candidate/{preview.candidate_id}",
        "quality_score": preview.quality_score,
        "quality_score_label": "heuristic",
        "edit_opportunity_score": preview.edit_opportunity_score,
        "edit_opportunity_score_label": "heuristic",
        "current_decision": None if effective is None else decision_json(effective),
        "history": history,
    }


def _history_item(review: ReviewDecision, artifact_id: str) -> dict[str, object]:
    payload = decision_json(review)
    payload["current_artifact"] = review.artifact_id == artifact_id
    return payload


def effective_review(
    reviews: list[ReviewDecision],
    artifact_id: str,
    candidate_id: str,
    *,
    subject_kind: str = "candidate",
) -> ReviewDecision | None:
    """Newest decision for this candidate and artifact. Older artifacts do not apply."""
    matched = [
        review
        for review in reviews
        if review.subject_kind == subject_kind
        and review.candidate_id == candidate_id
        and review.artifact_id == artifact_id
    ]
    if not matched:
        return None
    return max(matched, key=lambda review: (review.created_at, review.review_id))


def _hero_section(
    database: Database,
    source_asset_id: str,
    work_root: Path,
    reviews: list[ReviewDecision],
) -> dict[str, object] | None:
    del reviews
    from clipforge.review.hero_board import hero_review_board

    try:
        board = hero_review_board(database, source_asset_id, work_root)
    except MediaError as exc:
        if "No current Hero drafts" in str(exc):
            return None
        return {"status": "unavailable", "detail": "the current hero draft is not reviewable"}
    if board.get("status") == "empty":
        return None
    return board


def _require_fresh(current: CurrentPreview, context: DecisionContext) -> None:
    if context.project_id != current.inputs_project_id or context.source_asset_id != current.source_asset_id:
        raise MediaError(STALE_MESSAGE)
    if context.artifact_id != current.artifact_id or context.preview_set_id != current.document.preview_set_id:
        raise MediaError(STALE_MESSAGE)
    if context.manifest_sha256 != current.manifest_sha256:
        raise MediaError(STALE_MESSAGE)
    known = {item.candidate_id for item in current.document.previews}
    if context.candidate_id not in known:
        raise MediaError(f"unknown candidate {context.candidate_id}")


def _reviews(database: Database, project_id: str) -> list[ReviewDecision]:
    with database.connect() as connection:
        return list_reviews(connection, project_id)


def _read_record(path: Path) -> RoughPreviewCacheRecord | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return RoughPreviewCacheRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MediaError(f"{key} is required")
    return value


def _require_hero_identifiers(context: DecisionContext) -> None:
    identifiers = (
        context.source_asset_id,
        context.project_id,
        context.artifact_id,
        context.preview_set_id,
        context.candidate_id,
        context.hero_set_id,
        context.alignment_id,
        context.plan_id,
    )
    for value in identifiers:
        if not _IDENTIFIER.fullmatch(value):
            raise MediaError(f"malformed identifier {value!r}")
    digests = (
        context.manifest_sha256,
        context.source_sha256,
        context.alignment_sha256,
        context.plan_sha256,
    )
    for value in digests:
        if not _SHA256.fullmatch(value):
            raise MediaError("malformed sha256")


def _optional_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MediaError(f"{key} must be text")
    return value
