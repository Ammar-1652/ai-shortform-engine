"""Pinned, deterministic motion choices for Advanced Hero.

This is intentionally data-only.  Operators select the named profile; they do
not supply JavaScript, CSS, or arbitrary animation code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class MotionStyleProfile:
    style_id: str
    easing: str
    enter_frames: int
    exit_frames: int
    max_travel_px: int
    max_scale_permille: int
    caption_mode: str
    contrast: str
    font_identity: str
    font_sha256: tuple[str, ...]
    accent: str
    safe_left: int
    safe_right: int
    safe_top: int
    safe_bottom: int
    max_simultaneous_emphasis: int

    def fingerprint(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


EDITORIAL_CLEAN_V1 = MotionStyleProfile(
    style_id="editorial-clean-v1",
    easing="ease_out_cubic",
    enter_frames=12,
    exit_frames=10,
    max_travel_px=24,
    max_scale_permille=1020,
    caption_mode="phrase_active_word",
    contrast="outline_shadow_backplate",
    font_identity="dejavu-noto-local-v1",
    font_sha256=(
        "b5d64817b6331723b5e59eaaa6db90057cbed58e9733f65687f110638192359f",
        "faa5f3656a78b2e2d450d27fe8382c778bc2b6bb5ea29c986664a6a435056ceb",
    ),
    accent="#ffcf4a",
    safe_left=64,
    safe_right=64,
    safe_top=120,
    safe_bottom=300,
    max_simultaneous_emphasis=1,
)

LEGACY_V1 = MotionStyleProfile(
    style_id="legacy-v1",
    easing="linear",
    enter_frames=0,
    exit_frames=0,
    max_travel_px=0,
    max_scale_permille=1000,
    caption_mode="phrase_whole_run",
    contrast="legacy",
    font_identity="system-v1",
    font_sha256=(),
    accent="#ffffff",
    safe_left=48,
    safe_right=48,
    safe_top=48,
    safe_bottom=48,
    max_simultaneous_emphasis=1,
)


def style_for_renderer_version(version: str) -> MotionStyleProfile:
    if version == "advanced-hero-renderer-clean-v1":
        return EDITORIAL_CLEAN_V1
    return LEGACY_V1
