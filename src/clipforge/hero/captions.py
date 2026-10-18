"""Hero captions from forced words. Provisional timings are not accepted."""

from __future__ import annotations

import uuid

from clipforge.errors import MediaError
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


def hero_caption_pieces(words: list[AlignedWord]) -> list[HeroCaptionPiece]:
    """Chunk forced words. Overlapping cues fail. Text is copied."""
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
        if current and _exceeds(current, word):
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


def _exceeds(current: list[AlignedWord], word: AlignedWord) -> bool:
    if len(current) >= _MAX_WORDS:
        return True
    text = "".join(item.text for item in current) + word.text
    if len(text.strip()) > _MAX_CHARS:
        return True
    return word.output_end_us - current[0].output_start_us > _MAX_DURATION_US
