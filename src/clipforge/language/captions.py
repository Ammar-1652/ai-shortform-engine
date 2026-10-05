"""Caption cues. Provisional timing is never labeled as WhisperX alignment."""

from __future__ import annotations

from dataclasses import dataclass

from clipforge.language.matrix import require_language


@dataclass(frozen=True, slots=True)
class CaptionCue:
    text: str
    start_us: int
    end_us: int
    language: str
    text_direction: str
    alignment_status: str


def build_cues(
    text: str,
    *,
    language: str,
    duration_us: int,
    aligned: bool = False,
) -> list[CaptionCue]:
    """Split one caption line. Unsupported languages fail before any render job."""
    profile = require_language(language)
    if duration_us <= 0:
        raise ValueError("caption duration must be positive")
    if aligned and not language.startswith("en"):
        raise ValueError("alignment_not_claimed")
    status = "aligned" if aligned else "alignment_not_claimed"
    parts = [part.strip() for part in text.split("\n") if part.strip()]
    if not parts:
        raise ValueError("caption text is empty")
    span = duration_us // len(parts)
    cues: list[CaptionCue] = []
    for index, part in enumerate(parts):
        start = index * span
        end = duration_us if index == len(parts) - 1 else (index + 1) * span
        if cues and start < cues[-1].end_us:
            raise ValueError("caption cues overlap")
        cues.append(
            CaptionCue(
                text=part,
                start_us=start,
                end_us=end,
                language=profile.language,
                text_direction=profile.text_direction,
                alignment_status=status,
            )
        )
    return cues


def wrap_caption(text: str, *, language: str, width: int = 12) -> list[str]:
    """Keep source characters in order. Japanese wraps by character, not by a reversed word."""
    profile = require_language(language)
    if width < 1:
        raise ValueError("caption width must be positive")
    if not text or text.strip() != text:
        raise ValueError("caption text is empty")
    if profile.language == "ja":
        return [text[index : index + width] for index in range(0, len(text), width)]
    return [text]


def assert_no_overlap(cues: list[CaptionCue]) -> None:
    previous = -1
    for cue in cues:
        if cue.start_us < previous or cue.end_us <= cue.start_us:
            raise ValueError("caption cues overlap")
        previous = cue.end_us
