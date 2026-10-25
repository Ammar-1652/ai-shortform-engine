"""Deterministic campaign overlay staging.

Only campaign-provided, rights-cleared files may reach this module.  The
green-screen CTA is converted to a muted alpha *video* once in the run
staging directory; Remotion then composites the real animation as a layer.
The watermark is a separate alpha image because it is intentionally static.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from math import ceil, floor
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import AssetCatalogEntry, load_catalog, require_asset
from clipforge.media.clock import us_to_seconds_str
from clipforge.media.hashing import sha256_file
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg, resolve_ffprobe
from clipforge.media.workspace import SourceWorkspace, ensure_within
from clipforge.schemas.campaign import CampaignOverlaySpec, OverlayExclusionEvidence
from clipforge.storage import Database
from clipforge.timeline import FrameRate, frame_start_us

if TYPE_CHECKING:
    from clipforge.schemas.advanced import AdvancedHeroRenderInput

TARTEEL_PROFILE_ID = "profile-tarteel-campaign"
TARTEEL_CTA_TAG = "cta"
TARTEEL_WATERMARK_TAG = "watermark"


@dataclass(frozen=True, slots=True)
class StagedTarteelOverlay:
    spec: CampaignOverlaySpec
    cta_source: AssetCatalogEntry
    watermark_source: AssetCatalogEntry
    cta_path: Path
    watermark_path: Path


@dataclass(frozen=True, slots=True)
class TarteelOverlaySizing:
    """Measured source-native branding geometry used for one render."""

    source_width_px: int
    source_height_px: int
    native_cta_width_px: int
    native_logo_width_px: int | None
    source_logo_visible: bool
    measurement_sha256: str


def overlay_spec_sha256(spec: CampaignOverlaySpec) -> str:
    """Digest the reviewed declarative CTA/logo spec without local paths."""
    raw = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_tarteel_overlay_exclusion(
    root: Path,
    *,
    source_asset_id: str,
    candidate_id: str,
    source_sha256: str,
    time_map_sha256: str,
    transform_sha256: str,
    overlay: CampaignOverlaySpec,
) -> tuple[OverlayExclusionEvidence, str, Path]:
    """Load the one reviewed, source-bound exclusion record for a candidate."""
    root = root.resolve()
    base = root / "campaigns" / "Tarteel"
    if not base.is_dir() or base.is_symlink():
        raise MediaError("Tarteel overlay exclusion directory is missing")
    matches: list[tuple[OverlayExclusionEvidence, str, Path]] = []
    for path in sorted(base.rglob("overlay-exclusion.json")):
        if path.is_symlink() or not path.is_file() or not path.is_relative_to(root):
            raise MediaError("Tarteel overlay exclusion sidecar must be a regular file in the work root")
        if any(parent.is_symlink() for parent in path.parents if parent != root):
            raise MediaError("Tarteel overlay exclusion path cannot contain symlinks")
        try:
            evidence = OverlayExclusionEvidence.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise MediaError(f"invalid Tarteel overlay exclusion sidecar {path.name}: {exc}") from exc
        if (evidence.source_asset_id, evidence.candidate_id) != (source_asset_id, candidate_id):
            continue
        if evidence.source_sha256 != source_sha256:
            raise MediaError("Tarteel overlay exclusion evidence is stale: source hash differs")
        if evidence.time_map_sha256 != time_map_sha256:
            raise MediaError("Tarteel overlay exclusion evidence is stale: TimeMap differs")
        if evidence.transform_sha256 != transform_sha256:
            raise MediaError("Tarteel overlay exclusion evidence is stale: transform differs")
        if evidence.overlay_spec_sha256 != overlay_spec_sha256(overlay):
            raise MediaError("Tarteel overlay exclusion evidence is stale: overlay spec differs")
        if evidence.decision != "clear":
            raise MediaError("Tarteel overlay exclusion evidence is blocked")
        if (evidence.cta_start_us, evidence.cta_end_us) != (overlay.cta_start_us, overlay.cta_end_us):
            raise MediaError("Tarteel overlay exclusion evidence has stale CTA timing")
        validate_overlay_sample_files(root, evidence)
        matches.append((evidence, sha256_file(path), path))
    if len(matches) != 1:
        raise MediaError(f"Tarteel requires exactly one clear overlay exclusion sidecar for {candidate_id}")
    return matches[0]


def validate_overlay_sample_files(root: Path, evidence: OverlayExclusionEvidence) -> None:
    """A frame hash without inspectable frame bytes cannot certify clearance."""
    from clipforge.hero.advanced_assets import confine_work_path

    for sample in evidence.samples:
        if sample.output_time_us != frame_start_us(sample.output_frame_index, FrameRate(30, 1)):
            raise MediaError("overlay exclusion sample frame and output clock differ")
        if not sample.sample_frame_relative_path:
            raise MediaError("overlay exclusion requires inspectable sample frame files")
        path = confine_work_path(root, sample.sample_frame_relative_path, label="overlay exclusion frame")
        if not path.is_file() or sha256_file(path) != sample.sample_frame_sha256:
            raise MediaError("overlay exclusion sample frame hash is stale")
        decoded = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if decoded is None or decoded.shape[:2] != (1920, 1080):
            raise MediaError("overlay exclusion sample must decode in final 1080x1920 coordinates")


def campaign_cta_bounds(render_input: AdvancedHeroRenderInput) -> tuple[int, int, int, int]:
    """Conservative raster bounds of the actual CTA container after transform.

    The pinned keying recipe produces a 640x240 video. Fraction arithmetic
    mirrors the production layout; the envelope includes subpixel coverage.
    """
    overlay = render_input.campaign_overlay
    if overlay is None:
        raise MediaError("CTA bounds require a campaign overlay")
    left, top, width, height = Fraction(0), Fraction(0), Fraction(1080), Fraction(1920)
    if (
        render_input.reframing_strategy == "contain"
        and render_input.renderer_recipe_version == "advanced-hero-renderer-directed-v4"
    ):
        if not render_input.windows:
            raise MediaError("CTA geometry requires source dimensions")
        source = render_input.windows[0]
        scale = min(Fraction(1080, source.frame_width), Fraction(1920, source.frame_height))
        width = Fraction(floor(source.frame_width * scale + Fraction(1, 2)))
        height = Fraction(floor(source.frame_height * scale + Fraction(1, 2)))
        left, top = Fraction((1080 - width) // 2), Fraction((1920 - height) // 2)
        if render_input.frame_style_id != "none-v1" and render_input.frame_layout_id == "platform-bleed-v1":
            width = Fraction(1080)
            height = Fraction(floor(Fraction(1080 * source.frame_height, source.frame_width) + Fraction(1, 2)))
            top = Fraction(floor((1920 - height) / 2 + Fraction(1, 2)))
            left = Fraction(0)
        else:
            push = (
                Fraction(9, 10)
                if render_input.safe_region_id == "platform-resilient-portrait-v1"
                else Fraction(26, 25)
            )
            left += width * (1 - push) / 2
            top += height * (1 - push) / 2
            width *= push
            height *= push
    x = left + width * Fraction(overlay.cta_left_permille, 1000)
    y = top + height * Fraction(overlay.cta_top_permille, 1000)
    cta_width = width * Fraction(overlay.cta_width_permille, 1000)
    cta_height = cta_width * Fraction(3, 8)
    return floor(x), floor(y), ceil(x + cta_width) - floor(x), ceil(y + cta_height) - floor(y)


def validate_overlay_render_geometry(
    evidence: OverlayExclusionEvidence,
    render_input: AdvancedHeroRenderInput,
) -> None:
    """Reject a safe-looking proof that measures a different CTA rectangle."""
    from clipforge.preview.timing import frame_at_or_after

    overlay = render_input.campaign_overlay
    if overlay is None or (evidence.cta_start_us, evidence.cta_end_us) != (
        overlay.cta_start_us,
        overlay.cta_end_us,
    ):
        raise MediaError("overlay exclusion timing differs from the rendered CTA")
    bounds = campaign_cta_bounds(render_input)
    first = frame_at_or_after(overlay.cta_start_us, render_input.duration_in_frames)
    last = max(first + 1, frame_at_or_after(overlay.cta_end_us, render_input.duration_in_frames)) - 1
    if first >= render_input.duration_in_frames or last >= render_input.duration_in_frames:
        raise MediaError("CTA interval is outside the render")
    for sample in evidence.samples:
        if (sample.cta_left, sample.cta_top, sample.cta_width, sample.cta_height) != bounds:
            raise MediaError("overlay exclusion CTA bounds differ from production geometry")
        if not first <= sample.output_frame_index <= last:
            raise MediaError("overlay exclusion sample is outside rendered CTA frames")
    if not any(
        sample.phase == "entrance" and sample.output_frame_index == first for sample in evidence.samples
    ):
        raise MediaError("overlay exclusion must inspect the first CTA frame")
    if not any(sample.phase == "exit" and sample.output_frame_index == last for sample in evidence.samples):
        raise MediaError("overlay exclusion must inspect the last CTA frame")


def require_tarteel_overlay_matches_plan(
    planned: CampaignOverlaySpec,
    staged: CampaignOverlaySpec,
) -> None:
    """Do not replace reviewed overlay timing or geometry while staging media."""
    if planned == staged:
        return
    planned_fields = planned.model_dump(mode="json")
    staged_fields = staged.model_dump(mode="json")
    changed = sorted(key for key in planned_fields if planned_fields[key] != staged_fields.get(key))
    raise MediaError("Tarteel overlay staging differs from the reviewed plan: " + ", ".join(changed))


def _selected_source_sample_times(source_ranges_us: list[tuple[int, int]]) -> list[int]:
    if not source_ranges_us or any(end <= start for start, end in source_ranges_us):
        raise MediaError("Tarteel source measurement requires positive selected source ranges")
    return [
        start + (end - start) * fraction // 100
        for start, end in source_ranges_us
        for fraction in (10, 15, 18, 20, 25, 50, 80, 90)
    ]


def measure_tarteel_overlay_sizing(
    *,
    source_proxy_path: Path,
    source_ranges_us: list[tuple[int, int]],
    source_proxy_sha256: str,
    staging_dir: Path,
    log_path: Path,
) -> TarteelOverlaySizing:
    """Measure branding only in the source ranges retained by the edit."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    # A min/max envelope can include footage removed by a jump cut. Sample
    # each retained range independently, keeping output order in the digest.
    sample_times = _selected_source_sample_times(source_ranges_us)
    cta_widths: list[int] = []
    logo_widths: list[int] = []
    frame_width = 0
    frame_height = 0
    for index, timestamp_us in enumerate(sample_times):
        frame_path = staging_dir / f"tarteel-branding-measure-{index}.png"
        ProcessRunner().run(
            [
                resolve_ffmpeg(),
                "-y",
                "-ss",
                us_to_seconds_str(timestamp_us),
                "-i",
                str(source_proxy_path),
                "-frames:v",
                "1",
                "-f",
                "image2",
                str(frame_path),
            ],
            log_path=log_path,
            check=True,
        )
        image = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        try:
            if image is None or image.size == 0:
                continue
            frame_height, frame_width = image.shape[:2]
            cta_width = _scan_native_cta_width(image)
            if cta_width is not None:
                cta_widths.append(cta_width)
            logo_width = _scan_native_logo_width(image)
            if logo_width is not None:
                logo_widths.append(logo_width)
        finally:
            frame_path.unlink(missing_ok=True)
    if not cta_widths or frame_width <= 0 or frame_height <= 0:
        raise MediaError(
            "Tarteel native CTA geometry could not be measured from the source frames; "
            "branding placement is blocked"
        )
    native_cta_width = round(statistics.median(cta_widths))
    native_logo_width = round(statistics.median(logo_widths)) if logo_widths else None
    payload = {
        "method": "source-frame-scan-v1",
        "source_proxy_sha256": source_proxy_sha256,
        "source_ranges_us": source_ranges_us,
        "source_width_px": frame_width,
        "source_height_px": frame_height,
        "native_cta_width_px": native_cta_width,
        "native_logo_width_px": native_logo_width,
        "source_logo_visible": native_logo_width is not None,
        "sample_times_us": sample_times,
    }
    measurement_sha256 = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return TarteelOverlaySizing(
        source_width_px=frame_width,
        source_height_px=frame_height,
        native_cta_width_px=native_cta_width,
        native_logo_width_px=native_logo_width,
        source_logo_visible=native_logo_width is not None,
        measurement_sha256=measurement_sha256,
    )


