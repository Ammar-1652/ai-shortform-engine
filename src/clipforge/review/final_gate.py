"""Final human approval bound to the current Advanced Hero evidence.

Hero approval and a passing QA set do not authorize delivery. The decision row
stays in the existing reviews table. The evidence digest is append-only with
that row. The sidecar stores the same digest and no filesystem path.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from clipforge.errors import ClipforgeError, MediaError, StorageError
from clipforge.publish.errors import PublishError
from clipforge.publish.preflight import DeliveryFacts
from clipforge.review.service import NOTES_MAX, effective_review
from clipforge.schemas.governance import ReviewDecision
from clipforge.storage import Database, insert_review, list_reviews

FINAL_STALE = "The final review changed while this page was open; reload before saving."
_MARK = "\nfinal_evidence_sha256:"
_SHA = set("0123456789abcdef")


class FinalReviewError(ClipforgeError):
    """A final review cannot be recorded or is not effective."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def evidence_sha256(evidence: dict[str, str]) -> str:
    raw = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def evidence_for_facts(facts: DeliveryFacts) -> dict[str, str]:
    """Public evidence. Every value is an id, a hash, or a short status."""
    return {
        "advanced_artifact_id": facts.advanced_artifact_id,
        "advanced_manifest_sha256": facts.advanced_artifact_sha256,
        "advanced_plan_id": facts.advanced_plan_id,
        "advanced_plan_sha256": facts.advanced_plan_sha256,
        "alignment_id": facts.alignment_id or "",
        "alignment_sha256": facts.alignment_sha256 or "",
        "candidate_id": facts.candidate_id,
        "delivery_manifest_sha256": facts.delivery_manifest_sha256,
        "hero_plan_id": facts.hero_plan_id,
        "hero_plan_sha256": facts.hero_plan_sha256,
        "policy_fingerprint": facts.policy_fingerprint,
        "profile_fingerprint": facts.profile_fingerprint,
        "project_id": facts.project_id,
        "qa_set_id": facts.qa_set_id,
        "qa_set_sha256": facts.qa_set_sha256,
        "qa_status": "pass",
        "rights_fingerprint": facts.rights_fingerprint,
        "reframing_strategy": facts.reframing_strategy,
        "source_asset_id": facts.source_asset_id,
        "source_sha256": facts.source_sha256,
        "time_map_sha256": facts.time_map_sha256,
        "trajectory_sha256": facts.trajectory_sha256,
        **language_evidence(facts),
    }


def capture_final_decision(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    candidate_id: str,
    *,
    decision: str,
    reviewer_id: str,
    notes: str,
    include_narration: bool = False,
    narration_artifact_id: str | None = None,
) -> ReviewDecision:
    """Record a final decision from the current delivery evidence. This does not export."""
    from clipforge.publish.preflight import preflight_delivery

    facts = preflight_delivery(
        database,
        work_root,
        source_asset_id,
        candidate_id,
        include_narration=include_narration,
        narration_artifact_id=narration_artifact_id,
        probe=False,
        require_final=False,
    )
    return record_final_decision(
        database=database,
        work_root=work_root,
        facts=facts,
        evidence=evidence_for_facts(facts),
        decision=decision,
        reviewer_id=reviewer_id,
        notes=notes,
    )


def require_final_approval(
    database: Database,
    work_root: Path,
    facts: DeliveryFacts,
    reviews: list[ReviewDecision],
    evidence: dict[str, str],
) -> str:
    """Return the effective approved review id, or raise PublishError."""
    code = approval_code(work_root, facts, reviews, evidence)
    if code == "approved":
        review = _newest(reviews, facts.candidate_id, facts.advanced_artifact_id)
        if review is None:
            raise PublishError("final approval is missing", category="final_approval_required")
        return review.review_id
    raise PublishError(_message(code), category=code)


def approval_code(
    work_root: Path,
    facts: DeliveryFacts,
    reviews: list[ReviewDecision],
    evidence: dict[str, str],
) -> str:
    """Classify the newest final row for this artifact. Older rows stay history."""
    review = _newest(reviews, facts.candidate_id, facts.advanced_artifact_id)
    if review is None:
        return "final_approval_required"
    if review.decision == "rejected":
        return "final_approval_rejected"
    if review.decision == "changes_requested":
        return "final_approval_changes_requested"
    stored = _stored_evidence(work_root, review)
    if stored is None:
        return "stale_final_review"
    return _difference(stored, evidence)


