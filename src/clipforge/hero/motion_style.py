"""Pinned, deterministic motion choices for Advanced Hero.

This is intentionally data-only.  Operators select the named profile; they do
not supply JavaScript, CSS, or arbitrary animation code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace

from clipforge.schemas.direction import DirectionStyleId, MotionStyleSpec


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

    def contract(self) -> MotionStyleSpec:
        """Return the strict JSON contract shared with the Remotion input."""
        payload = asdict(self)
        payload["font_sha256"] = list(self.font_sha256)
        return MotionStyleSpec.model_validate(payload)


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
        "4e5462d2e8be880317b9f49b5b2da109ddb6a3563d91cc604b67f3535832a555",
    ),
    accent="#ffcf4a",
    safe_left=64,
    safe_right=64,
    safe_top=120,
    safe_bottom=300,
    max_simultaneous_emphasis=1,
)

QURAN_EDITORIAL_V1 = MotionStyleProfile(
    style_id="quran-editorial-v1",
    easing=EDITORIAL_CLEAN_V1.easing,
    enter_frames=EDITORIAL_CLEAN_V1.enter_frames,
    exit_frames=EDITORIAL_CLEAN_V1.exit_frames,
    max_travel_px=EDITORIAL_CLEAN_V1.max_travel_px,
    max_scale_permille=EDITORIAL_CLEAN_V1.max_scale_permille,
    caption_mode="phrase_active_word",
    contrast=EDITORIAL_CLEAN_V1.contrast,
    font_identity="amiri-quran-local-v1",
    font_sha256=(
        *EDITORIAL_CLEAN_V1.font_sha256,
        "8fa95faaf7bd18b71789f6f57312003e30c5029218a035e5baf613a0222ab82d",
    ),
    accent="#ffcf4a",
    safe_left=64,
    safe_right=64,
    safe_top=120,
    safe_bottom=300,
    max_simultaneous_emphasis=1,
)

QURAN_READABLE_V2 = replace(
    QURAN_EDITORIAL_V1,
    style_id="quran-readable-v2",
    enter_frames=4,
    exit_frames=0,
    max_travel_px=0,
    max_scale_permille=1000,
    safe_bottom=120,
)

CONCAT_EDITORIAL_V1 = MotionStyleProfile(
    style_id="concat-editorial-v1",
    easing="ease_out_cubic",
    enter_frames=10,
    exit_frames=8,
    max_travel_px=18,
    max_scale_permille=1018,
    caption_mode="phrase_active_word",
    contrast="outline_shadow_backplate",
    font_identity="concat-editorial-local-v1",
    font_sha256=(
        "4f70ae1dd1c951e80603732344f18507d6a6932a3df9f7f6d8a91d4495d41e17",
        "a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab",
        "42c2abe5fddba9a6da76fabab653246fcf48daa3ae3fc6251e61f8215fdda006",
        "9187fa244db5f50201cfb0ede30ae7269651d090290f164c0703403fd0fab1b2",
    ),
    accent="#e8b84a",
    safe_left=64,
    safe_right=64,
    safe_top=120,
    safe_bottom=300,
    max_simultaneous_emphasis=1,
)

KINETIC_CAPTION_V1 = MotionStyleProfile(
    style_id="kinetic-caption-v1",
    easing="ease_out_cubic",
    enter_frames=8,
    exit_frames=6,
    max_travel_px=18,
    max_scale_permille=1030,
    caption_mode="phrase_active_word",
    contrast="outline_shadow_backplate",
    font_identity="dejavu-noto-local-v1",
    font_sha256=EDITORIAL_CLEAN_V1.font_sha256,
    accent="#64d8ff",
    safe_left=64,
    safe_right=64,
    safe_top=120,
    safe_bottom=300,
    max_simultaneous_emphasis=1,
)

DOCUMENTARY_BROLL_V1 = MotionStyleProfile(
    style_id="documentary-broll-v1",
    easing="ease_out_cubic",
    enter_frames=10,
    exit_frames=8,
    max_travel_px=16,
    max_scale_permille=1010,
    caption_mode="phrase_whole_run",
    contrast="soft_backplate",
    font_identity="dejavu-noto-local-v1",
    font_sha256=EDITORIAL_CLEAN_V1.font_sha256,
    accent="#f0c36a",
    safe_left=64,
    safe_right=64,
    safe_top=120,
    safe_bottom=300,
    max_simultaneous_emphasis=1,
)

DATA_EXPLAINER_V1 = MotionStyleProfile(
    style_id="data-explainer-v1",
    easing="ease_in_out_cubic",
    enter_frames=8,
    exit_frames=8,
    max_travel_px=20,
    max_scale_permille=1015,
    caption_mode="phrase_active_word",
    contrast="outline_shadow_backplate",
    font_identity="dejavu-noto-local-v1",
    font_sha256=EDITORIAL_CLEAN_V1.font_sha256,
    accent="#63e6be",
    safe_left=64,
    safe_right=64,
    safe_top=120,
    safe_bottom=300,
    max_simultaneous_emphasis=1,
)

PAPER_EXPLAINER_V1 = MotionStyleProfile(
    style_id="paper-explainer-v1",
    easing="ease_out_cubic",
    enter_frames=12,
    exit_frames=10,
    max_travel_px=14,
    max_scale_permille=1012,
    caption_mode="phrase_whole_run",
    contrast="soft_backplate",
    font_identity="dejavu-noto-local-v1",
    font_sha256=EDITORIAL_CLEAN_V1.font_sha256,
    accent="#ffb86c",
    safe_left=64,
    safe_right=64,
    safe_top=120,
    safe_bottom=300,
    max_simultaneous_emphasis=1,
)

PREMIUM_MINIMAL_V1 = MotionStyleProfile(
    style_id="premium-minimal-v1",
    easing="ease_in_out_cubic",
    enter_frames=14,
    exit_frames=12,
    max_travel_px=10,
    max_scale_permille=1008,
    caption_mode="phrase_whole_run",
    contrast="minimal_outline",
    font_identity="dejavu-noto-local-v1",
    font_sha256=EDITORIAL_CLEAN_V1.font_sha256,
    accent="#ffffff",
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


STYLE_PROFILES: dict[str, MotionStyleProfile] = {
    item.style_id: item
    for item in (
        EDITORIAL_CLEAN_V1,
        QURAN_EDITORIAL_V1,
        QURAN_READABLE_V2,
        CONCAT_EDITORIAL_V1,
        KINETIC_CAPTION_V1,
        DOCUMENTARY_BROLL_V1,
        DATA_EXPLAINER_V1,
        PAPER_EXPLAINER_V1,
        PREMIUM_MINIMAL_V1,
        LEGACY_V1,
    )
}


def style_for_id(style_id: str) -> MotionStyleProfile:
    try:
        return STYLE_PROFILES[style_id]
    except KeyError as exc:
        raise ValueError(f"unsupported motion style {style_id}") from exc


def production_style_ids() -> tuple[DirectionStyleId, ...]:
    return (
        "editorial-clean-v1",
        "quran-editorial-v1",
        "quran-readable-v2",
        "concat-editorial-v1",
        "kinetic-caption-v1",
        "documentary-broll-v1",
        "data-explainer-v1",
        "paper-explainer-v1",
        "premium-minimal-v1",
    )


def style_for_renderer_version(version: str) -> MotionStyleProfile:
    if version in {
        "advanced-hero-renderer-clean-v1",
        "advanced-hero-renderer-directed-v2",
        "advanced-hero-renderer-directed-v3",
        "advanced-hero-renderer-directed-v4",
    }:
        return EDITORIAL_CLEAN_V1
    return LEGACY_V1