def _white_mask(region: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, np.array([0, 0, 205]), np.array([180, 85, 255]))


def _scan_native_logo_width(image: np.ndarray) -> int | None:
    height, width = image.shape[:2]
    regions = (
        (0, 0, int(width * 0.20), int(height * 0.25)),
        (int(width * 0.80), 0, width, int(height * 0.25)),
    )
    candidates: list[int] = []
    for left, top, right, bottom in regions:
        mask = _white_mask(image[top:bottom, left:right])
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        count, _labels, stats, _centers = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for index in range(1, count):
            _x, _y, box_width, box_height, area = stats[index]
            if area >= 80 and box_width >= width * 0.025 and box_height >= height * 0.025:
                candidates.append(int(box_width))
    return max(candidates) if candidates else None


def _scan_native_cta_width(image: np.ndarray) -> int | None:
    height, width = image.shape[:2]
    left, right = int(width * 0.28), int(width * 0.72)
    top, bottom = int(height * 0.76), int(height * 0.90)
    mask = _white_mask(image[top:bottom, left:right])
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)
    runs: list[int] = []
    for row in mask:
        occupied = np.flatnonzero(row > 0)
        if occupied.size == 0:
            continue
        boundaries = np.flatnonzero(np.diff(occupied) > 1)
        starts = np.concatenate(([occupied[0]], occupied[boundaries + 1]))
        ends = np.concatenate((occupied[boundaries], [occupied[-1]]))
        runs.extend((ends - starts + 1).tolist())
    candidates = [run for run in runs if run >= width * 0.20]
    if not candidates:
        return None
    return max(candidates)


