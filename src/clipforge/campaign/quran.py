"""Source-bound Quran caption evidence for the Tarteel campaign."""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from itertools import pairwise
from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.schemas.campaign import QuranCaptionReview, QuranVerificationPolicy, TarteelSpeechReview
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument

_ARABIC_LETTERS = re.compile(r"[\u0621-\u063A\u0641-\u064A\u0671\u067E\u0686\u06AF\u06CC]")


def reviewed_quran_font(root: Path, policy: QuranVerificationPolicy) -> Path:
    """Resolve the exact local font bound to the review, without a network fallback."""
    root = root.resolve()
    relative = Path(policy.font_relative_path)
    if relative.is_absolute() or ".." in relative.parts or "\\" in policy.font_relative_path:
        raise MediaError("Quran font must be a relative path inside the work root")
    font = _confined_regular_path(root, root / relative)
    if sha256_file(font) != policy.font_sha256:
        raise MediaError("Quran font hash changed after review")
    return font


def load_tarteel_quran_review(
    root: Path,
    *,
    source_asset_id: str,
    candidate_id: str,
    source_sha256: str = "",
    transcript_sha256: str = "",
) -> tuple[QuranCaptionReview, str, Path]:
    """Load exactly one verified Quran sidecar for a source/candidate.

    A sidecar is evidence only when it is a typed, regular file in the
    gitignored work root and its policy declares canonical-match verification
    or human pronunciation review. Missing or ambiguous evidence blocks
    Advanced Hero planning.
    """

    root = root.resolve()
    base = root / "campaigns" / "Tarteel"
    _confined_regular_path(root, base, directory=True)
    if not base.is_dir() or base.is_symlink():
        raise MediaError("Tarteel Quran review directory is missing")
    matches: list[tuple[QuranCaptionReview, str, Path]] = []
    for path in sorted(base.rglob("quran-caption-review.json")):
        _confined_regular_path(root, path)
        if path.is_symlink() or not path.is_file():
            raise MediaError("Tarteel Quran review sidecar must be a regular file")
        try:
            review = QuranCaptionReview.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            raise MediaError(f"invalid Tarteel Quran review sidecar {path.name}: {exc}") from exc
        if (review.source_asset_id, review.candidate_id) != (source_asset_id, candidate_id):
            continue
        if source_sha256 and source_sha256 != review.source_sha256:
            raise MediaError("Tarteel Quran text review is stale: source hash differs")
        if transcript_sha256 and transcript_sha256 != review.transcript_sha256:
            raise MediaError("Tarteel Quran text review is stale: transcript hash differs")
        if review.verification_policy.pronunciation_status not in {
            "human_reviewed",
            "canonical_match_verified",
        }:
            raise MediaError("Tarteel Quran review status must be canonical_match_verified or human_reviewed")
        if review.verification_policy.pronunciation_status == "canonical_match_verified":
            if not review.source_sha256 or not review.transcript_sha256:
                raise MediaError("automatic Quran text matching requires source and transcript hashes")
            validate_canonical_snapshot(root, review)
        if review.display_corrections:
            if not review.display_evidence_relative_path or not review.display_evidence_sha256:
                raise MediaError("Tarteel display corrections require hashed source subtitle evidence")
            evidence_path = _confined_regular_path(
                root,
                root / review.display_evidence_relative_path,
            )
            if sha256_file(evidence_path) != review.display_evidence_sha256:
                raise MediaError("Tarteel display evidence hash changed")
        matches.append((review, sha256_file(path), path))
    if len(matches) != 1:
        raise MediaError(
            f"Tarteel Advanced Hero requires exactly one reviewed Quran sidecar for {candidate_id}"
        )
    return matches[0]


