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
    text = " ".join(text.split()) if profile.language != "ja" else text.strip()
    if not text:
        raise ValueError("caption text is empty")
    if profile.language == "ja":
        return _wrap_cjk(text, width)
    return _wrap_words(text, width)


def _wrap_words(text: str, width: int) -> list[str]:
    """Wrap on spaces. Currency and numeric tokens stay intact. Text is not reversed."""
    words = text.split()
    if any(not word for word in words):
        raise ValueError("caption text is empty")
    lines: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
            continue
        joined = current + " " + word
        if len(joined) > width:
            lines.append(current)
            current = word
        else:
            current = joined
    if current:
        lines.append(current)
    if " ".join(lines) != text:
        raise ValueError("caption wrap changed the source characters")
    return lines


def _wrap_cjk(text: str, width: int) -> list[str]:
    """Wrap by character. Closing punctuation stays with the previous glyph."""
    forbidden_start = {chr(code) for code in (0x3002, 0x3001, 0xFF01, 0xFF1F, 0x300D, 0xFF09, 0x300F)}
    forbidden_end = {chr(code) for code in (0xFF08, 0x300C, 0x300E)}
    lines: list[str] = []
    current = ""
    for character in text:
        if len(current) >= width and character not in forbidden_start:
            carry = ""
            if current and current[-1] in forbidden_end:
                carry = current[-1]
                current = current[:-1]
            if current:
                lines.append(current)
            current = carry + character
            continue
        current += character
    if current:
        lines.append(current)
    return lines


def assert_no_overlap(cues: list[CaptionCue]) -> None:
    previous = -1
    for cue in cues:
        if cue.start_us < previous or cue.end_us <= cue.start_us:
            raise ValueError("caption cues overlap")
        previous = cue.end_us
