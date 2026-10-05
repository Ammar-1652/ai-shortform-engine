"""Decoded caption frames. Provisional timing is not called WhisperX alignment."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from clipforge.language.captions import CaptionCue, assert_no_overlap, build_cues

_WIDTH = 1080
_HEIGHT = 1920
_MARGIN = 64
_FONTS = {
    "en-US": "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "ar": "/usr/share/fonts/noto/NotoSansArabicUI-Regular.ttf",
    "ja": "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
}
_SAMPLES = (
    ("en-US", "Café costs $12.50 today."),
    ("ar", "مرحبا"),
    ("ja", "価格は100円です。"),
)


@dataclass(frozen=True, slots=True)
class CaptionProof:
    language: str
    text: str
    text_direction: str
    alignment_status: str
    safe_area: bool
    glyphs_present: bool


def prove_captions(directory: Path) -> list[CaptionProof]:
    """Render one still per tested language and check the safe area."""
    directory.mkdir(parents=True, exist_ok=True)
    proofs: list[CaptionProof] = []
    for language, text in _SAMPLES:
        font = _FONTS[language]
        if not Path(font).is_file():
            raise FileNotFoundError(f"caption font for {language} is not installed")
        cues = build_cues(text, language=language, duration_us=1_000_000)
        if cues[0].text != text or cues[0].alignment_status != "alignment_not_claimed":
            raise ValueError("caption proof changed the source text or claimed alignment")
        frame = _render(directory, language, font, cues[0])
        proofs.append(
            CaptionProof(
                language=cues[0].language,
                text=cues[0].text,
                text_direction=cues[0].text_direction,
                alignment_status=cues[0].alignment_status,
                safe_area=_margin_is_empty(frame),
                glyphs_present=_ink(frame, x0=160, y0=480, x1=980, y1=620) > 0,
            )
        )
    overlapped = build_cues(
        "Café costs $12.50 today.\n価格は100円です。",
        language="en-US",
        duration_us=2_000_000,
    )
    assert_no_overlap(overlapped)
    if any(not proof.safe_area or not proof.glyphs_present for proof in proofs):
        raise ValueError("caption glyphs left the safe area or did not draw")
    return proofs


def _render(directory: Path, language: str, font: str, cue: CaptionCue) -> bytes:
    text_path = directory / f"{language}.txt"
    frame_path = directory / f"{language}.raw"
    text_path.write_text(cue.text, encoding="utf-8")
    if text_path.read_text(encoding="utf-8") != cue.text:
        raise ValueError("caption render input changed the source text")
    draw = (
        f"drawtext=fontfile={_escape(font)}:textfile={_escape(text_path)}:"
        "text_shaping=1:x=160:y=480:fontsize=64:fontcolor=white"
    )
    completed = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={_WIDTH}x{_HEIGHT}:d=0.04",
            "-vf",
            draw,
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            str(frame_path),
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ValueError("caption frame could not be decoded")
    frame = frame_path.read_bytes()
    if len(frame) != _WIDTH * _HEIGHT * 3:
        raise ValueError("caption frame has the wrong size")
    return frame


def _escape(path: str | Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _margin_is_empty(frame: bytes) -> bool:
    top = _ink(frame, x0=0, y0=0, x1=_WIDTH, y1=_MARGIN)
    side = _ink(frame, x0=0, y0=0, x1=_MARGIN, y1=_HEIGHT)
    return top == 0 and side == 0


def _ink(frame: bytes, *, x0: int, y0: int, x1: int, y1: int) -> int:
    total = 0
    for y in range(y0, y1):
        row = y * _WIDTH * 3
        for x in range(x0, x1):
            offset = row + x * 3
            total += frame[offset] + frame[offset + 1] + frame[offset + 2]
    return total
