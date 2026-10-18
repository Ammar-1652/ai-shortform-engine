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
from pathlib import Path

import cv2
import numpy as np

from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import AssetCatalogEntry, load_catalog, require_asset
from clipforge.media.clock import us_to_seconds_str
from clipforge.media.hashing import sha256_file
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg, resolve_ffprobe
from clipforge.media.workspace import SourceWorkspace, ensure_within
from clipforge.schemas.campaign import CampaignOverlaySpec
from clipforge.storage import Database

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


def measure_tarteel_overlay_sizing(
    *,
    source_proxy_path: Path,
    source_start_us: int,
    source_end_us: int,
    source_proxy_sha256: str,
    staging_dir: Path,
    log_path: Path,
) -> TarteelOverlaySizing:
    """Measure native CTA/logo bounds before sizing added campaign layers."""
    if source_end_us <= source_start_us:
        raise MediaError("Tarteel source measurement requires a positive source interval")
    staging_dir.mkdir(parents=True, exist_ok=True)
    sample_times = [
        source_start_us + (source_end_us - source_start_us) * fraction // 100
        # The native CTA can be a short animation beat. Sample the early
        # window densely enough to catch its entrance, then use wider samples
        # for logo visibility across the rest of the candidate.
        for fraction in (10, 15, 18, 20, 25, 50, 80, 90)
    ]
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
        "source_start_us": source_start_us,
        "source_end_us": source_end_us,
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
    cta_left, cta_top = choose_tarteel_foreground_position(face_boxes or [])
    cta_width_permille = max(
        80,
        min(600, round(sizing.native_cta_width_px * 1000 / sizing.source_width_px)),
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
    # Prefer a caption-free slot; if every slot contains speech, the smallest
    # overlap wins and the middle/latter beat remains the tie-break.
    return min(scored)[2]


def choose_tarteel_foreground_position(
    face_boxes: list[tuple[float, float, float, float]],
) -> tuple[int, int]:
    """Place the small CTA in the least occupied source-picture region.

    Face detections are geometry only. They do not identify a speaker or a
    person. The chosen candidate is still carried as a clearance fact and is
    reviewed in decoded frames before delivery.
    """
    cta_width = 600
    cta_height = 225
    candidates = [(60, 180), (340, 180), (60, 520), (340, 520)]

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

    return min(candidates, key=lambda candidate: (overlap(candidate), candidate[1], candidate[0]))


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