def load_tarteel_speech_review(
    root: Path,
    *,
    source_asset_id: str,
    candidate_id: str,
    source_sha256: str = "",
    raw_asr_sha256: str = "",
    transcript_sha256: str = "",
) -> tuple[TarteelSpeechReview, str, Path] | None:
    """Load the optional reviewed audible-speech inventory for one candidate.

    Absence is deliberately distinct from an invalid sidecar: old drafts stay
    ``insufficient_evidence``, while a sidecar that names this candidate but
    is stale or malformed blocks the render instead of being ignored.
    """
    root = root.resolve()
    base = root / "campaigns" / "Tarteel"
    _confined_regular_path(root, base, directory=True)
    if not base.is_dir() or base.is_symlink():
        raise MediaError("Tarteel speech review directory is missing")
    matches: list[tuple[TarteelSpeechReview, str, Path]] = []
    for path in sorted(base.rglob("speech-review.json")):
        _confined_regular_path(root, path)
        if path.is_symlink() or not path.is_file():
            raise MediaError("Tarteel speech review sidecar must be a regular file")
        try:
            review = TarteelSpeechReview.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            raise MediaError(f"invalid Tarteel speech review sidecar {path.name}: {exc}") from exc
        if (review.source_asset_id, review.candidate_id) != (source_asset_id, candidate_id):
            continue
        if source_sha256 and review.source_sha256 != source_sha256:
            raise MediaError("Tarteel speech review is stale: source hash differs")
        if raw_asr_sha256 and review.raw_asr_sha256 != raw_asr_sha256:
            raise MediaError("Tarteel speech review is stale: ASR hash differs")
        if transcript_sha256 and review.transcript_sha256 != transcript_sha256:
            raise MediaError("Tarteel speech review is stale: transcript hash differs")
        matches.append((review, sha256_file(path), path))
    if len(matches) > 1:
        raise MediaError(f"multiple Tarteel speech review sidecars found for {candidate_id}")
    return matches[0] if matches else None


def validate_tarteel_speech_review_ranges(
    review: TarteelSpeechReview,
    source_ranges_us: list[tuple[int, int]],
) -> None:
    """Require the review to account for every retained source interval."""
    if not source_ranges_us:
        raise MediaError("Tarteel speech review requires selected source ranges")
    intervals = sorted(review.intervals, key=lambda item: item.source_start_us)
    for range_start, range_end in source_ranges_us:
        cursor = range_start
        for interval in intervals:
            if interval.source_end_us <= cursor:
                continue
            if interval.source_start_us >= range_end:
                break
            if interval.source_start_us > cursor:
                raise MediaError("Tarteel speech review has an uncovered selected source interval")
            cursor = max(cursor, interval.source_end_us)
            if cursor >= range_end:
                break
        if cursor < range_end:
            raise MediaError("Tarteel speech review does not cover the full selected source range")


def _confined_regular_path(root: Path, path: Path, *, directory: bool = False) -> Path:
    if not path.is_relative_to(root):
        raise MediaError("Quran evidence path escapes the work root")
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise MediaError("Quran evidence path cannot contain symlinks")
    if not (path.is_dir() if directory else path.is_file()):
        raise MediaError("Quran evidence path is missing or not a regular file/directory")
    return path


def validate_canonical_snapshot(root: Path, review: QuranCaptionReview) -> None:
    """Verify the saved official API response offline; never fetch during render."""
    canonical = review.canonical_source
    if not canonical.snapshot_relative_path or not canonical.snapshot_sha256:
        raise MediaError("automatic Quran text matching requires a hashed official canonical snapshot")
    path = _confined_regular_path(root.resolve(), root.resolve() / canonical.snapshot_relative_path)
    if sha256_file(path) != canonical.snapshot_sha256:
        raise MediaError("Quran canonical snapshot hash changed")
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        verses = snapshot["verses"]
        if not isinstance(verses, list):
            raise ValueError("verses must be a list")
        indexed = {row["verse_key"]: row["text_uthmani"] for row in verses}
        if len(indexed) != len(verses):
            raise ValueError("duplicate canonical verse keys")
        for offset, text in enumerate(canonical.text_uthmani):
            key = f"{canonical.surah}:{canonical.ayah_start + offset}"
            if indexed.get(key) != text:
                raise ValueError(f"canonical Uthmani text differs from official snapshot for {key}")
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise MediaError(f"invalid Quran canonical snapshot: {exc}") from exc