def stage_tarteel_overlay(
    *,
    database: Database,
    workspace: SourceWorkspace,
    project_id: str,
    work_root: Path,
    staging_dir: Path,
    duration_us: int,
    cta_start_us: int | None = None,
    cta_duration_us: int = 3_000_000,
    cta_asset_id: str | None = None,
    watermark_asset_id: str | None = None,
    caption_intervals: list[tuple[int, int]] | None = None,
    source_logo_visible: bool = False,
    face_boxes: list[tuple[float, float, float, float]] | None = None,
    face_boxes_by_time: list[tuple[int, float, float, float, float]] | None = None,
    sizing: TarteelOverlaySizing | None = None,
) -> StagedTarteelOverlay:
    """Stage the reviewed Tarteel CTA and watermark with deterministic alpha."""
    if duration_us <= 0:
        raise MediaError("Tarteel overlay staging requires a positive output duration")
    if sizing is None:
        raise MediaError(
            "Tarteel overlay staging requires source-measured CTA/logo sizing; "
            "fixed campaign overlay dimensions are blocked"
        )
    if cta_duration_us <= 0:
        raise MediaError("Tarteel CTA duration must be positive")
    entries = load_catalog(workspace)
    cta = _choose(entries, TARTEEL_CTA_TAG, preferred="cta-2-green-screen", asset_id=cta_asset_id)
    watermark = _choose(entries, TARTEEL_WATERMARK_TAG, preferred="watermark-1", asset_id=watermark_asset_id)
    cta_entry, _cta_license, cta_source = require_asset(
        database,
        workspace,
        project_id=project_id,
        asset_id=cta.reference.asset_id,
        expected_kind="graphic",
        work_root=work_root,
    )
    watermark_entry, _wm_license, watermark_source = require_asset(
        database,
        workspace,
        project_id=project_id,
        asset_id=watermark.reference.asset_id,
        expected_kind="graphic",
        work_root=work_root,
    )
    staging_dir.mkdir(parents=True, exist_ok=True)
    ensure_within(work_root, staging_dir)
    cta_video = staging_dir / "tarteel-cta-alpha.webm"
    watermark_path = staging_dir / "tarteel-watermark-alpha.png"
    _chroma_key_video(cta_source, cta_video, staging_dir / "tarteel-cta-key.log")
    _white_key(watermark_source, watermark_path, staging_dir / "tarteel-watermark-key.log")
    source_duration_us = _duration_us(cta_source, staging_dir / "tarteel-cta-probe.log")
    effective_duration_us = min(cta_duration_us, source_duration_us)
    start = (
        cta_start_us
        if cta_start_us is not None
        else choose_tarteel_overlay_start_us(
            duration_us,
            cta_duration_us,
            caption_intervals or [],
        )
    )
    end = min(duration_us, start + effective_duration_us)
    if end <= start:
        raise MediaError("Tarteel CTA interval does not fit the output")
    cta_width_permille = max(
        80,
        min(600, round(sizing.native_cta_width_px * 1000 / sizing.source_width_px)),
    )
    cta_height_permille = max(1, round(cta_width_permille * 240 / 640))
    cta_left, cta_top = choose_tarteel_foreground_position(
        face_boxes or [],
        face_boxes_by_time=face_boxes_by_time,
        cta_start_us=start,
        cta_end_us=end,
        cta_width_permille=cta_width_permille,
        cta_height_permille=cta_height_permille,
        source_logo_visible=source_logo_visible or sizing.source_logo_visible,
    )
    watermark_width_permille = max(
        24,
        min(
            280,
            round(
                (sizing.native_logo_width_px or sizing.native_cta_width_px // 4) * 1000 / sizing.source_width_px
            ),
        ),
    )
    return StagedTarteelOverlay(
        spec=CampaignOverlaySpec(
            cta_asset_id=cta_entry.reference.asset_id,
            cta_asset_sha256=cta_entry.file_sha256,
            cta_asset_name=cta_video.name,
            cta_render_mode="alpha_video_v1",
            cta_left_permille=cta_left,
            cta_top_permille=cta_top,
            cta_width_permille=cta_width_permille,
            cta_start_us=start,
            cta_end_us=end,
            watermark_asset_id=watermark_entry.reference.asset_id,
            watermark_asset_sha256=watermark_entry.file_sha256,
            watermark_asset_name=watermark_path.name,
            watermark_visibility=(
                "source_visible_v1"
                if (source_logo_visible or sizing.source_logo_visible)
                else "overlay_required_v1"
            ),
            watermark_width_permille=watermark_width_permille,
            sizing_method="source_frame_scan_v1",
            sizing_measurement_sha256=sizing.measurement_sha256,
        ),
        cta_source=cta_entry,
        watermark_source=watermark_entry,
        cta_path=cta_video,
        watermark_path=watermark_path,
    )


def choose_tarteel_overlay_start_us(
    duration_us: int,
    cta_duration_us: int,
    caption_intervals: list[tuple[int, int]],
) -> int:
    """Choose a reviewed-looking CTA beat without hiding a caption.

    The CTA is a short visual cue inside the source picture. It should not be
    blindly pinned to the final frame or laid over a spoken caption. Candidate
    starts are deterministic and prefer the middle/latter third of a long
    clip, with the latest safe option as a stable tie-break.
    """
    if duration_us <= cta_duration_us:
        return 0
    latest = duration_us - cta_duration_us
    raw_candidates = [
        int(duration_us * 0.46),
        int(duration_us * 0.62),
        int(duration_us * 0.78),
        latest,
    ]
    candidates = sorted({max(0, min(latest, value)) for value in raw_candidates})

    def overlap(start: int) -> int:
        end = start + cta_duration_us
        return sum(
            max(0, min(end, cue_end) - max(start, cue_start)) for cue_start, cue_end in caption_intervals
        )

    scored = [(overlap(start), -abs(start - int(duration_us * 0.62)), start) for start in candidates]
    if any(item[0] == 0 for item in scored):
        # Prefer a caption-free slot; the middle/latter beat remains the
        # deterministic tie-break.
        return min(scored)[2]
    # Dense speech can leave no fully caption-free CTA interval. In that case
    # do not hide the CTA at the last frame by default: the reviewed payoff
    # beat is the stable visual choice and is checked later against decoded
    # faces, tablet, branding, and caption geometry.
    payoff = int(duration_us * 0.78)
    return min(candidates, key=lambda start: (abs(start - payoff), overlap(start), start))


def choose_tarteel_foreground_position(
    face_boxes: list[tuple[float, float, float, float]],
    *,
    face_boxes_by_time: list[tuple[int, float, float, float, float]] | None = None,
    cta_start_us: int | None = None,
    cta_end_us: int | None = None,
    cta_width_permille: int = 600,
    cta_height_permille: int = 225,
    source_logo_visible: bool = False,
) -> tuple[int, int]:
    """Place the small CTA in the least occupied source-picture region.

    Face detections are geometry only. They do not identify a speaker or a
    person. The chosen candidate is still carried as a clearance fact and is
    reviewed in decoded frames before delivery.
    """
    if cta_width_permille <= 0 or cta_height_permille <= 0:
        raise MediaError("Tarteel CTA geometry must be positive")
    if face_boxes_by_time is not None:
        if cta_start_us is None or cta_end_us is None or cta_end_us <= cta_start_us:
            raise MediaError("Tarteel timed face clearance requires a positive CTA interval")
        face_boxes = [
            (x, y, width, height)
            for timestamp_us, x, y, width, height in face_boxes_by_time
            if cta_start_us <= timestamp_us < cta_end_us
        ]
        if not face_boxes:
            raise MediaError("Tarteel CTA has no face-clearance sample in its reviewed interval")
    cta_width = cta_width_permille
    cta_height = cta_height_permille
    # Prefer an upper foreground slot when it is clear. The former candidate
    # set started at 180‰, which can land on children's heads in a wide shot
    # even when the face detector has sparse samples. The final proof still
    # owns the visual clearance decision; this slot simply gives the solver a
    # safe geometry to choose.
    candidates = [(340, 60), (600, 60), (60, 60), (60, 180), (340, 180), (600, 180), (60, 520), (340, 520)]
    if source_logo_visible:
        # The source logo is in the upper-left foreground slot. Do not place
        # the added CTA over it when source branding remains visible.
        candidates = [candidate for candidate in candidates if candidate[0] >= 120]

    def overlap(candidate: tuple[int, int]) -> float:
        left, top = candidate
        right = left + cta_width
        bottom = top + cta_height
        total = 0.0
        for x, y, width, height in face_boxes:
            face_left = x * 1000
            face_top = y * 1000
            face_right = face_left + width * 1000
            face_bottom = face_top + height * 1000
            intersection = max(0.0, min(right, face_right) - max(left, face_left)) * max(
                0.0, min(bottom, face_bottom) - max(top, face_top)
            )
            total += intersection
        return total

    chosen = min(
        candidates,
        key=lambda candidate: (
            overlap(candidate),
            candidate[1],
            0 if candidate[0] == 340 else 1,
            candidate[0],
        ),
    )
    if overlap(chosen) > 0:
        raise MediaError("Tarteel CTA has no face-clear foreground position for the reviewed frame evidence")
    return chosen


def _choose(
    entries: list[AssetCatalogEntry],
    tag: str,
    *,
    preferred: str,
    asset_id: str | None = None,
) -> AssetCatalogEntry:
    candidates = [item for item in entries if tag in item.reference.content_tags]
    if asset_id is not None:
        chosen = next((item for item in candidates if item.reference.asset_id == asset_id), None)
        if chosen is None:
            raise MediaError(f"Tarteel {tag} asset {asset_id} is not in the local catalog")
        return chosen
    if not candidates:
        raise MediaError(f"Tarteel campaign has no catalogued {tag} asset")
    for item in candidates:
        if preferred in item.relative_path:
            return item
    return sorted(candidates, key=lambda item: item.relative_path)[0]


def _chroma_key_video(source: Path, destination: Path, log_path: Path) -> None:
    """Make a transparent, audio-free video while retaining every CTA frame.

    The supplied campaign CTA is a 1080x1920 green-screen recording.  Its
    reviewed graphic occupies the 640x240 window at (0, 840); cropping that
    window prevents a transparent full-canvas layer from affecting layout and
    keeps the safe-rail geometry stable across output resolutions. VP9/WebM is
    deliberately used instead of a PNG still, QuickTime Animation,
    or an audio-bearing MP4: it is a deterministic video format with an alpha
    channel that Remotion's in-browser ``Video`` layer can decode frame by
    frame in the shipped renderer.
    """
    ffmpeg = resolve_ffmpeg()
    ProcessRunner().run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-vf",
            "colorkey=0x00b52b:0.12:0.0,format=rgba,crop=640:240:0:840",
            "-an",
            "-c:v",
            "libvpx-vp9",
            "-pix_fmt",
            "yuva420p",
            "-auto-alt-ref",
            "0",
            "-crf",
            "20",
            "-b:v",
            "0",
            "-r",
            "30",
            str(destination),
        ],
        log_path=log_path,
        check=True,
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise MediaError("Tarteel CTA alpha video staging produced no file")


