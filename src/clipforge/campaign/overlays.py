"""Deterministic campaign overlay staging.

Only campaign-provided, rights-cleared files may reach this module.  The
green-screen CTA is converted to a muted alpha *video* once in the run
staging directory; Remotion then composites the real animation as a layer.
The watermark is a separate alpha image because it is intentionally static.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import AssetCatalogEntry, load_catalog, require_asset
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
) -> StagedTarteelOverlay:
    """Stage the reviewed Tarteel CTA and watermark with deterministic alpha."""
    if duration_us <= 0:
        raise MediaError("Tarteel overlay staging requires a positive output duration")
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
    start = cta_start_us if cta_start_us is not None else max(0, duration_us - cta_duration_us - 500_000)
    end = min(duration_us, start + effective_duration_us)
    if end <= start:
        raise MediaError("Tarteel CTA interval does not fit the output")
    return StagedTarteelOverlay(
        spec=CampaignOverlaySpec(
            cta_asset_id=cta_entry.reference.asset_id,
            cta_asset_sha256=cta_entry.file_sha256,
            cta_asset_name=cta_video.name,
            cta_render_mode="alpha_video_v1",
            cta_start_us=start,
            cta_end_us=end,
            watermark_asset_id=watermark_entry.reference.asset_id,
            watermark_asset_sha256=watermark_entry.file_sha256,
            watermark_asset_name=watermark_path.name,
        ),
        cta_source=cta_entry,
        watermark_source=watermark_entry,
        cta_path=cta_video,
        watermark_path=watermark_path,
    )


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