def record_final_decision(
    *,
    database: Database,
    work_root: Path,
    facts: DeliveryFacts,
    evidence: dict[str, str],
    decision: str,
    reviewer_id: str,
    notes: str,
) -> ReviewDecision:
    """Append one final decision for the evidence captured by the caller."""
    if decision not in {"approved", "rejected", "changes_requested"}:
        raise FinalReviewError(
            "decision must be approved, rejected, or changes_requested",
            code="invalid_document",
        )
    reviewer = reviewer_id.strip()
    if not reviewer or len(reviewer) > 200:
        raise FinalReviewError("reviewer_id must not be blank", code="invalid_document")
    if len(notes) > NOTES_MAX:
        raise FinalReviewError(f"notes are longer than {NOTES_MAX} characters", code="invalid_document")
    digest = evidence_sha256(evidence)
    review = ReviewDecision(
        review_id=str(uuid.uuid4()),
        project_id=facts.project_id,
        artifact_id=facts.advanced_artifact_id,
        candidate_id=facts.candidate_id,
        subject_kind="final",
        decision=decision,  # type: ignore[arg-type]
        reviewer_id=reviewer,
        created_at=datetime.now(UTC),
        notes=_join_notes(notes, digest),
        automated=False,
    )
    root = work_root.resolve()
    with database.transaction() as connection:
        insert_review(connection, review)
    _write_sidecar(root, review.review_id, evidence, digest)
    return review


def write_final_review(
    connection: Any,
    work_root: Path,
    *,
    project_id: str,
    artifact_id: str,
    candidate_id: str,
    evidence: dict[str, str],
    decision: str = "approved",
    reviewer_id: str = "reviewer",
    notes: str = "final",
    review_id: str | None = None,
    created_at: datetime | None = None,
) -> ReviewDecision:
    """Insert one bound final row. Callers already hold the write transaction."""
    digest = evidence_sha256(evidence)
    review = ReviewDecision(
        review_id=review_id or str(uuid.uuid4()),
        project_id=project_id,
        artifact_id=artifact_id,
        candidate_id=candidate_id,
        subject_kind="final",
        decision=decision,  # type: ignore[arg-type]
        reviewer_id=reviewer_id,
        created_at=created_at or datetime.now(UTC),
        notes=_join_notes(notes, digest),
        automated=False,
    )
    insert_review(connection, review)
    _write_sidecar(work_root.resolve(), review.review_id, evidence, digest)
    return review


def package_blocker(
    database: Database,
    work_root: Path,
    *,
    project_id: str,
    candidate_id: str,
    advanced_artifact_id: str,
    qa_set_sha256: str,
    source_sha256: str,
    delivery_manifest_sha256: str,
) -> str | None:
    """Block one campaign source when its final approval does not match the package."""
    try:
        with database.connect() as connection:
            reviews = list_reviews(connection, project_id)
    except StorageError:
        return "stale_final_review"
    matched = [
        item
        for item in reviews
        if item.subject_kind == "final"
        and item.candidate_id == candidate_id
        and item.artifact_id == advanced_artifact_id
    ]
    if not matched:
        return "final_approval_required"
    review = max(matched, key=lambda item: (item.created_at, item.review_id))
    if review.decision == "rejected":
        return "final_approval_rejected"
    if review.decision == "changes_requested":
        return "final_approval_changes_requested"
    if _stored_evidence(work_root, review) is None:
        return "stale_final_review"
    return None


