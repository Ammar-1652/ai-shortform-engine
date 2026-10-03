"""Which candidates may enter a Hero draft. The rule is the Round 7 effective decision."""

from __future__ import annotations

import hashlib
import json

from clipforge.schemas.candidates import CandidateMiningDocument
from clipforge.schemas.editorial import CandidateClip
from clipforge.schemas.governance import ReviewDecision


def review_digest(review: ReviewDecision) -> str:
    payload = {
        "artifact_id": review.artifact_id,
        "candidate_id": review.candidate_id,
        "created_at": review.created_at.isoformat(),
        "decision": review.decision,
        "review_id": review.review_id,
        "reviewer_id": review.reviewer_id,
        "subject_kind": review.subject_kind,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def approved_candidates(
    document: CandidateMiningDocument,
    reviews: list[ReviewDecision],
    *,
    rough_artifact_id: str,
) -> tuple[list[tuple[CandidateClip, ReviewDecision]], list[tuple[str, str]]]:
    """Return approved clips in rank order, and the excluded candidates with reasons."""
    from clipforge.review.service import effective_review

    chosen: list[tuple[CandidateClip, ReviewDecision]] = []
    excluded: list[tuple[str, str]] = []
    for candidate in document.candidates:
        decision = effective_review(reviews, rough_artifact_id, candidate.candidate_id)
        if decision is None:
            excluded.append((candidate.candidate_id, "no decision for the current rough preview"))
            continue
        if decision.decision == "approved":
            chosen.append((candidate, decision))
            continue
        if decision.decision == "changes_requested":
            excluded.append((candidate.candidate_id, "changes_requested"))
            continue
        excluded.append((candidate.candidate_id, "rejected"))
    return chosen, excluded
