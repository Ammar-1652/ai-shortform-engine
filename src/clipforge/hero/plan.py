"""Build one Hero EditPlan from forced alignment."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from clipforge.hero.captions import hero_caption_cues
from clipforge.hero.constants import MOTION_LIBRARY_VERSION, TOOL_NAME
from clipforge.hero.motion import hero_motion_events
from clipforge.hero.selection import review_digest
from clipforge.schemas.editorial import CandidateClip, EditPlan
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.hero import ForcedAlignmentDocument, HeroPlanDocument, HeroProfile
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import digest_time_map


def build_hero_plan(
    *,
    plan_id: str,
    candidate: CandidateClip,
    alignment: ForcedAlignmentDocument,
    review: ReviewDecision,
    rough_artifact_id: str,
    profile: HeroProfile,
    created_by: str,
    tool_version: str,
) -> HeroPlanDocument:
    duration = candidate.time_map.to_time_map().total_output_duration()
    captions = hero_caption_cues(alignment.words)
    motion = hero_motion_events(
        candidate_id=candidate.candidate_id,
        duration_us=duration,
        words=alignment.words,
    )
    stamp = datetime.now(UTC)
    provenance = ArtifactProvenance(
        created_at=stamp,
        created_by=created_by,
        tool=TOOL_NAME,
        tool_version=tool_version,
        source_asset_ids=[candidate.source_asset_id],
        inputs_sha256=alignment.config_sha256,
    )
    edit_plan = EditPlan(
        edit_plan_id=plan_id,
        project_id=candidate.project_id,
        candidate_id=candidate.candidate_id,
        stage="hero",
        time_map=candidate.time_map,
        time_map_sha256=digest_time_map(candidate.time_map),
        captions=captions,
        motion_events=motion,
        provenance=provenance,
    )
    return HeroPlanDocument(
        plan_id=plan_id,
        edit_plan=edit_plan,
        alignment_sha256=digest_alignment(alignment),
        review_id=review.review_id,
        review_digest=review_digest(review),
        rough_preview_artifact_id=rough_artifact_id,
        motion_library_version=MOTION_LIBRARY_VERSION,
        profile_fingerprint=profile.fingerprint(),
        qa_requirements=[
            "forced_alignment",
            "current_approval",
            "duration_tolerance",
            "contain_framing",
        ],
    )


def digest_alignment(alignment: ForcedAlignmentDocument) -> str:
    raw = json.dumps(alignment.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def digest_plan(plan: HeroPlanDocument) -> str:
    raw = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