def final_board(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    candidate_id: str,
) -> dict[str, object]:
    """Read-only final review card. Paths and media bytes stay off the payload."""
    from clipforge.publish.preflight import preflight_delivery

    try:
        facts = preflight_delivery(
            database,
            work_root,
            source_asset_id,
            candidate_id,
            probe=False,
            require_final=False,
        )
    except PublishError as exc:
        return {
            "candidate_id": candidate_id,
            "source_asset_id": source_asset_id,
            "blockers": [exc.category],
            "effective_decision": "missing",
            "history": [],
            "publishing": "deferred",
            "whop": "deferred",
        }
    with database.connect() as connection:
        reviews = list_reviews(connection, facts.project_id)
    code = approval_code(work_root, facts, reviews, evidence_for_facts(facts))
    effective = "approved" if code == "approved" else "missing"
    if code in {"final_approval_rejected", "final_approval_changes_requested"}:
        review = _newest(reviews, facts.candidate_id, facts.advanced_artifact_id)
        effective = review.decision if review is not None else "missing"
    return {
        "candidate_id": facts.candidate_id,
        "rank": facts.candidate_rank,
        "project_id": facts.project_id,
        "source_asset_id": facts.source_asset_id,
        "artifact_id": facts.advanced_artifact_id,
        "manifest_sha256": facts.advanced_artifact_sha256,
        "hero_plan_id": facts.hero_plan_id,
        "hero_plan_sha256": facts.hero_plan_sha256,
        "advanced_plan_id": facts.advanced_plan_id,
        "advanced_plan_sha256": facts.advanced_plan_sha256,
        "alignment_id": facts.alignment_id or "",
        "alignment_sha256": facts.alignment_sha256 or "",
        "duration_us": facts.output_duration_us,
        "video_codec": facts.video_codec,
        "audio_codec": facts.audio_codec,
        "caption_count": len(facts.caption_cues),
        "typography": list(facts.typography),
        "diagrams": list(facts.diagrams),
        "emphasis": list(facts.emphasis),
        "broll": [item[0] for item in facts.broll],
        "sfx": [item[0] for item in facts.sfx],
        "qa_set_id": facts.qa_set_id,
        "qa_set_sha256": facts.qa_set_sha256,
        "qa_status": "pass",
        "delivery_manifest_sha256": facts.delivery_manifest_sha256,
        "profile_fingerprint": facts.profile_fingerprint,
        "policy_fingerprint": facts.policy_fingerprint,
        "rights_fingerprint": facts.rights_fingerprint,
        "reframing_strategy": facts.reframing_strategy,
        "reframing_requested": facts.reframe_requested,
        "reframing_applied": facts.reframe_applied,
        "reframing_fallback": facts.reframe_fallback,
        "face_track_id": facts.face_track_id,
        "trajectory_sha256": facts.trajectory_sha256,
        "time_map_sha256": facts.time_map_sha256,
        "reframe_blocker": facts.reframe_blocker,
        **language_evidence(facts),
        "effective_decision": effective,
        "blockers": [] if code == "approved" else [code],
        "history": history_rows(reviews, facts.candidate_id, facts.advanced_artifact_id),
        "publishing": "deferred",
        "whop": "deferred",
        "automated": False,
    }


def language_evidence(facts: object) -> dict[str, str]:
    """Facts from the bound alignment and narration. A missing file is not English."""
    from clipforge.schemas.hero import ForcedAlignmentDocument

    workspace = getattr(facts, "workspace", None)
    candidate_id = str(getattr(facts, "candidate_id", "") or "")
    card = {
        "requested_locale": "missing",
        "normalized_language": "missing",
        "alignment_status": "alignment_not_claimed",
        "alignment_provider": "none",
        "alignment_model": "none",
        "alignment_revision": "none",
        "alignment_checkpoint": "none",
        "alignment_manifest": "none",
        "alignment_cache": "miss",
        "alignment_blocker": "alignment_not_claimed",
        "narration_status": "narration_not_requested",
        "narration_provider": "none",
        "narration_engine": "none",
        "narration_model": "none",
        "narration_revision": "none",
        "narration_voice": "none",
        "narration_license": "none",
        "narration_audio_sha256": "none",
    }
    path = None if workspace is None or not candidate_id else workspace.hero_alignment_file(candidate_id)
    if path is not None and path.is_file() and not path.is_symlink():
        try:
            document = ForcedAlignmentDocument.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            card["alignment_status"] = "stale_alignment"
            card["alignment_blocker"] = "stale_alignment"
        else:
            card["requested_locale"] = document.locale or "missing"
            card["normalized_language"] = document.normalized_language or "missing"
            card["alignment_status"] = document.alignment_status or "alignment_not_claimed"
            card["alignment_provider"] = "whisperx" if document.model_name != "fake-forced-align-v1" else "fake"
            card["alignment_model"] = document.model_name
            card["alignment_revision"] = document.model_revision or "none"
            card["alignment_checkpoint"] = document.checkpoint_sha256 or "none"
            card["alignment_manifest"] = document.manifest_sha256 or "none"
            card["alignment_cache"] = "stored"
            card["alignment_blocker"] = document.unavailable_reason or "none"
            if not document.binding_sha256:
                card["alignment_cache"] = "stale"
    readable = path is not None and path.is_file() and not path.is_symlink()
    if readable and card["alignment_status"] != "stale_alignment":
        document_locale = card["requested_locale"]
        if document_locale in {"", "missing"}:
            card["alignment_status"] = "stale_alignment"
            card["alignment_blocker"] = "stale_alignment"
        elif card["alignment_provider"] == "whisperx" and (
            card["alignment_revision"] == "none"
            or card["alignment_checkpoint"] == "none"
            or card["alignment_manifest"] == "none"
            or card["alignment_cache"] == "stale"
        ):
            card["alignment_status"] = "stale_alignment"
            card["alignment_blocker"] = "stale_alignment"
            card["alignment_cache"] = "stale"
    narration_sha = getattr(facts, "narration_sha256", None)
    voice = getattr(facts, "narration_voice_id", None)
    license_name = getattr(facts, "narration_model_license", None)
    if narration_sha:
        card["narration_provider"] = str(getattr(facts, "narration_provider_id", None) or "none")
        card["narration_engine"] = str(getattr(facts, "narration_engine_id", None) or "none")
        card["narration_model"] = str(getattr(facts, "narration_model_id", None) or "none")
        card["narration_revision"] = str(getattr(facts, "narration_model_revision", None) or "none")
        card["narration_voice"] = str(voice or "none")
        card["narration_license"] = str(license_name or "none")
        card["narration_audio_sha256"] = str(narration_sha)
        incomplete = card["narration_revision"] == "none" or card["narration_model"] == "none"
        card["narration_status"] = "stale_narration" if incomplete else "recorded"
    elif getattr(facts, "narration_requested", False) is True or getattr(facts, "narration_provider_id", None):
        card["narration_status"] = "missing"
    return card


