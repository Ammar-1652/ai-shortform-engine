"""Provisional caption planning. Text is copied. Word times are not invented."""

from __future__ import annotations

import pytest

from clipforge.errors import MediaError
from clipforge.preview.captions import plan_captions
from clipforge.preview.timing import frame_at_or_after
from clipforge.schemas.candidates import CandidateEvidenceBundle
from clipforge.schemas.media import TranscriptSegment, TranscriptWord
from clipforge.schemas.preview import RoughPreviewProfile
from clipforge.timeline import TimeMap
from clipforge.timeline.framerate import FrameRate
from tests.candidate_support import segment, transcript_document

pytestmark = pytest.mark.preview

_SHA = "a" * 64
_PROFILE = RoughPreviewProfile()


def _word(index: int, text: str, start: int, end: int) -> TranscriptWord:
    return TranscriptWord(word_id=f"w-{index}", text=text, start_us=start, end_us=end, confidence=0.9)


def _transcript(pieces: list[TranscriptSegment], duration: int = 60_000_000):
    return transcript_document(pieces, duration, asr_sha256=_SHA)


def _bundle(
    start: int,
    end: int,
    *,
    segments: list[str],
    words: list[str] | None = None,
) -> CandidateEvidenceBundle:
    return CandidateEvidenceBundle(
        candidate_id="cand-1",
        transcript_segment_ids=segments,
        transcript_word_ids=words or [],
        transcript_excerpt="excerpt",
        transcript_start_us=start,
        transcript_end_us=end,
        visual_scene_ids=["scene-0"],
        source_start_us=start,
        source_end_us=end,
    )


def _plan(
    transcript,
    bundle: CandidateEvidenceBundle,
    *,
    source_start: int | None = None,
    source_end: int | None = None,
):
    start = bundle.source_start_us if source_start is None else source_start
    end = bundle.source_end_us if source_end is None else source_end
    time_map = TimeMap.from_source_ranges([(start, end)])
    frames = time_map.output_frame_count(FrameRate(30, 1))
    return (
        plan_captions(
            transcript,
            bundle,
            time_map,
            profile=_PROFILE,
            frame_count=frames,
            mining_id="mining-1",
        ),
        time_map,
        frames,
    )


def test_word_chunks_preserve_text_and_split_on_eight_words() -> None:
    tokens = [
        _word(index, token if index == 0 else f" {token}", index * 200_000, index * 200_000 + 100_000)
        for index, token in enumerate(["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"])
    ]
    span = TranscriptSegment(
        segment_id="seg-0", ordinal=0, start_us=0, end_us=2_000_000, text="ignored", words=tokens
    )
    transcript = _transcript([span])
    cues, _, _ = _plan(
        transcript, _bundle(0, 2_000_000, segments=["seg-0"], words=[item.word_id for item in tokens])
    )
    assert len(cues) == 2
    assert cues[0].text == "one two three four five six seven eight"
    assert cues[1].text == "nine"
    assert cues[0].transcript_word_ids == [f"w-{index}" for index in range(8)]


def test_code_point_boundary_splits_before_the_overflow() -> None:
    first = _word(0, "a" * 20, 0, 100_000)
    second = _word(1, " " + "b" * 21, 100_000, 200_000)
    third = _word(2, " c", 200_000, 300_000)
    span = TranscriptSegment(
        segment_id="seg-0", ordinal=0, start_us=0, end_us=1_000_000, text="x", words=[first, second, third]
    )
    cues, _, _ = _plan(
        _transcript([span]),
        _bundle(0, 1_000_000, segments=["seg-0"], words=["w-0", "w-1", "w-2"]),
    )
    assert cues[0].text == ("a" * 20) + " " + ("b" * 21)
    assert len(cues[0].text) == 42
    assert cues[1].text == "c"


def test_duration_and_gap_boundaries() -> None:
    held = [
        _word(0, "Hello", 0, 1_000_000),
        _word(1, " there", 1_000_000, 3_000_001),
    ]
    span = TranscriptSegment(segment_id="seg-0", ordinal=0, start_us=0, end_us=4_000_000, text="x", words=held)
    cues, _, _ = _plan(_transcript([span]), _bundle(0, 4_000_000, segments=["seg-0"], words=["w-0", "w-1"]))
    assert [cue.text for cue in cues] == ["Hello", "there"]

    touching = [
        _word(0, "Alpha", 0, 500_000),
        _word(1, " beta", 500_000 + 1_250_000, 2_000_000),
    ]
    span = TranscriptSegment(
        segment_id="seg-0", ordinal=0, start_us=0, end_us=3_000_000, text="x", words=touching
    )
    together, _, _ = _plan(_transcript([span]), _bundle(0, 3_000_000, segments=["seg-0"], words=["w-0", "w-1"]))
    assert len(together) == 1

    gapped = [
        _word(0, "Alpha", 0, 500_000),
        _word(1, " beta", 500_000 + 1_250_001, 2_000_000),
    ]
    span = TranscriptSegment(
        segment_id="seg-0", ordinal=0, start_us=0, end_us=3_000_000, text="x", words=gapped
    )
    split, _, _ = _plan(_transcript([span]), _bundle(0, 3_000_000, segments=["seg-0"], words=["w-0", "w-1"]))
    assert [cue.text for cue in split] == ["Alpha", "beta"]


