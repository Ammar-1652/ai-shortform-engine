"""Deterministic provisional captions. Text is copied from the transcript.

Word mode chunks real ``TranscriptWord`` times. Segment mode uses the segment
interval when that segment has no words. No word time is invented, and the
text is not rewritten.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from itertools import pairwise

from clipforge.errors import MediaError
from clipforge.preview.timing import frame_at_or_after
from clipforge.schemas.candidates import CandidateEvidenceBundle
from clipforge.schemas.media import Transcript, TranscriptSegment, TranscriptWord
from clipforge.schemas.preview import RoughCaptionCue, RoughCaptionWord, RoughPreviewProfile
from clipforge.timeline import TimeMap

_PUNCT = frozenset(".?!…\u3002\uff1f\uff01:")


@dataclass(frozen=True, slots=True)
class _Piece:
    text: str
    source_start_us: int
    source_end_us: int
    segment_ids: tuple[str, ...]
    word_ids: tuple[str, ...]
    words: tuple[TranscriptWord, ...] = ()


def plan_captions(
    transcript: Transcript,
    bundle: CandidateEvidenceBundle,
    time_map: TimeMap,
    *,
    profile: RoughPreviewProfile,
    frame_count: int,
    mining_id: str,
) -> list[RoughCaptionCue]:
    """Build cues for one candidate. Overlapping cues are an error, not a silent repair."""
    pieces = _pieces(transcript, bundle, profile)
    cues: list[RoughCaptionCue] = []
    for index, piece in enumerate(pieces):
        source_start = max(piece.source_start_us, bundle.source_start_us)
        source_end = min(piece.source_end_us, bundle.source_end_us)
        if source_end <= source_start:
            continue
        output_start = time_map.source_to_output(source_start)
        output_end = time_map.source_to_output(source_end)
        if output_end <= output_start:
            continue
        start_frame = frame_at_or_after(output_start, frame_count)
        end_frame = frame_at_or_after(output_end, frame_count)
        if start_frame >= end_frame:
            continue
        cue_words: list[RoughCaptionWord] = []
        for word in piece.words:
            if word.start_us < bundle.source_start_us or word.end_us > bundle.source_end_us:
                continue
            word_start = time_map.source_to_output(word.start_us)
            word_end = time_map.source_to_output(word.end_us)
            word_start_frame = frame_at_or_after(word_start, frame_count)
            word_end_frame = frame_at_or_after(word_end, frame_count)
            if word_end <= word_start or word_end_frame <= word_start_frame:
                continue
            cue_words.append(
                RoughCaptionWord(
                    word_id=word.word_id,
                    text=word.text,
                    output_start_us=word_start,
                    output_end_us=word_end,
                    output_start_frame=word_start_frame,
                    output_end_frame_exclusive=word_end_frame,
                )
            )
        cues.append(
            RoughCaptionCue(
                cue_id=_cue_id(mining_id, bundle.candidate_id, index, source_start, source_end),
                text=piece.text,
                transcript_segment_ids=list(piece.segment_ids),
                transcript_word_ids=list(piece.word_ids),
                source_start_us=source_start,
                source_end_us=source_end,
                output_start_us=output_start,
                output_end_us=output_end,
                output_start_frame=start_frame,
                output_end_frame_exclusive=end_frame,
                words=cue_words,
            )
        )
    _reject_overlap(cues)
    return cues


def _pieces(
    transcript: Transcript,
    bundle: CandidateEvidenceBundle,
    profile: RoughPreviewProfile,
) -> list[_Piece]:
    segments = {segment.segment_id: segment for segment in transcript.segments}
    words = {word.word_id: word for segment in transcript.segments for word in segment.words}
    chosen: list[_Piece] = []
    if bundle.transcript_word_ids:
        ordered = _words_in_order(transcript, bundle, words)
        chosen.extend(_chunk_words(ordered, profile))
        word_segments = {segment_id for _word, segment_id in ordered}
        for segment_id in bundle.transcript_segment_ids:
            if segment_id in word_segments:
                continue
            segment = segments.get(segment_id)
            if segment is None or segment.words:
                continue
            piece = _segment_piece(segment, bundle)
            if piece is not None:
                chosen.append(piece)
    else:
        # No referenced word ids. Segment text and segment timing only.
        # Words that happen to sit on the segment are not harvested.
        for segment_id in bundle.transcript_segment_ids:
            segment = segments.get(segment_id)
            if segment is None:
                raise MediaError(f"candidate caption planning references unknown segment {segment_id}")
            piece = _segment_piece(segment, bundle)
            if piece is not None:
                chosen.append(piece)
    chosen.sort(key=lambda item: (item.source_start_us, item.source_end_us, item.text))
    return chosen


def _words_in_order(
    transcript: Transcript,
    bundle: CandidateEvidenceBundle,
    words: dict[str, TranscriptWord],
) -> list[tuple[TranscriptWord, str]]:
    wanted = set(bundle.transcript_word_ids)
    ordered: list[tuple[TranscriptWord, str]] = []
    for segment in transcript.segments:
        if segment.segment_id not in bundle.transcript_segment_ids and not any(
            word.word_id in wanted for word in segment.words
        ):
            continue
        for word in segment.words:
            if word.word_id not in wanted:
                continue
            if word.end_us <= bundle.source_start_us or word.start_us >= bundle.source_end_us:
                continue
            ordered.append((word, segment.segment_id))
    missing = wanted - {word.word_id for word, _segment in ordered}
    # Words that do not overlap the candidate are ignored. Unknown ids still fail.
    unknown = [word_id for word_id in bundle.transcript_word_ids if word_id not in words]
    if unknown:
        raise MediaError(
            "candidate caption planning references unknown transcript words: " + ", ".join(unknown)
        )
    del missing
    return ordered


def _chunk_words(
    ordered: list[tuple[TranscriptWord, str]],
    profile: RoughPreviewProfile,
) -> list[_Piece]:
    chunks: list[_Piece] = []
    current: list[tuple[TranscriptWord, str]] = []
    for word, segment_id in ordered:
        if current and word.start_us - current[-1][0].end_us > profile.max_caption_gap_us:
            chunks.append(_from_words(current))
            current = []
        if current and _would_exceed(current, word, profile):
            chunks.append(_from_words(current))
            current = []
        current.append((word, segment_id))
        if _ends_with_punctuation(word.text):
            chunks.append(_from_words(current))
            current = []
    if current:
        chunks.append(_from_words(current))
    return chunks


def _would_exceed(
    current: list[tuple[TranscriptWord, str]],
    word: TranscriptWord,
    profile: RoughPreviewProfile,
) -> bool:
    if len(current) >= profile.max_caption_words:
        return True
    text = _join([item[0] for item in current] + [word])
    if len(text) > profile.max_caption_code_points and current:
        return True
    start = current[0][0].start_us
    return word.end_us - start > profile.max_caption_duration_us


def _from_words(words: list[tuple[TranscriptWord, str]]) -> _Piece:
    return _Piece(
        text=_join([word for word, _segment in words]),
        source_start_us=words[0][0].start_us,
        source_end_us=words[-1][0].end_us,
        segment_ids=tuple(dict.fromkeys(segment for _word, segment in words)),
        word_ids=tuple(word.word_id for word, _segment in words),
        words=tuple(word for word, _segment in words),
    )


def _segment_piece(segment: TranscriptSegment, bundle: CandidateEvidenceBundle) -> _Piece | None:
    start = max(segment.start_us, bundle.source_start_us)
    end = min(segment.end_us, bundle.source_end_us)
    if end <= start:
        return None
    text = " ".join(segment.text.split())
    if not text:
        return None
    return _Piece(
        text=text[:300],
        source_start_us=start,
        source_end_us=end,
        segment_ids=(segment.segment_id,),
        word_ids=(),
    )


def _join(words: list[TranscriptWord]) -> str:
    return "".join(word.text for word in words).strip()


def _ends_with_punctuation(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in _PUNCT


def _reject_overlap(cues: list[RoughCaptionCue]) -> None:
    ordered = sorted(cues, key=lambda cue: (cue.source_start_us, cue.source_end_us, cue.cue_id))
    for previous, current in pairwise(ordered):
        if current.source_start_us < previous.source_end_us:
            raise MediaError(
                "provisional captions overlap in source time and were not repaired. "
                f"{previous.cue_id} ends at {previous.source_end_us} us and "
                f"{current.cue_id} starts at {current.source_start_us} us. "
                "Touching half-open boundaries are valid. Overlap is not."
            )


def _cue_id(mining_id: str, candidate_id: str, index: int, start: int, end: int) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"clipforge-preview|{mining_id}|{candidate_id}|cue|{index}|{start}|{end}",
        )
    )