def accept_final_post(
    database: Database,
    work_root: Path,
    source_asset_id: str,
    payload: dict[str, object],
) -> ReviewDecision:
    """Append a final decision when the posted artifact is still current."""
    allowed = {
        "subject_kind",
        "source_asset_id",
        "candidate_id",
        "artifact_id",
        "manifest_sha256",
        "decision",
        "reviewer_id",
        "notes",
        "automated",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise FinalReviewError("unknown review fields: " + ", ".join(unknown), code="invalid_document")
    if payload.get("automated") is not False:
        raise FinalReviewError("automated review decisions are rejected", code="invalid_document")
    if payload.get("source_asset_id") != source_asset_id:
        raise FinalReviewError(FINAL_STALE, code="stale_final_review")
    candidate_id = payload.get("candidate_id")
    artifact_id = payload.get("artifact_id")
    manifest_sha = payload.get("manifest_sha256")
    decision = payload.get("decision")
    reviewer = payload.get("reviewer_id")
    notes = payload.get("notes", "")
    if not isinstance(candidate_id, str) or not isinstance(artifact_id, str):
        raise FinalReviewError("final review ids must be text", code="invalid_document")
    if not isinstance(manifest_sha, str):
        raise FinalReviewError("final review ids must be text", code="invalid_document")
    if not isinstance(decision, str) or not isinstance(reviewer, str) or not isinstance(notes, str):
        raise FinalReviewError("final review fields must be text", code="invalid_document")
    from clipforge.publish.preflight import preflight_delivery

    facts = preflight_delivery(
        database,
        work_root,
        source_asset_id,
        candidate_id,
        probe=False,
        require_final=False,
    )
    if facts.advanced_artifact_id != artifact_id or facts.advanced_artifact_sha256 != manifest_sha:
        raise FinalReviewError(FINAL_STALE, code="stale_final_review")
    return record_final_decision(
        database=database,
        work_root=work_root,
        facts=facts,
        evidence=evidence_for_facts(facts),
        decision=decision,
        reviewer_id=reviewer,
        notes=notes,
    )


def final_media(database: Database, work_root: Path, source_asset_id: str, candidate_id: str) -> Path:
    from clipforge.publish.preflight import preflight_delivery

    facts = preflight_delivery(
        database,
        work_root,
        source_asset_id,
        candidate_id,
        probe=False,
        require_final=False,
    )
    return media_path_or_error(facts.video_path)


def human_notes(notes: str) -> str:
    human, _digest = _split_notes(notes)
    return human


def history_rows(reviews: list[ReviewDecision], candidate_id: str, artifact_id: str) -> list[dict[str, object]]:
    rows = [item for item in reviews if item.subject_kind == "final" and item.candidate_id == candidate_id]
    ordered = sorted(rows, key=lambda item: (item.created_at, item.review_id))
    return [
        {
            "review_id": item.review_id,
            "artifact_id": item.artifact_id,
            "decision": item.decision,
            "reviewer_id": item.reviewer_id,
            "created_at": item.created_at.isoformat(),
            "notes": human_notes(item.notes),
            "current_artifact": item.artifact_id == artifact_id,
            "automated": False,
        }
        for item in ordered
    ]


def _newest(reviews: list[ReviewDecision], candidate_id: str, artifact_id: str) -> ReviewDecision | None:
    return effective_review(reviews, artifact_id, candidate_id, subject_kind="final")


def _difference(stored: dict[str, str], current: dict[str, str]) -> str:
    if stored.get("source_sha256") != current.get("source_sha256"):
        return "stale_source"
    qa_changed = stored.get("qa_set_sha256") != current.get("qa_set_sha256")
    qa_id_changed = stored.get("qa_set_id") != current.get("qa_set_id")
    if qa_changed or qa_id_changed:
        return "stale_qa"
    if stored.get("advanced_manifest_sha256") != current.get("advanced_manifest_sha256"):
        return "stale_artifact"
    if stored.get("advanced_artifact_id") != current.get("advanced_artifact_id"):
        return "stale_artifact"
    recorded_delivery = stored.get("delivery_manifest_sha256") or ""
    current_delivery = current.get("delivery_manifest_sha256") or ""
    if recorded_delivery and recorded_delivery != current_delivery:
        return "stale_delivery"
    compared = {key: value for key, value in current.items() if key != "delivery_manifest_sha256"}
    stored_compared = {key: value for key, value in stored.items() if key != "delivery_manifest_sha256"}
    if stored_compared != compared:
        return "stale_final_review"
    return "approved"


def _stored_evidence(work_root: Path, review: ReviewDecision) -> dict[str, str] | None:
    _human, digest = _split_notes(review.notes)
    if digest is None or review.artifact_id is None or review.candidate_id is None:
        return None
    path = _sidecar_path(work_root.resolve(), review.review_id)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict) or payload.get("evidence_sha256") != digest:
        return None
    if any(not isinstance(value, str) for value in evidence.values()):
        return None
    typed = {str(key): str(value) for key, value in evidence.items()}
    if evidence_sha256(typed) != digest:
        return None
    return typed


