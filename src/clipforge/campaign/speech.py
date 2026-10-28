"""Source-bound Arabic display corrections and retained audible-speech checks."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from clipforge.campaign.quran import validate_tarteel_speech_review_ranges
from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import confine_work_path
from clipforge.hero.captions import validate_caption_word_coverage
from clipforge.media.hashing import sha256_file
from clipforge.schemas.advanced import TypographyEvent
from clipforge.schemas.campaign import TarteelArabicCorrectionDocument, TarteelSpeechReview
from clipforge.schemas.hero import ForcedAlignmentDocument
from clipforge.schemas.time import TimeMapDocument, digest_time_map

_EMOTION_EMOJIS = frozenset({"😂", "😮", "😢", "🤩", "👏", "❤️", "🔥", "✨", "😄"})


def load_arabic_corrections(
    root: Path,
    *,
    source_asset_id: str,
    candidate_id: str,
    source_sha256: str,
    raw_asr_sha256: str,
    transcript_sha256: str,
) -> tuple[TarteelArabicCorrectionDocument, str, Path] | None:
    """Find one immutable correction set; malformed or stale evidence raises."""
    root = root.resolve()
    base = root / "campaigns/Tarteel"
    confine_work_path(root, "campaigns/Tarteel", label="Arabic correction directory")
    matches: list[tuple[TarteelArabicCorrectionDocument, str, Path]] = []
    for lexical in sorted(base.rglob("arabic-corrections.json")):
        path = confine_work_path(root, lexical.relative_to(root).as_posix(), label="Arabic corrections")
        if not path.is_file():
            raise MediaError("Arabic corrections must be a regular file")
        try:
            document = TarteelArabicCorrectionDocument.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise MediaError(f"invalid Arabic correction sidecar: {exc}") from exc
        if (document.source_asset_id, document.candidate_id) != (source_asset_id, candidate_id):
            continue
        if (
            document.source_sha256 != source_sha256
            or document.raw_asr_sha256 != raw_asr_sha256
            or document.transcript_sha256 != transcript_sha256
        ):
            raise MediaError("Arabic correction evidence is stale against source/audio/transcript")
        matches.append((document, sha256_file(path), path))
    if len(matches) > 1:
        raise MediaError(f"multiple Arabic correction sets found for {candidate_id}")
    return matches[0] if matches else None


def apply_arabic_corrections(
    alignment: ForcedAlignmentDocument,
    document: TarteelArabicCorrectionDocument,
    *,
    source_sha256: str,
) -> ForcedAlignmentDocument:
    """Change reviewed display text, preserving ids, clocks, and live evidence."""
    if (
        document.source_asset_id != alignment.source_asset_id
        or document.candidate_id != alignment.candidate_id
        or document.source_sha256 != source_sha256
        or document.raw_asr_sha256 != alignment.asr_audio_sha256
        or document.transcript_sha256 != alignment.transcript_sha256
        or document.locale != alignment.locale
        or alignment.normalized_language != "ar"
    ):
        raise MediaError("Arabic corrections differ from the source alignment bindings")
    by_id = {word.word_id: word for word in alignment.words}
    updates: dict[str, str] = {}
    for correction in document.corrections:
        if correction.source_word_id in updates:
            raise MediaError("Arabic corrections repeat a forced word")
        word = by_id.get(correction.source_word_id)
        if word is None:
            raise MediaError("Arabic correction names an unknown forced word")
        if correction.locale != document.locale or correction.evidence_kind == "canonical_quran":
            raise MediaError("ordinary Arabic corrections cannot replace canonical Quran evidence")
        if not correction.original_text.strip() or correction.original_text.strip() != word.text.strip():
            raise MediaError("Arabic correction original text differs from the forced word")
        if not (
            correction.source_window_us[0] <= word.source_start_us
            and word.source_end_us <= correction.source_window_us[1]
        ):
            raise MediaError("Arabic correction window does not contain its forced word")
        text = correction.corrected_text.strip()
        if not text:
            raise MediaError("Arabic correction cannot erase a forced word")
        # ASR prefixes spaces to shaped words. Preserve that separator while
        # replacing only the reviewed lexical content.
        prefix = word.text[: len(word.text) - len(word.text.lstrip())]
        suffix = word.text[len(word.text.rstrip()) :]
        updates[word.word_id] = prefix + text + suffix
    return alignment.model_copy(
        update={
            "words": [
                word.model_copy(update={"text": updates[word.word_id]}) if word.word_id in updates else word
                for word in alignment.words
            ]
        }
    )


def _tokens(text: str) -> list[str]:
    # Uthmani marks and punctuation do not change lexical coverage. Do not
    # normalize different Arabic letters or guess a near match.
    plain = "".join(
        character if unicodedata.category(character)[0] in {"L", "N"} or character.isspace() else ""
        for character in unicodedata.normalize("NFC", text)
        if character != "\u0640"
    )
    return plain.split()


def retained_recitation(review: TarteelSpeechReview, time_map: TimeMapDocument) -> bool:
    """Require Quran evidence for retained recitation, including partial ranges."""
    return any(
        interval.kind == "recitation"
        and interval.source_start_us < segment.source_end_us
        and segment.source_start_us < interval.source_end_us
        for interval in review.intervals
        for segment in time_map.segments
    )


def validate_speech_captions(
    review: TarteelSpeechReview,
    *,
    alignment: ForcedAlignmentDocument,
    time_map: TimeMapDocument,
    captions: list[TypographyEvent],
) -> None:
    """Prove reviewed audible text is retained and rendered exactly once.

    A review covering the elapsed time is insufficient: an omitted laugh,
    invented sentence, or retained-but-excluded nasheed must fail before render.
    """
    if (
        review.source_asset_id != alignment.source_asset_id
        or review.candidate_id != alignment.candidate_id
        or review.raw_asr_sha256 != alignment.asr_audio_sha256
        or review.transcript_sha256 != alignment.transcript_sha256
        or review.locale != alignment.locale
        or alignment.time_map_sha256 != digest_time_map(time_map)
    ):
        raise MediaError("speech review differs from alignment identity, audio, locale, or TimeMap")
    validate_caption_word_coverage(alignment.words, (word for cue in captions for word in cue.words))
    for cue in captions:
        if _tokens(cue.text) != [token for word in cue.words for token in _tokens(word.text)]:
            raise MediaError("caption phrase text differs from its rendered forced words")
    ranges = [(segment.source_start_us, segment.source_end_us) for segment in time_map.segments]
    validate_tarteel_speech_review_ranges(review, ranges)
    accounted: set[str] = set()
    for interval in review.intervals:
        retained = [
            (start, end)
            for start, end in ranges
            if start < interval.source_end_us and interval.source_start_us < end
        ]
        if not retained:
            continue
        words = [
            word
            for word in alignment.words
            if interval.source_start_us < word.source_end_us and word.source_start_us < interval.source_end_us
        ]
        if interval.kind == "uncertain":
            raise MediaError("uncertain retained speech cannot certify caption coverage")
        if interval.kind == "silence":
            if words or interval.observed_text.strip():
                raise MediaError("reviewed silence contains forced words or observed speech")
            continue
        if interval.caption_decision != "captioned":
            raise MediaError("retained audible speech cannot be reviewed_excluded")
        if len(retained) != 1 or not (
            retained[0][0] <= interval.source_start_us and interval.source_end_us <= retained[0][1]
        ):
            raise MediaError("editorial cut splits a reviewed speech interval; review the retained phrase")
        if any(
            word.source_start_us < interval.source_start_us or word.source_end_us > interval.source_end_us
            for word in words
        ):
            raise MediaError("speech review boundary cuts through a forced word")
        displayed_tokens = [token for word in words for token in _tokens(word.text)]
        if not displayed_tokens or displayed_tokens != _tokens(interval.observed_text):
            raise MediaError(f"reviewed speech text differs from rendered forced words in {interval.span_id}")
        accounted.update(word.word_id for word in words)
    if accounted != {word.word_id for word in alignment.words}:
        raise MediaError("speech review does not account for every retained forced word")


def apply_speech_corrections(
    alignment: ForcedAlignmentDocument,
    review: TarteelSpeechReview,
    *,
    time_map: TimeMapDocument,
) -> ForcedAlignmentDocument:
    """Derive reviewed display words without mutating raw forced alignment."""
    if not review.corrections:
        return alignment
    by_id = {word.word_id: word for word in alignment.words}
    updates: dict[str, str] = {}
    mapped = time_map.to_time_map().segments
    for correction in review.corrections:
        words = [by_id.get(word_id) for word_id in correction.source_word_ids]
        if any(word is None for word in words):
            raise MediaError(f"speech correction names an unknown forced word: {correction.correction_id}")
        checked = [word for word in words if word is not None]
        if any(
            not (
                correction.source_window_us[0] <= word.source_start_us
                and word.source_end_us <= correction.source_window_us[1]
            )
            for word in checked
        ):
            raise MediaError(f"speech correction window does not contain its words: {correction.correction_id}")
        if not any(
            segment.source_start_us <= correction.source_window_us[0]
            and correction.source_window_us[1] <= segment.source_end_us
            for segment in mapped
        ):
            raise MediaError(f"speech correction crosses a retained TimeMap cut: {correction.correction_id}")
        original = " ".join(word.text.strip() for word in checked)
        if original != correction.original_text.strip():
            raise MediaError(f"speech correction original text differs: {correction.correction_id}")
        corrected_tokens = correction.corrected_text.strip().split()
        if len(corrected_tokens) != len(checked):
            raise MediaError(
                f"speech correction must preserve the number of forced words: {correction.correction_id}"
            )
        for word, token in zip(checked, corrected_tokens, strict=True):
            prefix = word.text[: len(word.text) - len(word.text.lstrip())]
            suffix = word.text[len(word.text.rstrip()) :]
            updates[word.word_id] = prefix + token + suffix
    return alignment.model_copy(
        update={
            "words": [
                word.model_copy(update={"text": updates[word.word_id]}) if word.word_id in updates else word
                for word in alignment.words
            ]
        }
    )


def apply_speech_review_emojis(
    review: TarteelSpeechReview,
    captions: list[TypographyEvent],
    *,
    time_map: TimeMapDocument,
) -> list[TypographyEvent]:
    """Attach source-clock emotion annotations to output-clock caption cues.

    Speech reviews are authored in source time while caption events are placed
    in output time. Mapping through the canonical TimeMap keeps annotations
    attached after jump cuts instead of accidentally comparing two clocks.
    """
    updated = list(captions)
    mapped = time_map.to_time_map()
    annotation_windows: list[tuple[str, int, int, str]] = [
        (item.annotation_id, item.source_window_us[0], item.source_window_us[1], item.emoji)
        for item in review.emotions
    ]
    if not annotation_windows:
        # Backward-compatible interpretation for existing review documents.
        for interval in review.intervals:
            emojis = [
                item
                for item in re.findall(r"😂|😮|😢|🤩|👏|❤️|🔥|✨|😄", interval.observed_text)
                if item in _EMOTION_EMOJIS
            ]
            if emojis:
                annotation_windows.append(
                    (interval.span_id, interval.source_start_us, interval.source_end_us, emojis[0])
                )
    for annotation_id, source_start_us, source_end_us, emoji in annotation_windows:
        output_ranges = [
            (
                segment.output_start_us
                + max(source_start_us, segment.source_start_us)
                - segment.source_start_us,
                segment.output_start_us + min(source_end_us, segment.source_end_us) - segment.source_start_us,
            )
            for segment in mapped.segments
            if segment.source_start_us < source_end_us and source_start_us < segment.source_end_us
        ]
        overlaps = [
            index
            for index, cue in enumerate(updated)
            if any(
                cue.interval.output_start_us < output_end and output_start < cue.interval.output_end_us
                for output_start, output_end in output_ranges
            )
        ]
        if not overlaps:
            raise MediaError(f"emotion annotation has no caption cue: {annotation_id}")
        for index in overlaps:
            if updated[index].emoji is not None and updated[index].emoji != emoji:
                raise MediaError(f"conflicting emotion emojis overlap caption cue: {updated[index].event_id}")
            updated[index] = updated[index].model_copy(update={"emoji": emoji})
    return updated
