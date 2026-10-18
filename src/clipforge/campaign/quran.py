"""Source-bound Quran caption evidence for the Tarteel campaign."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.schemas.campaign import QuranCaptionReview


def load_tarteel_quran_review(
    root: Path,
    *,
    source_asset_id: str,
    candidate_id: str,
) -> tuple[QuranCaptionReview, str, Path]:
    """Load exactly one reviewed Quran sidecar for a source/candidate.

    A sidecar is evidence only when it is a typed, regular file in the
    gitignored work root and its policy declares human pronunciation review.
    Missing or ambiguous evidence blocks Advanced Hero planning.
    """
    base = (root / "campaigns" / "Tarteel").resolve()
    if not base.is_dir() or base.is_symlink():
        raise MediaError("Tarteel Quran review directory is missing")
    matches: list[tuple[QuranCaptionReview, str, Path]] = []
    for path in sorted(base.rglob("quran-caption-review.json")):
        if path.is_symlink() or not path.is_file():
            raise MediaError("Tarteel Quran review sidecar must be a regular file")
        try:
            review = QuranCaptionReview.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            raise MediaError(f"invalid Tarteel Quran review sidecar {path.name}: {exc}") from exc
        if (review.source_asset_id, review.candidate_id) != (source_asset_id, candidate_id):
            continue
        if review.verification_policy.pronunciation_status != "human_reviewed":
            raise MediaError("Tarteel Quran review exists but pronunciation_status is not human_reviewed")
        matches.append((review, sha256_file(path), path))
    if len(matches) != 1:
        raise MediaError(
            f"Tarteel Advanced Hero requires exactly one reviewed Quran sidecar for {candidate_id}"
        )
    return matches[0]