def _duration_us(source: Path, log_path: Path) -> int:
    """Read the source duration without introducing a float timeline."""
    result = ProcessRunner().run(
        [
            resolve_ffprobe(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(source),
        ],
        log_path=log_path,
        check=True,
    )
    try:
        value = Decimal(result.stdout.strip())
    except Exception as exc:  # pragma: no cover - ffprobe contract failure
        raise MediaError(f"CTA ffprobe returned an invalid duration for {source.name}") from exc
    duration = int((value * Decimal(1_000_000)).to_integral_value(rounding=ROUND_HALF_UP))
    if duration <= 0:
        raise MediaError(f"CTA source {source.name} has no positive duration")
    return duration


def _white_key(source: Path, destination: Path, log_path: Path) -> None:
    ffmpeg = resolve_ffmpeg()
    ProcessRunner().run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-vf",
            "colorkey=0xFFFFFF:0.10:0.08,format=rgba",
            "-frames:v",
            "1",
            "-an",
            "-c:v",
            "png",
            str(destination),
        ],
        log_path=log_path,
        check=True,
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise MediaError("Tarteel watermark alpha staging produced no file")


def overlay_dependencies_digest(overlay: StagedTarteelOverlay) -> str:
    """Hash the exact source and alpha bytes consumed by a render input."""
    import hashlib

    digest = hashlib.sha256()
    for path in (overlay.cta_path, overlay.watermark_path):
        digest.update(path.name.encode("utf-8"))
        digest.update(sha256_file(path).encode("ascii"))
    import json

    digest.update(
        json.dumps(overlay.spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return digest.hexdigest()