def canonicalize_quran_alignment(
    alignment: ForcedAlignmentDocument, review: QuranCaptionReview
) -> ForcedAlignmentDocument:
    """Replace ASR Quran spellings with canonical words while retaining timing.

    ASR is still used for word boundaries, but its display text is not trusted
    for Quran. Each mapped canonical token owns the source/output interval of
    the one-to-three observed words that best match it. The surrounding spoken
    dialogue remains unchanged. This function never downloads text at render
    time; the typed sidecar carries the reviewed canonical source.
    """

    if (alignment.source_asset_id, alignment.candidate_id) != (
        review.source_asset_id,
        review.candidate_id,
    ):
        raise MediaError("Quran caption mapping belongs to a different source or candidate")
    if review.transcript_sha256 and alignment.transcript_sha256 != review.transcript_sha256:
        raise MediaError("Quran caption mapping is stale against the alignment transcript")
    alignment = _apply_display_corrections(alignment, review)
    replacements: dict[str, AlignedWord] = {}
    used_ids: set[str] = set()
    for mapping in review.source_audio_mapping:
        observed = [
            word
            for word in alignment.words
            if word.source_start_us < mapping.source_end_us and mapping.source_start_us < word.source_end_us
        ]
        if not observed:
            raise MediaError(f"Quran ayah {mapping.ayah} has no aligned words in its reviewed source interval")
        if any(
            word.source_start_us < mapping.source_start_us or word.source_end_us > mapping.source_end_us
            for word in observed
        ):
            raise MediaError(f"Quran ayah {mapping.ayah} mapping cuts through an aligned word")
        if used_ids.intersection(word.word_id for word in observed):
            raise MediaError("Quran mapping reuses an aligned word in multiple ayahs")
        canonical_text = _canonical_text_for_ayah(review, mapping.ayah)
        canonical_words = _canonical_tokens(canonical_text)
        matched = _match_canonical_words(canonical_words, observed, mapping.ayah)
        for canonical_word, span in matched:
            first = span[0]
            last = span[-1]
            status = "unverified"
            statuses = {word.verification_status for word in span}
            if "incorrect" in statuses:
                status = "incorrect"
            elif review.verification_policy.pronunciation_status in {
                "canonical_match_verified",
                "human_reviewed",
            } and (
                review.verification_policy.pronunciation_status == "canonical_match_verified"
                or statuses == {"correct"}
            ):
                status = "correct"
            replacement = first.model_copy(
                update={
                    "text": f" {canonical_word}",
                    "source_start_us": first.source_start_us,
                    "source_end_us": last.source_end_us,
                    "output_start_us": first.output_start_us,
                    "output_end_us": last.output_end_us,
                    "output_start_frame": first.output_start_frame,
                    "output_end_frame_exclusive": last.output_end_frame_exclusive,
                    "verification_status": status,
                    "source_word_ids": [
                        word_id for word in span for word_id in (word.source_word_ids or [word.word_id])
                    ],
                }
            )
            replacements[first.word_id] = replacement
            used_ids.update(word.word_id for word in span)
    corrected: list[AlignedWord] = []
    for word in alignment.words:
        if word.word_id in replacements:
            corrected.append(replacements[word.word_id])
        elif word.word_id not in used_ids:
            corrected.append(word)
    if len(corrected) != len(alignment.words) - len(used_ids) + len(replacements):
        raise MediaError("Quran canonicalization lost an aligned word")
    return ForcedAlignmentDocument.model_validate({**alignment.model_dump(), "words": corrected})


def quran_review_for_alignment(
    review: QuranCaptionReview,
    *,
    source_alignment: ForcedAlignmentDocument,
    target_alignment: ForcedAlignmentDocument,
) -> QuranCaptionReview:
    """Bind reviewed dialogue corrections to a recut without losing provenance.

    Corrections are authored against the full selected-clip alignment. A
    reviewed editorial arc may omit some of those words; omitted corrections
    must not block the recut, while an id absent from the source alignment is
    still a hard evidence error.
    """

    source_ids = {word.word_id for word in source_alignment.words}
    target_ids = {word.word_id for word in target_alignment.words}
    corrections = review.display_corrections
    unknown = [item.source_word_id for item in corrections if item.source_word_id not in source_ids]
    if unknown:
        raise MediaError(f"Tarteel display correction names an unknown forced word: {unknown[0]}")
    return review.model_copy(
        update={"display_corrections": [item for item in corrections if item.source_word_id in target_ids]}
    )


