"""Hero captions from forced words. Provisional timings are not accepted."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from clipforge.errors import MediaError
from clipforge.schemas.advanced import CaptionWordTiming
from clipforge.schemas.editorial import CaptionCue, OutputInterval
from clipforge.schemas.hero import AlignedWord

_MAX_WORDS = 8
_MAX_CHARS = 42
_MAX_DURATION_US = 3_000_000
_MAX_GAP_US = 1_250_000
_PUNCT = frozenset(".?!…。？！:")  # noqa: RUF001


def hero_caption_cues(words: list[AlignedWord]) -> list[CaptionCue]:
    """Chunk forced words. Overlapping cues fail. Text is copied."""
    return [item.cue for item in hero_caption_pieces(words)]


def validate_caption_word_coverage(
    alignment_words: Iterable[AlignedWord],
    caption_words: Iterable[CaptionWordTiming],
) -> None:
    """Require a one-to-one mapping from forced words to rendered captions.

    A non-empty caption list is not coverage.  This check is intentionally
    independent of the renderer: it catches copied/manual inputs that omit a
    spoken span, duplicate a word id, or move a word outside its measured
    interval before a browser render is started.
    """
    expected = list(alignment_words)
    rendered = list(caption_words)
    if not expected:
        raise MediaError("caption coverage requires at least one forced word")
    if any(word.alignment_quality != "forced" for word in expected):
        raise MediaError("caption coverage refuses provisional alignment")
    expected_ids = [word.word_id for word in expected]
    if len(expected_ids) != len(set(expected_ids)):
        raise MediaError("caption coverage alignment contains a duplicate forced word id")
    rendered_ids = [word.word_id for word in rendered]
    if len(rendered_ids) != len(set(rendered_ids)):
        raise MediaError("caption coverage contains a duplicate forced word id")
    if rendered_ids != expected_ids:
        missing = [word_id for word_id in expected_ids if word_id not in set(rendered_ids)]
        extra = [word_id for word_id in rendered_ids if word_id not in set(expected_ids)]
        details = []
        if missing:
            details.append("missing=" + ",".join(missing[:5]))
        if extra:
            details.append("extra=" + ",".join(extra[:5]))
        raise MediaError("caption coverage does not match forced-word order (" + "; ".join(details) + ")")
    by_id = {word.word_id: word for word in expected}
    for item in rendered:
        source = by_id[item.word_id]
        if item.text.strip() != source.text.strip() or item.verification_status != source.verification_status:
            raise MediaError(f"caption word text or verification differs from forced alignment {item.word_id}")
        if (
            item.output_start_us != source.output_start_us
            or item.output_end_us != source.output_end_us
            or item.output_start_frame != source.output_start_frame
            or item.output_end_frame_exclusive != source.output_end_frame_exclusive
        ):
            raise MediaError(f"caption word interval does not match forced alignment {item.word_id}")


class HeroCaptionPiece:
    """One caption plus the source times and frames CaptionCue cannot store."""

    def __init__(
        self,
        cue: CaptionCue,
        *,
        source_start_us: int,
        source_end_us: int,
        output_start_frame: int,
        output_end_frame_exclusive: int,
        words: list[AlignedWord],
    ) -> None:
        self.cue = cue
        self.source_start_us = source_start_us
        self.source_end_us = source_end_us
        self.output_start_frame = output_start_frame
        self.output_end_frame_exclusive = output_end_frame_exclusive
        self.words = words


def hero_caption_pieces(
    words: list[AlignedWord],
    *,
    max_words: int = _MAX_WORDS,
    max_chars: int = _MAX_CHARS,
    max_duration_us: int = _MAX_DURATION_US,
) -> list[HeroCaptionPiece]:
    """Chunk forced words. Overlapping cues fail. Text is copied.

    The readable Quran preset uses a stricter word/character budget than the
    general caption path.  Keeping the budget here (rather than relying on a
    renderer's emergency font shrink) means the persisted cue itself remains a
    readable, single-line unit in every production renderer.
    """
    if max_words < 1 or max_chars < 1 or max_duration_us < 1:
        raise MediaError("Hero caption grouping limits must be positive")
    if not words:
        raise MediaError("Hero captions require forced words. Provisional captions were not used.")
    if any(word.alignment_quality != "forced" for word in words):
        raise MediaError("Hero captions refuse alignment that is not forced")
    chunks: list[list[AlignedWord]] = []
    current: list[AlignedWord] = []
    for word in words:
        # A caption must never survive an editorial TimeMap cut. Even when
        # source ranges are close together, the output picture/audio clock
        # changes owner at the segment boundary, so split the phrase first.
        if (
            current
            and current[-1].segment_index >= 0
            and word.segment_index >= 0
            and word.segment_index != current[-1].segment_index
        ):
            chunks.append(current)
            current = []
        if current and word.source_start_us - current[-1].source_end_us > _MAX_GAP_US:
            chunks.append(current)
            current = []
        if current and _exceeds(
            current,
            word,
            max_words=max_words,
            max_chars=max_chars,
            max_duration_us=max_duration_us,
        ):
            chunks.append(current)
            current = []
        current.append(word)
        if word.text.rstrip()[-1:] in _PUNCT:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    pieces: list[HeroCaptionPiece] = []
    previous_end = -1
    for index, chunk in enumerate(chunks):
        text = "".join(word.text for word in chunk).strip()
        start = chunk[0].output_start_us
        end = chunk[-1].output_end_us
        if end <= start:
            raise MediaError("Hero caption has no positive duration")
        if start < previous_end:
            raise MediaError("Hero captions overlap. They were not repaired.")
        previous_end = end
        cue = CaptionCue(
            cue_id=str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"clipforge-hero-caption|{chunk[0].candidate_id}|{index}|{start}|{end}",
                )
            ),
            interval=OutputInterval(output_start_us=start, output_end_us=end),
            text=text,
        )
        pieces.append(
            HeroCaptionPiece(
                cue,
                source_start_us=chunk[0].source_start_us,
                source_end_us=chunk[-1].source_end_us,
                output_start_frame=chunk[0].output_start_frame,
                output_end_frame_exclusive=chunk[-1].output_end_frame_exclusive,
                words=list(chunk),
            )
        )
    return pieces


def _exceeds(
    current: list[AlignedWord],
    word: AlignedWord,
    *,
    max_words: int = _MAX_WORDS,
    max_chars: int = _MAX_CHARS,
    max_duration_us: int = _MAX_DURATION_US,
) -> bool:
    if len(current) >= max_words:
        return True
    text = "".join(item.text for item in current) + word.text
    if len(text.strip()) > max_chars:
        return True
    return word.output_end_us - current[0].output_start_us > max_duration_us
