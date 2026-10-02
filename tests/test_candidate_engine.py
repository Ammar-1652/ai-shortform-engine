"""Deterministic candidate mining without a database, a model, or a video file."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from clipforge.candidates.dedupe import RankedHypothesis, dedupe_hypotheses
from clipforge.candidates.engine import mine_documents, reset_stage_calls, stage_calls
from clipforge.candidates.overlap import intersection_us
from clipforge.candidates.scoring import duration_fit, hard_duration_reason
from clipforge.candidates.service import default_profile
from clipforge.candidates.tokenize import token_set
from clipforge.schemas.candidates import CandidateMiningProfile
from tests.candidate_support import segment, sha256_bytes, transcript_document, visual_document

pytestmark = pytest.mark.candidate

SOURCE_SHA = sha256_bytes(b"source")
PROXY_SHA = sha256_bytes(b"proxy")
ASR_SHA = sha256_bytes(b"asr")
WHEN = datetime(2026, 10, 2, 15, 0, tzinfo=UTC)


def _mine(
    transcript: object,
    visual: object,
    mining_id: str = "mine-1",
    profile: CandidateMiningProfile | None = None,
):
    active = profile or default_profile()
    return mine_documents(
        transcript=transcript,  # type: ignore[arg-type]
        visual=visual,  # type: ignore[arg-type]
        profile=active,
        mining_id=mining_id,
        created_at=WHEN,
        created_by="tester",
        job_id="job-candidate",
        source_sha256=SOURCE_SHA,
        transcript_sha256="a" * 64,
        visual_sha256="b" * 64,
        candidate_input_sha256="c" * 64,
        transcript_job_id="job-transcript",
        visual_job_id="job-visual",
        transcript_recipe_name="transcription",
        transcript_recipe_version="1",
        visual_recipe_name="visual-analysis",
        visual_recipe_version="1",
        tool_version="0.1.0",
    )


def test_duration_edges_use_microseconds() -> None:
    profile = default_profile()
    assert hard_duration_reason(7_999_999, profile) == "too_short"
    assert hard_duration_reason(8_000_000, profile) is None
    assert hard_duration_reason(65_000_000, profile) is None
    assert hard_duration_reason(65_000_001, profile) == "too_long"
    assert duration_fit(8_000_000, profile) == 0.0
    assert duration_fit(18_000_000, profile) == 1.0
    assert duration_fit(45_000_000, profile) == 1.0
    assert duration_fit(65_000_000, profile) == 0.0
    assert duration_fit(30_000_000, profile) == 1.0
    midpoint = duration_fit(13_000_000, profile)
    assert 0.0 < midpoint < 1.0


def test_adjacent_ranges_do_not_overlap() -> None:
    assert intersection_us(0, 10, 10, 20) == 0
    assert intersection_us(0, 10, 5, 15) == 5


def test_empty_token_sets_are_not_similarity_evidence() -> None:
    profile = default_profile()
    # Five seconds of overlap is below both temporal thresholds. Empty tokens add nothing.
    left = RankedHypothesis("h-a", 0, 20_000_000, 0.9, 1.0, 1.0, frozenset())
    right = RankedHypothesis("h-b", 15_000_000, 35_000_000, 0.8, 1.0, 1.0, frozenset())
    decisions = dedupe_hypotheses([left, right], profile)
    assert all(item.kept for item in decisions)
    identical = RankedHypothesis("h-c", 0, 20_000_000, 0.7, 1.0, 1.0, frozenset())
    contained = dedupe_hypotheses([left, identical], profile)
    duplicate = next(item for item in contained if not item.kept)
    assert duplicate.token_similarity == 0.0


def test_empty_transcript_selects_nothing() -> None:
    duration = 120_000_000
    transcript = transcript_document([], duration, asr_sha256=ASR_SHA)
    visual = visual_document(duration, [(0, duration)], source_sha256=SOURCE_SHA, proxy_sha256=PROXY_SHA)
    document = _mine(transcript, visual)
    assert document.summary.selected_count == 0
    assert document.candidates == []
    assert document.summary.mean_quality_score is None
    assert document.summary.below_soft_target is True


def test_short_source_is_not_padded_up_to_the_target() -> None:
    duration = 6_000_000
    transcript = transcript_document(
        [segment(0, 0, duration, "One two three four five words here.")],
        duration,
        asr_sha256=ASR_SHA,
    )
    visual = visual_document(duration, [(0, duration)], source_sha256=SOURCE_SHA, proxy_sha256=PROXY_SHA)
    document = _mine(transcript, visual)
    assert document.summary.selected_count == 0
    assert document.candidates == []


def test_seven_distinct_windows_stay_seven() -> None:
    pieces = []
    scenes = []
    cursor = 0
    for index in range(7):
        pieces.append(
            segment(
                index,
                cursor,
                cursor + 20_000_000,
                f"Point number {index} explains one concrete step in the walk.",
            )
        )
        scenes.append((cursor, cursor + 70_000_000 if index < 6 else cursor + 20_000_000))
        cursor += 70_000_000
    duration = cursor - 50_000_000
    # The last gap was not added. Rebuild a clean tiling instead.
    del scenes
    bounds = [(0, duration)]
    transcript = transcript_document(pieces, duration, asr_sha256=ASR_SHA)
    visual = visual_document(duration, bounds, source_sha256=SOURCE_SHA, proxy_sha256=PROXY_SHA)
    document = _mine(transcript, visual)
    assert document.summary.selected_count == 7
    assert document.summary.below_soft_target is True
    assert len(document.candidates) == 7


def test_rich_source_stops_at_max_candidates() -> None:
    pieces = []
    cursor = 0
    for index in range(30):
        pieces.append(
            segment(
                index,
                cursor,
                cursor + 20_000_000,
                f"Chapter {index} names one separate idea about rivers and tools.",
            )
        )
        cursor += 70_000_000
    duration = cursor - 50_000_000
    transcript = transcript_document(pieces, duration, asr_sha256=ASR_SHA)
    visual = visual_document(duration, [(0, duration)], source_sha256=SOURCE_SHA, proxy_sha256=PROXY_SHA)
    document = _mine(transcript, visual)
    assert document.summary.selected_count == 25
    assert document.summary.eligible_distinct_count >= 25
    assert document.summary.output_cap_count == document.summary.eligible_distinct_count - 25
    assert len({item.candidate_id for item in document.candidates}) == 25


def test_quality_orders_ahead_of_edit_opportunity() -> None:
    duration = 160_000_000
    calm = segment(
        0,
        0,
        30_000_000,
        "A clear sentence explains the whole method from start to finish.",
        confidence=0.99,
    )
    busy = segment(
        1,
        80_000_000,
        110_000_000,
        "Wait 12 percent? Then 4 more? And version 2.1 again?",
        confidence=0.2,
    )
    transcript = transcript_document([calm, busy], duration, asr_sha256=ASR_SHA)
    visual = visual_document(
        duration,
        [
            (0, 40_000_000),
            (40_000_000, 80_000_000),
            (80_000_000, 95_000_000),
            (95_000_000, 110_000_000),
            (110_000_000, duration),
        ],
        source_sha256=SOURCE_SHA,
        proxy_sha256=PROXY_SHA,
        faces=True,
        differences=[0.1, 0.2, 0.8, 0.9, 0.4],
    )
    document = _mine(transcript, visual)
    assert len(document.candidates) >= 2
    scores = {item.candidate_id: item for item in document.score_breakdowns}
    first = document.candidates[0]
    later = next(item for item in document.candidates if item.candidate_id != first.candidate_id)
    assert scores[first.candidate_id].quality_score >= scores[later.candidate_id].quality_score
    calm_id = next(
        item.candidate_id for item in document.evidence_bundles if "clear sentence" in item.transcript_excerpt
    )
    busy_id = next(
        item.candidate_id for item in document.evidence_bundles if "percent" in item.transcript_excerpt
    )
    assert scores[calm_id].quality_score > scores[busy_id].quality_score
    assert scores[busy_id].edit_opportunity_score > scores[calm_id].edit_opportunity_score
    assert document.candidates[0].candidate_id == calm_id


def test_repeat_is_identical_for_the_same_mining_id() -> None:
    duration = 90_000_000
    transcript = transcript_document(
        [segment(0, 0, 30_000_000, "People can walk through the steps without a script.")],
        duration,
        asr_sha256=ASR_SHA,
    )
    visual = visual_document(duration, [(0, duration)], source_sha256=SOURCE_SHA, proxy_sha256=PROXY_SHA)
    reset_stage_calls()
    first = _mine(transcript, visual)
    called = stage_calls()
    second = _mine(transcript, visual)
    assert called["windows"] == 1
    assert stage_calls()["windows"] == 2
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.candidates
    assert first.candidates[0].creative_score == first.score_breakdowns[0].quality_score
    assert len(first.candidates[0].time_map.segments) == 1
    assert first.boundary_timing_quality == "provisional"


def test_word_edges_and_missing_confidence_are_not_invented() -> None:
    duration = 60_000_000
    spoken = segment(0, 1_000_000, 21_000_000, "alpha bravo charlie delta echo foxtrot.")
    transcript = transcript_document([spoken], duration, asr_sha256=ASR_SHA)
    visual = visual_document(duration, [(0, duration)], source_sha256=SOURCE_SHA, proxy_sha256=PROXY_SHA)
    document = _mine(transcript, visual)
    clip = document.candidates[0]
    assert clip.time_map.segments[0].source_start_us == spoken.words[0].start_us - 250_000
    assert clip.time_map.segments[0].source_end_us == spoken.words[-1].end_us + 250_000
    bare = segment(
        0,
        1_000_000,
        21_000_000,
        "alpha bravo charlie delta echo foxtrot.",
        confidence=None,
        diagnostics=False,
    )
    bare_document = _mine(
        transcript_document([bare], duration, asr_sha256=ASR_SHA),
        visual,
        mining_id="mine-bare",
    )
    breakdown = bare_document.score_breakdowns[0]
    assert breakdown.transcript_reliability is None
    assert breakdown.quality_weight_coverage == 0.8
    assert 0.5 not in (
        breakdown.duration_fit,
        breakdown.speech_coverage,
        breakdown.boundary_completeness,
        breakdown.information_density,
        breakdown.opening_structure,
        breakdown.visual_evidence_coverage,
    )


def test_segment_without_words_uses_segment_edges() -> None:
    duration = 60_000_000
    spoken = segment(
        0,
        2_000_000,
        22_000_000,
        "alpha bravo charlie delta echo foxtrot.",
        words=False,
        diagnostics=False,
    )
    document = _mine(
        transcript_document([spoken], duration, asr_sha256=ASR_SHA),
        visual_document(duration, [(0, duration)], source_sha256=SOURCE_SHA, proxy_sha256=PROXY_SHA),
    )
    clip = document.candidates[0]
    assert clip.time_map.segments[0].source_start_us == 2_000_000
    assert clip.time_map.segments[0].source_end_us == 22_000_000
    assert document.evidence_bundles[0].transcript_word_ids == []
    assert document.score_breakdowns[0].transcript_reliability is None


def test_faces_do_not_change_quality_or_claim_a_speaker() -> None:
    duration = 60_000_000
    transcript = transcript_document(
        [segment(0, 0, 30_000_000, "A plain sentence carries five ordinary words today.")],
        duration,
        asr_sha256=ASR_SHA,
    )
    plain = visual_document(duration, [(0, duration)], source_sha256=SOURCE_SHA, proxy_sha256=PROXY_SHA)
    faced = visual_document(
        duration,
        [(0, duration)],
        source_sha256=SOURCE_SHA,
        proxy_sha256=PROXY_SHA,
        faces=True,
        analysis_id="analysis-faces",
    )
    without = _mine(transcript, plain, mining_id="mine-plain")
    with_faces = _mine(transcript, faced, mining_id="mine-faces")
    assert without.score_breakdowns[0].quality_score == with_faces.score_breakdowns[0].quality_score
    assert with_faces.evidence_bundles[0].face_observation_ids
    dumped = with_faces.model_dump_json()
    for phrase in ("active_speaker", "speaker_score", "main speaker", "host speaking", "speaker face"):
        assert phrase not in dumped
    assert "speaker_attribution" not in dumped


def test_failed_compliance_cannot_become_ready() -> None:
    from pydantic import ValidationError

    from clipforge.schemas.editorial import CandidateStatus
    from clipforge.schemas.governance import ComplianceResult, ComplianceStatus

    duration = 60_000_000
    document = _mine(
        transcript_document(
            [segment(0, 0, 30_000_000, "A plain sentence carries five ordinary words today.")],
            duration,
            asr_sha256=ASR_SHA,
        ),
        visual_document(duration, [(0, duration)], source_sha256=SOURCE_SHA, proxy_sha256=PROXY_SHA),
    )
    candidate = document.candidates[0]
    blocked = candidate.compliance[0].model_copy(update={"status": ComplianceStatus.FAIL})
    assert isinstance(blocked, ComplianceResult)
    with pytest.raises(ValidationError):
        candidate.model_copy(update={"compliance": [blocked, *candidate.compliance[1:]]}).model_validate(
            candidate.model_copy(update={"compliance": [blocked, *candidate.compliance[1:]]}).model_dump()
        )
    proposed = candidate.model_copy(update={"status": CandidateStatus.PROPOSED, "compliance": [blocked]})
    assert proposed.status is CandidateStatus.PROPOSED


def test_cross_source_documents_are_refused() -> None:
    from clipforge.errors import MediaError

    duration = 60_000_000
    transcript = transcript_document(
        [segment(0, 0, 30_000_000, "A plain sentence carries five ordinary words today.")],
        duration,
        asr_sha256=ASR_SHA,
    )
    visual = visual_document(
        duration,
        [(0, duration)],
        source_sha256=SOURCE_SHA,
        proxy_sha256=PROXY_SHA,
        source_id="source-2",
    )
    with pytest.raises(MediaError, match="different sources"):
        _mine(transcript, visual)


def test_token_punctuation_is_not_a_perfect_match() -> None:
    assert token_set("...") == frozenset()
    assert token_set("!!!") == frozenset()
    assert "café" in token_set("Café number 3")
    assert any(token[0].isdigit() or token[0] in "$€£¥" for token in token_set("$12 and 3.5%"))
