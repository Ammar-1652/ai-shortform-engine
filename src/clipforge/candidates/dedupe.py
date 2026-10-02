"""Greedy temporal and token dedupe.

A pair is a near-duplicate when the shorter range is at least 80 percent
contained, or when temporal IoU and token-set Jaccard are both at least 0.70.
Adjacent ranges have an empty intersection, so they stay distinct. Empty token
sets are not treated as a match.

The survivor is the higher quality score, then higher quality coverage, then
higher boundary completeness, then the earlier start, then the shorter
duration, then the stable hypothesis id. Edit opportunity does not pick it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from clipforge.candidates.overlap import intersection_us, milli_threshold, ratio_at_least
from clipforge.schemas.candidates import CandidateMiningProfile, quantize_unit


@dataclass(frozen=True, slots=True)
class RankedHypothesis:
    hypothesis_id: str
    start_us: int
    end_us: int
    quality: float
    coverage: float
    boundary: float
    tokens: frozenset[str]


@dataclass(frozen=True, slots=True)
class DedupeHit:
    hypothesis_id: str
    kept: bool
    duplicate_of: str | None
    temporal_iou: float | None
    containment_ratio: float | None
    token_similarity: float | None
    reason: str


def dedupe_hypotheses(
    hypotheses: list[RankedHypothesis],
    profile: CandidateMiningProfile,
) -> list[DedupeHit]:
    """Walk hypotheses best-first and keep the first of each near-duplicate cluster."""
    ordered = sorted(hypotheses, key=_rank_key)
    kept: list[RankedHypothesis] = []
    decisions: list[DedupeHit] = []
    contain_milli = milli_threshold(profile.containment_threshold)
    iou_milli = milli_threshold(profile.temporal_iou_threshold)
    token_milli = milli_threshold(profile.token_similarity_threshold)
    for item in ordered:
        match: tuple[RankedHypothesis, float, float, float] | None = None
        for survivor in kept:
            duplicate, iou, containment, similarity = _compare(
                item,
                survivor,
                contain_milli=contain_milli,
                iou_milli=iou_milli,
                token_milli=token_milli,
            )
            if duplicate:
                match = (survivor, iou, containment, similarity)
                break
        if match is None:
            kept.append(item)
            decisions.append(
                DedupeHit(
                    hypothesis_id=item.hypothesis_id,
                    kept=True,
                    duplicate_of=None,
                    temporal_iou=None,
                    containment_ratio=None,
                    token_similarity=None,
                    reason="kept; no earlier higher-ranked near-duplicate",
                )
            )
            continue
        survivor, iou, containment, similarity = match
        decisions.append(
            DedupeHit(
                hypothesis_id=item.hypothesis_id,
                kept=False,
                duplicate_of=survivor.hypothesis_id,
                temporal_iou=quantize_unit(iou),
                containment_ratio=quantize_unit(containment),
                token_similarity=quantize_unit(similarity),
                reason=f"duplicate of {survivor.hypothesis_id}",
            )
        )
    return decisions


def _compare(
    left: RankedHypothesis,
    right: RankedHypothesis,
    *,
    contain_milli: int,
    iou_milli: int,
    token_milli: int,
) -> tuple[bool, float, float, float]:
    inter = intersection_us(left.start_us, left.end_us, right.start_us, right.end_us)
    duration_left = left.end_us - left.start_us
    duration_right = right.end_us - right.start_us
    union = duration_left + duration_right - inter
    shorter = min(duration_left, duration_right)
    iou = 0.0 if union <= 0 else inter / union
    containment = 0.0 if shorter <= 0 else inter / shorter
    similarity = _jaccard(left.tokens, right.tokens)
    contained = ratio_at_least(inter, shorter, contain_milli)
    temporal = ratio_at_least(inter, union, iou_milli)
    textual = _jaccard_at_least(left.tokens, right.tokens, token_milli)
    return contained or (temporal and textual), iou, containment, similarity


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    shared = len(left & right)
    total = len(left | right)
    if total <= 0:
        return 0.0
    return shared / total


def _jaccard_at_least(left: frozenset[str], right: frozenset[str], milli: int) -> bool:
    if not left or not right:
        return False
    shared = len(left & right)
    total = len(left | right)
    return ratio_at_least(shared, total, milli)


def _rank_key(item: RankedHypothesis) -> tuple[Decimal, Decimal, Decimal, int, int, str]:
    return (
        -Decimal(str(item.quality)),
        -Decimal(str(item.coverage)),
        -Decimal(str(item.boundary)),
        item.start_us,
        item.end_us - item.start_us,
        item.hypothesis_id,
    )
