"""Pure candidate mining from a transcript document and a visual document.

The function does not open video, audio, or a model. The same documents and
profile produce the same candidates when ``mining_id`` is unchanged.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from clipforge.candidates.constants import RECIPE_NAME, RECIPE_VERSION, TOOL_NAME
from clipforge.candidates.dedupe import DedupeHit, RankedHypothesis, dedupe_hypotheses
from clipforge.candidates.scoring import (
    MeasuredWindow,
    hard_duration_reason,
    measure_window,
    score_edit,
    score_quality,
)
from clipforge.candidates.windows import RawWindow, generate_windows
from clipforge.errors import MediaError
from clipforge.schemas.candidates import (
    CandidateDeduplicationDecision,
    CandidateEvidenceBundle,
    CandidateFilterDecision,
    CandidateFilterReason,
    CandidateMiningDocument,
    CandidateMiningProfile,
    CandidateMiningSummary,
    CandidateScoreBreakdown,
    DedupDisposition,
    aggregate_duration_us,
    aggregate_unit_score,
)
from clipforge.schemas.editorial import CandidateClip, CandidateEvidence, CandidateStatus, EvidenceKind
from clipforge.schemas.governance import ComplianceResult, ComplianceStatus
from clipforge.schemas.media import Transcript
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimelineSegment, TimeMapDocument
from clipforge.schemas.vision import VisualAnalysisDocument

STAGE_CALLS = {"windows": 0, "features": 0, "score": 0, "dedupe": 0}
_COMPLIANCE = (
    ("candidate_source_rights", "source rights are cleared"),
    ("candidate_current_transcript", "current transcript artifact is bound to this source"),
    ("candidate_current_visual", "current visual analysis artifact is bound to this source"),
    ("candidate_source_range_valid", "candidate range lies inside the canonical source duration"),
    ("candidate_transcript_evidence_present", "transcript segments overlap the candidate"),
    ("candidate_visual_evidence_present", "visual scenes overlap the candidate"),
)


def reset_stage_calls() -> None:
    for key in STAGE_CALLS:
        STAGE_CALLS[key] = 0


def stage_calls() -> dict[str, int]:
    return dict(STAGE_CALLS)


@dataclass(frozen=True, slots=True)
class _Scored:
    measured: MeasuredWindow
    hypothesis_id: str
    quality: float
    coverage: float
    edit: float
    edit_coverage: float


def mine_documents(
    *,
    transcript: Transcript,
    visual: VisualAnalysisDocument,
    profile: CandidateMiningProfile,
    mining_id: str,
    created_at: datetime,
    created_by: str,
    job_id: str,
    source_sha256: str,
    transcript_sha256: str,
    visual_sha256: str,
    candidate_input_sha256: str,
    transcript_job_id: str,
    visual_job_id: str,
    transcript_recipe_name: str,
    transcript_recipe_version: str,
    visual_recipe_name: str,
    visual_recipe_version: str,
    tool_version: str,
) -> CandidateMiningDocument:
    """Mine one source. Raises when the transcript and visual documents disagree."""
    _require_same_source(transcript, visual, source_sha256)
    duration = transcript.canonical_duration_us
    if duration is None or duration != visual.canonical_duration_us:
        raise MediaError(
            "transcript and visual analysis canonical durations do not match. "
            "Candidate mining will not pair evidence from different timelines."
        )
    STAGE_CALLS["windows"] += 1
    windows, cap_reached = generate_windows(transcript, profile, duration_us=duration)
    STAGE_CALLS["features"] += 1
    measured = extract_features(windows, transcript, visual, profile, duration_us=duration)
    STAGE_CALLS["score"] += 1
    hard_filters, weak_filters, scored = score_features(measured, profile, mining_id, duration_us=duration)
    STAGE_CALLS["dedupe"] += 1
    _pool, pool_filters, decisions, kept = dedupe_features(scored, profile)
    selected = kept[: profile.max_candidates]
    capped = kept[profile.max_candidates :]
    cap_filters = [_filter(item, CandidateFilterReason.OUTPUT_CAP) for item in capped]
    by_id = {item.hypothesis_id: item for item in _pool}
    duplicate_filters = [
        _filter_scored(by_id[decision.hypothesis_id], CandidateFilterReason.DUPLICATE)
        for decision in decisions
        if not decision.kept
    ]
    filters = [*hard_filters, *weak_filters, *pool_filters, *duplicate_filters, *cap_filters]
    return _assemble(
        transcript=transcript,
        visual=visual,
        profile=profile,
        mining_id=mining_id,
        created_at=created_at,
        created_by=created_by,
        job_id=job_id,
        source_sha256=source_sha256,
        transcript_sha256=transcript_sha256,
        visual_sha256=visual_sha256,
        candidate_input_sha256=candidate_input_sha256,
        transcript_job_id=transcript_job_id,
        visual_job_id=visual_job_id,
        transcript_recipe_name=transcript_recipe_name,
        transcript_recipe_version=transcript_recipe_version,
        visual_recipe_name=visual_recipe_name,
        visual_recipe_version=visual_recipe_version,
        tool_version=tool_version,
        duration_us=duration,
        raw_count=len(windows),
        cap_reached=cap_reached,
        hard_filters=hard_filters,
        weak_filters=weak_filters,
        pool_filters=pool_filters,
        decisions=decisions,
        selected=selected,
        filters=filters,
    )


def extract_features(
    windows: list[RawWindow],
    transcript: Transcript,
    visual: VisualAnalysisDocument,
    profile: CandidateMiningProfile,
    *,
    duration_us: int,
) -> list[MeasuredWindow]:
    known = [word for segment in transcript.segments for word in segment.words]
    return [
        measure_window(
            window,
            list(transcript.segments),
            known,
            list(visual.scenes),
            list(visual.frame_evidence),
            list(visual.face_detection_samples),
            list(visual.face_observations),
            profile,
            duration_us=duration_us,
        )
        for window in windows
    ]


def score_features(
    measured: list[MeasuredWindow],
    profile: CandidateMiningProfile,
    mining_id: str,
    *,
    duration_us: int,
) -> tuple[list[CandidateFilterDecision], list[CandidateFilterDecision], list[_Scored]]:
    hard: list[CandidateFilterDecision] = []
    weak: list[CandidateFilterDecision] = []
    scored: list[_Scored] = []
    for item in measured:
        reason = _hard_reason(item, profile, duration_us)
        if reason is not None:
            hard.append(_filter_measured(item, reason, mining_id))
            continue
        quality, coverage = score_quality(item, profile)
        edit, edit_coverage = score_edit(item, profile)
        hypothesis_id = _range_id(mining_id, item.window.start_us, item.window.end_us)
        if coverage < profile.minimum_quality_coverage:
            weak.append(
                CandidateFilterDecision(
                    hypothesis_id=hypothesis_id,
                    source_start_us=item.window.start_us,
                    source_end_us=item.window.end_us,
                    reason=CandidateFilterReason.INSUFFICIENT_SCORE_COVERAGE,
                )
            )
            continue
        scored.append(
            _Scored(
                measured=item,
                hypothesis_id=hypothesis_id,
                quality=quality,
                coverage=coverage,
                edit=edit,
                edit_coverage=edit_coverage,
            )
        )
    return hard, weak, scored


def dedupe_features(
    scored: list[_Scored],
    profile: CandidateMiningProfile,
) -> tuple[list[_Scored], list[CandidateFilterDecision], list[DedupeHit], list[_Scored]]:
    ordered = sorted(scored, key=_score_key)
    pool = ordered[: profile.pre_dedupe_pool_size]
    excluded = [
        _filter_scored(item, CandidateFilterReason.PRE_DEDUPE_POOL)
        for item in ordered[profile.pre_dedupe_pool_size :]
    ]
    ranked = [
        RankedHypothesis(
            hypothesis_id=item.hypothesis_id,
            start_us=item.measured.window.start_us,
            end_us=item.measured.window.end_us,
            quality=item.quality,
            coverage=item.coverage,
            boundary=item.measured.boundary_completeness,
            tokens=item.measured.window.tokens,
        )
        for item in pool
    ]
    decisions = dedupe_hypotheses(ranked, profile)
    by_id = {item.hypothesis_id: item for item in pool}
    kept = [by_id[decision.hypothesis_id] for decision in decisions if decision.kept]
    kept.sort(key=_score_key)
    return pool, excluded, decisions, kept


def _assemble(
    *,
    transcript: Transcript,
    visual: VisualAnalysisDocument,
    profile: CandidateMiningProfile,
    mining_id: str,
    created_at: datetime,
    created_by: str,
    job_id: str,
    source_sha256: str,
    transcript_sha256: str,
    visual_sha256: str,
    candidate_input_sha256: str,
    transcript_job_id: str,
    visual_job_id: str,
    transcript_recipe_name: str,
    transcript_recipe_version: str,
    visual_recipe_name: str,
    visual_recipe_version: str,
    tool_version: str,
    duration_us: int,
    raw_count: int,
    cap_reached: bool,
    hard_filters: list[CandidateFilterDecision],
    weak_filters: list[CandidateFilterDecision],
    pool_filters: list[CandidateFilterDecision],
    decisions: list[DedupeHit],
    selected: list[_Scored],
    filters: list[CandidateFilterDecision],
) -> CandidateMiningDocument:
    provenance = ArtifactProvenance(
        created_at=created_at,
        created_by=created_by,
        tool=TOOL_NAME,
        tool_version=tool_version,
        source_asset_ids=[transcript.source_asset_id],
        parent_artifact_ids=[],
        job_id=job_id,
        inputs_sha256=candidate_input_sha256,
    )
    scene_ordinals = {scene.scene_id: index for index, scene in enumerate(visual.scenes)}
    candidates: list[CandidateClip] = []
    bundles: list[CandidateEvidenceBundle] = []
    breakdowns: list[CandidateScoreBreakdown] = []
    for item in selected:
        candidates.append(
            _clip(
                item,
                mining_id=mining_id,
                transcript=transcript,
                visual=visual,
                provenance=provenance,
                scene_ordinals=scene_ordinals,
                source_sha256=source_sha256,
            )
        )
        bundles.append(_bundle(item))
        breakdowns.append(_breakdown(item))
    durations = [item.measured.window.end_us - item.measured.window.start_us for item in selected]
    qualities = [item.quality for item in selected]
    edits = [item.edit for item in selected]
    duplicate_count = sum(1 for decision in decisions if not decision.kept)
    eligible = sum(1 for decision in decisions if decision.kept)
    summary = CandidateMiningSummary(
        raw_hypothesis_count=raw_count,
        hard_filtered_count=len(hard_filters),
        scored_count=raw_count - len(hard_filters),
        insufficient_evidence_count=len(weak_filters),
        pre_dedupe_excluded_count=len(pool_filters),
        duplicate_count=duplicate_count,
        eligible_distinct_count=eligible,
        output_cap_count=eligible - len(selected),
        selected_count=len(selected),
        soft_target_min=profile.soft_target_min,
        max_candidates=profile.max_candidates,
        below_soft_target=len(selected) < profile.soft_target_min,
        raw_hypothesis_cap_reached=cap_reached,
        mean_selected_duration_us=aggregate_duration_us(durations),
        shortest_selected_duration_us=min(durations) if durations else None,
        longest_selected_duration_us=max(durations) if durations else None,
        mean_quality_score=aggregate_unit_score(qualities),
        mean_edit_opportunity_score=aggregate_unit_score(edits),
    )
    dedupe_rows = [
        CandidateDeduplicationDecision(
            hypothesis_id=decision.hypothesis_id,
            disposition=DedupDisposition.KEPT if decision.kept else DedupDisposition.DUPLICATE,
            duplicate_of_candidate_id=decision.duplicate_of,
            temporal_iou=decision.temporal_iou,
            containment_ratio=decision.containment_ratio,
            token_similarity=decision.token_similarity,
            reason=decision.reason,
        )
        for decision in decisions
    ]
    return CandidateMiningDocument(
        mining_id=mining_id,
        project_id=transcript.project_id,
        source_asset_id=transcript.source_asset_id,
        created_at=created_at,
        canonical_duration_us=duration_us,
        source_sha256=source_sha256,
        transcript_id=transcript.transcript_id,
        transcript_sha256=transcript_sha256,
        transcript_job_id=transcript_job_id,
        transcript_recipe_name=transcript_recipe_name,
        transcript_recipe_version=transcript_recipe_version,
        transcript_alignment="approximate",
        transcript_timing_quality="provisional",
        visual_analysis_id=visual.analysis_id,
        visual_analysis_sha256=visual_sha256,
        visual_job_id=visual_job_id,
        visual_recipe_name=visual_recipe_name,
        visual_recipe_version=visual_recipe_version,
        candidate_input_sha256=candidate_input_sha256,
        recipe_name=RECIPE_NAME,
        recipe_version=RECIPE_VERSION,
        boundary_timing_quality="provisional",
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        window_algorithm_version=profile.window_algorithm_version,
        tokenizer_version=profile.tokenizer_version,
        scoring_version=profile.scoring_version,
        dedupe_version=profile.dedupe_version,
        candidates=candidates,
        evidence_bundles=bundles,
        score_breakdowns=breakdowns,
        dedupe_decisions=dedupe_rows,
        filter_decisions=filters,
        summary=summary,
        provenance=provenance,
    )


def _clip(
    item: _Scored,
    *,
    mining_id: str,
    transcript: Transcript,
    visual: VisualAnalysisDocument,
    provenance: ArtifactProvenance,
    scene_ordinals: dict[str, int],
    source_sha256: str,
) -> CandidateClip:
    window = item.measured.window
    segment_id = _child(mining_id, "segment", item.hypothesis_id)
    time_map = TimeMapDocument(
        time_map_id=_child(mining_id, "timemap", item.hypothesis_id),
        segments=[
            TimelineSegment(
                segment_id=segment_id,
                source_start_us=window.start_us,
                source_end_us=window.end_us,
            )
        ],
    )
    ordinals = window.segment_ordinals
    segment_label = f"{ordinals[0]}-{ordinals[-1]}" if ordinals else "none"
    scene_indexes = [
        scene_ordinals[scene_id] for scene_id in item.measured.visual.scene_ids if scene_id in scene_ordinals
    ]
    scene_label = _index_label(scene_indexes)
    excerpt_hash = hashlib.sha256(window.excerpt.encode("utf-8")).hexdigest()[:12]
    transcript_detail = f"Segments {segment_label}; words {window.word_count}; excerpt digest {excerpt_hash}"
    evidence = [
        CandidateEvidence(
            evidence_id=_child(mining_id, "transcript-evidence", item.hypothesis_id),
            kind=EvidenceKind.TRANSCRIPT,
            detail=transcript_detail,
            source_start_us=window.start_us,
            source_end_us=window.end_us,
        ),
        CandidateEvidence(
            evidence_id=_child(mining_id, "visual-evidence", item.hypothesis_id),
            kind=EvidenceKind.VISUAL,
            detail=(
                f"Scenes {scene_label}; {len(item.measured.visual.frame_ids)} representative frames; "
                f"{len(item.measured.visual.track_ids)} geometry-only face tracks"
            ),
            source_start_us=window.start_us,
            source_end_us=window.end_us,
        ),
    ]
    compliance = [
        ComplianceResult(
            result_id=_child(mining_id, rule_id, item.hypothesis_id),
            rule_id=rule_id,
            status=ComplianceStatus.PASS,
            evidence=(
                f"{detail}. source {transcript.source_asset_id} sha256 {source_sha256[:12]} "
                f"transcript {transcript.transcript_id} visual {visual.analysis_id}"
            ),
        )
        for rule_id, detail in _COMPLIANCE
    ]
    return CandidateClip(
        candidate_id=item.hypothesis_id,
        project_id=transcript.project_id,
        source_asset_id=transcript.source_asset_id,
        status=CandidateStatus.READY_FOR_REVIEW,
        time_map=time_map,
        evidence=evidence,
        compliance=compliance,
        creative_score=item.quality,
        provenance=provenance,
    )


def _bundle(item: _Scored) -> CandidateEvidenceBundle:
    window = item.measured.window
    excerpt = window.excerpt or window.text[:300]
    return CandidateEvidenceBundle(
        candidate_id=item.hypothesis_id,
        transcript_segment_ids=list(window.segment_ids),
        transcript_word_ids=list(window.word_ids),
        transcript_excerpt=excerpt,
        transcript_start_us=window.start_us,
        transcript_end_us=window.end_us,
        visual_scene_ids=list(item.measured.visual.scene_ids),
        representative_frame_ids=list(item.measured.visual.frame_ids),
        face_observation_ids=list(item.measured.visual.face_observation_ids),
        source_start_us=window.start_us,
        source_end_us=window.end_us,
    )


def _breakdown(item: _Scored) -> CandidateScoreBreakdown:
    measured = item.measured
    return CandidateScoreBreakdown(
        candidate_id=item.hypothesis_id,
        duration_fit=measured.duration_fit,
        speech_coverage=measured.speech_coverage,
        boundary_completeness=measured.boundary_completeness,
        transcript_reliability=measured.transcript_reliability,
        information_density=measured.information_density,
        opening_structure=measured.opening_structure,
        visual_evidence_coverage=measured.visual_evidence_coverage,
        quality_score=item.quality,
        quality_weight_coverage=item.coverage,
        scene_change_signal=measured.scene_change_signal,
        visual_difference_signal=measured.visual_difference_signal,
        face_layout_variation=measured.face_layout_variation,
        numeric_token_signal=measured.numeric_token_signal,
        punctuation_emphasis_signal=measured.punctuation_emphasis_signal,
        multi_scene_signal=measured.multi_scene_signal,
        edit_opportunity_score=item.edit,
        edit_opportunity_weight_coverage=item.edit_coverage,
        scoring_version="quality-edit-v1",
    )


def _hard_reason(
    item: MeasuredWindow,
    profile: CandidateMiningProfile,
    duration_us: int,
) -> CandidateFilterReason | None:
    window = item.window
    if window.end_us <= window.start_us:
        return CandidateFilterReason.EMPTY_OR_REVERSED
    if window.start_us < 0 or window.end_us > duration_us:
        return CandidateFilterReason.RANGE_OUTSIDE_SOURCE
    span = window.end_us - window.start_us
    duration_reason = hard_duration_reason(span, profile)
    if duration_reason == "too_short":
        return CandidateFilterReason.TOO_SHORT
    if duration_reason == "too_long":
        return CandidateFilterReason.TOO_LONG
    if window.word_count < profile.minimum_transcript_words:
        return CandidateFilterReason.TOO_FEW_WORDS
    if not window.segment_ids or not window.excerpt:
        return CandidateFilterReason.NO_TRANSCRIPT_EVIDENCE
    if not item.visual.scene_ids:
        return CandidateFilterReason.NO_VISUAL_EVIDENCE
    return None


def _filter_measured(
    item: MeasuredWindow,
    reason: CandidateFilterReason,
    mining_id: str,
) -> CandidateFilterDecision:
    return CandidateFilterDecision(
        hypothesis_id=_range_id(mining_id, item.window.start_us, item.window.end_us),
        source_start_us=item.window.start_us,
        source_end_us=item.window.end_us,
        reason=reason,
    )


def _filter_scored(item: _Scored, reason: CandidateFilterReason) -> CandidateFilterDecision:
    return CandidateFilterDecision(
        hypothesis_id=item.hypothesis_id,
        source_start_us=item.measured.window.start_us,
        source_end_us=item.measured.window.end_us,
        reason=reason,
    )


def _filter(item: _Scored, reason: CandidateFilterReason) -> CandidateFilterDecision:
    return _filter_scored(item, reason)


def _score_key(item: _Scored) -> tuple[object, ...]:
    from decimal import Decimal

    return (
        -Decimal(str(item.quality)),
        -Decimal(str(item.coverage)),
        -Decimal(str(item.measured.boundary_completeness)),
        item.measured.window.start_us,
        item.measured.window.end_us - item.measured.window.start_us,
        item.hypothesis_id,
    )


def _require_same_source(transcript: Transcript, visual: VisualAnalysisDocument, source_sha256: str) -> None:
    if transcript.project_id != visual.project_id or transcript.source_asset_id != visual.source_asset_id:
        raise MediaError(
            "refusing to mine candidates from a transcript and a visual analysis for different sources. "
            f"Transcript source is {transcript.source_asset_id}; visual source is {visual.source_asset_id}."
        )
    if visual.source_sha256 != source_sha256:
        raise MediaError(
            "visual analysis source hash does not match the current source. Candidate mining was not started."
        )
    if transcript.alignment != "approximate" or transcript.timing_quality != "provisional":
        raise MediaError(
            "candidate boundaries stay provisional. "
            "The transcript alignment is not the first-pass approximate transcript."
        )


def _range_id(mining_id: str, start_us: int, end_us: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"clipforge|{mining_id}|range|{start_us}|{end_us}"))


def _child(mining_id: str, kind: str, parent: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"clipforge|{mining_id}|{kind}|{parent}"))


def _index_label(indexes: list[int]) -> str:
    if not indexes:
        return "none"
    ordered = sorted(indexes)
    if ordered[-1] - ordered[0] + 1 == len(ordered) and len(ordered) > 1:
        return f"{ordered[0]}-{ordered[-1]}"
    return ", ".join(str(index) for index in ordered)