def _apply_display_corrections(
    alignment: ForcedAlignmentDocument, review: QuranCaptionReview
) -> ForcedAlignmentDocument:
    if not review.display_corrections:
        return alignment
    by_id = {word.word_id: word for word in alignment.words}
    seen: set[str] = set()
    corrected: list[AlignedWord] = []
    for correction in review.display_corrections:
        if correction.source_word_id in seen:
            raise MediaError("Tarteel display corrections reuse a source word")
        word = by_id.get(correction.source_word_id)
        if word is None:
            raise MediaError("Tarteel display correction names an unknown forced word")
        seen.add(correction.source_word_id)
        by_id[correction.source_word_id] = word.model_copy(
            update={"text": f" {correction.display_text.strip()}"}
        )
    for word in alignment.words:
        corrected.append(by_id[word.word_id])
    return ForcedAlignmentDocument.model_validate({**alignment.model_dump(), "words": corrected})


def _canonical_text_for_ayah(review: QuranCaptionReview, ayah: int) -> str:
    offset = ayah - review.canonical_source.ayah_start
    texts = review.canonical_source.text_uthmani
    if offset < 0 or offset >= len(texts):
        raise MediaError(f"Quran review has no canonical text for ayah {ayah}")
    return texts[offset]


def _canonical_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in text.split():
        if _ARABIC_LETTERS.search(token):
            tokens.append(token)
        elif tokens:
            # Preserve Uthmani pause/verse markers with their preceding word.
            # They do not own a fabricated spoken interval of their own.
            tokens[-1] = f"{tokens[-1]} {token}"
        else:
            raise MediaError("Quran canonical text starts with an unbound non-word marker")
    if not tokens:
        raise MediaError("Quran canonical text contains no Arabic words")
    return tokens


def _normalize_word(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = normalized.replace("ـ", "").replace("ٱ", "ا").replace("أ", "ا").replace("إ", "ا")  # noqa: RUF001
    normalized = normalized.replace("آ", "ا").replace("ى", "ي")  # noqa: RUF001
    return "".join(char for char in normalized if _ARABIC_LETTERS.match(char))


def _match_canonical_words(
    canonical_words: list[str], observed: list[AlignedWord], ayah: int
) -> list[tuple[str, list[AlignedWord]]]:
    """Match canonical words in order, allowing ASR splits and small errors."""

    matched: list[tuple[str, list[AlignedWord]]] = []
    complete_target = "".join(_normalize_word(word) for word in canonical_words)
    complete_observed = "".join(_normalize_word(word.text) for word in observed)
    if SequenceMatcher(a=complete_target, b=complete_observed, autojunk=False).ratio() < 0.88:
        raise MediaError(f"Quran ayah {ayah} does not match the complete observed passage")
    cursor = 0
    for canonical in canonical_words:
        if cursor >= len(observed):
            raise MediaError(f"Quran ayah {ayah} alignment ended before {canonical!r}")
        target = _normalize_word(canonical)
        best: tuple[float, list[AlignedWord]] | None = None
        for width in range(1, min(3, len(observed) - cursor) + 1):
            span = observed[cursor : cursor + width]
            if any(
                left.segment_index != right.segment_index or left.source_end_us > right.source_start_us
                for left, right in pairwise(span)
            ):
                continue
            candidate = "".join(_normalize_word(item.text) for item in span)
            score = SequenceMatcher(a=target, b=candidate, autojunk=False).ratio()
            if candidate == target:
                score = 1.0
            if best is None or score > best[0] or (score == best[0] and width < len(best[1])):
                best = (score, span)
        if best is None or best[0] < 0.65 or (len(target) <= 2 and best[0] != 1):
            raise MediaError(f"Quran ayah {ayah} could not match canonical word {canonical!r}")
        matched.append((canonical, best[1]))
        cursor += len(best[1])
    if cursor != len(observed):
        trailing = " ".join(item.text.strip() for item in observed[cursor:])
        raise MediaError(f"Quran ayah {ayah} has unmatched ASR words: {trailing}")
    return matched
