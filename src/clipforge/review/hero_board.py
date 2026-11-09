"""Read-only Hero review board. Decisions are stored by the review service."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.constants import KIND_HERO
from clipforge.hero.show import CurrentHero, load_current_hero
from clipforge.media.workspace import SourceWorkspace
from clipforge.review.service import (
    HERO_STALE_MESSAGE,
    DecisionContext,
    effective_review,
    require_current_preview,
)
from clipforge.schemas.editorial import CandidateClip
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument, HeroDraftOutput, HeroPlanDocument
from clipforge.storage import Database, find_artifact, list_reviews

_CATEGORIES = (
    ("MP4 hash or size", "corrupt_mp4"),
    ("MP4 is missing", "missing_mp4"),
    ("MP4 failed inspection", "ffprobe"),
    ("render input", "render_input"),
    ("alignment hash", "alignment_binding"),
    ("alignment names", "alignment_binding"),
    ("alignment is not bound", "alignment_binding"),
    ("alignment could not", "alignment_binding"),
    ("alignment does not match", "alignment_binding"),
    ("alignment TimeMap", "alignment_binding"),
    ("alignment is not forced", "alignment_binding"),
    ("plan hash", "plan_binding"),
    ("plan is not bound", "plan_binding"),
    ("plan could not", "plan_binding"),
    ("plan is not a Hero", "plan_binding"),
    ("symlink", "symlink"),
    ("outside the work root", "path_confinement"),
    ("sidecar does not match", "hero_set_binding"),
    ("manifest bytes", "manifest_hash"),
    ("manifest size", "manifest_hash"),
    ("not bound to this job", "artifact_binding"),
    ("succeeded producer", "artifact_binding"),
    ("artifact input digest", "artifact_binding"),
    ("artifact provenance", "artifact_binding"),
    ("not manifest.json", "missing_manifest"),
    ("sidecar is missing", "missing_manifest"),
    ("artifact kind", "artifact_kind"),
    ("could not be read", "corrupt_manifest"),
    ("rough preview", "preview"),
    ("not reviewable", "preview"),
    ("names another", "artifact_binding"),
    ("does not match the current evidence", "candidate_set_binding"),
)


def integrity_category(detail: str) -> str:
    """Name the first integrity failure in a Hero review error."""
    for needle, category in _CATEGORIES:
        if needle in detail:
            return category
    return "integrity"


def integrity_error(detail: str) -> MediaError:
    category = integrity_category(detail)
    return MediaError(f"Hero review integrity failed [{category}]: {detail}")


def hero_review_board(database: Database, source_asset_id: str, work_root: Path) -> dict[str, object]:
    """Return the current Hero review board, or an empty board when no draft exists."""
    root = work_root.resolve()
    try:
        preview = require_current_preview(database, source_asset_id, root)
    except MediaError as exc:
        raise integrity_error(str(exc)) from exc
    workspace = SourceWorkspace(root, preview.inputs_project_id, source_asset_id)
    sidecar = workspace.hero_sidecar()
    with database.connect() as connection:
        row = find_artifact(connection, preview.inputs_project_id, source_asset_id, KIND_HERO)
    sidecar_file = sidecar.is_file() and not sidecar.is_symlink()
    if row is None and not sidecar.exists():
        return _empty(preview.inputs_project_id, source_asset_id)
    if sidecar.is_symlink():
        raise integrity_error("hero sidecar is a symlink")
    if row is None:
        raise integrity_error("hero artifact kind is not hero_draft_set_json")
    if not sidecar_file:
        raise integrity_error("hero sidecar is missing")
    try:
        current = load_current_hero(database, source_asset_id, root)
    except MediaError as exc:
        text = str(exc)
        if text.startswith("no current hero draft"):
            raise integrity_error(f"hero artifact kind is not {KIND_HERO}: {text}") from exc
        raise integrity_error(text) from exc
    with database.connect() as connection:
        reviews = list_reviews(connection, current.project_id)
    return _ready(current, reviews)


def hero_review_card(
    database: Database,
    source_asset_id: str,
    hero_id: str,
    work_root: Path,
) -> dict[str, object]:
    """Return one draft. ``hero_id`` is the candidate id in the current manifest."""
    board = hero_review_board(database, source_asset_id, work_root)
    drafts = board["drafts"]
    if not isinstance(drafts, list):
        raise MediaError("hero review drafts were not a list")
    for draft in drafts:
        if isinstance(draft, dict) and draft.get("candidate_id") == hero_id:
            return draft
    raise MediaError(f"unknown candidate {hero_id}")


def decision_context_for(board: dict[str, object], candidate_id: str) -> DecisionContext:
    """Build the write context the page must repeat."""
    draft = hero_draft(board, candidate_id)
    return DecisionContext(
        source_asset_id=_text(board, "source_asset_id"),
        project_id=_text(board, "project_id"),
        artifact_id=_text(board, "artifact_id"),
        preview_set_id=_text(board, "hero_set_id"),
        manifest_sha256=_text(board, "manifest_sha256"),
        candidate_id=candidate_id,
        subject_kind="hero",
        hero_set_id=_text(board, "hero_set_id"),
        source_sha256=_text(board, "source_sha256"),
        alignment_id=_text(draft, "alignment_id"),
        alignment_sha256=_text(draft, "alignment_sha256"),
        plan_id=_text(draft, "plan_id"),
        plan_sha256=_text(draft, "plan_sha256"),
    )


def hero_draft(board: dict[str, object], candidate_id: str) -> dict[str, object]:
    drafts = board.get("drafts")
    if isinstance(drafts, list):
        for draft in drafts:
            if isinstance(draft, dict) and draft.get("candidate_id") == candidate_id:
                return draft
    raise MediaError(f"unknown candidate {candidate_id}")


def require_current_binding(current: CurrentHero, context: DecisionContext) -> None:
    """Reject a write whose copied identities are not the current Hero draft."""
    if context.subject_kind != "hero":
        raise MediaError("a hero review requires subject_kind hero")
    same_project = context.project_id == current.project_id
    same_source = context.source_asset_id == current.source_asset_id
    same_set = context.hero_set_id == current.document.hero_set_id
    same_preview = context.preview_set_id == current.document.hero_set_id
    same_artifact = context.artifact_id == current.artifact_id
    same_manifest = context.manifest_sha256 == current.manifest_sha256
    same_source_sha = context.source_sha256 == current.document.source_sha256
    fresh = same_project and same_source and same_set and same_preview and same_artifact
    if not (fresh and same_manifest and same_source_sha):
        raise MediaError(HERO_STALE_MESSAGE)
    draft = next((item for item in current.document.drafts if item.candidate_id == context.candidate_id), None)
    if draft is None:
        raise MediaError(f"unknown candidate {context.candidate_id}")
    facts = _stored_facts(current, draft)
    same_alignment = context.alignment_id == facts[0] and context.alignment_sha256 == draft.alignment_sha256
    same_plan = context.plan_id == facts[1] and context.plan_sha256 == draft.edit_plan_sha256
    if not same_alignment or not same_plan:
        raise MediaError(HERO_STALE_MESSAGE)


def format_hero_review_list(board: dict[str, object]) -> str:
    if board.get("status") == "empty":
        return "No current Hero drafts are stored for this source."
    lines = [
        f"hero_set_id: {board.get('hero_set_id')}",
        f"artifact_id: {board.get('artifact_id')}",
        f"manifest_sha256: {board.get('manifest_sha256')}",
        f"source_sha256: {board.get('source_sha256')}",
        "rank\tcandidate_id\tdecision\treviewer\tcreated_at",
    ]
    history_lines = ["history:"]
    drafts = board.get("drafts")
    if not isinstance(drafts, list):
        return "\n".join(lines)
    for draft in drafts:
        if not isinstance(draft, dict):
            continue
        current_decision = draft.get("current_decision")
        if isinstance(current_decision, dict):
            lines.append(
                f"{draft.get('rank')}\t{draft.get('candidate_id')}\t{current_decision.get('decision')}\t"
                f"{current_decision.get('reviewer_id')}\t{current_decision.get('created_at')}"
            )
        else:
            lines.append(f"{draft.get('rank')}\t{draft.get('candidate_id')}\tnone\t\t")
        history = draft.get("history")
        if isinstance(history, list):
            for item in history:
                if not isinstance(item, dict):
                    continue
                scope = "current" if item.get("current_artifact") is True else "older_artifact"
                history_lines.append(
                    f"{draft.get('candidate_id')}\t{item.get('decision')}\t{item.get('reviewer_id')}\t"
                    f"{item.get('created_at')}\t{scope}"
                )
    return "\n".join(lines + history_lines)


def format_hero_review_show(board: dict[str, object], candidate_id: str) -> str:
    draft = hero_draft(board, candidate_id)
    lines = [
        "stage: hero",
        f"source_asset_id: {draft.get('source_asset_id')}",
        f"project_id: {draft.get('project_id')}",
        f"candidate_id: {draft.get('candidate_id')}",
        f"rank: {draft.get('rank')}",
        f"hero_set_id: {draft.get('hero_set_id')}",
        f"artifact_id: {draft.get('artifact_id')}",
        f"manifest_sha256: {draft.get('manifest_sha256')}",
        f"candidate_set_id: {draft.get('candidate_set_artifact_id')}",
        f"candidate_set_sha256: {draft.get('candidate_set_sha256')}",
        f"source_sha256: {draft.get('source_sha256')}",
        f"profile_id: {draft.get('profile_id')}",
        f"profile_fingerprint: {draft.get('profile_fingerprint')}",
        f"plan_id: {draft.get('plan_id')}",
        f"plan_sha256: {draft.get('plan_sha256')}",
        f"alignment_id: {draft.get('alignment_id')}",
        f"alignment_sha256: {draft.get('alignment_sha256')}",
        f"whisperx_version: {_shown(draft.get('whisperx_version'))}",
        f"alignment_model: {_shown(draft.get('alignment_model'))}",
        f"alignment_checkpoint_sha256: {_shown(draft.get('alignment_checkpoint_sha256'))}",
        f"alignment_language: {_shown(draft.get('alignment_language'))}",
        f"timing_quality: {_shown(draft.get('timing_quality'))}",
        f"source_range_us: {draft.get('source_start_us')}-{draft.get('source_end_us')}",
        f"output_duration_us: {draft.get('output_duration_us')}",
        f"dimensions: {draft.get('width')}x{draft.get('height')}",
        f"fps: {draft.get('fps_numerator')}/{draft.get('fps_denominator')}",
        f"video_codec: {_shown(draft.get('video_codec'))}",
        f"pixel_format: {_shown(draft.get('pixel_format'))}",
        f"audio_codec: {_shown(draft.get('audio_codec'))}",
        f"audio_sample_rate: {_shown(draft.get('audio_sample_rate'))}",
        f"motion_library_version: {_shown(draft.get('motion_library_version'))}",
        f"word_count: {draft.get('word_count')}",
    ]
    settings = draft.get("motion_settings")
    if isinstance(settings, list) and settings:
        for item in settings:
            if isinstance(item, dict):
                lines.append(
                    "motion: "
                    f"{item.get('purpose')} {item.get('component_id')} "
                    f"{item.get('output_start_us')}-{item.get('output_end_us')}"
                )
    else:
        lines.append("motion_settings: unavailable")
    words = draft.get("words")
    if isinstance(words, list):
        for word in words:
            if not isinstance(word, dict):
                continue
            lines.append(
                "word: "
                f"{word.get('text')}\t{word.get('source_start_us')}\t{word.get('source_end_us')}\t"
                f"{word.get('output_start_us')}\t{word.get('output_end_us')}\t"
                f"{word.get('output_start_frame')}\t{word.get('output_end_frame_exclusive')}"
            )
    decision = draft.get("current_decision")
    if isinstance(decision, dict):
        lines.append(f"current_decision: {decision.get('decision')} {decision.get('review_id')}")
    else:
        lines.append("current_decision: none")
    return "\n".join(lines)


def _empty(project_id: str, source_asset_id: str) -> dict[str, object]:
    return {
        "status": "empty",
        "stage": "hero",
        "source_asset_id": source_asset_id,
        "project_id": project_id,
        "hero_set_id": None,
        "artifact_id": None,
        "manifest_sha256": None,
        "source_sha256": None,
        "integrity": "PASS",
        "draft_count": 0,
        "drafts": [],
        "detail": "No current Hero drafts are stored for this source.",
    }


def _ready(current: CurrentHero, reviews: list[ReviewDecision]) -> dict[str, object]:
    drafts = [_draft_card(current, item, reviews) for item in current.document.drafts]
    document = current.document
    return {
        "status": "ready",
        "stage": "hero",
        "source_asset_id": current.source_asset_id,
        "project_id": current.project_id,
        "hero_set_id": document.hero_set_id,
        "artifact_id": current.artifact_id,
        "manifest_sha256": current.manifest_sha256,
        "candidate_set_artifact_id": document.candidate_set_artifact_id,
        "candidate_set_sha256": document.candidate_set_sha256,
        "source_sha256": document.source_sha256,
        "profile_id": document.profile.profile_id,
        "profile_fingerprint": document.profile_fingerprint,
        "whisperx_version": document.whisperx_version,
        "alignment_model": document.alignment_model,
        "alignment_checkpoint_sha256": None,
        "alignment_language": None,
        "motion_library_version": document.motion_library_version,
        "integrity": "PASS",
        "draft_count": len(drafts),
        "drafts": drafts,
    }


def _draft_card(
    current: CurrentHero,
    draft: HeroDraftOutput,
    reviews: list[ReviewDecision],
) -> dict[str, object]:
    alignment, plan = _load_pair(current, draft)
    candidate = _candidate(current, draft.candidate_id)
    if len(candidate.time_map.segments) != 1:
        raise integrity_error(f"{draft.candidate_id} alignment TimeMap has more than one segment")
    segment = candidate.time_map.segments[0]
    history = [
        _history_item(review, current.artifact_id)
        for review in sorted(reviews, key=lambda item: (item.created_at, item.review_id))
        if review.subject_kind == "hero" and review.candidate_id == draft.candidate_id
    ]
    effective = effective_review(reviews, current.artifact_id, draft.candidate_id, subject_kind="hero")
    approval = next((item for item in reviews if item.review_id == draft.review_id), None)
    document = current.document
    words = [_word(word) for word in alignment.words]
    return {
        "rank": draft.rank,
        "candidate_id": draft.candidate_id,
        "source_asset_id": current.source_asset_id,
        "project_id": current.project_id,
        "hero_set_id": document.hero_set_id,
        "artifact_id": current.artifact_id,
        "manifest_sha256": current.manifest_sha256,
        "candidate_set_artifact_id": document.candidate_set_artifact_id,
        "candidate_set_sha256": document.candidate_set_sha256,
        "source_sha256": document.source_sha256,
        "profile_id": document.profile.profile_id,
        "profile_fingerprint": document.profile_fingerprint,
        "plan_id": plan.plan_id,
        "plan_sha256": draft.edit_plan_sha256,
        "alignment_id": alignment.alignment_id,
        "alignment_sha256": draft.alignment_sha256,
        "whisperx_version": document.whisperx_version,
        "alignment_model": document.alignment_model,
        "alignment_checkpoint_sha256": None,
        "alignment_language": None,
        "timing_quality": "forced",
        "alignment_quality": "forced",
        "source_start_us": segment.source_start_us,
        "source_end_us": segment.source_end_us,
        "output_duration_us": draft.output_duration_us,
        "duration_us": draft.output_duration_us,
        "duration_error_us": draft.duration_error_us,
        "width": draft.width,
        "height": draft.height,
        "fps_numerator": draft.output_fps_numerator,
        "fps_denominator": draft.output_fps_denominator,
        "video_codec": draft.detected_video_codec,
        "pixel_format": draft.detected_pixel_format,
        "audio_codec": draft.detected_audio_codec,
        "audio_sample_rate": None,
        "motion_library_version": document.motion_library_version,
        "motion_settings": _motion(plan),
        "word_count": len(words),
        "words": words,
        "caption_count": draft.caption_count,
        "preview_url": f"/media/hero/{draft.candidate_id}",
        "approval_review_id": draft.review_id,
        "approval_decision": None if approval is None else approval.decision,
        "approval_reviewer_id": None if approval is None else approval.reviewer_id,
        "approval_reviewer_role": None if approval is None else approval.reviewer_role,
        "current_decision": None if effective is None else _decision(effective),
        "history": history,
    }


def _stored_facts(current: CurrentHero, draft: HeroDraftOutput) -> tuple[str, str]:
    alignment, plan = _load_pair(current, draft)
    return alignment.alignment_id, plan.plan_id


def _load_pair(
    current: CurrentHero,
    draft: HeroDraftOutput,
) -> tuple[ForcedAlignmentDocument, HeroPlanDocument]:
    directory = current.manifest_path.parent / "candidates" / draft.candidate_id
    alignment_path = directory / "alignment.json"
    plan_path = directory / "plan.json"
    try:
        alignment = ForcedAlignmentDocument.model_validate_json(alignment_path.read_text(encoding="utf-8"))
        plan = HeroPlanDocument.model_validate_json(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise integrity_error(f"{draft.candidate_id} alignment could not be read: {exc}") from exc
    if alignment.candidate_id != draft.candidate_id or plan.edit_plan.candidate_id != draft.candidate_id:
        raise integrity_error(f"{draft.candidate_id} alignment names another candidate")
    return alignment, plan


def _candidate(current: CurrentHero, candidate_id: str) -> CandidateClip:
    for candidate in current.inputs.candidate_document.candidates:
        if candidate.candidate_id == candidate_id:
            return candidate
    raise integrity_error(f"{candidate_id} alignment names another candidate")


def _word(word: AlignedWord) -> dict[str, object]:
    return {
        "text": word.text,
        "source_start_us": word.source_start_us,
        "source_end_us": word.source_end_us,
        "output_start_us": word.output_start_us,
        "output_end_us": word.output_end_us,
        "output_start_frame": word.output_start_frame,
        "output_end_frame_exclusive": word.output_end_frame_exclusive,
    }


def _motion(plan: HeroPlanDocument) -> list[dict[str, object]]:
    settings: list[dict[str, object]] = []
    for event in plan.edit_plan.motion_events:
        settings.append(
            {
                "purpose": event.purpose.value,
                "component_id": event.component_id,
                "output_start_us": event.interval.output_start_us,
                "output_end_us": event.interval.output_end_us,
            }
        )
    return settings


def _history_item(review: ReviewDecision, artifact_id: str) -> dict[str, object]:
    payload = _decision(review)
    payload["current_artifact"] = review.artifact_id == artifact_id
    return payload


def _decision(review: ReviewDecision) -> dict[str, object]:
    return {
        "review_id": review.review_id,
        "candidate_id": review.candidate_id,
        "artifact_id": review.artifact_id,
        "decision": review.decision,
        "reviewer_id": review.reviewer_id,
        "reviewer_role": review.reviewer_role,
        "created_at": review.created_at.isoformat(),
        "notes": review.notes,
        "automated": False,
        "subject_kind": review.subject_kind,
    }


def _text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise MediaError(HERO_STALE_MESSAGE)
    return value


def _shown(value: object) -> str:
    if value is None or value == "":
        return "unavailable"
    return str(value)
