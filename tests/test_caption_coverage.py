import pytest

from clipforge.errors import MediaError
from clipforge.hero.captions import validate_caption_word_coverage
from clipforge.schemas.advanced import CaptionWordTiming
from clipforge.schemas.hero import AlignedWord


def _word(index: int, start: int, end: int) -> AlignedWord:
    return AlignedWord(
        word_id=f"word-{index}",
        candidate_id="candidate-1",
        text=f" word{index}",
        source_start_us=start,
        source_end_us=end,
        output_start_us=start,
        output_end_us=end,
        output_start_frame=start * 30 // 1_000_000,
        output_end_frame_exclusive=(end * 30 + 999_999) // 1_000_000,
    )


def _caption(word: AlignedWord) -> CaptionWordTiming:
    return CaptionWordTiming(
        word_id=word.word_id,
        text=word.text,
        output_start_us=word.output_start_us,
        output_end_us=word.output_end_us,
        output_start_frame=word.output_start_frame,
        output_end_frame_exclusive=word.output_end_frame_exclusive,
    )


def test_caption_coverage_requires_every_forced_word() -> None:
    words = [_word(0, 0, 500_000), _word(1, 500_000, 1_000_000)]
    with pytest.raises(MediaError, match="missing=word-1"):
        validate_caption_word_coverage(words, [_caption(words[0])])


def test_caption_coverage_rejects_duplicate_word_ids() -> None:
    words = [_word(0, 0, 500_000), _word(1, 500_000, 1_000_000)]
    with pytest.raises(MediaError, match="duplicate"):
        validate_caption_word_coverage(words, [_caption(words[0]), _caption(words[0])])


def test_caption_coverage_accepts_ordered_forced_words() -> None:
    words = [_word(0, 0, 500_000), _word(1, 500_000, 1_000_000)]
    validate_caption_word_coverage(words, [_caption(words[0]), _caption(words[1])])


@pytest.mark.parametrize(
    "changes",
    [
        {"output_start_us": 0},
        {"output_end_us": 900_000},
        {"output_start_frame": 1},
        {"output_end_frame_exclusive": 29},
    ],
)
def test_caption_preflight_rejects_widened_or_shifted_timing(changes: dict[str, int]) -> None:
    word = _word(0, 100_000, 500_000)
    caption = _caption(word).model_copy(update=changes)
    with pytest.raises(MediaError, match="does not match forced alignment"):
        validate_caption_word_coverage([word], [caption])


def test_caption_preflight_rejects_duplicate_alignment_ids() -> None:
    word = _word(0, 100_000, 500_000)
    with pytest.raises(MediaError, match="alignment contains a duplicate"):
        validate_caption_word_coverage([word, word], [_caption(word)])


def test_caption_coverage_rejects_equal_duration_word_distribution() -> None:
    """A phrase cannot replace forced timing with evenly split timing."""
    words = [_word(0, 0, 100_000), _word(1, 100_000, 1_000_000)]
    distributed = [
        _caption(words[0]).model_copy(update={"output_end_us": 500_000, "output_end_frame_exclusive": 15}),
        _caption(words[1]).model_copy(update={"output_start_us": 500_000, "output_start_frame": 15}),
    ]
    with pytest.raises(MediaError, match="does not match forced alignment"):
        validate_caption_word_coverage(words, distributed)


@pytest.mark.parametrize("update", [{"text": "different"}, {"verification_status": "correct"}])
def test_caption_coverage_rejects_changed_words_and_unearned_green_status(update: dict[str, str]) -> None:
    word = _word(0, 0, 500_000)
    with pytest.raises(MediaError, match="text or verification"):
        validate_caption_word_coverage([word], [_caption(word).model_copy(update=update)])