def _write_sidecar(root: Path, review_id: str, evidence: dict[str, str], digest: str) -> None:
    directory = root / "final-reviews"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{review_id}.json"
    if target.is_symlink() or directory.is_symlink():
        raise FinalReviewError("final review destination is a symlink", code="unsafe_path")
    payload = {"evidence": evidence, "evidence_sha256": digest}
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    partial = target.with_suffix(".json.partial")
    if partial.is_symlink():
        raise FinalReviewError("final review destination is a symlink", code="unsafe_path")
    descriptor = os.open(partial, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)
    os.replace(partial, target)


def _sidecar_path(root: Path, review_id: str) -> Path:
    return root / "final-reviews" / f"{review_id}.json"


def _join_notes(notes: str, digest: str) -> str:
    return f"{notes}{_MARK}{digest}"


def _split_notes(notes: str) -> tuple[str, str | None]:
    if _MARK not in notes:
        return notes, None
    human, _marker, digest = notes.rpartition(_MARK)
    if len(digest) != 64 or set(digest) - _SHA:
        return notes, None
    return human, digest


def _message(code: str) -> str:
    return {
        "final_approval_required": "final approval is missing",
        "final_approval_rejected": "final review decision is rejected",
        "final_approval_changes_requested": "final review decision is changes_requested",
        "stale_final_review": "final approval is bound to older evidence",
        "stale_source": "source hash changed after final approval",
        "stale_qa": "QA set changed after final approval",
        "stale_artifact": "advanced Hero artifact changed after final approval",
        "stale_delivery": "delivery package changed after final approval",
    }.get(code, "final approval is missing")


def media_path_or_error(path: Path) -> Path:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise MediaError("advanced Hero MP4 is not available")
    return path
