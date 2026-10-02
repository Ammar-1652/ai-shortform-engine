"""Candidate mining contracts. Scores are editorial heuristics, not predictions.

``quality_score`` is copied onto ``CandidateClip.creative_score``. It is a
deterministic ranking heuristic. It is not a probability of views, virality,
compliance, factual truth, or human approval. ``edit_opportunity_score`` is a
separate measurement of visible structure. The two are not added together.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import ContractModel, EntityId, Microseconds, Versioned
from clipforge.schemas.editorial import CandidateClip
from clipforge.schemas.governance import ComplianceStatus, is_compliance_cleared
from clipforge.schemas.provenance import ArtifactProvenance

_SHA = r"^[0-9a-f]{64}$"
_UNIT = Decimal("0.000001")
_ROUND_RULES = (
    "candidate_source_rights",
    "candidate_current_transcript",
    "candidate_current_visual",
    "candidate_source_range_valid",
    "candidate_transcript_evidence_present",
    "candidate_visual_evidence_present",
)


class CandidateFilterReason(StrEnum):
    """Why a raw hypothesis was not published as a candidate."""

    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    TOO_FEW_WORDS = "too_few_words"
    NO_TRANSCRIPT_EVIDENCE = "no_transcript_evidence"
    NO_VISUAL_EVIDENCE = "no_visual_evidence"
    RANGE_OUTSIDE_SOURCE = "range_outside_source"
    EMPTY_OR_REVERSED = "empty_or_reversed"
    INSUFFICIENT_SCORE_COVERAGE = "insufficient_score_coverage"
    PRE_DEDUPE_POOL = "pre_dedupe_pool"
    DUPLICATE = "duplicate"
    OUTPUT_CAP = "output_cap"


class DedupDisposition(StrEnum):
    KEPT = "kept"
    DUPLICATE = "duplicate"


def quantize_unit(value: float) -> float:
    """Round a unit-interval score to six decimal places. Reject non-finite values."""
    if not math.isfinite(value):
        raise ValueError("score must be finite")
    quantized = Decimal(str(value)).quantize(_UNIT, rounding=ROUND_HALF_UP)
    if quantized < 0 or quantized > 1:
        raise ValueError("score must be between 0 and 1")
    return float(quantized)


def weighted_score(pairs: Sequence[tuple[float | None, float]]) -> tuple[float, float]:
    """Renormalize ``pairs`` of ``(value, weight)`` over the values that are present.

    A missing value is skipped. It is not replaced with 0.5. The second result
    is the fraction of the total weight that was available.
    """
    if not pairs:
        raise ValueError("score weights are empty")
    total = Decimal(0)
    available = Decimal(0)
    accumulated = Decimal(0)
    for value, weight in pairs:
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("score weight must be a finite non-negative number")
        weight_d = Decimal(str(weight))
        total += weight_d
        if value is None:
            continue
        if not math.isfinite(value):
            raise ValueError("score feature must be finite")
        value_d = Decimal(str(value))
        if value_d < 0 or value_d > 1:
            raise ValueError("score feature must be between 0 and 1")
        available += weight_d
        accumulated += weight_d * value_d
    if total <= 0:
        raise ValueError("score weights must sum to a positive total")
    if available <= 0:
        raise ValueError("no score features were available")
    score = (accumulated / available).quantize(_UNIT, rounding=ROUND_HALF_UP)
    coverage = (available / total).quantize(_UNIT, rounding=ROUND_HALF_UP)
    if score < 0 or score > 1 or coverage < 0 or coverage > 1:
        raise ValueError("weighted score must stay between 0 and 1")
    return float(score), float(coverage)


def aggregate_duration_us(values: Sequence[int]) -> int | None:
    """Integer mean duration. Empty input is missing, not zero."""
    if not values:
        return None
    mean = (Decimal(sum(values)) / Decimal(len(values))).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(mean)


def aggregate_unit_score(values: Sequence[float]) -> float | None:
    """Mean of already-rounded unit scores. Empty input is missing, not zero."""
    if not values:
        return None
    total = sum((Decimal(str(value)) for value in values), start=Decimal(0))
    mean = (total / Decimal(len(values))).quantize(_UNIT, rounding=ROUND_HALF_UP)
    return float(mean)


class QualityWeights(ContractModel):
    """Weights for the editorial quality heuristic. They sum to 1."""

    duration_fit: float = 0.15
    speech_coverage: float = 0.20
    boundary_completeness: float = 0.20
    transcript_reliability: float = 0.20
    information_density: float = 0.10
    opening_structure: float = 0.05
    visual_evidence_coverage: float = 0.10

    @model_validator(mode="after")
    def sums_to_one(self) -> Self:
        _require_weight_total(self._pairs())
        return self

    def pairs(self, values: Mapping[str, float | None]) -> list[tuple[float | None, float]]:
        return [(values.get(name), weight) for name, weight in self._pairs()]

    def _pairs(self) -> list[tuple[str, float]]:
        return [
            ("duration_fit", self.duration_fit),
            ("speech_coverage", self.speech_coverage),
            ("boundary_completeness", self.boundary_completeness),
            ("transcript_reliability", self.transcript_reliability),
            ("information_density", self.information_density),
            ("opening_structure", self.opening_structure),
            ("visual_evidence_coverage", self.visual_evidence_coverage),
        ]


class EditOpportunityWeights(ContractModel):
    """Weights for editing opportunity. They do not enter the quality score."""

    scene_change_signal: float = 0.25
    visual_difference_signal: float = 0.25
    face_layout_variation: float = 0.15
    numeric_token_signal: float = 0.15
    punctuation_emphasis_signal: float = 0.10
    multi_scene_signal: float = 0.10

    @model_validator(mode="after")
    def sums_to_one(self) -> Self:
        _require_weight_total(self._pairs())
        return self

    def pairs(self, values: Mapping[str, float | None]) -> list[tuple[float | None, float]]:
        return [(values.get(name), weight) for name, weight in self._pairs()]

    def _pairs(self) -> list[tuple[str, float]]:
        return [
            ("scene_change_signal", self.scene_change_signal),
            ("visual_difference_signal", self.visual_difference_signal),
            ("face_layout_variation", self.face_layout_variation),
            ("numeric_token_signal", self.numeric_token_signal),
            ("punctuation_emphasis_signal", self.punctuation_emphasis_signal),
            ("multi_scene_signal", self.multi_scene_signal),
        ]


class CandidateMiningProfile(Versioned):
    """Output-changing settings for one candidate-mining recipe.

    ``soft_target_min`` is informational. Mining does not invent candidates to
    reach it. ``max_candidates`` is a real cap. There is no quality floor:
    eligibility is the hard filters plus score-coverage, then dedupe.
    """

    profile_id: Literal["candidate-mining-v1"] = "candidate-mining-v1"
    hard_min_duration_us: Microseconds = 8_000_000
    preferred_min_duration_us: Microseconds = 18_000_000
    preferred_max_duration_us: Microseconds = 45_000_000
    hard_max_duration_us: Microseconds = 65_000_000
    boundary_padding_us: Microseconds = 250_000
    soft_target_min: int = Field(default=15, ge=0)
    max_candidates: int = Field(default=25, ge=1)
    minimum_transcript_words: int = Field(default=5, ge=1)
    maximum_raw_hypotheses: int = Field(default=5000, ge=1)
    pre_dedupe_pool_size: int = Field(default=200, ge=1)
    minimum_quality_coverage: float = Field(default=0.70, ge=0, le=1)
    containment_threshold: float = Field(default=0.80, ge=0, le=1)
    temporal_iou_threshold: float = Field(default=0.70, ge=0, le=1)
    token_similarity_threshold: float = Field(default=0.70, ge=0, le=1)
    window_algorithm_version: Literal["window-v1"] = "window-v1"
    tokenizer_version: Literal["unicode-regex-v1"] = "unicode-regex-v1"
    scoring_version: Literal["quality-edit-v1"] = "quality-edit-v1"
    dedupe_version: Literal["temporal-jaccard-v1"] = "temporal-jaccard-v1"
    boundary_algorithm_version: Literal["word-pad-v1"] = "word-pad-v1"
    quality_weights: QualityWeights = Field(default_factory=QualityWeights)
    edit_weights: EditOpportunityWeights = Field(default_factory=EditOpportunityWeights)

    @model_validator(mode="after")
    def limits_are_ordered(self) -> Self:
        if self.hard_min_duration_us <= 0:
            raise ValueError("hard_min_duration_us must be greater than 0")
        if not (
            self.hard_min_duration_us
            <= self.preferred_min_duration_us
            <= self.preferred_max_duration_us
            <= self.hard_max_duration_us
        ):
            raise ValueError("duration limits must run hard min, preferred min, preferred max, hard max")
        if self.soft_target_min > self.max_candidates:
            raise ValueError("soft_target_min cannot exceed max_candidates")
        if self.pre_dedupe_pool_size < self.max_candidates:
            raise ValueError("pre_dedupe_pool_size must be at least max_candidates")
        for label, value in (
            ("minimum_quality_coverage", self.minimum_quality_coverage),
            ("containment_threshold", self.containment_threshold),
            ("temporal_iou_threshold", self.temporal_iou_threshold),
            ("token_similarity_threshold", self.token_similarity_threshold),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{label} must be finite")
        return self

    def fingerprint(self) -> str:
        """SHA-256 of every output-changing field. ``created_at`` is not a field."""
        payload = self.model_dump(mode="json")
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class CandidateEvidenceBundle(Versioned):
    """Machine-readable evidence for one candidate. Prose details are not the ids."""

    candidate_id: EntityId
    transcript_segment_ids: list[EntityId] = Field(min_length=1)
    transcript_word_ids: list[EntityId] = Field(default_factory=list)
    transcript_excerpt: str = Field(min_length=1, max_length=300)
    transcript_start_us: Microseconds
    transcript_end_us: Microseconds
    visual_scene_ids: list[EntityId] = Field(min_length=1)
    representative_frame_ids: list[EntityId] = Field(default_factory=list)
    face_observation_ids: list[EntityId] = Field(default_factory=list)
    source_start_us: Microseconds
    source_end_us: Microseconds

    @model_validator(mode="after")
    def ranges_match(self) -> Self:
        if self.source_end_us <= self.source_start_us:
            raise ValueError("candidate source range must be positive")
        if self.transcript_start_us != self.source_start_us or self.transcript_end_us != self.source_end_us:
            raise ValueError("transcript evidence range must equal the candidate source range")
        if len(set(self.transcript_segment_ids)) != len(self.transcript_segment_ids):
            raise ValueError("transcript segment ids must be unique")
        if len(set(self.transcript_word_ids)) != len(self.transcript_word_ids):
            raise ValueError("transcript word ids must be unique")
        if len(set(self.visual_scene_ids)) != len(self.visual_scene_ids):
            raise ValueError("visual scene ids must be unique")
        if len(set(self.representative_frame_ids)) != len(self.representative_frame_ids):
            raise ValueError("representative frame ids must be unique")
        if len(set(self.face_observation_ids)) != len(self.face_observation_ids):
            raise ValueError("face observation ids must be unique")
        return self


class CandidateScoreBreakdown(Versioned):
    """Persisted features. Missing evidence stays null and is omitted from the weight."""

    candidate_id: EntityId
    duration_fit: float | None = None
    speech_coverage: float | None = None
    boundary_completeness: float | None = None
    transcript_reliability: float | None = None
    information_density: float | None = None
    opening_structure: float | None = None
    visual_evidence_coverage: float | None = None
    quality_score: float = Field(ge=0, le=1)
    quality_weight_coverage: float = Field(ge=0, le=1)
    scene_change_signal: float | None = None
    visual_difference_signal: float | None = None
    face_layout_variation: float | None = None
    numeric_token_signal: float | None = None
    punctuation_emphasis_signal: float | None = None
    multi_scene_signal: float | None = None
    edit_opportunity_score: float = Field(ge=0, le=1)
    edit_opportunity_weight_coverage: float = Field(ge=0, le=1)
    scoring_version: Literal["quality-edit-v1"] = "quality-edit-v1"

    @model_validator(mode="after")
    def scores_are_finite(self) -> Self:
        for label, value in (
            ("duration_fit", self.duration_fit),
            ("speech_coverage", self.speech_coverage),
            ("boundary_completeness", self.boundary_completeness),
            ("transcript_reliability", self.transcript_reliability),
            ("information_density", self.information_density),
            ("opening_structure", self.opening_structure),
            ("visual_evidence_coverage", self.visual_evidence_coverage),
            ("quality_score", self.quality_score),
            ("quality_weight_coverage", self.quality_weight_coverage),
            ("scene_change_signal", self.scene_change_signal),
            ("visual_difference_signal", self.visual_difference_signal),
            ("face_layout_variation", self.face_layout_variation),
            ("numeric_token_signal", self.numeric_token_signal),
            ("punctuation_emphasis_signal", self.punctuation_emphasis_signal),
            ("multi_scene_signal", self.multi_scene_signal),
            ("edit_opportunity_score", self.edit_opportunity_score),
            ("edit_opportunity_weight_coverage", self.edit_opportunity_weight_coverage),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{label} must be finite")
        return self

    def quality_values(self) -> dict[str, float | None]:
        return {
            "duration_fit": self.duration_fit,
            "speech_coverage": self.speech_coverage,
            "boundary_completeness": self.boundary_completeness,
            "transcript_reliability": self.transcript_reliability,
            "information_density": self.information_density,
            "opening_structure": self.opening_structure,
            "visual_evidence_coverage": self.visual_evidence_coverage,
        }

    def edit_values(self) -> dict[str, float | None]:
        return {
            "scene_change_signal": self.scene_change_signal,
            "visual_difference_signal": self.visual_difference_signal,
            "face_layout_variation": self.face_layout_variation,
            "numeric_token_signal": self.numeric_token_signal,
            "punctuation_emphasis_signal": self.punctuation_emphasis_signal,
            "multi_scene_signal": self.multi_scene_signal,
        }


class CandidateDeduplicationDecision(Versioned):
    """One kept-or-duplicate decision. Hypotheses are not dropped without a record."""

    hypothesis_id: EntityId
    disposition: DedupDisposition
    duplicate_of_candidate_id: EntityId | None = None
    temporal_iou: float | None = Field(default=None, ge=0, le=1)
    containment_ratio: float | None = Field(default=None, ge=0, le=1)
    token_similarity: float | None = Field(default=None, ge=0, le=1)
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def duplicate_names_the_survivor(self) -> Self:
        for label, value in (
            ("temporal_iou", self.temporal_iou),
            ("containment_ratio", self.containment_ratio),
            ("token_similarity", self.token_similarity),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{label} must be finite")
        if self.disposition is DedupDisposition.DUPLICATE:
            if self.duplicate_of_candidate_id is None:
                raise ValueError("a duplicate decision must name the surviving hypothesis")
            if self.temporal_iou is None or self.containment_ratio is None or self.token_similarity is None:
                raise ValueError("a duplicate decision must record temporal and token measurements")
        if self.disposition is DedupDisposition.KEPT and self.duplicate_of_candidate_id is not None:
            raise ValueError("a kept decision does not name another survivor")
        return self


class CandidateFilterDecision(Versioned):
    """Compact audit row for a hypothesis that was not selected."""

    hypothesis_id: EntityId
    source_start_us: Microseconds
    source_end_us: Microseconds
    reason: CandidateFilterReason

    @model_validator(mode="after")
    def range_is_ordered(self) -> Self:
        if self.source_end_us <= self.source_start_us:
            raise ValueError("filter decision range must be positive")
        return self


class CandidateMiningSummary(Versioned):
    """Counts for one mining run. A shortfall under the soft target is not a failure."""

    raw_hypothesis_count: int = Field(ge=0)
    hard_filtered_count: int = Field(ge=0)
    scored_count: int = Field(ge=0)
    insufficient_evidence_count: int = Field(ge=0)
    pre_dedupe_excluded_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    eligible_distinct_count: int = Field(ge=0)
    output_cap_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    soft_target_min: int = Field(ge=0)
    max_candidates: int = Field(ge=1)
    below_soft_target: bool
    raw_hypothesis_cap_reached: bool = False
    mean_selected_duration_us: Microseconds | None = None
    shortest_selected_duration_us: Microseconds | None = None
    longest_selected_duration_us: Microseconds | None = None
    mean_quality_score: float | None = Field(default=None, ge=0, le=1)
    mean_edit_opportunity_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def aggregates_match_the_count(self) -> Self:
        for label, value in (
            ("mean_quality_score", self.mean_quality_score),
            ("mean_edit_opportunity_score", self.mean_edit_opportunity_score),
        ):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{label} must be finite")
        empty = self.selected_count == 0
        aggregates = (
            self.mean_selected_duration_us,
            self.shortest_selected_duration_us,
            self.longest_selected_duration_us,
            self.mean_quality_score,
            self.mean_edit_opportunity_score,
        )
        if empty and any(value is not None for value in aggregates):
            raise ValueError("a run with no selected candidates must leave duration and score means empty")
        if not empty and any(value is None for value in aggregates):
            raise ValueError("a run with selected candidates must record duration and score means")
        if self.below_soft_target != (self.selected_count < self.soft_target_min):
            raise ValueError("below_soft_target does not match the selected count")
        if self.selected_count > self.max_candidates:
            raise ValueError("selected_count exceeds max_candidates")
        return self


class CandidateMiningDocument(Versioned):
    """One immutable candidate-mining run for one source."""

    mining_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    created_at: AwareDatetime
    canonical_duration_us: Microseconds
    source_sha256: str = Field(pattern=_SHA)
    transcript_id: EntityId
    transcript_sha256: str = Field(pattern=_SHA)
    transcript_job_id: EntityId
    transcript_recipe_name: str = Field(min_length=1, max_length=80)
    transcript_recipe_version: str = Field(min_length=1, max_length=40)
    transcript_alignment: Literal["approximate"] = "approximate"
    transcript_timing_quality: Literal["provisional"] = "provisional"
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    visual_job_id: EntityId
    visual_recipe_name: str = Field(min_length=1, max_length=80)
    visual_recipe_version: str = Field(min_length=1, max_length=40)
    candidate_input_sha256: str = Field(pattern=_SHA)
    recipe_name: Literal["candidate-mining"] = "candidate-mining"
    recipe_version: Literal["1"] = "1"
    boundary_timing_quality: Literal["provisional"] = "provisional"
    profile: CandidateMiningProfile
    profile_fingerprint: str = Field(pattern=_SHA)
    window_algorithm_version: Literal["window-v1"] = "window-v1"
    tokenizer_version: Literal["unicode-regex-v1"] = "unicode-regex-v1"
    scoring_version: Literal["quality-edit-v1"] = "quality-edit-v1"
    dedupe_version: Literal["temporal-jaccard-v1"] = "temporal-jaccard-v1"
    candidates: list[CandidateClip] = Field(default_factory=list)
    evidence_bundles: list[CandidateEvidenceBundle] = Field(default_factory=list)
    score_breakdowns: list[CandidateScoreBreakdown] = Field(default_factory=list)
    dedupe_decisions: list[CandidateDeduplicationDecision] = Field(default_factory=list)
    filter_decisions: list[CandidateFilterDecision] = Field(default_factory=list)
    summary: CandidateMiningSummary
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def run_is_consistent(self) -> Self:
        if self.canonical_duration_us <= 0:
            raise ValueError("canonical_duration_us must be greater than 0")
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("candidate mining provenance must include source_asset_id")
        if self.provenance.inputs_sha256 != self.candidate_input_sha256:
            raise ValueError("provenance input digest must be the combined candidate input digest")
        if self.profile.fingerprint() != self.profile_fingerprint:
            raise ValueError("profile fingerprint does not match the stored profile")
        if self.profile.window_algorithm_version != self.window_algorithm_version:
            raise ValueError("window algorithm version does not match the profile")
        if self.profile.tokenizer_version != self.tokenizer_version:
            raise ValueError("tokenizer version does not match the profile")
        if self.profile.scoring_version != self.scoring_version:
            raise ValueError("scoring version does not match the profile")
        if self.profile.dedupe_version != self.dedupe_version:
            raise ValueError("dedupe version does not match the profile")
        _check_candidates(self)
        _check_summary_counts(self)
        return self


class CandidateMiningCacheRecord(Versioned):
    """Sidecar for the current candidate set. ``created_at`` is not identity."""

    project_id: EntityId
    source_asset_id: EntityId
    mining_id: EntityId
    job_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    transcript_id: EntityId
    transcript_sha256: str = Field(pattern=_SHA)
    visual_analysis_id: EntityId
    visual_analysis_sha256: str = Field(pattern=_SHA)
    candidate_input_sha256: str = Field(pattern=_SHA)
    recipe_name: Literal["candidate-mining"] = "candidate-mining"
    recipe_version: Literal["1"] = "1"
    profile_fingerprint: str = Field(pattern=_SHA)
    window_algorithm_version: Literal["window-v1"] = "window-v1"
    tokenizer_version: Literal["unicode-regex-v1"] = "unicode-regex-v1"
    scoring_version: Literal["quality-edit-v1"] = "quality-edit-v1"
    dedupe_version: Literal["temporal-jaccard-v1"] = "temporal-jaccard-v1"
    candidate_artifact_sha256: str = Field(pattern=_SHA)
    candidate_artifact_size: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    validation_status: Literal["passed"]
    created_at: AwareDatetime


def _require_weight_total(pairs: Sequence[tuple[str, float]]) -> None:
    total = sum((Decimal(str(weight)) for _name, weight in pairs), start=Decimal(0))
    if total.quantize(_UNIT, rounding=ROUND_HALF_UP) != Decimal(1):
        raise ValueError("score weights must sum to 1")
    for name, weight in pairs:
        if not math.isfinite(weight) or weight < 0:
            raise ValueError(f"{name} weight must be a finite non-negative number")


def _check_candidates(document: CandidateMiningDocument) -> None:
    ids = [item.candidate_id for item in document.candidates]
    if len(set(ids)) != len(ids):
        raise ValueError("candidate ids must be unique")
    bundles = {item.candidate_id: item for item in document.evidence_bundles}
    scores = {item.candidate_id: item for item in document.score_breakdowns}
    if len(bundles) != len(document.evidence_bundles) or len(scores) != len(document.score_breakdowns):
        raise ValueError("evidence bundles and score breakdowns must be one per candidate")
    if set(bundles) != set(ids) or set(scores) != set(ids):
        raise ValueError("every candidate needs one evidence bundle and one score breakdown")
    for candidate in document.candidates:
        if candidate.project_id != document.project_id or candidate.source_asset_id != document.source_asset_id:
            raise ValueError("candidate project or source does not match the mining document")
        if candidate.provenance.job_id != document.provenance.job_id:
            raise ValueError("candidate provenance job must be the candidate mining job")
        if candidate.provenance.inputs_sha256 != document.candidate_input_sha256:
            raise ValueError("candidate provenance input digest must be the combined input digest")
        if candidate.status.value != "ready_for_review":
            raise ValueError("selected candidates are ready_for_review")
        if not is_compliance_cleared(candidate.compliance):
            raise ValueError("selected candidates must pass every Round 5 compliance rule")
        rule_ids = [item.rule_id for item in candidate.compliance]
        if rule_ids != list(_ROUND_RULES):
            raise ValueError("selected candidates must record the Round 5 compliance rules in order")
        if any(item.status is not ComplianceStatus.PASS for item in candidate.compliance):
            raise ValueError("a failing compliance result cannot be ready_for_review")
        segments = candidate.time_map.segments
        if len(segments) != 1:
            raise ValueError("Round 5 candidates use exactly one source range")
        segment = segments[0]
        bundle = bundles[candidate.candidate_id]
        if segment.source_start_us != bundle.source_start_us or segment.source_end_us != bundle.source_end_us:
            raise ValueError("time map range must equal the evidence bundle range")
        if bundle.source_end_us > document.canonical_duration_us or bundle.source_start_us < 0:
            raise ValueError("candidate range is outside the canonical source duration")
        output = segment.source_end_us - segment.source_start_us
        if candidate.time_map.to_time_map().total_output_duration() != output:
            raise ValueError("candidate output duration must equal the source range")
        kinds = {item.kind.value for item in candidate.evidence}
        if "transcript" not in kinds or "visual" not in kinds:
            raise ValueError("selected candidates need transcript evidence and visual evidence")
        for evidence in candidate.evidence:
            if (
                evidence.source_start_us != bundle.source_start_us
                or evidence.source_end_us != bundle.source_end_us
            ):
                raise ValueError("candidate evidence ranges must equal the candidate interval")
        breakdown = scores[candidate.candidate_id]
        if candidate.creative_score != breakdown.quality_score:
            raise ValueError("creative_score must equal the quality score")
        if breakdown.scoring_version != document.scoring_version:
            raise ValueError("score breakdown version does not match the document")
        if breakdown.quality_weight_coverage < document.profile.minimum_quality_coverage:
            raise ValueError("selected candidate is below the minimum quality evidence coverage")
        expected_quality, expected_coverage = weighted_score(
            document.profile.quality_weights.pairs(breakdown.quality_values())
        )
        if (
            expected_quality != breakdown.quality_score
            or expected_coverage != breakdown.quality_weight_coverage
        ):
            raise ValueError("quality score does not match the stored quality features")
        expected_edit, expected_edit_coverage = weighted_score(
            document.profile.edit_weights.pairs(breakdown.edit_values())
        )
        if (
            expected_edit != breakdown.edit_opportunity_score
            or expected_edit_coverage != breakdown.edit_opportunity_weight_coverage
        ):
            raise ValueError("edit opportunity score does not match the stored edit features")
        _reject_speaker_claims(evidence.detail for evidence in candidate.evidence)
        _reject_speaker_claims((bundle.transcript_excerpt,))


def _check_summary_counts(document: CandidateMiningDocument) -> None:
    summary = document.summary
    if summary.selected_count != len(document.candidates):
        raise ValueError("summary selected_count does not match the candidates")
    if summary.max_candidates != document.profile.max_candidates:
        raise ValueError("summary max_candidates does not match the profile")
    if summary.soft_target_min != document.profile.soft_target_min:
        raise ValueError("summary soft target does not match the profile")
    if summary.raw_hypothesis_count > document.profile.maximum_raw_hypotheses:
        raise ValueError("raw hypothesis count exceeds the profile cap")
    durations = [
        item.time_map.segments[0].source_end_us - item.time_map.segments[0].source_start_us
        for item in document.candidates
    ]
    if summary.shortest_selected_duration_us != (min(durations) if durations else None):
        raise ValueError("summary shortest duration does not match")
    if summary.longest_selected_duration_us != (max(durations) if durations else None):
        raise ValueError("summary longest duration does not match")
    if summary.mean_selected_duration_us != aggregate_duration_us(durations):
        raise ValueError("summary mean duration does not match")
    qualities = [item.creative_score for item in document.candidates if item.creative_score is not None]
    if len(qualities) != len(document.candidates):
        raise ValueError("every selected candidate needs a quality score")
    ordered_edits = [
        next(
            score.edit_opportunity_score
            for score in document.score_breakdowns
            if score.candidate_id == item.candidate_id
        )
        for item in document.candidates
    ]
    if summary.mean_quality_score != aggregate_unit_score(qualities):
        raise ValueError("summary mean quality score does not match")
    if summary.mean_edit_opportunity_score != aggregate_unit_score(ordered_edits):
        raise ValueError("summary mean edit opportunity score does not match")
    parts = (
        summary.hard_filtered_count
        + summary.insufficient_evidence_count
        + summary.pre_dedupe_excluded_count
        + summary.duplicate_count
        + summary.eligible_distinct_count
    )
    if parts != summary.raw_hypothesis_count or summary.scored_count != (
        summary.insufficient_evidence_count
        + summary.pre_dedupe_excluded_count
        + summary.duplicate_count
        + summary.eligible_distinct_count
    ):
        raise ValueError("summary counts do not add up to the raw hypotheses")
    if summary.eligible_distinct_count != summary.selected_count + summary.output_cap_count:
        raise ValueError("selected and output-capped candidates must equal the distinct eligible count")
    if summary.duplicate_count != sum(
        1 for item in document.dedupe_decisions if item.disposition is DedupDisposition.DUPLICATE
    ):
        raise ValueError("summary duplicate_count does not match the dedupe audit")
    kept = sum(1 for item in document.dedupe_decisions if item.disposition is DedupDisposition.KEPT)
    if kept != summary.eligible_distinct_count:
        raise ValueError("kept dedupe decisions must equal the distinct eligible count")
    reasons = [item.reason for item in document.filter_decisions]
    if reasons.count(CandidateFilterReason.OUTPUT_CAP) != summary.output_cap_count:
        raise ValueError("output cap filter rows do not match the summary")
    if reasons.count(CandidateFilterReason.INSUFFICIENT_SCORE_COVERAGE) != summary.insufficient_evidence_count:
        raise ValueError("insufficient evidence filter rows do not match the summary")
    if reasons.count(CandidateFilterReason.PRE_DEDUPE_POOL) != summary.pre_dedupe_excluded_count:
        raise ValueError("pre-dedupe filter rows do not match the summary")
    if reasons.count(CandidateFilterReason.DUPLICATE) != summary.duplicate_count:
        raise ValueError("duplicate filter rows do not match the summary")
    hard_reasons = {
        CandidateFilterReason.TOO_SHORT,
        CandidateFilterReason.TOO_LONG,
        CandidateFilterReason.TOO_FEW_WORDS,
        CandidateFilterReason.NO_TRANSCRIPT_EVIDENCE,
        CandidateFilterReason.NO_VISUAL_EVIDENCE,
        CandidateFilterReason.RANGE_OUTSIDE_SOURCE,
        CandidateFilterReason.EMPTY_OR_REVERSED,
    }
    if sum(1 for reason in reasons if reason in hard_reasons) != summary.hard_filtered_count:
        raise ValueError("hard filter rows do not match the summary")


def _reject_speaker_claims(details: Iterable[str]) -> None:
    banned = (
        "host speaking",
        "guest speaking",
        "main speaker",
        "speaker face",
        "active_speaker",
        "speaker_score",
        "speaker_probability",
        "likely_speaker",
    )
    for detail in details:
        lowered = detail.casefold()
        for phrase in banned:
            if phrase in lowered:
                raise ValueError(f"candidate evidence must not claim speaker identity ({phrase})")