def test_punctuation_unicode_and_numbers_are_preserved() -> None:
    tokens = [
        _word(0, "Hello", 0, 200_000),
        _word(1, " world.", 200_000, 400_000),
        _word(2, " Next", 400_000, 600_000),
    ]
    span = TranscriptSegment(
        segment_id="seg-0", ordinal=0, start_us=0, end_us=1_000_000, text="x", words=tokens
    )
    cues, _, _ = _plan(
        _transcript([span]),
        _bundle(0, 1_000_000, segments=["seg-0"], words=["w-0", "w-1", "w-2"]),
    )
    assert [cue.text for cue in cues] == ["Hello world.", "Next"]

    spoken = [
        _word(0, "café", 0, 200_000),
        _word(1, " 日本語", 200_000, 400_000),
        _word(2, " 42", 400_000, 600_000),
    ]
    span = TranscriptSegment(
        segment_id="seg-0", ordinal=0, start_us=0, end_us=1_000_000, text="x", words=spoken
    )
    kept, _, _ = _plan(
        _transcript([span]),
        _bundle(0, 1_000_000, segments=["seg-0"], words=["w-0", "w-1", "w-2"]),
    )
    assert kept[0].text == "café 日本語 42"
    assert kept[0].timing_quality == "provisional"


def test_unreferenced_words_stay_out_of_the_cue() -> None:
    spoken = segment(0, 0, 4_000_000, "one two three four five six seven eight nine ten.")
    assert len(spoken.words) >= 9
    cues, _, _ = _plan(
        _transcript([spoken]),
        _bundle(0, 4_000_000, segments=["seg-0"], words=[]),
    )
    assert len(cues) == 1
    assert cues[0].transcript_word_ids == []
    assert cues[0].text == "one two three four five six seven eight nine ten."
    assert cues[0].source_start_us == 0
    assert cues[0].source_end_us == 4_000_000


def test_segment_fallback_does_not_invent_word_times() -> None:
    bare = segment(0, 1_000_000, 3_000_000, "Only the segment text.", words=False)
    cues, _, _ = _plan(_transcript([bare]), _bundle(0, 4_000_000, segments=["seg-0"]))
    assert len(cues) == 1
    assert cues[0].text == "Only the segment text."
    assert cues[0].transcript_word_ids == []
    assert cues[0].source_start_us == 1_000_000
    assert cues[0].source_end_us == 3_000_000


def test_mixed_evidence_sorts_without_reordering_meaning() -> None:
    spoken = segment(0, 0, 1_000_000, "Words first please.")
    bare = segment(1, 2_000_000, 3_000_000, "Segment second.", words=False)
    cues, _, _ = _plan(
        _transcript([spoken, bare]),
        _bundle(0, 4_000_000, segments=["seg-0", "seg-1"], words=[word.word_id for word in spoken.words]),
    )
    assert cues[0].transcript_word_ids
    assert cues[-1].transcript_word_ids == []
    assert cues[-1].text == "Segment second."
    assert [cue.source_start_us for cue in cues] == sorted(cue.source_start_us for cue in cues)


def test_candidate_edges_clip_and_map_through_the_time_map() -> None:
    tokens = [
        _word(0, "before", 1_000_000, 1_500_000),
        _word(1, " inside", 2_200_000, 2_800_000),
        _word(2, " after", 3_500_000, 4_000_000),
    ]
    span = TranscriptSegment(
        segment_id="seg-0", ordinal=0, start_us=0, end_us=5_000_000, text="x", words=tokens
    )
    bundle = _bundle(2_000_000, 3_000_000, segments=["seg-0"], words=["w-0", "w-1", "w-2"])
    cues, time_map, frames = _plan(_transcript([span]), bundle)
    assert len(cues) == 1
    assert cues[0].text == "inside"
    assert cues[0].source_start_us == 2_200_000
    assert cues[0].source_end_us == 2_800_000
    assert cues[0].output_start_us == time_map.source_to_output(2_200_000)
    assert cues[0].output_end_us == time_map.source_to_output(2_800_000)
    assert cues[0].output_start_frame == frame_at_or_after(cues[0].output_start_us, frames)
    assert cues[0].output_start_frame > 0 or cues[0].output_start_us == 0

    edge = [_word(0, "ends", 5_000_000, 8_000_000)]
    span = TranscriptSegment(
        segment_id="seg-0", ordinal=0, start_us=5_000_000, end_us=8_000_000, text="x", words=edge
    )
    mapped = _bundle(5_000_000, 8_000_000, segments=["seg-0"], words=["w-0"])
    exact, time_map, frames = _plan(_transcript([span], 10_000_000), mapped)
    assert exact[0].output_end_us == time_map.total_output_duration()
    assert exact[0].output_end_frame_exclusive == frames


def test_frame_quantization_does_not_start_early() -> None:
    token = _word(0, "late", 1, 100_000)
    span = TranscriptSegment(
        segment_id="seg-0", ordinal=0, start_us=0, end_us=1_000_000, text="x", words=[token]
    )
    cues, _, _ = _plan(_transcript([span]), _bundle(0, 1_000_000, segments=["seg-0"], words=["w-0"]))
    assert cues[0].output_start_us == 1
    assert cues[0].output_start_frame == 1
    assert cues[0].output_end_frame_exclusive > cues[0].output_start_frame


def test_overlapping_cues_fail_and_repeat_runs_match() -> None:
    left = segment(0, 0, 2_000_000, "Alpha sentence.", words=False)
    right = segment(1, 1_000_000, 3_000_000, "Beta sentence.", words=False)
    transcript = _transcript([left, right])
    bundle = _bundle(0, 4_000_000, segments=["seg-0", "seg-1"])
    with pytest.raises(MediaError, match="overlap"):
        _plan(transcript, bundle)

    spoken = segment(0, 0, 2_000_000, "A stable sentence for the repeat.")
    stable = _transcript([spoken])
    stable_bundle = _bundle(0, 2_000_000, segments=["seg-0"], words=[word.word_id for word in spoken.words])
    first, _, _ = _plan(stable, stable_bundle)
    second, _, _ = _plan(stable, stable_bundle)
    assert [cue.model_dump() for cue in first] == [cue.model_dump() for cue in second]
